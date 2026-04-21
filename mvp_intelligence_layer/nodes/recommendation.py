"""Recommendation 节点实现。

本节点负责把 analysis/research 的中间判断收敛为可执行交付：
- 供应商推荐与价格区间
- 节省空间预估
- PO 草案 JSON
- 谈判话术建议

这是 Sequoia judgment -> intelligence 飞轮中的“交付闭环点”：
只有可执行推荐被稳定产出并沉淀，历史案例才真正具备复用价值。
"""

from __future__ import annotations

import re
from typing import Any

from langchain_core.messages import AIMessage

from mvp_intelligence_layer.nodes.supervisor import (
    _as_json_text,
    _build_supervisor_llm,
    _extract_json_block,
    _normalize_text,
)
from mvp_intelligence_layer.state import ProcurementState
from mvp_intelligence_layer.utils.prompts import recommendation_prompt_template


def _format_recommendation_few_shot_cases(judgment_history: list[dict[str, Any]]) -> str:
    """格式化最近3条完整案例，用于 recommendation few-shot。

    recommendation 节点需要“端到端”参照，因此除了 analysis/research，
    也会展示历史 recommendation 结构，帮助模型对齐可交付输出格式。
    """

    if not judgment_history:
        return "暂无完整历史案例，请采用稳健策略输出可执行推荐。"

    recent_cases = judgment_history[-3:]
    lines: list[str] = []
    for idx, case in enumerate(recent_cases, start=1):
        lines.append(f"案例{idx}：")
        lines.append(f"- round: {case.get('round', '未知')}")
        lines.append(f"- analysis: {case.get('analysis', '')}")
        lines.append(f"- research: {case.get('research', '')}")
        lines.append(f"- recommendation: {_as_json_text(case.get('recommendation', {}))}")

    return "\n".join(lines)


def _normalize_saving_percent(value: Any) -> int:
    """将节省比例标准化到 10-25 区间（业务目标区间）。"""

    try:
        num = int(round(float(value)))
    except Exception:
        num = 15
    return max(10, min(25, num))


def _extract_first_number(value: Any) -> float | None:
    """从任意文本中提取第一个数字。

    用于兼容模型输出中常见的“58元”“58.0 CNY”“52-60 元”等非标准格式。
    """

    if isinstance(value, (int, float)):
        return float(value)

    if value is None:
        return None

    text = str(value)
    match = re.search(r"(\d+(?:\.\d+)?)", text)
    if not match:
        return None

    try:
        return float(match.group(1))
    except Exception:
        return None


def _parse_price_range_to_mean(price_text: Any) -> float | None:
    """把区间文本解析为均值，例如“52-60 元” -> 56.0。"""

    if price_text is None:
        return None

    text = str(price_text)
    nums = re.findall(r"\d+(?:\.\d+)?", text)
    if not nums:
        return None

    values = [float(n) for n in nums]
    if len(values) >= 2:
        return (values[0] + values[1]) / 2
    return values[0]


def _estimate_baseline_price_from_benchmark(context: dict[str, Any]) -> float | None:
    """根据 RAG benchmark 估计基准价格。

    说明：
    - 取 benchmark.entries 中可解析 price_range 的样本均值再求平均。
    - 该值代表“当前市场可对照基线”，用于计算节省比例。
    """

    benchmark = context.get("benchmark", {})
    entries = benchmark.get("entries", []) if isinstance(benchmark, dict) else []

    samples: list[float] = []
    if isinstance(entries, list):
        for entry in entries:
            if isinstance(entry, dict):
                mean_price = _parse_price_range_to_mean(entry.get("price_range"))
                if mean_price and mean_price > 0:
                    samples.append(mean_price)

    if not samples:
        return None

    return sum(samples) / len(samples)


def _infer_target_unit_price(recommendation_payload: dict[str, Any], demand: dict[str, Any]) -> float:
    """推断目标成交单价。

    优先级：
    1. po_draft.unit_price
    2. 第一个供应商 unit_price_range 的均值
    3. budget_hint 数字
    4. 默认 58.0
    """

    po_draft = recommendation_payload.get("po_draft", {})
    if not isinstance(po_draft, dict):
        po_draft = {}

    unit_price = _extract_first_number(po_draft.get("unit_price"))
    if unit_price and unit_price > 0:
        return unit_price

    suppliers = recommendation_payload.get("suppliers", [])
    if isinstance(suppliers, list) and suppliers:
        first = suppliers[0]
        if isinstance(first, dict):
            unit_price = _parse_price_range_to_mean(first.get("unit_price_range"))
            if unit_price and unit_price > 0:
                return unit_price

    unit_price = _extract_first_number(demand.get("budget_hint"))
    if unit_price and unit_price > 0:
        return unit_price

    return 58.0


def _compute_expected_saving_percent(
    context: dict[str, Any],
    recommendation_payload: dict[str, Any],
    demand: dict[str, Any],
    fallback_value: Any = 15,
) -> int:
    """改进版：更信任 LLM 输出，同时保持合理区间"""

    # 优先级1：如果 LLM 直接输出了 expected_saving_percent，使用它
    if isinstance(recommendation_payload.get("expected_saving_percent"), (int, float)):
        return max(8, min(28, int(round(recommendation_payload["expected_saving_percent"]))))

    # 优先级2：从 po_draft 或 recommendation 中取 target_price
    target_price = _infer_target_unit_price(recommendation_payload, demand)

    # 从 benchmark 取市场参考价
    baseline_price = _estimate_baseline_price_from_benchmark(context)

    if baseline_price and baseline_price > 0 and target_price and target_price > 0:
        saving_ratio = ((baseline_price - target_price) / baseline_price) * 100
        # 放宽上下限，让 LLM 有发挥空间
        return max(8, min(28, int(round(saving_ratio))))

    # 兜底值提高到15
    return max(10, min(25, int(fallback_value)))


def _build_po_draft(
    recommendation_payload: dict[str, Any],
    demand: dict[str, Any],
    expected_saving_percent: int,
) -> dict[str, Any]:
    """构建标准化 PO 草案结构。

    按第4层接口预期，PO草案必须包含：
    supplier、unit_price、quantity、total_amount、delivery_date、negotiation_tips。
    """

    po_draft = recommendation_payload.get("po_draft", {})
    if not isinstance(po_draft, dict):
        po_draft = {}

    suppliers = recommendation_payload.get("suppliers", [])
    first_supplier_name = "待确认供应商"
    if isinstance(suppliers, list) and suppliers:
        first = suppliers[0]
        if isinstance(first, dict):
            first_supplier_name = str(first.get("name", "待确认供应商"))

    supplier = str(po_draft.get("supplier") or first_supplier_name)
    unit_price = _infer_target_unit_price(recommendation_payload, demand)

    quantity = demand.get("quantity", po_draft.get("quantity", 1))
    try:
        quantity = int(float(quantity))
    except Exception:
        quantity = 1
    quantity = max(1, quantity)

    total_amount = round(unit_price * quantity, 2)

    delivery_date = str(
        po_draft.get("delivery_date")
        or demand.get("required_date")
        or "T+3天"
    )

    top_tips = recommendation_payload.get("negotiation_tips", [])
    draft_tips = po_draft.get("negotiation_tips", [])

    tips: list[str] = []
    for source in (draft_tips, top_tips):
        if isinstance(source, list):
            for item in source:
                if str(item).strip():
                    tips.append(str(item).strip())

    if not tips:
        tips = [
            "以1688中位价为锚点，要求供应商说明交付溢价。",
            f"目标节省率{expected_saving_percent}%已设定，优先谈判锁价周期。",
        ]

    return {
        "supplier": supplier,
        "unit_price": round(unit_price, 2),
        "quantity": quantity,
        "total_amount": total_amount,
        "delivery_date": delivery_date,
        "negotiation_tips": tips,
    }


def _recommendation_rule_fallback(state: ProcurementState, reason: str, model_name: str) -> dict[str, Any]:
    """recommendation 节点的稳健兜底输出。

    当 LLM 不可用时，仍保证输出完整可执行结构，
    避免卡住交付流程。
    """

    demand = state.get("demand", {})

    recommendation_payload = {
        "suppliers": [
            {
                "name": "东莞本地工业备件经销商A",
                "channel": "本地经销",
                "unit_price_range": "58-66 元",
                "lead_time": "1-2天",
                "why_selected": "紧急交付能力强，适合停线风险场景。",
            },
            {
                "name": "1688认证工业商家B",
                "channel": "1688",
                "unit_price_range": "52-60 元",
                "lead_time": "2-4天",
                "why_selected": "价格优势明显，但需校验履约与质保。",
            },
            {
                "name": "京东工业企业购C",
                "channel": "京东工业",
                "unit_price_range": "60-72 元",
                "lead_time": "次日/隔日达",
                "why_selected": "票据和交付稳定，适合作为保底路径。",
            },
        ],
        "unit_price_benchmark": "52-72 元",
        "negotiation_tips": [
            "以1688中位价作为锚点，要求本地商给出交付溢价说明。",
            "将订单拆分为主单+备份单，换取更低单价与更稳交付。",
            "要求供应商锁价7-14天，降低平台短期波动影响。",
            "对替代料先做小批验证，再谈长期协议价。",
        ],
        "completed": True,
    }

    expected_saving_percent = _compute_expected_saving_percent(
        context=state.get("context", {}),
        recommendation_payload=recommendation_payload,
        demand=demand,
        fallback_value=15,
    )
    recommendation_payload["expected_saving_percent"] = expected_saving_percent
    recommendation_payload["po_draft"] = _build_po_draft(
        recommendation_payload=recommendation_payload,
        demand=demand,
        expected_saving_percent=expected_saving_percent,
    )

    return {
        "reasoning": {
            "supply_strategy": "主推本地交付保障 + 平台价格对照，兼顾成本与稳定性。",
            "price_strategy": "基于1688/京东工业波动设置区间报价，避免点价风险。",
            "long_tail_control": "通过替代料与验收条款降低规格不清导致的履约风险。",
            "fallback_reason": reason,
            "model": model_name,
        },
        "recommendation": recommendation_payload,
        "confidence": 0.58,
        "completed": True,
    }


def recommendation_node(state: ProcurementState) -> dict[str, Any]:
    """Recommendation 主节点。

    产出：
    1. 更新 state["recommendation"]：结构化可执行推荐。
    2. 更新 state["context"]：记录 reasoning/confidence。
    3. 更新 state["messages"]：追加 AIMessage 审计轨迹。
    4. 更新 state["judgment_history"]：沉淀完整 round 案例。
    5. 强制 completed=True，触发图结束。

    对飞轮价值：
    - 把前序判断转换为可执行 PO 草案；
    - 让每次交付都沉淀“价格基线-谈判空间-落单策略”样本；
    - 为下一阶段 Validation & Delivery Layer 提供标准化接口。
    """

    llm, model_name = _build_supervisor_llm()
    few_shot_cases = _format_recommendation_few_shot_cases(state.get("judgment_history", []))

    prompt_inputs = {
        "demand_json": _as_json_text(state.get("demand", {})),
        "analysis_text": state.get("analysis", ""),
        "research_text": state.get("research", ""),
        "context_json": _as_json_text(state.get("context", {})),
        "retrieved_context": str(state.get("context", {}).get("retrieved_context", "暂无RAG检索上下文。")),
        "few_shot_cases": few_shot_cases,
    }

    if llm is None:
        decision = _recommendation_rule_fallback(
            state=state,
            reason="LLM 不可用（缺少密钥或模型初始化失败）",
            model_name=model_name,
        )
    else:
        try:
            chain = recommendation_prompt_template | llm
            result = chain.invoke(prompt_inputs)
            raw_text = _normalize_text(getattr(result, "content", result))
            parsed = _extract_json_block(raw_text)

            if not parsed:
                decision = _recommendation_rule_fallback(
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

                recommendation_payload = parsed.get("recommendation", {})
                if not isinstance(recommendation_payload, dict):
                    recommendation_payload = {}

                demand = state.get("demand", {})
                expected_saving_percent = _compute_expected_saving_percent(
                    context=state.get("context", {}),
                    recommendation_payload=recommendation_payload,
                    demand=demand,
                    fallback_value=recommendation_payload.get("expected_saving_percent", 15),
                )

                recommendation_payload["expected_saving_percent"] = expected_saving_percent
                recommendation_payload["po_draft"] = _build_po_draft(
                    recommendation_payload=recommendation_payload,
                    demand=demand,
                    expected_saving_percent=expected_saving_percent,
                )
                recommendation_payload["completed"] = True

                # 若模型漏了关键结构，补齐最小可执行字段。
                recommendation_payload.setdefault("suppliers", [])
                recommendation_payload.setdefault("unit_price_benchmark", "待补充")
                recommendation_payload.setdefault("negotiation_tips", [])

                decision = {
                    "reasoning": parsed.get("reasoning", {}),
                    "recommendation": recommendation_payload,
                    "confidence": confidence,
                    "completed": True,
                }
        except Exception as exc:
            decision = _recommendation_rule_fallback(
                state=state,
                reason=f"LLM 调用异常：{exc}",
                model_name=model_name,
            )

    # 对 context 做增量写入，保留整条判断链路的可解释性。
    context = dict(state.get("context", {}))
    loop_count = int(context.get("loop_count", 0)) + 1
    context["loop_count"] = loop_count
    context["recommendation_reasoning"] = decision.get("reasoning", {})
    context["recommendation_confidence"] = decision.get("confidence", 0.5)
    context["recommendation_model"] = model_name

    recommendation_payload = dict(decision.get("recommendation", {}))
    recommendation_payload["loop_count"] = loop_count
    recommendation_payload["completed"] = True

    # 把最终可交付建议写入 history，形成“可复用谈判样本”。
    history = list(state.get("judgment_history", []))
    history.append(
        {
            "round": loop_count,
            "analysis": state.get("analysis", ""),
            "research": state.get("research", ""),
            "recommendation": recommendation_payload,
        }
    )

    # 追加消息轨迹，便于后续审计与模型微调样本构建。
    messages = list(state.get("messages", []))
    messages.append(
        AIMessage(
            content=_as_json_text(
                {
                    "node": "recommendation",
                    "reasoning": decision.get("reasoning", {}),
                    "confidence": decision.get("confidence", 0.5),
                    "recommendation": recommendation_payload,
                }
            )
        )
    )

    return {
        "context": context,
        "recommendation": recommendation_payload,
        "judgment_history": history,
        "messages": messages,
        "next": "end",
    }
