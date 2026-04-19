"""Analysis 节点实现。

本节点负责把工厂侧的原始需求文本拆解成可执行采购语言，
并把判断依据沉淀到状态中，服务 Sequoia 的 judgment -> intelligence 飞轮。
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage

from mvp_intelligence_layer.nodes.supervisor import (
    _as_json_text,
    _build_supervisor_llm,
    _extract_json_block,
    _normalize_text,
)
from mvp_intelligence_layer.state import ProcurementState
from mvp_intelligence_layer.utils.prompts import analysis_prompt_template


def _format_analysis_few_shot_cases(judgment_history: list[dict[str, Any]]) -> str:
    """将最近 2-3 条历史案例格式化为 few-shot 输入。

    这里优先取最近 3 条；若不足 3 条则按实际数量注入。
    通过把历史分析结果显式喂给模型，减少重复犯错，提升稳定性。
    """

    if not judgment_history:
        return "暂无历史案例，请采用保守拆解策略并显式标注信息缺口。"

    recent_cases = judgment_history[-3:]
    lines: list[str] = []
    for idx, case in enumerate(recent_cases, start=1):
        lines.append(f"示例{idx}:")
        lines.append(f"- analysis: {case.get('analysis', '')}")
        lines.append(f"- research: {case.get('research', '')}")
        lines.append(f"- recommendation: {_as_json_text(case.get('recommendation', {}))}")

    return "\n".join(lines)


def _analysis_rule_fallback(state: ProcurementState, reason: str, model_name: str) -> dict[str, Any]:
    """LLM 不可用或输出异常时的稳健回退。

    目标不是追求最优，而是保证流程可持续推进，并把不确定性显式化。
    """

    demand = state.get("demand", {})
    main_output = (
        "【需求拆解（规则兜底）】\n"
        f"1) 品类识别：{demand.get('category', 'MRO备件')} / {demand.get('item_name', '未提供物料名')}\n"
        f"2) 规格确认：{demand.get('spec', '规格缺失，需补充型号、电压、品牌兼容性')}\n"
        f"3) 用量与节奏：需求数量 {demand.get('quantity', '未提供')}，建议确认月均消耗与安全库存。\n"
        "4) 风险点：存在 long-tail 规格模糊风险，需在 research 阶段校验可替代型号。\n"
        "5) 价格波动提醒：1688/京东工业同款价可能日内波动，需设 benchmark 区间。"
    )

    return {
        "main_output": main_output,
        "reasoning": {
            "completeness": "按已有字段进行结构化拆解，缺失字段以风险提示方式暴露。",
            "long_tail_risk": "规格信息不完整时，优先把兼容性风险前置。",
            "next_action": "进入 research 验证供应路径与价格区间。",
            "fallback_reason": reason,
            "model": model_name,
        },
        "confidence": 0.56,
    }


def analysis_node(state: ProcurementState) -> dict[str, Any]:
    """Analysis 主节点。

    产出：
    - 更新 state["analysis"]：详细需求拆解文本。
    - 更新 state["context"]：记录 reasoning/confidence，便于后续监督与复盘。
    - 更新 state["messages"]：追加 AIMessage，保留可审计轨迹。
    """

    llm, model_name = _build_supervisor_llm()
    few_shot_cases = _format_analysis_few_shot_cases(state.get("judgment_history", []))

    prompt_inputs = {
        "demand_json": _as_json_text(state.get("demand", {})),
        "context_json": _as_json_text(state.get("context", {})),
        "few_shot_cases": few_shot_cases,
    }

    if llm is None:
        decision = _analysis_rule_fallback(
            state=state,
            reason="LLM 不可用（缺少密钥或模型初始化失败）",
            model_name=model_name,
        )
    else:
        try:
            chain = analysis_prompt_template | llm
            result = chain.invoke(prompt_inputs)
            raw_text = _normalize_text(getattr(result, "content", result))
            parsed = _extract_json_block(raw_text)

            if not parsed:
                decision = _analysis_rule_fallback(
                    state=state,
                    reason="LLM 输出非 JSON 或解析失败",
                    model_name=model_name,
                )
            else:
                confidence = parsed.get("confidence", 0.5)
                try:
                    confidence = float(confidence)
                except Exception:
                    confidence = 0.5
                confidence = max(0.0, min(1.0, confidence))

                decision = {
                    "main_output": str(parsed.get("main_output", "")).strip() or "分析结果为空，需补充信息。",
                    "reasoning": parsed.get("reasoning", {}),
                    "confidence": confidence,
                }
        except Exception as exc:
            decision = _analysis_rule_fallback(
                state=state,
                reason=f"LLM 调用异常：{exc}",
                model_name=model_name,
            )

    # 将分析判断写入 context，构造可追踪判断轨迹。
    context = dict(state.get("context", {}))
    context["analysis_reasoning"] = decision.get("reasoning", {})
    context["analysis_confidence"] = decision.get("confidence", 0.5)
    context["analysis_model"] = model_name

    # 追加消息日志，支持后续 supervisor 读取并进行动态调度。
    messages = list(state.get("messages", []))
    messages.append(
        AIMessage(
            content=_as_json_text(
                {
                    "node": "analysis",
                    "reasoning": decision.get("reasoning", {}),
                    "confidence": decision.get("confidence", 0.5),
                    "main_output": decision.get("main_output", ""),
                }
            )
        )
    )

    return {
        "analysis": str(decision.get("main_output", "")),
        "context": context,
        "messages": messages,
        "next": "research",
    }
