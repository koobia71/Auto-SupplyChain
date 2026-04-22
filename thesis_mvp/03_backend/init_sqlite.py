"""初始化 thesis_mvp SQLite 数据库。"""

from __future__ import annotations

import sqlite3
from pathlib import Path


def init_db(db_path: Path, schema_path: Path) -> None:
    schema_sql = schema_path.read_text(encoding="utf-8")
    with sqlite3.connect(db_path) as conn:
        conn.executescript(schema_sql)
        conn.commit()


if __name__ == "__main__":
    base_dir = Path(__file__).resolve().parent
    db_file = base_dir / "thesis_mvp.db"
    schema_file = base_dir / "sqlite_schema.sql"
    init_db(db_file, schema_file)
    print(f"SQLite initialized: {db_file}")
