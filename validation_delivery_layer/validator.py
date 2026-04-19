"""Validation & Delivery Layer - 轻量自检模块。

本模块目标：
1. 在 Intelligence Layer 产出 recommendation 后做最小可交付校验；
2. 用可量化规则（confidence、节省%、PO完整性）决定是否自动交付；
3. 将校验结果结构化写回 state，供 Delivery 层和后续飞轮复盘使用。

与 Sequoia judgment -> intelligence 飞轮关系：
- 若交付前校验不过，系统会触发 human-in-loop，避免低质量判断污染案例库；
- 若校验通过，交付结果与校验指标会沉淀到历史，成为未来判断的高质量样本。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any


def _to_float(value: Any, default: float = 0.0) -> float:
    """安全转换为 float，避免脏数据导致校验中断。"""

    try:
        return float(value)
    except Exception:
        return default


def _to_int(value: Any, default: int = 0) -> int:
    """安全转换为 int，避免脏数据导致校验中断。"""

    try:
        return int(round(float(value)))
    except Exception:
        return default


def validate_delivery_readiness(state: dict[str, Any]) -> dict[str, Any]:
    """执行轻量自检，返回 state patch。

    校验项：
    1. recommendation_confidence > 0.75
    2. expected_saving_percent 在 10-25
    3. po_draft 包含关键字段

    返回字段：
    - validation_flags: 详细校验结果
    - delivery_ready: 是否可自动交付
    - context: human_in_loop 标记与时间戳
    """

    context = dict(state.get("context", {}))
    validation_flags = dict(state.get("validation_flags", {}))

    recommendation = state.get("recommendation", {})
    if not isinstance(recommendation, dict):
        recommendation = {}

    po_draft = recommendation.get("po_draft", {})
    if not isinstance(po_draft, dict):
        po_draft = {}

    confidence = _to_float(context.get("recommendation_confidence", 0.0), default=0.0)
    saving_percent = _to_int(recommendation.get("expected_saving_percent", 0), default=0)

    required_po_fields = [
        "supplier",
        "unit_price",
        "quantity",
        "total_amount",
        "delivery_date",
        "negotiation_tips",
    ]
    missing_fields = [field for field in required_po_fields if field not in po_draft]

    # negotiation_tips 需为非空列表，保证交付件具备可执行谈判动作。
    tips = po_draft.get("negotiation_tips", [])
    tips_ok = isinstance(tips, list) and len(tips) > 0
    if not tips_ok and "negotiation_tips" not in missing_fields:
        missing_fields.append("negotiation_tips(非空列表)")

    confidence_ok = confidence > 0.75
    saving_ok = 10 <= saving_percent <= 25
    po_complete = len(missing_fields) == 0

    # 总分用于后续可视化监控：三项各占一分。
    score = int(confidence_ok) + int(saving_ok) + int(po_complete)

    delivery_ready = confidence_ok and saving_ok and po_complete
    human_in_loop = not delivery_ready

    validation_flags.update(
        {
            "validated_at": datetime.now().isoformat(timespec="seconds"),
            "confidence": confidence,
            "confidence_ok": confidence_ok,
            "expected_saving_percent": saving_percent,
            "saving_percent_ok": saving_ok,
            "po_complete": po_complete,
            "missing_po_fields": missing_fields,
            "validation_score": score,
            "human_in_loop": human_in_loop,
        }
    )

    context["human_in_loop"] = human_in_loop
    context["validation_score"] = score

    return {
        "validation_flags": validation_flags,
        "delivery_ready": delivery_ready,
        "context": context,
    }
