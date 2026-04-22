"""Batch experiment runner for thesis ablation study.

Runs 12 standardized demands (6 MRO + 6 packaging) across 4 ablation configs.
Results are persisted to thesis_mvp.db and exported to CSV.

Usage:
    conda activate auto_sc
    cd /Users/col/Desktop/Auto_SupplyChain
    python thesis_mvp/04_experiments/run_experiments.py

    # Run only one config group for testing:
    python thesis_mvp/04_experiments/run_experiments.py --config A1

    # Skip delivery layer (faster):
    python thesis_mvp/04_experiments/run_experiments.py --skip-delivery

Output:
    thesis_mvp/04_experiments/generated/ablation_results_<timestamp>.csv
    thesis_mvp/04_experiments/generated/chapter5_inputs.csv  (overwritten)
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

# ── Path setup ───────────────────────────────────────────────────────────────
_ROOT = Path(__file__).resolve().parents[2]
_BACKEND = _ROOT / "thesis_mvp" / "03_backend"
for p in [str(_ROOT), str(_BACKEND)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from autopilot_service import run_autopilot_and_persist  # noqa: E402
from repository import ThesisRepository  # noqa: E402

DB_PATH = _BACKEND / "thesis_mvp.db"
GEN_DIR = Path(__file__).resolve().parent / "generated"
GEN_DIR.mkdir(exist_ok=True)

# ── Standard 12-demand dataset ───────────────────────────────────────────────
STANDARD_DEMANDS: list[dict[str, Any]] = [
    # ── MRO备件 (6) ──────────────────────────────────────────────────────────
    {
        "id": "D01", "factory_city": "东莞", "category": "MRO备件",
        "item_name": "气动电磁阀", "spec": "4V210-08, DC24V",
        "quantity": 30, "required_date": "2026-04-25",
        "budget_hint": "单价不高于65元", "urgency": "高",
    },
    {
        "id": "D02", "factory_city": "东莞", "category": "MRO备件",
        "item_name": "轴承", "spec": "6205 2RS, 25×52×15mm",
        "quantity": 50, "required_date": "2026-04-28",
        "budget_hint": "单价不高于20元", "urgency": "中",
    },
    {
        "id": "D03", "factory_city": "苏州", "category": "MRO备件",
        "item_name": "工业皮带", "spec": "A型三角带 A-60, 1524mm",
        "quantity": 20, "required_date": "2026-05-02",
        "budget_hint": "单价不高于40元", "urgency": "低",
    },
    {
        "id": "D04", "factory_city": "苏州", "category": "MRO备件",
        "item_name": "断路器", "spec": "DZ47-63 C20A 3P",
        "quantity": 10, "required_date": "2026-04-24",
        "budget_hint": "单价不高于80元", "urgency": "高",
    },
    {
        "id": "D05", "factory_city": "无锡", "category": "MRO备件",
        "item_name": "密封圈", "spec": "O型圈 NBR 50×3.5mm",
        "quantity": 200, "required_date": "2026-04-30",
        "budget_hint": "单价不高于3元", "urgency": "中",
    },
    {
        "id": "D06", "factory_city": "无锡", "category": "MRO备件",
        "item_name": "气动接头", "spec": "PC8-02 快插接头 8mm管径",
        "quantity": 100, "required_date": "2026-05-05",
        "budget_hint": "单价不高于6元", "urgency": "低",
    },
    # ── 包装辅料 (6) ──────────────────────────────────────────────────────────
    {
        "id": "D07", "factory_city": "佛山", "category": "包装辅料",
        "item_name": "气泡膜", "spec": "宽度100cm, 双层, 厚0.08mm",
        "quantity": 500, "required_date": "2026-04-26",
        "budget_hint": "每卷不高于80元", "urgency": "中",
    },
    {
        "id": "D08", "factory_city": "佛山", "category": "包装辅料",
        "item_name": "瓦楞纸箱", "spec": "三层B瓦 400×300×250mm",
        "quantity": 1000, "required_date": "2026-04-28",
        "budget_hint": "单价不高于5元", "urgency": "高",
    },
    {
        "id": "D09", "factory_city": "东莞", "category": "包装辅料",
        "item_name": "打包带", "spec": "PP材质 宽15mm 厚0.8mm 500m/卷",
        "quantity": 50, "required_date": "2026-05-03",
        "budget_hint": "每卷不高于35元", "urgency": "低",
    },
    {
        "id": "D10", "factory_city": "东莞", "category": "包装辅料",
        "item_name": "封箱胶带", "spec": "透明BOPP 宽4.5cm 长100m",
        "quantity": 200, "required_date": "2026-04-27",
        "budget_hint": "每卷不高于8元", "urgency": "中",
    },
    {
        "id": "D11", "factory_city": "苏州", "category": "包装辅料",
        "item_name": "珍珠棉", "spec": "EPE白色 厚5mm 1m×1m",
        "quantity": 300, "required_date": "2026-05-01",
        "budget_hint": "每张不高于12元", "urgency": "低",
    },
    {
        "id": "D12", "factory_city": "苏州", "category": "包装辅料",
        "item_name": "热收缩膜", "spec": "POF双向 宽50cm 厚0.015mm",
        "quantity": 100, "required_date": "2026-04-29",
        "budget_hint": "每卷不高于60元", "urgency": "高",
    },
]

# ── Ablation configs ──────────────────────────────────────────────────────────
# A1: Full system (few-shot + messages + supervisor)
# A2: No few-shot (judgment_history disabled)
# A3: No messages (messages disabled)
# A4: No supervisor (skip supervisor node)
ABLATION_CONFIGS = {
    "A1": {
        "label": "完整系统（few-shot+messages+supervisor）",
        "use_few_shot": True,
        "use_messages": True,
        "use_supervisor": True,
        "env_overrides": {},
    },
    "A2": {
        "label": "无few-shot（禁用judgment_history）",
        "use_few_shot": False,
        "use_messages": True,
        "use_supervisor": True,
        "env_overrides": {"ABLATION_NO_FEW_SHOT": "1"},
    },
    "A3": {
        "label": "无messages追踪",
        "use_few_shot": True,
        "use_messages": False,
        "use_supervisor": True,
        "env_overrides": {"ABLATION_NO_MESSAGES": "1"},
    },
    "A4": {
        "label": "无supervisor路由",
        "use_few_shot": True,
        "use_messages": True,
        "use_supervisor": False,
        "env_overrides": {"ABLATION_NO_SUPERVISOR": "1"},
    },
}


def _set_env(overrides: dict[str, str]) -> None:
    """Set environment variables for ablation config."""
    # Clear all ablation flags first
    for key in ["ABLATION_NO_FEW_SHOT", "ABLATION_NO_MESSAGES", "ABLATION_NO_SUPERVISOR"]:
        os.environ.pop(key, None)
    for k, v in overrides.items():
        os.environ[k] = v


def _extract_metrics(result: dict[str, Any], config_id: str, demand_id: str) -> dict[str, Any]:
    """Extract standardized metrics from a run result."""
    final_state = result.get("final_state", {})
    context = final_state.get("context", {})
    recommendation = final_state.get("recommendation", {})
    node_outputs = []

    # Reconstruct confidence list from final_state context
    confidences = []
    for key in ["analysis_confidence", "research_confidence", "recommendation_confidence"]:
        v = context.get(key)
        if v is not None:
            try:
                confidences.append(float(v))
            except Exception:
                pass

    avg_conf = sum(confidences) / len(confidences) if confidences else 0.0
    saving_pct = recommendation.get("expected_saving_percent", 0) or 0
    po_draft = recommendation.get("po_draft", {})

    return {
        "config_id": config_id,
        "config_label": ABLATION_CONFIGS[config_id]["label"],
        "demand_id": demand_id,
        "run_uid": result["run_uid"],
        "execution_path": result.get("execution_path", "unknown"),
        "delivery_status": result.get("delivery_status", "unknown"),
        "duration_ms": result["duration_ms"],
        "duration_s": round(result["duration_ms"] / 1000, 2),
        "loop_count": context.get("loop_count", 0),
        "analysis_confidence": context.get("analysis_confidence"),
        "research_confidence": context.get("research_confidence"),
        "recommendation_confidence": context.get("recommendation_confidence"),
        "avg_confidence": round(avg_conf, 3),
        "saving_pct": saving_pct,
        "saving_rate": round(saving_pct / 100.0, 4),
        "po_supplier": po_draft.get("supplier", ""),
        "po_unit_price": po_draft.get("unit_price", ""),
        "po_total_amount": po_draft.get("total_amount", ""),
        "analysis_model": context.get("analysis_model", ""),
        "research_model": context.get("research_model", ""),
        "recommendation_model": context.get("recommendation_model", ""),
        "judgment_cases_count": len(final_state.get("judgment_history", [])),
        "messages_count": len(final_state.get("messages", [])),
        "human_in_loop": 0,  # autopilot mode
        "first_pass": 1 if context.get("loop_count", 1) <= 1 else 0,
    }


def run_all_experiments(
    configs: list[str] | None = None,
    skip_delivery: bool = False,
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    """Run all 12 demands × 4 configs (or subset) and return metrics rows."""
    target_configs = configs or list(ABLATION_CONFIGS.keys())
    all_metrics: list[dict[str, Any]] = []

    total = len(STANDARD_DEMANDS) * len(target_configs)
    done = 0

    print(f"\n{'='*60}")
    print(f"Ablation Experiment Runner")
    print(f"  Demands: {len(STANDARD_DEMANDS)} | Configs: {len(target_configs)} | Total: {total}")
    print(f"  skip_delivery={skip_delivery} | dry_run={dry_run}")
    print(f"{'='*60}\n")

    for config_id in target_configs:
        cfg = ABLATION_CONFIGS[config_id]
        print(f"\n--- Config {config_id}: {cfg['label']} ---")
        _set_env(cfg["env_overrides"])

        for demand_raw in STANDARD_DEMANDS:
            demand_id = demand_raw["id"]
            demand = {k: v for k, v in demand_raw.items() if k != "id"}
            done += 1

            print(f"  [{done}/{total}] {config_id}/{demand_id} {demand['item_name']} "
                  f"({demand['category']}, {demand['factory_city']})...", end=" ", flush=True)

            if dry_run:
                print("SKIP (dry_run)")
                continue

            try:
                t0 = time.time()
                result = run_autopilot_and_persist(
                    DB_PATH,
                    demand=demand,
                    source_channel="experiment",
                    skip_delivery=skip_delivery,
                )
                elapsed = time.time() - t0
                metrics = _extract_metrics(result, config_id, demand_id)
                all_metrics.append(metrics)
                print(f"OK | {elapsed:.1f}s | saving={metrics['saving_pct']}% "
                      f"| conf={metrics['avg_confidence']:.2f} "
                      f"| path={metrics['execution_path']}")
            except Exception as exc:
                print(f"ERROR: {exc}")
                all_metrics.append({
                    "config_id": config_id,
                    "demand_id": demand_id,
                    "error": str(exc),
                    "duration_ms": 0,
                })

    # Clear ablation env flags
    _set_env({})

    return all_metrics


def save_results(metrics: list[dict[str, Any]], tag: str = "") -> Path:
    """Save metrics to CSV."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"ablation_results_{ts}{('_' + tag) if tag else ''}.csv"
    out_path = GEN_DIR / filename

    if not metrics:
        print("No metrics to save.")
        return out_path

    fieldnames = list(metrics[0].keys())
    # Ensure all rows have same keys
    for row in metrics:
        for key in fieldnames:
            row.setdefault(key, "")

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(metrics)

    # Also overwrite chapter5_inputs.csv for easy access
    chapter5_path = GEN_DIR / "chapter5_inputs.csv"
    with open(chapter5_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(metrics)

    print(f"\n✓ Results saved: {out_path}")
    print(f"✓ chapter5_inputs.csv updated: {chapter5_path}")
    return out_path


def print_summary(metrics: list[dict[str, Any]]) -> None:
    """Print a quick summary table by config."""
    from collections import defaultdict

    by_config: dict[str, list[dict]] = defaultdict(list)
    for m in metrics:
        if "error" not in m:
            by_config[m["config_id"]].append(m)

    print(f"\n{'='*70}")
    print(f"{'Config':<6} {'Label':<40} {'n':>4} {'Saving%':>8} {'Conf':>6} {'Time(s)':>8}")
    print(f"{'-'*70}")

    for config_id in sorted(by_config.keys()):
        rows = by_config[config_id]
        label = ABLATION_CONFIGS.get(config_id, {}).get("label", "")[:38]
        n = len(rows)
        avg_saving = sum(r.get("saving_pct", 0) or 0 for r in rows) / n if n else 0
        avg_conf = sum(r.get("avg_confidence", 0) or 0 for r in rows) / n if n else 0
        avg_time = sum(r.get("duration_s", 0) or 0 for r in rows) / n if n else 0
        print(f"{config_id:<6} {label:<40} {n:>4} {avg_saving:>7.1f}% {avg_conf:>6.3f} {avg_time:>7.1f}s")

    print(f"{'='*70}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ablation experiment runner")
    parser.add_argument("--config", nargs="+", choices=list(ABLATION_CONFIGS.keys()),
                        help="Config(s) to run (default: all)")
    parser.add_argument("--skip-delivery", action="store_true",
                        help="Skip PDF delivery layer (faster)")
    parser.add_argument("--dry-run", action="store_true",
                        help="List demands/configs without running")
    args = parser.parse_args()

    metrics = run_all_experiments(
        configs=args.config,
        skip_delivery=args.skip_delivery,
        dry_run=args.dry_run,
    )

    if not args.dry_run:
        save_results(metrics, tag=("_".join(args.config) if args.config else "full"))
        print_summary(metrics)
