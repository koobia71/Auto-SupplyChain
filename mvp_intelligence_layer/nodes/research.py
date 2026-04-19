"""Research 节点实现。

本节点负责模拟市场调研，输出可执行采购 benchmark，
覆盖供应商路径、价格区间、替代建议与交付风险。
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
from mvp_intelligence_layer.utils.prompts import research_prompt_template


def _format_research_few_shot_cases(judgment_history: list[dict[str, Any]]) -> str:
    """将最近 2-3 条历史案例格式化，用于研究节点 few-shot。"""

    if not judgment_history:
        return "暂无历史案例，请采用保守市场调研策略并给出价格区间。"

    recent_cases = judgment_history[-3:]
    lines: list[str] = []
    for idx, case in enumerate(recent_cases, start=1):
        lines.append(f"示例{idx}:")
        lines.append(f"- analysis: {case.get('analysis', '')}")
        lines.append(f"- research: {case.get('research', '')}")
        lines.append(f"- recommendation: {_as_json_text(case.get('recommendation', {}))}")

    return "\n".join(lines)


def _research_rule_fallback(state: ProcurementState, reason: str, model_name: str) -> dict[str, Any]:
    """调研节点兜底策略。

    当模型不可用时，仍需给出可执行采购基准，避免流程阻塞。
    """

    demand = state.get("demand", {})
    analysis_text = state.get("analysis", "")

    main_output = (
        "【市场调研（规则兜底）】\n"
        "1) 供应商路径：\n"
        "- 路径A：1688 工业品商家（样本多、价格敏感，需筛选履约评分）。\n"
        "- 路径B：京东工业企业购（发票与交付稳定，单价通常略高）。\n"
        "- 路径C：东莞/苏州本地经销商（紧急补货响应快，需防止高溢价）。\n"
        "2) 价格区间 benchmark：\n"
        f"- 目标物料：{demand.get('item_name', '未提供')} {demand.get('spec', '')}\n"
        "- 建议初始区间：以 1688 中位价为下沿、京东工业价为上沿，允许 8%~20% 波动。\n"
        "3) 替代建议：\n"
        "- 规格模糊时，要求供应商提供兼容清单（电压/接口/耐久等级）。\n"
        "- 若原品牌断供，优先同参数国产替代并小批量试产验证。\n"
        "4) 风险与执行：\n"
        "- long-tail 规格存在误配风险，需二次确认关键参数。\n"
        "- 大单建议分批锁价，降低 1688/京东工业短期波动影响。\n"
        f"5) 分析关联：{analysis_text}"
    )

    return {
        "main_output": main_output,
        "reasoning": {
            "source_strategy": "采用多路径对照，平衡价格、交付与合规性。",
            "price_volatility": "显式纳入 1688/京东工业波动，给出区间而非点价。",
            "long_tail_control": "通过兼容清单与小批量验证降低误配风险。",
            "fallback_reason": reason,
            "model": model_name,
        },
        "confidence": 0.57,
    }


def research_node(state: ProcurementState) -> dict[str, Any]:
    """Research 主节点。

    产出：
    - 更新 state["research"]：包含供应路径、价格区间与替代建议。
    - 更新 state["context"]：记录调研 reasoning/confidence。
    - 更新 state["messages"]：追加 AIMessage，沉淀可复盘轨迹。
    """

    llm, model_name = _build_supervisor_llm()
    few_shot_cases = _format_research_few_shot_cases(state.get("judgment_history", []))

    prompt_inputs = {
        "demand_json": _as_json_text(state.get("demand", {})),
        "analysis_text": state.get("analysis", ""),
        "context_json": _as_json_text(state.get("context", {})),
        "few_shot_cases": few_shot_cases,
    }

    if llm is None:
        decision = _research_rule_fallback(
            state=state,
            reason="LLM 不可用（缺少密钥或模型初始化失败）",
            model_name=model_name,
        )
    else:
        try:
            chain = research_prompt_template | llm
            result = chain.invoke(prompt_inputs)
            raw_text = _normalize_text(getattr(result, "content", result))
            parsed = _extract_json_block(raw_text)

            if not parsed:
                decision = _research_rule_fallback(
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
                    "main_output": str(parsed.get("main_output", "")).strip() or "调研结果为空，需补充信息。",
                    "reasoning": parsed.get("reasoning", {}),
                    "confidence": confidence,
                }
        except Exception as exc:
            decision = _research_rule_fallback(
                state=state,
                reason=f"LLM 调用异常：{exc}",
                model_name=model_name,
            )

    # 将调研判断写入 context，供 supervisor 与 recommendation 使用。
    context = dict(state.get("context", {}))
    context["research_reasoning"] = decision.get("reasoning", {})
    context["research_confidence"] = decision.get("confidence", 0.5)
    context["research_model"] = model_name

    # 记录消息轨迹，使每次市场判断都可追踪可复盘。
    messages = list(state.get("messages", []))
    messages.append(
        AIMessage(
            content=_as_json_text(
                {
                    "node": "research",
                    "reasoning": decision.get("reasoning", {}),
                    "confidence": decision.get("confidence", 0.5),
                    "main_output": decision.get("main_output", ""),
                }
            )
        )
    )

    return {
        "research": str(decision.get("main_output", "")),
        "context": context,
        "messages": messages,
        "next": "recommendation",
    }
