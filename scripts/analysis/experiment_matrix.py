#!/usr/bin/env python3
"""
Prints a done/missing matrix for experiments.csv, so you can see at a glance
which (controller, scenario, seed) combos still need a run.

Usage:
    python experiment_matrix.py path/to/experiments.csv [more.csv or folders ...]

Folders are searched recursively for .csv files, so per-run result files
(e.g. results/real_signals/) can be checked without merging them first.
Controllers found in the results are added to the expected list below.

Marks:
    F   = full-length run present (simulation_seconds >= FULL_LENGTH_THRESHOLD)
    s   = short/partial run present (a row exists, but under the threshold)
    .   = missing entirely
"""

import sys
import csv
from collections import defaultdict
from pathlib import Path

# --- Config: edit these if your corridor's expected set changes ---
CONTROLLERS = [
    "static_fixed_time",
    "imported_actuated",
    "independent_rl",
    "multi_agent_independent_rl",
    "multi_agent_spatial_rl",
    "marl_neighbor_reward",
    "marl_global_reward",
]
SCENARIOS = ["low", "medium", "high", "peak", "stress"]
SEEDS = ["42", "43", "44"]
FULL_LENGTH_THRESHOLD = 4000  # seconds; ~3600s demand + 600s cooldown = "full" run


def load_rows(paths):
    rows = []
    for path in map(Path, paths):
        files = sorted(path.rglob("*.csv")) if path.is_dir() else [path]
        for file in files:
            with open(file, newline="") as f:
                rows.extend(row for row in csv.DictReader(f) if row.get("controller"))
    return rows


def controllers_to_show(rows):
    found = {row["controller"] for row in rows}
    return CONTROLLERS + sorted(found - set(CONTROLLERS))


def build_status(rows):
    # status[(controller, scenario, seed)] = "F" | "s" | best-of-duplicates
    status = defaultdict(lambda: None)
    for row in rows:
        key = (row["controller"], row["scenario"], row["seed"])
        try:
            secs = float(row["simulation_seconds"])
        except (KeyError, ValueError):
            secs = 0
        mark = "F" if secs >= FULL_LENGTH_THRESHOLD else "s"
        # if both a short and a full run exist for the same key, keep the better one
        if status[key] is None or (status[key] == "s" and mark == "F"):
            status[key] = mark
    return status


def print_matrix(status, controllers):
    col_w = 6
    name_w = max(30, *(len(c) + 2 for c in controllers))
    for scenario in SCENARIOS:
        print(f"\n=== scenario: {scenario} ===")
        header = "controller".ljust(name_w) + "".join(s.center(col_w) for s in SEEDS)
        print(header)
        print("-" * len(header))
        for controller in controllers:
            cells = []
            for seed in SEEDS:
                mark = status.get((controller, scenario, seed), ".")
                cells.append((mark or ".").center(col_w))
            print(controller.ljust(name_w) + "".join(cells))

    # only count cells shown in the grid, not rows for other scenarios or seeds
    shown = [status.get((c, sc, se)) for c in controllers for sc in SCENARIOS for se in SEEDS]
    total = len(shown)
    done_full = shown.count("F")
    done_short = shown.count("s")
    missing = shown.count(None)
    print(f"\nSummary: {done_full} full, {done_short} short/partial, {missing} missing "
          f"(out of {total} expected combos)")
    print("F = full-length run, s = short/partial run present, . = missing\n")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: python {sys.argv[0]} path/to/experiments.csv [more.csv or folders ...]")
        sys.exit(1)
    rows = load_rows(sys.argv[1:])
    status = build_status(rows)
    print_matrix(status, controllers_to_show(rows))