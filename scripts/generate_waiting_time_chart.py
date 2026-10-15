#!/usr/bin/env python3
"""Generate the README waiting-time chart from the experiment results CSV."""

from __future__ import annotations

import argparse
import csv
import html
import math
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT = PROJECT_ROOT / "results" / "experiments.csv"
DEFAULT_OUTPUT = PROJECT_ROOT / "results" / "waiting-time-comparison.svg"
SCENARIO_ORDER = ("low", "medium", "high")
COLORS = (
    "#667085",
    "#16856b",
    "#2878b5",
    "#d17b18",
    "#8b5fbf",
    "#c43c55",
    "#168aad",
    "#7652a5",
    "#4d7c0f",
    "#b45309",
)


def load_means(path: Path) -> tuple[list[str], list[str], dict[tuple[str, str], float], bool]:
    """Return controller/scenario means and whether duplicate seed rows exist."""
    groups: dict[tuple[str, str], list[float]] = defaultdict(list)
    run_keys: set[tuple[str, str, str]] = set()
    duplicate_seed_rows = False

    with path.open(encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        required = {"controller", "scenario", "average_waiting_time"}
        missing = required.difference(reader.fieldnames or ())
        if missing:
            raise ValueError(f"Missing required CSV columns: {', '.join(sorted(missing))}")

        for line_number, row in enumerate(reader, start=2):
            controller = (row.get("controller") or "").strip()
            scenario = (row.get("scenario") or "").strip()
            if not controller or not scenario:
                raise ValueError(f"Missing controller or scenario on CSV line {line_number}")
            try:
                waiting_time = float(row["average_waiting_time"])
            except (TypeError, ValueError) as error:
                raise ValueError(
                    f"Invalid average_waiting_time on CSV line {line_number}"
                ) from error

            groups[(controller, scenario)].append(waiting_time)
            if row.get("seed"):
                run_key = (controller, scenario, row["seed"].strip())
                if run_key in run_keys:
                    duplicate_seed_rows = True
                run_keys.add(run_key)

    if not groups:
        raise ValueError(f"No experiment rows found in {path}")

    controllers = sorted({controller for controller, _ in groups})
    scenarios_found = {scenario for _, scenario in groups}
    scenarios = [scenario for scenario in SCENARIO_ORDER if scenario in scenarios_found]
    scenarios.extend(sorted(scenarios_found.difference(scenarios)))
    means = {
        key: sum(values) / len(values)
        for key, values in groups.items()
    }
    return controllers, scenarios, means, duplicate_seed_rows


def tick_step(maximum: float) -> float:
    """Choose a readable axis interval near one fifth of the chart range."""
    raw_step = maximum / 4 if maximum else 1
    magnitude = 10 ** math.floor(math.log10(raw_step))
    for multiplier in (1, 2, 5, 10):
        step = multiplier * magnitude
        if step >= raw_step:
            return step
    return 10 * magnitude


def create_svg(
    controllers: list[str],
    scenarios: list[str],
    means: dict[tuple[str, str], float],
    duplicate_seed_rows: bool,
) -> str:
    width = 1000
    height = max(500, 180 + len(controllers) * 32)
    left, right, top, bottom = 95, 715, 90, height - 120
    maximum_value = max(means.values())
    step = tick_step(maximum_value)
    axis_maximum = math.ceil(maximum_value / step) * step
    scale = (bottom - top) / axis_maximum
    x_positions = [
        left + (right - left) * index / max(1, len(scenarios) - 1)
        for index in range(len(scenarios))
    ]

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title description">',
        '<title id="title">Mean average waiting time by traffic scenario for all controllers</title>',
        '<desc id="description">Line chart comparing all controllers in the experiment results across traffic scenarios. Lower waiting time is better.</desc>',
        f'<rect width="{width}" height="{height}" fill="#ffffff"/>',
        f'<text x="500" y="32" text-anchor="middle" font-family="Arial, sans-serif" font-size="22" font-weight="700" fill="#182230">Mean average waiting time by scenario</text>',
        f'<text x="500" y="56" text-anchor="middle" font-family="Arial, sans-serif" font-size="13" fill="#526174">Seconds, lower is better · all controllers in experiments.csv</text>',
        '<g font-family="Arial, sans-serif" font-size="12" fill="#526174" text-anchor="end">',
    ]

    tick_count = int(axis_maximum / step)
    for tick in range(tick_count + 1):
        value = tick * step
        y = bottom - value * scale
        parts.append(f'<text x="83" y="{y + 4:.1f}">{value:g}</text>')
    parts.append('</g><g stroke="#dbe2ea" stroke-width="1">')
    for tick in range(tick_count + 1):
        y = bottom - tick * step * scale
        parts.append(f'<line x1="{left}" y1="{y:.1f}" x2="{right}" y2="{y:.1f}"/>')
    parts.append(
        f'</g><g stroke="#748195" stroke-width="1.5"><line x1="{left}" y1="{top}" x2="{left}" y2="{bottom}"/><line x1="{left}" y1="{bottom}" x2="{right}" y2="{bottom}"/></g>'
    )

    parts.append('<g font-family="Arial, sans-serif" font-size="13" fill="#344054" text-anchor="middle">')
    for scenario, x in zip(scenarios, x_positions):
        parts.append(f'<text x="{x:.1f}" y="{bottom + 25}">{html.escape(scenario.title())}</text>')
    parts.append(
        f'<text x="{(left + right) / 2:.1f}" y="{bottom + 52}" font-size="12" fill="#526174">Traffic scenario</text></g>'
    )

    parts.append('<g fill="none" stroke-width="2.5">')
    for index, controller in enumerate(controllers):
        color = COLORS[index % len(COLORS)]
        points = []
        for scenario, x in zip(scenarios, x_positions):
            value = means.get((controller, scenario))
            if value is not None:
                points.append(f'{x:.1f},{bottom - value * scale:.1f}')
        if points:
            parts.append(f'<polyline points="{" ".join(points)}" stroke="{color}"/>')
    parts.append('</g><g stroke="#ffffff" stroke-width="1.5">')
    for index, controller in enumerate(controllers):
        color = COLORS[index % len(COLORS)]
        for scenario, x in zip(scenarios, x_positions):
            value = means.get((controller, scenario))
            if value is not None:
                y = bottom - value * scale
                parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4.5" fill="{color}"/>')
    parts.append('</g><g font-family="Arial, sans-serif" font-size="12.5" fill="#344054">')
    legend_x = 750
    legend_start = top + 12
    for index, controller in enumerate(controllers):
        color = COLORS[index % len(COLORS)]
        y = legend_start + index * 30
        label_y = y + 4
        label = html.escape(controller)
        parts.append(
            f'<line x1="{legend_x}" y1="{y}" x2="{legend_x + 28}" y2="{y}" stroke="{color}" stroke-width="3"/><text x="{legend_x + 37}" y="{label_y}">{label}</text>'
        )
    parts.append('</g>')

    note = (
        "Means include all recorded rows, including repeated controller/scenario/seed rows."
        if duplicate_seed_rows
        else "Means include all recorded rows in the CSV."
    )
    parts.append(
        f'<text x="500" y="{height - 20}" text-anchor="middle" font-family="Arial, sans-serif" font-size="11" fill="#667085">{note}</text></svg>'
    )
    return "\n".join(parts) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="Experiment CSV path.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output SVG path.")
    args = parser.parse_args()

    controllers, scenarios, means, duplicate_seed_rows = load_means(args.input)
    svg = create_svg(controllers, scenarios, means, duplicate_seed_rows)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(svg, encoding="utf-8")
    print(f"Loaded {len(means)} controller/scenario group(s) for {len(controllers)} controller(s).")
    print(f"Saved chart to {args.output}")


if __name__ == "__main__":
    main()
