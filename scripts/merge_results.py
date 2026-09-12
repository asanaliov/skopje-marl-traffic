#!/usr/bin/env python3
"""Merge experiment result rows from another machine into the results table.

Training is split across two machines, and the file lock that makes
concurrent writes safe only protects one filesystem -- it cannot merge two
separately grown copies of experiments.csv. The final comparison needs every
row in one file, so incoming rows have to be folded in explicitly.

A run is identified by (controller, scenario, seed, demand_seconds). Rows
whose key is not already present are appended. Rows whose key is present and
whose metrics match are skipped as the same run arriving twice. Rows whose
key is present but whose metrics differ are reported as conflicts and are
*not* written: the results table is append-only by design, and silently
picking a winner between two different runs of the same configuration would
quietly change a published number. Resolve those by hand.

Usage:
    python scripts/merge_results.py incoming.csv
    python scripts/merge_results.py from_borjan.csv --dry-run
    python scripts/merge_results.py a.csv b.csv --into results/experiments.csv
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from src.evaluation.results_writer import (  # noqa: E402
    DEFAULT_RESULTS_PATH,
    append_rows,
    read_results,
)

# What makes two rows "the same run". Episode length is part of the identity
# because a 600-second run and a 3600-second run of one configuration are
# different experiments, which is the same reason the summary groups by it.
KEY_COLUMNS = ("controller", "scenario", "seed", "demand_seconds")

# Compared to decide whether a same-key row is a duplicate or a conflict.
# Values are compared as text, exactly as the CSV holds them, so a row that
# survives a write/read round trip matches itself.
METRIC_COLUMNS = (
    "average_waiting_time",
    "average_queue_length",
    "max_queue_length",
    "average_speed",
    "throughput",
    "arrived_vehicles",
)

RowKey = tuple[str, ...]


def row_key(row: dict) -> RowKey:
    return tuple(str(row.get(column, "")).strip() for column in KEY_COLUMNS)


def metrics_differ(left: dict, right: dict) -> bool:
    return any(
        str(left.get(column, "")).strip() != str(right.get(column, "")).strip()
        for column in METRIC_COLUMNS
    )


def describe(key: RowKey) -> str:
    controller, scenario, seed, demand = key
    return f"{controller} / {scenario} / seed {seed} / {demand}s demand"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "sources",
        type=Path,
        nargs="+",
        help="CSV file(s) holding rows to merge in.",
    )
    parser.add_argument(
        "--into",
        type=Path,
        default=DEFAULT_RESULTS_PATH,
        help="Results table to merge into (default: results/experiments.csv).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would change without writing anything.",
    )
    args = parser.parse_args()

    missing = [path for path in args.sources if not path.is_file()]
    if missing:
        parser.error(f"source file(s) not found: {', '.join(str(p) for p in missing)}")

    existing = read_results(args.into)
    by_key = {row_key(row): row for row in existing}
    print(f"Target {args.into} holds {len(existing)} row(s).")

    to_append: list[dict] = []
    staged: dict[RowKey, dict] = {}
    duplicates = 0
    conflicts: list[tuple[Path, RowKey]] = []

    for source in args.sources:
        incoming = read_results(source)
        print(f"Reading {source}: {len(incoming)} row(s).")
        for row in incoming:
            key = row_key(row)
            against = by_key.get(key) or staged.get(key)
            if against is None:
                staged[key] = row
                to_append.append(row)
            elif metrics_differ(against, row):
                conflicts.append((source, key))
            else:
                duplicates += 1

    print()
    for row in to_append:
        print(f"  + {describe(row_key(row))}")
    if duplicates:
        print(f"  = {duplicates} row(s) already present with matching metrics, skipped.")
    for source, key in conflicts:
        print(f"  ! CONFLICT {describe(key)} -- differs from the existing row ({source})")

    print()
    if conflicts:
        print(
            f"{len(conflicts)} conflict(s) not written. The same configuration was "
            "run twice with different results; decide which run is canonical and "
            "remove the other by hand before merging again."
        )

    if not to_append:
        print("Nothing to append.")
        return

    if args.dry_run:
        print(f"Dry run: {len(to_append)} row(s) would be appended.")
        return

    written = append_rows(to_append, path=args.into)
    print(f"Appended {written} row(s) to {args.into}.")
    print("Check coverage with: python scripts/experiment_matrix.py " f"{args.into}")


if __name__ == "__main__":
    main()
