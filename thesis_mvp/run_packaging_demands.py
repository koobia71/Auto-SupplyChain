"""Run 6 包装辅料 demands to populate DB with dual-category data."""
from __future__ import annotations
import json, sys
from pathlib import Path

base_dir = Path(__file__).resolve().parent
backend_dir = base_dir / "03_backend"
project_root = base_dir.parent
for p in [str(backend_dir), str(project_root)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from autopilot_service import run_autopilot_and_persist
from init_sqlite import init_db

DEMANDS = [
    {"factory_city": "东莞", "category": "包装辅料", "item_name": "打包带",
     "spec": "PP, 16mm×1000m", "quantity": 50, "required_date": "2026-05-01", "budget_hint": "单价不高于80元/卷"},
    {"factory_city": "东莞", "category": "包装辅料", "item_name": "封箱胶带",
     "spec": "透明, 48mm×100m", "quantity": 200, "required_date": "2026-05-01", "budget_hint": "单价不高于5元/卷"},
    {"factory_city": "苏州", "category": "包装辅料", "item_name": "珍珠棉",
     "spec": "EPE 10mm厚, 1m×1m", "quantity": 100, "required_date": "2026-05-10", "budget_hint": "单价不高于3元/张"},
    {"factory_city": "苏州", "category": "包装辅料", "item_name": "热收缩膜",
     "spec": "PE, 500mm宽", "quantity": 30, "required_date": "2026-05-10", "budget_hint": "单价不高于150元/卷"},
    {"factory_city": "东莞", "category": "包装辅料", "item_name": "气泡膜",
     "spec": "双层, 60cm×50m", "quantity": 40, "required_date": "2026-05-05", "budget_hint": "单价不高于25元/卷"},
    {"factory_city": "苏州", "category": "包装辅料", "item_name": "纸箱",
     "spec": "5层瓦楞, 400×300×250mm", "quantity": 500, "required_date": "2026-05-15", "budget_hint": "单价不高于4元/个"},
]

def main():
    db_path = backend_dir / "thesis_mvp.db"
    init_db(db_path, backend_dir / "sqlite_schema.sql")
    for i, demand in enumerate(DEMANDS, 1):
        print(f"\n[{i}/6] {demand['item_name']} ({demand['category']}, {demand['factory_city']})...")
        try:
            result = run_autopilot_and_persist(db_path=db_path, demand=demand, source_channel="A1")
            saving = result.get("estimated_saving_rate", 0) or 0
            print(f"  ✓ run_uid={result.get('run_uid','?')}  saving={saving*100:.1f}%  status={result.get('status','?')}")
        except Exception as e:
            print(f"  ✗ Error: {e}")

if __name__ == "__main__":
    main()
