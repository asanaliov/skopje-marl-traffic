"""Append-only CSV storage for experiment results.

Design goals (per task spec):
- the header is written exactly once, the first time the file is created
- new runs are appended, never overwriting previous runs
- column order is fixed regardless of dict/field ordering
- reading back a missing or empty CSV is handled gracefully (no exceptions)
"""

from __future__ import annotations

import csv
from pathlib import Path

from filelock import FileLock

from src.evaluation.metrics import EpisodeMetrics

DEFAULT_RESULTS_PATH = Path("results/experiments.csv")

# Fixed column order. Do not reorder existing columns -- if new fields are
# ever added, append them at the end so old CSVs stay readable with
# csv.DictReader (missing trailing columns just read back as "" / None).
COLUMNS: list[str] = [
    "controller",
    "scenario",
    "seed",
    "simulation_seconds",
    "average_waiting_time",
    "average_queue_length",
    "max_queue_length",
    "average_speed",
    "throughput",
    "departed_vehicles",
    "arrived_vehicles",
    "total_stopped_vehicles",
    "active_vehicles_remaining",
    "teleport_count",
    "total_reward",
    "fixed_green_seconds",
    "demand_seconds",
    "cooldown_seconds",
]


def append_result(
    metrics: EpisodeMetrics, path: Path | str = DEFAULT_RESULTS_PATH
) -> None:
    """Append one experiment result as a new CSV row.

    Creates the results directory if needed and writes the header only if
    the file does not already exist (or exists but is empty). Never
    truncates or rewrites existing rows -- opens in append mode.
    Acquires an advisory file lock so concurrent processes cannot interleave
    writes or duplicate headers.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")

    lock = FileLock(lock_path)
    with lock:
        needs_header = not path.exists() or path.stat().st_size == 0
        row = metrics.as_flat_dict()
        with path.open("a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=COLUMNS)
            if needs_header:
                writer.writeheader()
            writer.writerow({col: row.get(col, "") for col in COLUMNS})


def read_results(path: Path | str = DEFAULT_RESULTS_PATH) -> list[dict]:
    """Read all saved results back as a list of dicts.

    Returns an empty list if the file is missing or empty, so callers
    (e.g. the summary script) never need to catch FileNotFoundError.
    """
    path = Path(path)
    if not path.exists() or path.stat().st_size == 0:
        return []

    lock_path = path.with_suffix(path.suffix + ".lock")
    lock = FileLock(lock_path)
    with lock:
        with path.open("r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            return list(reader)
