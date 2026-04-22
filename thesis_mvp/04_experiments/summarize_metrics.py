"""从消融记录表汇总论文可用指标。"""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path


def summarize(path: Path) -> dict[str, dict[str, float]]:
    buckets: dict[str, dict[str, list[float]]] = defaultdict(
        lambda: defaultdict(list)
    )
    with path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            variant = row["variant"]
            buckets[variant]["route_correct"].append(float(row["route_correct"]))
            buckets[variant]["output_completeness"].append(float(row["output_completeness"]))
            buckets[variant]["retry_count"].append(float(row["retry_count"]))
            buckets[variant]["latency_ms"].append(float(row["latency_ms"]))
            buckets[variant]["human_intervention"].append(float(row["human_intervention"]))
            buckets[variant]["adopted"].append(float(row["adopted"]))
            buckets[variant]["saving_rate"].append(float(row["saving_rate"]))

    result: dict[str, dict[str, float]] = {}
    for variant, metrics in buckets.items():
        result[variant] = {
            f"{name}_avg": sum(values) / len(values) for name, values in metrics.items()
        }
    return result


if __name__ == "__main__":
    csv_path = Path(__file__).resolve().parent / "ablation_result_template.csv"
    summary = summarize(csv_path)
    for variant, metrics in summary.items():
        print(f"[{variant}]")
        for metric_name, value in metrics.items():
            print(f"  {metric_name}: {value:.4f}")
