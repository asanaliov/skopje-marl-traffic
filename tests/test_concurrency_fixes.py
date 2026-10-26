"""Tests for the two concurrency fixes introduced in this branch.

1. Checkpoint auto-naming
   - default_checkpoint_path() in run_q_learning.py produces a unique,
     deterministic filename that encodes agent ID, scenario, and seed.
   - default_checkpoint_path() in run_multi_agent_q_learning.py encodes
     reward mode, scenario, seed, and (optionally) the spatial tag.
   - Any two runs with different args produce different paths, so parallel
     jobs never overwrite each other's checkpoints by accident.

2. Safe concurrent writes to experiments.csv
   - append_result() acquires a FileLock before touching the file, so two
     threads cannot interleave writes or both decide to write a header.
   - A basic two-thread stress-test verifies that the resulting CSV has
     exactly one header line and the expected number of data rows.
"""

from __future__ import annotations

import csv
import threading
from pathlib import Path


from scripts.experiments.run_multi_agent_q_learning import (
    default_checkpoint_path as marl_default_checkpoint_path,
)
from scripts.experiments.run_q_learning import (
    default_checkpoint_path as single_default_checkpoint_path,
)
from src.evaluation.metrics import EpisodeMetrics
from src.evaluation.results_writer import append_result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _valid_metrics(**overrides) -> EpisodeMetrics:
    """Build a minimal valid EpisodeMetrics for write tests."""
    base = {
        "controller": "test_controller",
        "scenario": "medium",
        "seed": 42,
        "simulation_seconds": 600.0,
        "average_waiting_time": 5.0,
        "average_queue_length": 2.0,
        "max_queue_length": 6.0,
        "average_speed": 8.0,
        "throughput": 50,
        "departed_vehicles": 60,
        "arrived_vehicles": 50,
        "total_stopped_vehicles": 10,
    }
    base.update(overrides)
    return EpisodeMetrics(**base)


# ---------------------------------------------------------------------------
# 1a. Single-agent checkpoint auto-naming
# ---------------------------------------------------------------------------


class TestSingleAgentDefaultCheckpointPath:
    """default_checkpoint_path() in run_q_learning.py."""

    def test_encodes_agent_id_scenario_and_seed(self):
        path = single_default_checkpoint_path("A19", "medium", 42)
        assert path == Path("checkpoints/A19_medium_seed42.json")

    def test_different_agent_id_yields_different_path(self):
        p1 = single_default_checkpoint_path("A19", "medium", 42)
        p2 = single_default_checkpoint_path("A26", "medium", 42)
        assert p1 != p2

    def test_different_scenario_yields_different_path(self):
        p1 = single_default_checkpoint_path("A19", "low", 42)
        p2 = single_default_checkpoint_path("A19", "high", 42)
        assert p1 != p2

    def test_different_seed_yields_different_path(self):
        p1 = single_default_checkpoint_path("A19", "medium", 1)
        p2 = single_default_checkpoint_path("A19", "medium", 2)
        assert p1 != p2

    def test_all_three_dimensions_differ(self):
        """Two completely different arg sets must not accidentally collide."""
        p1 = single_default_checkpoint_path("A9", "low", 1)
        p2 = single_default_checkpoint_path("A19", "medium", 42)
        assert p1 != p2

    def test_returns_path_inside_checkpoints_dir(self):
        path = single_default_checkpoint_path("A19", "medium", 42)
        assert path.parent == Path("checkpoints")

    def test_deterministic_for_same_args(self):
        p1 = single_default_checkpoint_path("A19", "medium", 42)
        p2 = single_default_checkpoint_path("A19", "medium", 42)
        assert p1 == p2


# ---------------------------------------------------------------------------
# 1b. Multi-agent checkpoint auto-naming
# ---------------------------------------------------------------------------


class TestMarlDefaultCheckpointPath:
    """default_checkpoint_path() in run_multi_agent_q_learning.py."""

    def test_encodes_reward_mode_scenario_and_seed(self):
        path = marl_default_checkpoint_path("medium", 42, reward_mode="local")
        assert path == Path("checkpoints/marl_local_medium_seed42.json")

    def test_different_reward_mode_yields_different_path(self):
        p1 = marl_default_checkpoint_path("medium", 42, reward_mode="local")
        p2 = marl_default_checkpoint_path("medium", 42, reward_mode="neighbor_aware")
        assert p1 != p2

    def test_different_scenario_yields_different_path(self):
        p1 = marl_default_checkpoint_path("low", 42)
        p2 = marl_default_checkpoint_path("high", 42)
        assert p1 != p2

    def test_different_seed_yields_different_path(self):
        p1 = marl_default_checkpoint_path("medium", 1)
        p2 = marl_default_checkpoint_path("medium", 99)
        assert p1 != p2

    def test_spatial_flag_adds_suffix(self):
        local = marl_default_checkpoint_path("medium", 42, spatial_observations=False)
        spatial = marl_default_checkpoint_path("medium", 42, spatial_observations=True)
        assert local != spatial
        assert "_spatial" in spatial.name
        assert "_spatial" not in local.name

    def test_spatial_and_non_spatial_share_same_reward_mode_scenario_seed(self):
        """Two runs that differ ONLY in spatial flag must not share a file."""
        local = marl_default_checkpoint_path(
            "medium", 42, reward_mode="local", spatial_observations=False
        )
        spatial = marl_default_checkpoint_path(
            "medium", 42, reward_mode="local", spatial_observations=True
        )
        assert local != spatial

    def test_all_dimensions_differ(self):
        """Maximally different args must not collide."""
        p1 = marl_default_checkpoint_path("low", 1, reward_mode="local")
        p2 = marl_default_checkpoint_path("high", 99, reward_mode="global")
        assert p1 != p2

    def test_returns_path_inside_checkpoints_dir(self):
        path = marl_default_checkpoint_path("medium", 42)
        assert path.parent == Path("checkpoints")

    def test_deterministic_for_same_args(self):
        p1 = marl_default_checkpoint_path("medium", 42, reward_mode="global")
        p2 = marl_default_checkpoint_path("medium", 42, reward_mode="global")
        assert p1 == p2

    def test_local_baseline_single_versus_marl_are_distinct(self):
        """A single-agent run and a MARL run with the same scenario/seed must
        not share a checkpoint path, even if both use 'local' reward mode."""
        single = single_default_checkpoint_path("A19", "medium", 42)
        marl = marl_default_checkpoint_path("medium", 42, reward_mode="local")
        assert single != marl


# ---------------------------------------------------------------------------
# 2. Concurrent writes to experiments.csv
# ---------------------------------------------------------------------------


class TestConcurrentAppendResult:
    """append_result() is safe when called from two threads at once."""

    def test_header_written_exactly_once_across_threads(self, tmp_path):
        """Two threads writing concurrently must produce exactly one header."""
        csv_path = tmp_path / "experiments.csv"
        n_threads = 8
        n_rows_each = 5
        errors: list[Exception] = []

        def write_rows():
            try:
                for _ in range(n_rows_each):
                    append_result(_valid_metrics(), path=csv_path)
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=write_rows) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Threads raised exceptions: {errors}"

        lines = csv_path.read_text(encoding="utf-8").splitlines()
        # First line must be the header.
        assert lines[0].startswith("controller")
        # Header must appear exactly once.
        header_count = sum(1 for line in lines if line.startswith("controller,"))
        assert header_count == 1, (
            f"Header appeared {header_count} times; expected exactly 1"
        )
        # Every thread wrote n_rows_each rows.
        data_rows = lines[1:]
        assert len(data_rows) == n_threads * n_rows_each

    def test_rows_are_not_interleaved_or_corrupted(self, tmp_path):
        """Each row must be a valid, fully-formed CSV line."""
        csv_path = tmp_path / "experiments.csv"
        n_threads = 4
        n_rows_each = 10

        def write_rows():
            for _ in range(n_rows_each):
                append_result(_valid_metrics(), path=csv_path)

        threads = [threading.Thread(target=write_rows) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        rows = list(csv.DictReader(csv_path.open(encoding="utf-8")))
        assert len(rows) == n_threads * n_rows_each
        for row in rows:
            # Every row must have a value for the first three columns.
            assert row["controller"] == "test_controller"
            assert row["scenario"] == "medium"
            assert row["seed"] == "42"

    def test_second_call_does_not_duplicate_header(self, tmp_path):
        """Regression: a second sequential call must append data, not header."""
        csv_path = tmp_path / "exp.csv"
        append_result(_valid_metrics(seed=1), path=csv_path)
        append_result(_valid_metrics(seed=2), path=csv_path)

        rows = list(csv.DictReader(csv_path.open(encoding="utf-8")))
        assert len(rows) == 2
        assert rows[0]["seed"] == "1"
        assert rows[1]["seed"] == "2"
