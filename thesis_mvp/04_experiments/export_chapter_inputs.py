"""从 thesis_mvp.db 自动导出第5/6章图表输入。"""

from __future__ import annotations

import csv
import sqlite3
from pathlib import Path


def _query_rows(db_path: Path) -> list[dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT
                r.run_uid,
                r.status,
                r.duration_ms,
                r.loop_count,
                r.estimated_saving_rate,
                r.human_in_loop,
                d.category,
                d.factory_city,
                d.item_name,
                COUNT(DISTINCT n.id) AS node_count,
                COUNT(DISTINCT c.id) AS case_count,
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
    finally:
        conn.close()


def _write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k) for k in fieldnames})


def export(db_path: Path, output_dir: Path) -> tuple[Path, Path]:
    rows = _query_rows(db_path)

    chapter5_rows = []
    chapter6_rows = []
    for row in rows:
        chapter5_rows.append(
            {
                "run_uid": row.get("run_uid"),
                "category": row.get("category"),
                "route_proxy_ok": 1 if (row.get("node_count") or 0) >= 3 else 0,
                "avg_confidence": row.get("avg_confidence") or 0.0,
                "latency_ms": row.get("duration_ms") or 0,
                "human_in_loop": row.get("human_in_loop") or 0,
                "saving_rate": row.get("estimated_saving_rate") or 0.0,
            }
        )
        chapter6_rows.append(
            {
                "run_uid": row.get("run_uid"),
                "factory_city": row.get("factory_city"),
                "category": row.get("category"),
                "item_name": row.get("item_name"),
                "status": row.get("status"),
                "node_count": row.get("node_count") or 0,
                "case_count": row.get("case_count") or 0,
                "feedback_count": row.get("feedback_count") or 0,
            }
        )

    chapter5_file = output_dir / "chapter5_inputs.csv"
    chapter6_file = output_dir / "chapter6_casepack.csv"
    _write_csv(
        chapter5_file,
        chapter5_rows,
        ["run_uid", "category", "route_proxy_ok", "avg_confidence", "latency_ms", "human_in_loop", "saving_rate"],
    )
    _write_csv(
        chapter6_file,
        chapter6_rows,
        ["run_uid", "factory_city", "category", "item_name", "status", "node_count", "case_count", "feedback_count"],
    )
    return chapter5_file, chapter6_file


if __name__ == "__main__":
    base_dir = Path(__file__).resolve().parents[1]
    db_path = base_dir / "03_backend" / "thesis_mvp.db"
    output_dir = Path(__file__).resolve().parent / "generated"
    chapter5_file, chapter6_file = export(db_path, output_dir)
    print(f"chapter5 input: {chapter5_file}")
    print(f"chapter6 casepack: {chapter6_file}")
