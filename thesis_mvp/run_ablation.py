"""Run ablation experiments: A3 (rule-baseline) and A4 (no-supervisor).

A3 = no LLM, zero API cost
A4 = no supervisor node, 3 LLM calls per demand (analysis+research+recommendation only)

Usage:
    conda run -n auto_sc python thesis_mvp/run_ablation.py --configs A3 A4
    conda run -n auto_sc python thesis_mvp/run_ablation.py --configs A3  # free, no API
"""
from __future__ import annotations
import argparse, sys
from pathlib import Path

base_dir = Path(__file__).resolve().parent
backend_dir = base_dir / "03_backend"
project_root = base_dir.parent
for p in [str(backend_dir), str(project_root)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from autopilot_service import run_autopilot_and_persist
from init_sqlite import init_db

# Use 3 representative demands (MRO category, from the original 6)
SAMPLE_DEMANDS = [
    {"factory_city": "东莞", "category": "MRO备件", "item_name": "轴承",
     "spec": "6204-2RS, 内径20mm", "quantity": 10, "required_date": "2026-05-01",
     "budget_hint": "单价不超过25元"},
    {"factory_city": "苏州", "category": "MRO备件", "item_name": "工业手套",
     "spec": "丁腈橡胶, M码", "quantity": 100, "required_date": "2026-05-10",
     "budget_hint": "单价不超过5元"},
    {"factory_city": "东莞", "category": "MRO备件", "item_name": "切削液",
     "spec": "水溶性, 20L桶", "quantity": 5, "required_date": "2026-05-05",
     "budget_hint": "单价不超过200元/桶"},
]

def run_config(config_id: str, db_path: Path, skip_delivery: bool = True):
    print(f"\n{'='*50}")
    print(f"  消融配置 {config_id}: {_config_label(config_id)}")
    print(f"{'='*50}")
    results = []
    for i, demand in enumerate(SAMPLE_DEMANDS, 1):
        print(f"  [{i}/3] {demand['item_name']}...", end=" ", flush=True)
        try:
            r = run_autopilot_and_persist(
                db_path=db_path,
                demand=demand,
                source_channel=config_id,   # stored as config_id in DB
                ablation_config=config_id,
                skip_delivery=skip_delivery,
            )
            state = r.get("final_state", {})
            rec = state.get("recommendation", {})
            saving = rec.get("expected_saving_percent", 0) or 0
            dur = r.get("duration_ms", 0) / 1000
            print(f"✓  run={r['run_uid']}  saving={saving}%  path={r['execution_path']}  {dur:.1f}s")
            results.append(r)
        except Exception as e:
            print(f"✗ Error: {e}")
    return results

def _config_label(cfg):
    return {
        "A1": "完整系统（few-shot+messages+supervisor）",
        "A2": "无few-shot（judgment_history清空）",
        "A3": "规则基线（无LLM调用）",
        "A4": "无supervisor节点",
    }.get(cfg, cfg)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--configs", nargs="+", default=["A3", "A4"],
                        choices=["A1","A2","A3","A4"])
    parser.add_argument("--with-delivery", action="store_true",
                        help="Also run delivery/PDF layer (slower)")
    args = parser.parse_args()

    db_path = backend_dir / "thesis_mvp.db"
    init_db(db_path, backend_dir / "sqlite_schema.sql")

    for cfg in args.configs:
        run_config(cfg, db_path, skip_delivery=not args.with_delivery)

    print(f"\n✅ Done. DB: {db_path}")
    print("   Next: python thesis_mvp/04_experiments/export_charts.py")

if __name__ == "__main__":
    main()
