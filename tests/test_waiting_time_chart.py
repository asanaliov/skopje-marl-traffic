from __future__ import annotations

import csv

import pytest

from scripts.analysis.generate_waiting_time_chart import load_means


def _write_results(path, rows):
    fieldnames = (
        "controller",
        "scenario",
        "seed",
        "average_waiting_time",
        "demand_seconds",
    )
    with path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_load_means_excludes_short_trials(tmp_path):
    results = tmp_path / "experiments.csv"
    _write_results(
        results,
        [
            {
                "controller": "marl_neighbor_reward",
                "scenario": "medium",
                "seed": "42",
                "average_waiting_time": "18.76",
                "demand_seconds": "600",
            },
            {
                "controller": "marl_neighbor_reward",
                "scenario": "medium",
                "seed": "42",
                "average_waiting_time": "8",
                "demand_seconds": "3600",
            },
            {
                "controller": "marl_neighbor_reward",
                "scenario": "medium",
                "seed": "43",
                "average_waiting_time": "10",
                "demand_seconds": "3600.0",
            },
        ],
    )

    controllers, scenarios, means, duplicate_seed_rows = load_means(results)

    assert controllers == ["marl_neighbor_reward"]
    assert scenarios == ["medium"]
    assert means == {("marl_neighbor_reward", "medium"): 9}
    assert duplicate_seed_rows is False


def test_load_means_requires_at_least_one_full_length_run(tmp_path):
    results = tmp_path / "experiments.csv"
    _write_results(
        results,
        [
            {
                "controller": "marl_neighbor_reward",
                "scenario": "medium",
                "seed": "42",
                "average_waiting_time": "18.76",
                "demand_seconds": "600",
            },
        ],
    )

    with pytest.raises(ValueError, match="No full-length experiment rows"):
        load_means(results)
