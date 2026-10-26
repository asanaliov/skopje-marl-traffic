#!/usr/bin/env python3
"""Group saved experiment results by controller, scenario, and episode
length, and print a summary (run count + mean/stdev of the headline metrics).

Episode length is part of the group key because it changes what the metrics
mean. A 600-second evaluation and a 3600-second one release different amounts
of traffic, so averaging them under one controller label would silently mix
two different experiments -- which is exactly what happened when the
multi-agent runners were evaluated at their 600-second default while the
baselines ran the full 3600-second demand.

Does not generate charts -- that is a later task, per the sprint 1 spec.
"""

from __future__ import annotations

import argparse
import statistics
import sys
from collections import defaultdict
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))

from src.evaluation.results_writer import (  # noqa: E402
    DEFAULT_RESULTS_PATH,
    read_results,
)

# For each printed metric: whether a lower or higher value is the better
# outcome. Purely a human-readable label -- it does not change any math.
METRIC_DIRECTION = {
    "average_waiting_time": "lower is better",
    "average_queue_length": "lower is better",
    "max_queue_length": "lower is better",
    "average_speed": "higher is better",
    "throughput": "higher is better",
}

RUN_LENGTH_COLUMN = "demand_seconds"
UNKNOWN_RUN_LENGTH = "unknown"

GroupKey = tuple[str, str, str]  # (controller, scenario, demand seconds)


def _to_float(value, default: float = 0.0) -> float:
    """Best-effort float conversion for possibly missing/malformed values.

    The summary must not crash on incomplete data, so anything that can't
    be parsed falls back to `default` instead of raising.
    """
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def format_run_length(value) -> str:
    """Label one row's demand period, tolerating older rows without one."""
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return UNKNOWN_RUN_LENGTH
    return f"{seconds:g}"


def _sort_key(key: GroupKey) -> tuple[str, str, float]:
    """Order groups by controller, scenario, then shortest run first."""
    controller, scenario, run_length = key
    try:
        seconds = float(run_length)
    except ValueError:
        seconds = -1.0
    return (controller, scenario, seconds)


def group_results(rows: list[dict]) -> dict[GroupKey, list[dict]]:
    groups: dict[GroupKey, list[dict]] = defaultdict(list)
    for row in rows:
        controller = row.get("controller") or "unknown"
        scenario = row.get("scenario") or "unknown"
        run_length = format_run_length(row.get(RUN_LENGTH_COLUMN))
        groups[(controller, scenario, run_length)].append(row)
    return groups


def summarize(rows: list[dict]) -> dict[GroupKey, dict]:
    """Compute run count plus mean/stdev of the headline metrics for each
    (controller, scenario, demand seconds) group. Stdev is 0.0 for single-run
    groups."""
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

    for key, entry in sorted(summary.items(), key=lambda item: _sort_key(item[0])):
        controller, scenario, run_length = key
        demand = (
            run_length if run_length == UNKNOWN_RUN_LENGTH else f"{run_length}s"
        )
        print(
            f"\n{controller} / {scenario} / {demand} demand  "
            f"(runs: {entry['run_count']})"
        )
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
