"""CLI demo: initialize DB and run one autopilot demand."""

from __future__ import annotations

import json
import sys
from pathlib import Path

base_dir = Path(__file__).resolve().parent
backend_dir = base_dir / "03_backend"
project_root = base_dir.parent

if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from autopilot_service import run_autopilot_and_persist
from init_sqlite import init_db


def main() -> None:
    db_path = backend_dir / "thesis_mvp.db"
    schema_path = backend_dir / "sqlite_schema.sql"
    init_db(db_path, schema_path)

    demand = {
        "factory_city": "东莞",
        "category": "MRO备件",
        "item_name": "气动电磁阀",
        "spec": "4V210-08, DC24V",
        "quantity": 30,
        "required_date": "2026-04-25",
        "budget_hint": "单价不高于65元",
    }
    result = run_autopilot_and_persist(db_path=db_path, demand=demand, source_channel="cli_demo")
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
