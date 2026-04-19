"""Supervisor 节点实现。

本文件只负责监督节点路由决策，不放图结构定义。

设计要点：
1. 通过 LLM 做“下一步节点”判断，把采购判断过程显式化。
2. 动态注入最近3条 judgment_history，形成轻量 few-shot。
3. 每次决策都输出 reasoning + confidence，并追加到 messages，
   让每一次路由选择都可追溯、可复盘、可沉淀。
4. 按 Sequoia 的“judgment -> intelligence”逻辑，持续积累案例飞轮。
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from langchain_core.messages import AIMessage

from mvp_intelligence_layer.state import ProcurementState
from mvp_intelligence_layer.utils.prompts import supervisor_prompt_template


def _create_chat_model(model: str, api_key: str, base_url: str):
    """创建 ChatModel（兼容不同 LangChain 发行包）。

    说明：
    - 优先尝试 langchain_openai.ChatOpenAI（当前主流用法）。
    - 若环境是旧版本生态，则回退到 langchain_community.chat_models.ChatOpenAI。
    - 返回 None 表示当前环境不可用，外层将使用规则兜底。
    """

    try:
        from langchain_openai import ChatOpenAI  # type: ignore

        return ChatOpenAI(
            model=model,
            temperature=0.1,
            api_key=api_key,
            base_url=base_url,
        )
    except Exception:
        try:
            from langchain_community.chat_models import ChatOpenAI  # type: ignore

            return ChatOpenAI(
                model_name=model,
                temperature=0.1,
                openai_api_key=api_key,
                openai_api_base=base_url,
            )
        except Exception:
            return None


def _build_supervisor_llm():
    """按“qwen-max 优先，DeepSeek-V3 回退”构建模型。"""

    # 第一优先：qwen-max（阿里云 DashScope 兼容 OpenAI 协议）。
    qwen_key = os.getenv("DASHSCOPE_API_KEY")
    if qwen_key:
        llm = _create_chat_model(
            model="qwen-max",
            api_key=qwen_key,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
        if llm is not None:
            return llm, "qwen-max"

    # 第二优先：DeepSeek-V3（作为兜底模型）。
    deepseek_key = os.getenv("DEEPSEEK_API_KEY")
    if deepseek_key:
        llm = _create_chat_model(
            model="deepseek-v3",
            api_key=deepseek_key,
            base_url="https://api.deepseek.com",
        )
        if llm is not None:
            return llm, "deepseek-v3"

    # 若模型不可用，外层将走规则路由，保障流程不中断。
    return None, "rule-fallback"


def _as_json_text(data: Any) -> str:
    """把任意对象安全转为 JSON 字符串，便于塞入 Prompt。"""

    return json.dumps(data, ensure_ascii=False, indent=2)


def _normalize_text(content: Any) -> str:
    """把模型返回内容标准化为纯文本。

    某些模型返回 content 可能是列表分片，这里统一拼接为字符串。
    """

    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                text_parts.append(part)
            elif isinstance(part, dict) and part.get("type") == "text":
                text_parts.append(str(part.get("text", "")))
            else:
                text_parts.append(str(part))
        return "\n".join(text_parts)
    return str(content)


def _extract_json_block(text: str) -> dict[str, Any] | None:
    """从模型文本中提取 JSON。

    为了提高鲁棒性，支持：
    1. 直接纯 JSON
    2. ```json 代码块包裹
    3. 前后有解释文本，仅中间含 JSON
    """

    cleaned = text.strip()
    cleaned = re.sub(r"^```json\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^```\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            return data
    except Exception:
        pass

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = cleaned[start : end + 1]
        try:
            data = json.loads(candidate)
            if isinstance(data, dict):
                return data
        except Exception:
            return None
    return None


def _format_few_shot_cases(judgment_history: list[dict[str, Any]]) -> str:
    """把最近3条判断案例格式化为 few-shot 文本。

    设计目标：
    - 使用“最近、相似、可解释”的案例作为路由参照。
    - 降低每次从零判断的成本，让系统逐步形成行业经验。
    """

    if not judgment_history:
        return "暂无历史案例，可按保守策略先 analysis 再 research。"

    recent_cases = judgment_history[-3:]
    lines: list[str] = []
    for idx, case in enumerate(recent_cases, start=1):
        lines.append(f"案例{idx}：")
        lines.append(f"- round: {case.get('round', '未知')}")
        lines.append(f"- analysis: {case.get('analysis', '')}")
        lines.append(f"- research: {case.get('research', '')}")
        lines.append(f"- recommendation: {_as_json_text(case.get('recommendation', {}))}")

    return "\n".join(lines)


def _summarize_messages(messages: list[Any]) -> str:
    """提取最近消息摘要，帮助 Supervisor 感知当前轨迹。"""

    if not messages:
        return "暂无消息历史。"

    recent = messages[-5:]
    lines: list[str] = []
    for i, msg in enumerate(recent, start=1):
        if hasattr(msg, "content"):
            content = _normalize_text(getattr(msg, "content"))
            role = getattr(msg, "type", msg.__class__.__name__)
            lines.append(f"{i}. [{role}] {content}")
        else:
            lines.append(f"{i}. {str(msg)}")
    return "\n".join(lines)


def _sanitize_next(next_value: Any) -> str:
    """确保 next 字段始终落在图允许的节点集合中。"""

    allowed = {"analysis", "research", "recommendation", "end"}
    if isinstance(next_value, str) and next_value in allowed:
        return next_value
    return "analysis"


def _rule_based_fallback(state: ProcurementState, reason: str) -> dict[str, Any]:
    """当 LLM 不可用或输出异常时的稳定兜底策略。"""

    context = state.get("context", {})
    loop_count = int(context.get("loop_count", 0))

    if state.get("recommendation", {}).get("completed"):
        decided_next = "end"
    elif not state.get("analysis"):
        decided_next = "analysis"
    elif not state.get("research"):
        decided_next = "research"
    elif loop_count >= 2:
        decided_next = "end"
    else:
        decided_next = "recommendation"

    return {
        "next": decided_next,
        "reasoning": {
            "complexity": "采用规则兜底：先保证流程闭环，再逐步优化智能判断。",
            "history_hit": "未使用模型相似度判断，暂按字段完整性做稳健路由。",
            "risk": "为避免流程中断，优先选择可收敛路径。",
            "loop_decision": f"当前 loop_count={loop_count}，最多允许2轮循环。",
            "fallback_reason": reason,
        },
        "confidence": 0.55,
    }


def supervisor_node(state: ProcurementState) -> dict[str, Any]:
    """Supervisor 主节点。

    输入：ProcurementState
    输出：至少包含 next 与 messages（与现有 State 结构完全兼容）

    关键价值：
    1. 将“为什么走下一步”沉淀到消息中，形成可审计判断轨迹。
    2. 利用 judgment_history 动态 few-shot，让历史经验参与当前决策。
    3. 支持 LLM 失败兜底，保障生产稳定性。
    """

    # 若推荐已经明确完成，直接结束，避免无意义推理与成本开销。
    if state.get("recommendation", {}).get("completed"):
        decision = {
            "next": "end",
            "reasoning": {
                "complexity": "推荐结果已完成并标记 completed=True。",
                "history_hit": "当前无需额外命中判断。",
                "risk": "继续循环会带来额外成本且收益有限。",
                "loop_decision": "满足结束条件，直接 end。",
            },
            "confidence": 0.95,
            "model": "rule-shortcut",
        }
    else:
        llm, model_name = _build_supervisor_llm()

        # 准备动态 few-shot 与上下文输入。
        few_shot_cases = _format_few_shot_cases(state.get("judgment_history", []))
        messages_summary = _summarize_messages(state.get("messages", []))

        prompt_inputs = {
            "demand_json": _as_json_text(state.get("demand", {})),
            "context_json": _as_json_text(state.get("context", {})),
            "analysis_text": state.get("analysis", ""),
            "research_text": state.get("research", ""),
            "recommendation_json": _as_json_text(state.get("recommendation", {})),
            "messages_summary": messages_summary,
            "few_shot_cases": few_shot_cases,
        }

        if llm is None:
            decision = _rule_based_fallback(state, "LLM 不可用（缺少密钥或模型初始化失败）")
            decision["model"] = model_name
        else:
            try:
                # 使用 Runnable（ChatPromptTemplate | LLM）完成调用。
                chain = supervisor_prompt_template | llm
                llm_result = chain.invoke(prompt_inputs)

                raw_text = _normalize_text(getattr(llm_result, "content", llm_result))
                parsed = _extract_json_block(raw_text)

                if not parsed:
                    decision = _rule_based_fallback(state, "LLM 输出非 JSON 或解析失败")
                    decision["model"] = model_name
                    decision["raw_output"] = raw_text
                else:
                    # 标准化 next 与 confidence，避免脏数据污染状态。
                    parsed_next = _sanitize_next(parsed.get("next"))
                    parsed_confidence = parsed.get("confidence", 0.5)
                    try:
                        parsed_confidence = float(parsed_confidence)
                    except Exception:
                        parsed_confidence = 0.5
                    parsed_confidence = max(0.0, min(1.0, parsed_confidence))

                    decision = {
                        "next": parsed_next,
                        "reasoning": parsed.get("reasoning", {}),
                        "confidence": parsed_confidence,
                        "model": model_name,
                    }
            except Exception as exc:
                decision = _rule_based_fallback(state, f"LLM 调用异常：{exc}")
                decision["model"] = model_name

    # 额外安全阀：严格限制循环不超过2轮。
    context = state.get("context", {})
    loop_count = int(context.get("loop_count", 0))
    if loop_count >= 2 and decision.get("next") in {"analysis", "research"}:
        decision["next"] = "recommendation"
        decision_reasoning = decision.get("reasoning", {})
        if isinstance(decision_reasoning, dict):
            decision_reasoning["loop_decision"] = (
                f"当前 loop_count={loop_count}，触发最大循环保护，转为 recommendation 收敛。"
            )
            decision["reasoning"] = decision_reasoning

    # 把结构化决策追加到 messages，形成“可积累判断日志”。
    existing_messages = list(state.get("messages", []))
    ai_message = AIMessage(content=_as_json_text(decision))
    updated_messages = existing_messages + [ai_message]

    return {
        "next": _sanitize_next(decision.get("next")),
        "messages": updated_messages,
    }
