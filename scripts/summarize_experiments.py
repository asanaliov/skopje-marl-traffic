#!/usr/bin/env python3
"""Group saved experiment results by controller and scenario, and print a
summary (run count + mean/stdev of the headline metrics).

Does not generate charts -- that is a later task, per the sprint 1 spec.
"""

from __future__ import annotations

import argparse
import statistics
from collections import defaultdict
from pathlib import Path

from src.evaluation.results_writer import DEFAULT_RESULTS_PATH, read_results

# For each printed metric: whether a lower or higher value is the better
# outcome. Purely a human-readable label -- it does not change any math.
METRIC_DIRECTION = {
    "average_waiting_time": "lower is better",
    "average_queue_length": "lower is better",
    "max_queue_length": "lower is better",
    "average_speed": "higher is better",
    "throughput": "higher is better",
}

GroupKey = tuple[str, str]  # (controller, scenario)


def _to_float(value, default: float = 0.0) -> float:
    """Best-effort float conversion for possibly missing/malformed values.

    The summary must not crash on incomplete data, so anything that can't
    be parsed falls back to `default` instead of raising.
    """
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def group_results(rows: list[dict]) -> dict[GroupKey, list[dict]]:
    groups: dict[GroupKey, list[dict]] = defaultdict(list)
    for row in rows:
        controller = row.get("controller") or "unknown"
        scenario = row.get("scenario") or "unknown"
        groups[(controller, scenario)].append(row)
    return groups


def summarize(rows: list[dict]) -> dict[GroupKey, dict]:
    """Compute run count plus mean/stdev of the headline metrics for each
    (controller, scenario) group. Stdev is 0.0 for single-run groups."""
    groups = group_results(rows)

    summary: dict[GroupKey, dict] = {}
    for key, group_rows in groups.items():
        entry: dict[str, float] = {"run_count": len(group_rows)}
        for metric in METRIC_DIRECTION:
            values = [_to_float(r.get(metric)) for r in group_rows]
            entry[f"mean_{metric}"] = statistics.mean(values) if values else 0.0
            entry[f"stdev_{metric}"] = (
                statistics.stdev(values) if len(values) > 1 else 0.0
            )
        summary[key] = entry
    return summary


def print_summary(summary: dict[GroupKey, dict]) -> None:
    if not summary:
        print("No experiment results found.")
        return

    for (controller, scenario), entry in sorted(summary.items()):
        print(f"\n{controller} / {scenario}  (runs: {entry['run_count']})")
        for metric, direction in METRIC_DIRECTION.items():
            mean = entry[f"mean_{metric}"]
            stdev = entry[f"stdev_{metric}"]
            print(
                f"  {metric:24s} mean={mean:10.3f}  stdev={stdev:8.3f}  ({direction})"
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--results",
        type=Path,
        default=DEFAULT_RESULTS_PATH,
        help="Path to results/experiments.csv (default: results/experiments.csv)",
    )
    args = parser.parse_args()

    rows = read_results(args.results)
    summary = summarize(rows)
    print_summary(summary)


if __name__ == "__main__":
    main()
