"""Validation & Delivery Layer - 交付与审计沉淀模块。

本模块负责：
1. 调用 validator 做交付前校验；
2. 调用 report_generator 生成 PDF 报告；
3. 模拟微信/邮件交付；
4. 将交付记录写入 SQLite；
5. 把 delivery_feedback 回写到 judgment_history，形成闭环。

与 Sequoia judgment -> intelligence 飞轮关系：
- 每次交付都会产生可量化的“结果+反馈”记录；
- 这些记录沉淀后可反哺下一次决策，持续提升自动化质量。
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from typing import Any

from langchain_core.messages import AIMessage

from validation_delivery_layer.report_generator import generate_validation_report
from validation_delivery_layer.validator import validate_delivery_readiness


def _default_db_path() -> str:
    """默认 SQLite 路径。"""

    base_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_dir, "delivery_audit.db")


def _simulate_wechat_delivery(report_path: str, state: dict[str, Any]) -> str:
    """模拟微信交付（MVP阶段）。"""

    demand = state.get("demand", {}) if isinstance(state.get("demand"), dict) else {}
    return (
        f"[微信模拟] 已向采购负责人推送报告：{report_path} | "
        f"工厂={demand.get('factory_city', 'N/A')} | 物料={demand.get('item_name', 'N/A')}"
    )


def _simulate_email_delivery(report_path: str, state: dict[str, Any]) -> str:
    """模拟邮件交付（MVP阶段）。"""

    demand = state.get("demand", {}) if isinstance(state.get("demand"), dict) else {}
    return (
        f"[邮件模拟] 已发送采购报告附件：{report_path} | "
        f"主题=AutoProcurement交付-{demand.get('item_name', 'N/A')}"
    )


def _persist_delivery_record(
    *,
    state: dict[str, Any],
    report_path: str,
    status: str,
    channels: str,
    db_path: str,
) -> int:
    """写入 SQLite 交付记录，返回记录ID。"""

    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    demand = state.get("demand", {}) if isinstance(state.get("demand"), dict) else {}
    recommendation = state.get("recommendation", {}) if isinstance(state.get("recommendation"), dict) else {}
    validation_flags = state.get("validation_flags", {}) if isinstance(state.get("validation_flags"), dict) else {}
    judgment_history = state.get("judgment_history", []) if isinstance(state.get("judgment_history"), list) else []

    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS delivery_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                factory_city TEXT,
                item_name TEXT,
                status TEXT,
                channels TEXT,
                report_path TEXT,
                expected_saving_percent REAL,
                delivery_ready INTEGER,
                recommendation_json TEXT,
                validation_flags_json TEXT,
                judgment_history_count INTEGER
            )
            """
        )

        cursor = conn.execute(
            """
            INSERT INTO delivery_records (
                created_at,
                factory_city,
                item_name,
                status,
                channels,
                report_path,
                expected_saving_percent,
                delivery_ready,
                recommendation_json,
                validation_flags_json,
                judgment_history_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now().isoformat(timespec="seconds"),
                str(demand.get("factory_city", "")),
                str(demand.get("item_name", "")),
                status,
                channels,
                report_path,
                float(recommendation.get("expected_saving_percent", 0) or 0),
                1 if state.get("delivery_ready") else 0,
                json.dumps(recommendation, ensure_ascii=False),
                json.dumps(validation_flags, ensure_ascii=False),
                len(judgment_history),
            ),
        )
        conn.commit()
        return int(cursor.lastrowid)
    finally:
        conn.close()


def get_delivery_record_count(db_path: str | None = None) -> int:
    """查询交付记录总数。"""

    if db_path is None:
        db_path = _default_db_path()

    if not os.path.exists(db_path):
        return 0

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute("SELECT COUNT(1) FROM delivery_records")
        row = cursor.fetchone()
        return int(row[0]) if row else 0
    finally:
        conn.close()


def run_delivery_workflow(state: dict[str, Any]) -> dict[str, Any]:
    """执行完整交付工作流（validator -> report -> delivery -> sqlite -> feedback）。

    返回 state patch，可直接作为 LangGraph 节点输出使用。
    """

    context = dict(state.get("context", {}))

    # 幂等保护：若本次状态已完成交付，则不重复写库。
    if context.get("delivery_completed") is True and context.get("report_path"):
        return {
            "context": context,
            "validation_flags": state.get("validation_flags", {}),
            "delivery_ready": state.get("delivery_ready", False),
            "judgment_history": state.get("judgment_history", []),
            "messages": state.get("messages", []),
            "next": "end",
        }

    # 1) 自检
    validation_patch = validate_delivery_readiness(state)

    merged_context = dict(context)
    merged_context.update(validation_patch.get("context", {}))

    merged_state = dict(state)
    merged_state.update(validation_patch)
    merged_state["context"] = merged_context

    # 2) 生成交付报告
    report_path = generate_validation_report(merged_state)

    # 3) 模拟交付
    delivery_ready = bool(merged_state.get("delivery_ready", False))
    if delivery_ready:
        wx_result = _simulate_wechat_delivery(report_path, merged_state)
        email_result = _simulate_email_delivery(report_path, merged_state)
        channels = "wechat,email"
        status = "auto_delivered"
    else:
        wx_result = "[人工介入] 自检未通过，已转人工审核通道。"
        email_result = "[人工介入] 已发送人工复核提醒邮件。"
        channels = "manual_review"
        status = "human_in_loop"

    # 4) 写入 SQLite 审计记录
    db_path = _default_db_path()
    record_id = _persist_delivery_record(
        state=merged_state,
        report_path=report_path,
        status=status,
        channels=channels,
        db_path=db_path,
    )

    # 5) 回写 delivery_feedback 到 judgment_history，形成闭环样本。
    history = list(merged_state.get("judgment_history", []))
    feedback = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "status": status,
        "channels": channels,
        "report_path": report_path,
        "delivery_record_id": record_id,
        "delivery_ready": delivery_ready,
        "validator_score": merged_state.get("validation_flags", {}).get("validation_score", "N/A"),
    }

    if history:
        latest = dict(history[-1]) if isinstance(history[-1], dict) else {"round": len(history)}
        latest["delivery_feedback"] = feedback
        history[-1] = latest
    else:
        history.append({"round": 0, "delivery_feedback": feedback})

    # 6) 更新 context 与消息轨迹。
    updated_context = dict(merged_context)
    updated_context["report_path"] = report_path
    updated_context["delivery_db_path"] = db_path
    updated_context["delivery_record_id"] = record_id
    updated_context["delivery_channels"] = channels
    updated_context["delivery_completed"] = True

    messages = list(merged_state.get("messages", []))
    messages.append(
        AIMessage(
            content=json.dumps(
                {
                    "node": "delivery_workflow",
                    "status": status,
                    "delivery_ready": delivery_ready,
                    "report_path": report_path,
                    "delivery_record_id": record_id,
                    "wechat_result": wx_result,
                    "email_result": email_result,
                },
                ensure_ascii=False,
            )
        )
    )

    return {
        "context": updated_context,
        "validation_flags": merged_state.get("validation_flags", {}),
        "delivery_ready": delivery_ready,
        "judgment_history": history,
        "messages": messages,
        "next": "end",
    }


def delivery_workflow_node(state: dict[str, Any]) -> dict[str, Any]:
    """LangGraph节点包装器：直接调用 run_delivery_workflow。"""

    return run_delivery_workflow(state)
