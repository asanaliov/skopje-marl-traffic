#!/usr/bin/env python3
"""
Prints a done/missing matrix for experiments.csv, so you can see at a glance
which (controller, scenario, seed) combos still need a run.

Usage:
    python experiment_matrix.py path/to/experiments.csv

Marks:
    F   = full-length run present (simulation_seconds >= FULL_LENGTH_THRESHOLD)
    s   = short/partial run present (a row exists, but under the threshold)
    .   = missing entirely
"""

import sys
import csv
from collections import defaultdict

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
SCENARIOS = ["low", "medium", "high"]
SEEDS = ["42", "43", "44"]
FULL_LENGTH_THRESHOLD = 4000  # seconds; ~3600s demand + 600s cooldown = "full" run


def load_rows(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


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


def print_matrix(status):
    col_w = 6
    for scenario in SCENARIOS:
        print(f"\n=== scenario: {scenario} ===")
        header = "controller".ljust(30) + "".join(s.center(col_w) for s in SEEDS)
        print(header)
        print("-" * len(header))
        for controller in CONTROLLERS:
            cells = []
            for seed in SEEDS:
                mark = status.get((controller, scenario, seed), ".")
                cells.append((mark or ".").center(col_w))
            print(controller.ljust(30) + "".join(cells))

    total = len(CONTROLLERS) * len(SCENARIOS) * len(SEEDS)
    done_full = sum(1 for v in status.values() if v == "F")
    done_short = sum(1 for v in status.values() if v == "s")
    missing = total - len(status)
    print(f"\nSummary: {done_full} full, {done_short} short/partial, {missing} missing "
          f"(out of {total} expected combos)")
    print("F = full-length run, s = short/partial run present, . = missing\n")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: python {sys.argv[0]} path/to/experiments.csv")
        sys.exit(1)
    rows = load_rows(sys.argv[1])
    status = build_status(rows)
    print_matrix(status)