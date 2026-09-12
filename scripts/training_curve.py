#!/usr/bin/env python3
"""Recover a per-episode training curve from a training run's stdout log.

Checkpoints store Q-tables, epsilon, and the completed episode count, but no
reward history -- so once a training run ends, the only surviving record of
how reward evolved is whatever stdout was captured. A 300-episode run at full
episode length takes many hours, and the comparison report has to state
whether a controller had converged or was still improving when its episode
budget ran out. That question is unanswerable from a checkpoint alone, which
is why training runs must be logged and why this script exists.

Reads the "Episode N:" lines emitted by both the multi-agent and the
single-agent runners, writes the curve as CSV, and reports whether reward was
still trending upward over the final stretch of training.

Usage:
    python scripts/training_curve.py logs/marl_local_high_seed42.log
    python scripts/training_curve.py logs/*.log --csv results/curves/high.csv

Pass several logs for a run that was interrupted and continued with --resume;
they are merged by episode number.
"""

from __future__ import annotations

import argparse
import codecs
import csv
import re
import statistics
import sys
from pathlib import Path

# Windows PowerShell 5.1's Tee-Object writes UTF-16LE with a BOM, not UTF-8,
# so a log captured the documented way is not a UTF-8 file. Decoding it as
# UTF-8 yields text whose every character is separated by a NUL, which
# matches no episode line at all -- a silent empty curve rather than an
# error. Longest BOMs are checked first: UTF-32LE starts with the UTF-16LE
# BOM and would otherwise be misread as UTF-16.
_BOMS = (
    (codecs.BOM_UTF32_LE, "utf-32-le"),
    (codecs.BOM_UTF32_BE, "utf-32-be"),
    (codecs.BOM_UTF8, "utf-8"),
    (codecs.BOM_UTF16_LE, "utf-16-le"),
    (codecs.BOM_UTF16_BE, "utf-16-be"),
)

# Anchored on the "Episode N:" prefix so the indented per-agent lines the
# multi-agent runner prints underneath ("  A19: reward=...") never match.
EPISODE_PREFIX = re.compile(r"^Episode (\d+):")

# The two runners label these fields differently: the multi-agent runner sums
# every agent into combined_reward and averages epsilon into mean_epsilon,
# while the single-agent runner reports a plain reward and epsilon. The
# leading (?:^|\s) stops a bare "reward=" pattern from matching the tail of
# "combined_reward=".
FIELD_PATTERNS = {
    "reward": (r"(?:^|\s)combined_reward=(-?[\d.]+)", r"(?:^|\s)reward=(-?[\d.]+)"),
    "epsilon": (r"(?:^|\s)mean_epsilon=([\d.]+)", r"(?:^|\s)epsilon=([\d.]+)"),
    "states": (r"(?:^|\s)states=(\d+)",),
    "seconds": (r"(?:^|\s)seconds=([\d.]+)",),
}

CSV_COLUMNS = ["episode", "reward", "epsilon", "states", "seconds"]

# Fraction of the run compared head-to-tail for the convergence verdict. The
# window is floored, because a 10% window on a short run is a handful of
# episodes and single-episode traffic noise would swamp any real trend.
TAIL_FRACTION = 0.1
MIN_WINDOW = 5


def _extract(line: str, patterns: tuple[str, ...]) -> float | None:
    for pattern in patterns:
        match = re.search(pattern, line)
        if match:
            return float(match.group(1))
    return None


def read_log_text(path: Path) -> str:
    """Decode a log written by any of the shells used to capture one."""
    raw = path.read_bytes()
    for bom, encoding in _BOMS:
        if raw.startswith(bom):
            return raw[len(bom) :].decode(encoding, errors="replace")
    # No BOM. A redirect can still produce UTF-16 without one, and its
    # ASCII text is then riddled with NULs, so sniff for those rather than
    # returning mojibake.
    if b"\x00" in raw[:4096]:
        return raw.decode("utf-16-le", errors="replace")
    return raw.decode("utf-8", errors="replace")


def parse_log(path: Path) -> dict[int, dict[str, float]]:
    """Extract every episode line from one log, keyed by episode number."""
    episodes: dict[int, dict[str, float]] = {}
    for line in read_log_text(path).splitlines():
        prefix = EPISODE_PREFIX.match(line)
        if not prefix:
            continue
        record = {
            name: _extract(line, patterns)
            for name, patterns in FIELD_PATTERNS.items()
        }
        if record["reward"] is None:
            continue
        episodes[int(prefix.group(1))] = record
    return episodes


def merge_logs(paths: list[Path]) -> list[dict[str, float]]:
    """Merge several logs by episode number, newest occurrence winning.

    A run continued with --resume numbers its episodes from where it left
    off, so merging is normally clean. A run restarted *without* --resume
    numbers from 1 again and genuinely collides; later files win and the
    collision is reported, because silently averaging two different training
    attempts would fabricate a curve that never happened.
    """
    merged: dict[int, dict[str, float]] = {}
    collisions = 0
    for path in paths:
        for episode, record in parse_log(path).items():
            if episode in merged:
                collisions += 1
            merged[episode] = record
    if collisions:
        print(
            f"Warning: {collisions} episode number(s) appeared in more than "
            "one log. Later files won. If these logs are separate training "
            "attempts rather than one resumed run, plot them separately.",
            file=sys.stderr,
        )
    return [
        {"episode": episode, **merged[episode]} for episode in sorted(merged)
    ]


def write_csv(rows: list[dict[str, float]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in CSV_COLUMNS})


def report(rows: list[dict[str, float]]) -> None:
    """Print the headline numbers and a converged / still-improving verdict."""
    rewards = [row["reward"] for row in rows]
    first, last = rows[0], rows[-1]
    gaps = [
        b["episode"] - a["episode"]
        for a, b in zip(rows, rows[1:])
        if b["episode"] - a["episode"] > 1
    ]

    print(f"Episodes parsed:   {len(rows)} (from {first['episode']} to {last['episode']})")
    if gaps:
        print(f"Gaps in numbering: {len(gaps)} -- some episodes were not logged")
    print(f"First reward:      {first['reward']:.1f}")
    print(f"Last reward:       {last['reward']:.1f}")
    print(f"Best reward:       {max(rewards):.1f}")
    if last["epsilon"] is not None:
        print(f"Final epsilon:     {last['epsilon']:.4f}")
    if last["states"] is not None:
        print(f"Q-table states:    {int(last['states'])}")

    window = max(MIN_WINDOW, int(len(rows) * TAIL_FRACTION))
    if len(rows) < 2 * window:
        print(
            f"\nToo few episodes for a convergence verdict "
            f"(need {2 * window} to compare two {window}-episode windows)."
        )
        return

    tail = statistics.fmean(rewards[-window:])
    preceding = statistics.fmean(rewards[-2 * window : -window])
    spread = statistics.pstdev(rewards[-window:])
    delta = tail - preceding

    print(f"\nLast {window} episodes:     mean reward {tail:.1f} (sd {spread:.1f})")
    print(f"Preceding {window}:        mean reward {preceding:.1f}")
    print(f"Change:              {delta:+.1f}")

    # Reward is negative here (accumulated delay), so a rising mean means the
    # controller is still getting better. Judging the change against the tail's
    # own spread keeps episode-to-episode traffic noise from reading as a trend.
    if spread and abs(delta) < spread / 2:
        print(
            "\nVerdict: PLATEAUED -- the final change is small next to normal "
            "episode-to-episode variation. Reportable as converged."
        )
    elif delta > 0:
        print(
            "\nVerdict: STILL IMPROVING -- reward was rising when the budget "
            "ran out. Report this controller's result as a floor, not a "
            "converged ceiling, or extend training with --resume."
        )
    else:
        print(
            "\nVerdict: DEGRADING -- reward fell over the final stretch. Check "
            "for an over-large learning rate or too little remaining "
            "exploration before treating this as a final result."
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "logs",
        type=Path,
        nargs="+",
        help="Training log file(s). Pass several for one resumed run.",
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=None,
        help="Also write the parsed curve to this CSV path.",
    )
    args = parser.parse_args()

    missing = [path for path in args.logs if not path.is_file()]
    if missing:
        parser.error(f"log file(s) not found: {', '.join(str(p) for p in missing)}")

    rows = merge_logs(args.logs)
    if not rows:
        # A log holding SUMO's startup banner but no episode line yet is the
        # normal state early in a run, not a failure: one full-length high
        # scenario episode takes about three minutes before it reports.
        started = any(read_log_text(path).strip() for path in args.logs)
        if started:
            parser.error(
                "no 'Episode N:' lines yet -- the run has not finished its "
                "first episode. A full-length episode takes roughly 1-3 "
                "minutes depending on scenario. Try again shortly."
            )
        parser.error(
            "log is empty, so no stdout was captured. Pipe training through "
            "Tee-Object, and pass -u to python so output is not buffered."
        )

    report(rows)
    if args.csv:
        write_csv(rows, args.csv)
        print(f"\nCurve written to {args.csv}")


if __name__ == "__main__":
    main()
