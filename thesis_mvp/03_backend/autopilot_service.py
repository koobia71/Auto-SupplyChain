"""Run LangGraph workflow and persist results into SQLite.

Enhancement v2:
- RAG retrieved_context injected into initial_state
- Delivery layer (validation → PDF → audit) called after graph.invoke
- execution_path clearly tagged ('langgraph' | 'fallback')
- PDF path returned for UI download
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

# Ensure project root on sys.path so data_layer / mvp_intelligence_layer import cleanly.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from repository import ThesisRepository, now_ms  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_rag_context(demand: dict[str, Any]) -> str:
    """Try to retrieve RAG benchmark context. Returns empty string on failure."""
    try:
        from data_layer.rag_utils import retrieve_benchmark_context
        item_name = demand.get("item_name", "")
        category = demand.get("category", "")
        query = f"{item_name} {category}".strip()
        ctx = retrieve_benchmark_context(query)
        return str(ctx) if ctx else ""
    except Exception as exc:  # noqa: BLE001
        return f"[RAG不可用: {exc}]"


def build_initial_state(demand: dict[str, Any], rag_context: str = "") -> dict[str, Any]:
    return {
        "demand": demand,
        "context": {
            "loop_count": 0,
            "retrieved_context": rag_context,
        },
        "analysis": "",
        "research": "",
        "recommendation": {},
        "judgment_history": [],
        "messages": [],
        "next": "analysis",
    }


def _run_with_fallback(initial_state: dict[str, Any]) -> dict[str, Any]:
    """Fallback pipeline when LangGraph dependencies are unavailable."""
    demand = initial_state["demand"]
    recommendation_payload = {
        "summary": f"推荐结果（fallback）：优先本地稳定交付供应商采购 {demand.get('item_name', '目标物料')}。",
        "suppliers": [
            {
                "name": "本地经销商",
                "channel": "本地经销",
                "unit_price_range": "58-66 元",
                "lead_time": "1-2天",
                "why_selected": "紧急交付能力强，适合停线风险场景。",
            }
        ],
        "expected_saving_percent": 15,
        "po_draft": {
            "supplier": "本地经销商",
            "unit_price": 60.0,
            "quantity": demand.get("quantity", 1),
            "total_amount": 60.0 * int(demand.get("quantity", 1)),
            "delivery_date": demand.get("required_date", "T+3天"),
            "negotiation_tips": [
                "强调紧急需求，请求尽快发货。",
                "询问是否可以接受目标预算内的报价。",
                "确认是否有现货及能否提供正规发票。",
            ],
        },
        "loop_count": 1,
        "completed": True,
    }
    return {
        **initial_state,
        "context": {
            **initial_state.get("context", {}),
            "execution_path": "fallback",
            "analysis_model": "rule-fallback",
            "research_model": "rule-fallback",
            "recommendation_model": "rule-fallback",
            "analysis_confidence": 0.5,
            "research_confidence": 0.5,
            "recommendation_confidence": 0.6,
        },
        "analysis": "【fallback分析】已按品类/规格/用量/风险四维拆解需求。",
        "research": "【fallback调研】已给出供应商路径、价格区间、替代建议与风险提示。",
        "recommendation": recommendation_payload,
        "judgment_history": [
            {
                "round": 1,
                "analysis": "【fallback分析】已按品类/规格/用量/风险四维拆解需求。",
                "research": "【fallback调研】已给出供应商路径、价格区间、替代建议与风险提示。",
                "recommendation": recommendation_payload,
            }
        ],
        "messages": [json.dumps({"node": "fallback", "reason": "langgraph_unavailable"}, ensure_ascii=False)],
        "next": "end",
    }


def _run_delivery(final_state: dict[str, Any]) -> tuple[str, str]:
    """Call validation & delivery layer. Returns (status, pdf_path)."""
    try:
        from validation_delivery_layer.delivery import run_delivery_workflow
        updated_state = run_delivery_workflow(final_state)
        context = updated_state.get("context", {})
        pdf_path = context.get("pdf_report_path", "")
        status = context.get("delivery_status", "unknown")
        return status, pdf_path
    except Exception as exc:  # noqa: BLE001
        return f"delivery_error:{exc}", ""


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_autopilot_and_persist(
    db_path: Path,
    demand: dict[str, Any],
    source_channel: str = "portal",
    skip_delivery: bool = False,
) -> dict[str, Any]:
    """Run full autopilot pipeline and persist all artifacts to SQLite.

    Returns a dict with:
        run_uid, demand_uid, duration_ms, final_state,
        execution_path, delivery_status, pdf_path
    """
    repo = ThesisRepository(db_path=db_path)
    demand_uid = repo.create_demand(demand=demand, source_channel=source_channel)
    run_uid = repo.create_run(demand_uid=demand_uid)
    repo.mark_run_running(run_uid=run_uid)

    # ---- RAG context -------------------------------------------------------
    rag_context = _load_rag_context(demand)

    # ---- Graph invocation --------------------------------------------------
    t0 = now_ms()
    initial_state = build_initial_state(demand, rag_context=rag_context)
    execution_path = "fallback"
    try:
        from mvp_intelligence_layer.graph import graph  # noqa: PLC0415

        final_state = graph.invoke(initial_state)
        execution_path = "langgraph"
        context = dict(final_state.get("context", {}))
        context["execution_path"] = "langgraph"
        final_state["context"] = context
    except ModuleNotFoundError:
        final_state = _run_with_fallback(initial_state)

    duration_ms = now_ms() - t0

    # ---- Delivery layer ----------------------------------------------------
    delivery_status, pdf_path = "skipped", ""
    if not skip_delivery:
        delivery_status, pdf_path = _run_delivery(final_state)
        # Write pdf_path back into context so node_outputs can reference it
        ctx = dict(final_state.get("context", {}))
        ctx["pdf_report_path"] = pdf_path
        ctx["delivery_status"] = delivery_status
        final_state["context"] = ctx

    # ---- Persist -----------------------------------------------------------
    repo.persist_node_outputs(run_uid=run_uid, final_state=final_state)
    repo.persist_judgment_cases(run_uid=run_uid, final_state=final_state)
    repo.mark_run_completed(run_uid=run_uid, final_state=final_state, duration_ms=duration_ms)

    return {
        "run_uid": run_uid,
        "demand_uid": demand_uid,
        "duration_ms": duration_ms,
        "execution_path": execution_path,
        "delivery_status": delivery_status,
        "pdf_path": pdf_path,
        "final_state": final_state,
    }
