"""Export chapter 5/6 chart inputs from thesis_mvp.db.

Reads all completed runs from SQLite and generates:
  - chapter5_ablation.csv   : ablation study comparison (5.2/5.3节)
  - chapter5_kpi.csv        : business KPI per run (5.4节)
  - chapter6_cases.csv      : per-demand case pack (6.2节案例)
  - chapter6_summary.csv    : category-level summary (6.3节)

Usage:
    conda activate auto_sc
    cd /Users/col/Desktop/Auto_SupplyChain
    python thesis_mvp/04_experiments/export_charts.py

Output folder: thesis_mvp/04_experiments/generated/
"""

from __future__ import annotations

import csv
import json
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[2]
_BACKEND = _ROOT / "thesis_mvp" / "03_backend"
DB_PATH = _BACKEND / "thesis_mvp.db"
GEN_DIR = Path(__file__).resolve().parent / "generated"
GEN_DIR.mkdir(exist_ok=True)


# ── DB helpers ────────────────────────────────────────────────────────────────

def _fetchall(db: Path, sql: str, params: tuple = ()) -> list[dict]:
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def load_runs() -> list[dict]:
    return _fetchall(DB_PATH, """
        SELECT r.*,
               d.category, d.factory_city, d.item_name, d.quantity,
               d.budget_hint, d.required_date, d.spec,
               d.source_channel, d.demand_json
        FROM runs r
        LEFT JOIN demands d ON d.demand_uid = r.demand_uid
        ORDER BY r.started_at
    """)


def load_node_outputs() -> list[dict]:
    return _fetchall(DB_PATH, """
        SELECT no.*, r.demand_uid
        FROM node_outputs no
        LEFT JOIN runs r ON r.run_uid = no.run_uid
        ORDER BY no.run_uid, no.id
    """)


def load_judgment_cases() -> list[dict]:
    return _fetchall(DB_PATH, """
        SELECT jc.*, r.demand_uid
        FROM judgment_cases jc
        LEFT JOIN runs r ON r.run_uid = jc.run_uid
        ORDER BY jc.run_uid, jc.round
    """)


# ── Export helpers ────────────────────────────────────────────────────────────

def _write_csv(rows: list[dict], path: Path) -> None:
    if not rows:
        print(f"  [WARN] No data for {path.name}")
        return
    fieldnames = list(rows[0].keys())
    for row in rows:
        for k in fieldnames:
            row.setdefault(k, "")
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"  ✓ {path.name}  ({len(rows)} rows)")


# ── Chapter 5: Ablation + KPI ─────────────────────────────────────────────────

def export_chapter5(runs: list[dict], node_outputs: list[dict]) -> None:
    """Generate ablation comparison and KPI tables."""

    # Group node outputs by run_uid for fast lookup
    nodes_by_run: dict[str, list[dict]] = defaultdict(list)
    for n in node_outputs:
        nodes_by_run[n["run_uid"]].append(n)

    kpi_rows: list[dict] = []
    ablation_rows: list[dict] = []

    for r in runs:
        uid = r["run_uid"]
        nodes = nodes_by_run.get(uid, [])

        # Parse context JSON for confidence values
        ctx = {}
        for n in nodes:
            raw = n.get("output_json") or "{}"
            try:
                parsed = json.loads(raw)
                ctx.update(parsed)
            except Exception:
                pass

        # Collect confidence from node_outputs.confidence column directly
        node_confs = [float(n["confidence"]) for n in nodes if n.get("confidence") is not None]
        # Also try parsing from output_text / reasoning_json
        for n in nodes:
            rj = n.get("reasoning_json") or "{}"
            try:
                rjp = json.loads(rj)
                if isinstance(rjp, dict) and "confidence" in rjp:
                    pass  # already captured via node_confs
            except Exception:
                pass
        confidences = node_confs if node_confs else []
        avg_conf = round(sum(confidences) / len(confidences), 3) if confidences else 0.0

        saving_pct = r.get("estimated_saving_rate", 0) or 0
        if saving_pct <= 1.0:  # stored as decimal
            saving_pct = round(saving_pct * 100, 1)

        node_count = len(nodes)
        exec_path = "langgraph"
        duration_s = round((r.get("duration_ms", 0) or 0) / 1000, 1)
        loop = r.get("loop_count", 1) or 1
        first_pass = 1 if loop <= 1 else 0

        # Detect ablation config from source_channel or meta
        config_id = r.get("source_channel", "A1")
        if config_id not in ("A1", "A2", "A3", "A4"):
            config_id = "A1"  # default to full system

        kpi_row = {
            "run_uid": uid,
            "demand_uid": r.get("demand_uid", ""),
            "config_id": config_id,
            "category": r.get("category", ""),
            "factory_city": r.get("factory_city", ""),
            "item_name": r.get("item_name", ""),
            "quantity": r.get("quantity", ""),
            "execution_path": exec_path,
            "duration_s": duration_s,
            "loop_count": loop,
            "first_pass": first_pass,
            "node_count": node_count,
            "avg_confidence": avg_conf,
            "analysis_confidence": next((n["confidence"] for n in nodes if n.get("node_name") == "analysis"), ""),
            "research_confidence": next((n["confidence"] for n in nodes if n.get("node_name") == "research"), ""),
            "recommendation_confidence": next((n["confidence"] for n in nodes if n.get("node_name") == "recommendation"), ""),
            "saving_pct": saving_pct,
            "saving_rate": round(saving_pct / 100, 4),
            "status": r.get("status", ""),
            "human_in_loop": r.get("human_in_loop", 0),
            "started_at": r.get("started_at", ""),
            "finished_at": r.get("finished_at", ""),
        }
        kpi_rows.append(kpi_row)

        ablation_row = {
            "run_uid": uid,
            "config_id": config_id,
            "demand_uid": r.get("demand_uid", ""),
            "category": r.get("category", ""),
            "avg_confidence": avg_conf,
            "saving_pct": saving_pct,
            "duration_s": duration_s,
            "first_pass": first_pass,
            "loop_count": loop,
            "node_count": node_count,
        }
        ablation_rows.append(ablation_row)

    _write_csv(kpi_rows, GEN_DIR / "chapter5_kpi.csv")
    _write_csv(ablation_rows, GEN_DIR / "chapter5_ablation.csv")

    # Also overwrite the standard chapter5_inputs.csv
    _write_csv(kpi_rows, GEN_DIR / "chapter5_inputs.csv")

    # ── Ablation summary: aggregate by config_id (filter invalid LLM runs with saving=0 + duration≈0) ──
    from collections import defaultdict as _dd
    cfg_agg: dict[str, dict] = _dd(lambda: {"n": 0, "saving_sum": 0.0, "conf_sum": 0.0,
                                             "dur_sum": 0.0, "fp_sum": 0})
    for row in ablation_rows:
        cfg = row.get("config_id", "A1")
        saving = float(row.get("saving_pct", 0) or 0)
        dur = float(row.get("duration_s", 0) or 0)
        conf = float(row.get("avg_confidence", 0) or 0)
        fp = int(row.get("first_pass", 1) or 1)
        # Filter: non-A3 runs with saving=0 AND duration<1s are invalid (broken LLM runs)
        # A3 legitimately has dur=0 (no LLM), so only filter other configs
        if saving == 0 and dur < 1.0 and cfg != "A3":
            continue  # skip broken/invalid LLM runs
        agg = cfg_agg[cfg]
        agg["n"] += 1
        agg["saving_sum"] += saving
        agg["conf_sum"] += conf
        agg["dur_sum"] += dur
        agg["fp_sum"] += fp

    config_labels = {
        "A1": "完整系统（few-shot+messages+supervisor）",
        "A2": "无few-shot（judgment_history清空）",
        "A3": "规则基线（无LLM调用）",
        "A4": "无supervisor LLM（规则路由替代）",
    }
    summary_rows: list[dict] = []
    for cfg in ["A1", "A2", "A3", "A4"]:
        if cfg not in cfg_agg:
            continue
        agg = cfg_agg[cfg]
        n = max(agg["n"], 1)
        summary_rows.append({
            "config_id": cfg,
            "label": config_labels.get(cfg, cfg),
            "n_valid_runs": agg["n"],
            "avg_saving_pct": round(agg["saving_sum"] / n, 1),
            "avg_confidence": round(agg["conf_sum"] / n, 3),
            "avg_duration_s": round(agg["dur_sum"] / n, 1),
            "first_pass_rate": round(agg["fp_sum"] / n, 3),
        })
    _write_csv(summary_rows, GEN_DIR / "chapter5_ablation_summary.csv")
    print(f"  ✓ chapter5_ablation_summary.csv  ({len(summary_rows)} configs)")


# ── Chapter 6: Case pack + Category summary ───────────────────────────────────

def export_chapter6(runs: list[dict], judgment_cases: list[dict], node_outputs: list[dict] | None = None) -> None:
    """Generate per-demand cases and category summary."""

    jc_by_run: dict[str, list[dict]] = defaultdict(list)
    for jc in judgment_cases:
        jc_by_run[jc["run_uid"]].append(jc)

    nodes_by_run: dict[str, list[dict]] = defaultdict(list)
    for n in (node_outputs or []):
        nodes_by_run[n["run_uid"]].append(n)

    case_rows: list[dict] = []
    cat_agg: dict[str, dict] = defaultdict(lambda: {
        "n": 0, "saving_sum": 0.0, "conf_sum": 0.0,
        "first_pass_sum": 0, "duration_sum": 0.0,
    })

    for r in runs:
        uid = r["run_uid"]
        jcs = jc_by_run.get(uid, [])

        saving_pct = r.get("estimated_saving_rate", 0) or 0
        if saving_pct <= 1.0:
            saving_pct = round(saving_pct * 100, 1)

        # avg_confidence: compute from node_outputs
        nodes = nodes_by_run.get(uid, [])
        node_confs = [float(n["confidence"]) for n in nodes if n.get("confidence") is not None]
        avg_conf = round(sum(node_confs) / len(node_confs), 3) if node_confs else 0.0
        duration_s = round((r.get("duration_ms", 0) or 0) / 1000, 1)
        loop = r.get("loop_count", 1) or 1
        first_pass = 1 if loop <= 1 else 0

        # Get judgments summary from judgment_cases (round, category, recommendation_json)
        judgment_summary = []
        for jc in jcs:
            rec = {}
            try:
                rec = json.loads(jc.get("recommendation_json") or "{}")
            except Exception:
                pass
            judgment_summary.append({
                "round": jc.get("round", ""),
                "category": jc.get("category", ""),
                "supplier": rec.get("supplier", "") if isinstance(rec, dict) else "",
            })

        case_row = {
            "run_uid": uid,
            "demand_uid": r.get("demand_uid", ""),
            "category": r.get("category", ""),
            "factory_city": r.get("factory_city", ""),
            "item_name": r.get("item_name", ""),
            "spec": r.get("spec", ""),
            "quantity": r.get("quantity", ""),
            "budget_hint": r.get("budget_hint", ""),
            "required_date": r.get("required_date", ""),
            "execution_path": "langgraph",
            "duration_s": duration_s,
            "loop_count": loop,
            "first_pass": first_pass,
            "avg_confidence": avg_conf,
            "saving_pct": saving_pct,
            "saving_amount_hint": "",  # to be computed post-hoc
            "status": r.get("status", ""),
            "human_in_loop": r.get("human_in_loop", 0),
            "judgment_count": len(jcs),
            "judgment_summary": json.dumps(judgment_summary, ensure_ascii=False)[:200],
            "started_at": r.get("started_at", ""),
        }
        case_rows.append(case_row)

        # Aggregate by category
        cat = r.get("category", "未知")
        agg = cat_agg[cat]
        agg["n"] += 1
        agg["saving_sum"] += saving_pct
        agg["conf_sum"] += float(avg_conf)
        agg["first_pass_sum"] += first_pass
        agg["duration_sum"] += duration_s

    _write_csv(case_rows, GEN_DIR / "chapter6_cases.csv")
    # Also overwrite chapter6_casepack.csv
    _write_csv(case_rows, GEN_DIR / "chapter6_casepack.csv")

    # Category summary
    summary_rows = []
    for cat, agg in cat_agg.items():
        n = agg["n"] or 1
        summary_rows.append({
            "category": cat,
            "n_runs": agg["n"],
            "avg_saving_pct": round(agg["saving_sum"] / n, 1),
            "avg_confidence": round(agg["conf_sum"] / n, 3),
            "first_pass_rate": round(agg["first_pass_sum"] / n, 3),
            "avg_duration_s": round(agg["duration_sum"] / n, 1),
        })
    _write_csv(summary_rows, GEN_DIR / "chapter6_summary.csv")


# ── Print quick stats ─────────────────────────────────────────────────────────

def print_stats(runs: list[dict]) -> None:
    n = len(runs)
    if n == 0:
        print("No runs found in DB.")
        return

    savings = [
        r.get("estimated_saving_rate", 0) or 0
        for r in runs
    ]
    savings_pct = [s * 100 if s <= 1.0 else s for s in savings]
    confs = [r.get("avg_confidence", 0) or 0 for r in runs]
    durations_s = [(r.get("duration_ms", 0) or 0) / 1000 for r in runs]

    print(f"\n{'='*55}")
    print(f"  DB Summary  ({DB_PATH.name})")
    print(f"{'='*55}")
    print(f"  Total runs      : {n}")
    print(f"  Avg saving      : {sum(savings_pct)/n:.1f}%")
    print(f"  Avg confidence  : {sum(confs)/n:.3f}")
    print(f"  Avg duration    : {sum(durations_s)/n:.1f}s")

    cats = {}
    for r in runs:
        c = r.get("category", "?")
        cats[c] = cats.get(c, 0) + 1
    print(f"  By category     : {cats}")
    print(f"{'='*55}\n")


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"\nExporting chart data from: {DB_PATH}")
    print(f"Output dir: {GEN_DIR}\n")

    runs = load_runs()
    node_outputs = load_node_outputs()
    judgment_cases = load_judgment_cases()

    print_stats(runs)

    print("Chapter 5 exports:")
    export_chapter5(runs, node_outputs)

    print("\nChapter 6 exports:")
    export_chapter6(runs, judgment_cases, node_outputs)

    print("\nAll exports complete. Files:")
    for f in sorted(GEN_DIR.glob("*.csv")):
        size = f.stat().st_size
        print(f"  {f.name:<40} {size:>8} bytes")
