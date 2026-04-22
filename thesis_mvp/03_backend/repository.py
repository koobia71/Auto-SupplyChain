"""SQLite repository for thesis MVP demo flow."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any


class ThesisRepository:
    """Minimal persistence layer for demand/run lifecycle."""

    def __init__(self, db_path: Path):
        self.db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def create_demand(self, demand: dict[str, Any], source_channel: str = "portal") -> str:
        demand_uid = f"demand_{uuid.uuid4().hex[:12]}"
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO demands (
                    demand_uid, source_channel, factory_city, category, item_name, spec,
                    quantity, required_date, budget_hint, demand_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    demand_uid,
                    source_channel,
                    demand.get("factory_city"),
                    demand.get("category", ""),
                    demand.get("item_name", ""),
                    demand.get("spec"),
                    demand.get("quantity"),
                    demand.get("required_date"),
                    demand.get("budget_hint"),
                    json.dumps(demand, ensure_ascii=False),
                ),
            )
            conn.commit()
        return demand_uid

    def create_run(self, demand_uid: str) -> str:
        run_uid = f"run_{uuid.uuid4().hex[:12]}"
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO runs (run_uid, demand_uid, status, current_node)
                VALUES (?, ?, 'queued', 'supervisor')
                """,
                (run_uid, demand_uid),
            )
            conn.commit()
        return run_uid

    def mark_run_running(self, run_uid: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE runs SET status='running', started_at=datetime('now') WHERE run_uid=?",
                (run_uid,),
            )
            conn.commit()

    def mark_run_completed(self, run_uid: str, final_state: dict[str, Any], duration_ms: int) -> None:
        context = final_state.get("context", {})
        recommendation = final_state.get("recommendation", {})
        messages = final_state.get("messages", [])
        route_model = None
        if isinstance(messages, list):
            for msg in messages:
                payload = self._parse_message_payload(msg)
                if payload.get("node") == "supervisor":
                    route_model = payload.get("model")
                    break
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE runs
                SET status='completed',
                    current_node='end',
                    finished_at=datetime('now'),
                    duration_ms=?,
                    loop_count=?,
                    supervisor_model=?,
                    analysis_model=?,
                    research_model=?,
                    estimated_saving_rate=?
                WHERE run_uid=?
                """,
                (
                    duration_ms,
                    int(context.get("loop_count", 0)),
                    route_model or context.get("supervisor_model"),
                    context.get("analysis_model"),
                    context.get("research_model"),
                    self._estimate_saving_rate(recommendation),
                    run_uid,
                ),
            )
            conn.commit()

    def persist_node_outputs(self, run_uid: str, final_state: dict[str, Any]) -> None:
        context = final_state.get("context", {})
        rows: list[tuple[Any, ...]] = []

        rows.append(
            (
                run_uid,
                "analysis",
                final_state.get("analysis", ""),
                json.dumps(context.get("analysis_reasoning", {}), ensure_ascii=False),
                float(context.get("analysis_confidence", 0.0)),
                context.get("analysis_model"),
                "research",
            )
        )
        rows.append(
            (
                run_uid,
                "research",
                final_state.get("research", ""),
                json.dumps(context.get("research_reasoning", {}), ensure_ascii=False),
                float(context.get("research_confidence", 0.0)),
                context.get("research_model"),
                "recommendation",
            )
        )
        rows.append(
            (
                run_uid,
                "recommendation",
                json.dumps(final_state.get("recommendation", {}), ensure_ascii=False),
                json.dumps(context.get("recommendation_reasoning", {}), ensure_ascii=False),
                float(context.get("recommendation_confidence", 0.8)),
                context.get("recommendation_model") or "rule-stub",
                final_state.get("next", "end"),
            )
        )

        # 从 messages 中补充 supervisor / delivery_workflow 等节点轨迹。
        for msg in final_state.get("messages", []) if isinstance(final_state.get("messages"), list) else []:
            payload = self._parse_message_payload(msg)
            node_name = str(payload.get("node", "")).strip()
            if not node_name or node_name in {"analysis", "research", "recommendation"}:
                continue
            rows.append(
                (
                    run_uid,
                    node_name,
                    self._build_message_output_text(payload),
                    json.dumps(payload.get("reasoning", {}), ensure_ascii=False),
                    self._safe_float(payload.get("confidence"), default=0.0),
                    str(payload.get("model", "unknown")),
                    str(payload.get("next", payload.get("route_next", "end"))),
                )
            )

        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO node_outputs (
                    run_uid, node_name, output_text, reasoning_json, confidence, model_name, route_next
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            conn.commit()

    def persist_judgment_cases(self, run_uid: str, final_state: dict[str, Any]) -> None:
        history = final_state.get("judgment_history", [])
        rows: list[tuple[Any, ...]] = []
        for case in history:
            case_uid = f"case_{uuid.uuid4().hex[:12]}"
            rows.append(
                (
                    case_uid,
                    run_uid,
                    int(case.get("round", 1)),
                    final_state.get("demand", {}).get("category", "unknown"),
                    case.get("analysis", ""),
                    case.get("research", ""),
                    json.dumps(case.get("recommendation", {}), ensure_ascii=False),
                )
            )

        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO judgment_cases (
                    case_uid, run_uid, round, category, analysis_text, research_text, recommendation_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            conn.commit()

    def list_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT run_uid, demand_uid, status, current_node, started_at, finished_at, duration_ms
                FROM runs
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_run_detail(self, run_uid: str) -> dict[str, Any]:
        with self._connect() as conn:
            run_row = conn.execute(
                """
                SELECT run_uid, demand_uid, status, current_node, started_at, finished_at,
                       duration_ms, loop_count, supervisor_model, analysis_model,
                       research_model, estimated_saving_rate, human_in_loop
                FROM runs
                WHERE run_uid=?
                """,
                (run_uid,),
            ).fetchone()
            if not run_row:
                return {}

            demand_row = conn.execute(
                "SELECT demand_json, source_channel, category, item_name FROM demands WHERE demand_uid=?",
                (run_row["demand_uid"],),
            ).fetchone()
            node_rows = conn.execute(
                """
                SELECT node_name, output_text, reasoning_json, confidence, model_name, route_next, created_at
                FROM node_outputs
                WHERE run_uid=?
                ORDER BY id ASC
                """,
                (run_uid,),
            ).fetchall()
            case_rows = conn.execute(
                """
                SELECT case_uid, round, category, analysis_text, research_text, recommendation_json, created_at
                FROM judgment_cases
                WHERE run_uid=?
                ORDER BY id ASC
                """,
                (run_uid,),
            ).fetchall()
            feedback_rows = conn.execute(
                """
                SELECT feedback_uid, adopted_status, rating, correction_note, not_adopt_reason, created_at
                FROM feedbacks
                WHERE run_uid=?
                ORDER BY id DESC
                """,
                (run_uid,),
            ).fetchall()

        return {
            "run": dict(run_row),
            "demand": self._json_or_empty(demand_row["demand_json"]) if demand_row else {},
            "source_channel": demand_row["source_channel"] if demand_row else None,
            "node_outputs": [self._format_node_output(dict(r)) for r in node_rows],
            "judgment_cases": [self._format_judgment_case(dict(r)) for r in case_rows],
            "feedbacks": [dict(r) for r in feedback_rows],
        }

    def create_feedback(
        self,
        *,
        run_uid: str,
        adopted_status: str,
        rating: int | None = None,
        correction_note: str | None = None,
        not_adopt_reason: str | None = None,
    ) -> str:
        feedback_uid = f"fb_{uuid.uuid4().hex[:12]}"
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO feedbacks (
                    feedback_uid, run_uid, adopted_status, rating, correction_note, not_adopt_reason
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (feedback_uid, run_uid, adopted_status, rating, correction_note, not_adopt_reason),
            )
            conn.commit()
        return feedback_uid

    def export_experiment_rows(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    r.run_uid,
                    d.category,
                    d.factory_city,
                    d.item_name,
                    r.duration_ms,
                    r.loop_count,
                    r.estimated_saving_rate,
                    r.human_in_loop,
                    COUNT(DISTINCT n.id) AS node_count,
                    COUNT(DISTINCT c.id) AS judgment_case_count,
                    COUNT(DISTINCT f.id) AS feedback_count,
                    AVG(CASE WHEN n.confidence IS NOT NULL THEN n.confidence END) AS avg_confidence
                FROM runs r
                JOIN demands d ON d.demand_uid = r.demand_uid
                LEFT JOIN node_outputs n ON n.run_uid = r.run_uid
                LEFT JOIN judgment_cases c ON c.run_uid = r.run_uid
                LEFT JOIN feedbacks f ON f.run_uid = r.run_uid
                GROUP BY r.run_uid
                ORDER BY r.id ASC
                """
            ).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def _estimate_saving_rate(recommendation: dict[str, Any]) -> float:
        value = recommendation.get("expected_saving_percent")
        try:
            if value is not None:
                return round(float(value) / 100.0, 4)
        except Exception:
            pass
        if recommendation.get("completed"):
            return 0.10
        return 0.0

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except Exception:
            return default

    @staticmethod
    def _json_or_empty(value: Any) -> dict[str, Any]:
        if not value:
            return {}
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def _parse_message_payload(msg: Any) -> dict[str, Any]:
        content = getattr(msg, "content", msg)
        if not isinstance(content, str):
            content = str(content)
        try:
            parsed = json.loads(content)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def _build_message_output_text(payload: dict[str, Any]) -> str:
        if "main_output" in payload:
            return str(payload.get("main_output", ""))
        if "recommendation" in payload:
            return json.dumps(payload.get("recommendation", {}), ensure_ascii=False)
        if "status" in payload:
            return json.dumps(
                {"status": payload.get("status"), "report_path": payload.get("report_path")},
                ensure_ascii=False,
            )
        return json.dumps(payload, ensure_ascii=False)

    @staticmethod
    def _format_node_output(row: dict[str, Any]) -> dict[str, Any]:
        reasoning_raw = row.get("reasoning_json", "{}")
        try:
            reasoning = json.loads(reasoning_raw) if isinstance(reasoning_raw, str) else {}
        except Exception:
            reasoning = {}
        row["reasoning"] = reasoning if isinstance(reasoning, dict) else {}
        return row

    @staticmethod
    def _format_judgment_case(row: dict[str, Any]) -> dict[str, Any]:
        rec_raw = row.get("recommendation_json", "{}")
        try:
            recommendation = json.loads(rec_raw) if isinstance(rec_raw, str) else {}
        except Exception:
            recommendation = {}
        row["recommendation"] = recommendation if isinstance(recommendation, dict) else {}
        return row


def now_ms() -> int:
    return int(datetime.utcnow().timestamp() * 1000)
