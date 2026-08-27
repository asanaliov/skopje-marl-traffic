from pathlib import Path

import matplotlib.pyplot as plt
import pandas
from pandas.core.groupby import groupby

RESULTS_FILE = Path("results/experiments.csv")
PLOTS_DIR = Path("results/plots")

CONTROLLER_LABELS = {
    "static_fixed_time": "Static Fixed-Time",
    "imported_actuated": "Imported Actuated",
    "independent rl": "Independent RL",
    "coordinated rl": "Coordinated RL",
}

SCENARIO_ORDER = ["low", "medium", "high"]


def load_results():
    if not RESULTS_FILE.exists():
        raise FileNotFoundError("Results file not found.")

    df = pandas.read_csv(RESULTS_FILE)

    if df.empty:
        raise ValueError("experiments.csv is empty")

    return df


def prepare_plot_style():
    """for clean and consistent plot style"""
    plt.style.use("seaborn-v0_8-whitegrid")


def format_controller_name(controller):
    """convert internal controller names into readable labels"""
    return CONTROLLER_LABELS.get(controller, controller.replace("_", " ").title())


def get_scenario_order(df):
    """low -> medium -> high"""
    return [
        scenario for scenario in SCENARIO_ORDER
        if scenario in df["scenario"].unique()
    ]


def plot_average_waiting_time(df):
    scenario_order = get_scenario_order(df)

    grouped = (
        df.groupby(["scenario", "controller"])["average_waiting_time"]
        .mean()
        .unstack()
        .reindex(scenario_order)
    )

    ax = grouped.plot(
        kind="bar",
        figsize=(10, 6),
        width=0.8,
    )

    ax.set_title("Average Waiting Time by Scenario and Controller")
    ax.set_xlabel("Traffic Scenario")
    ax.set_ylabel("Average Waiting Time (seconds)")

    ax.legend(
        title="Controller",
        labels=[
            format_controller_name(controller)
            for controller in grouped.columns
        ]
    )

    plt.xticks(rotation=0)
    plt.tight_layout()

    output_path = PLOTS_DIR / "average_waiting_time.png"

    plt.savefig(
        output_path,
        dpi=300,
        bbox_inches="tight",
    )

    plt.close()

    print(f"Saved: {output_path}")


def plot_average_speed_vs_density(df):
    scenario_order = get_scenario_order(df)

    grouped = (
        df.groupby(["scenario", "controller"])["average_speed"]
        .mean()
        .reset_index()
    )

    plt.figure(figsize=(10, 6))

    for controller, controller_data in grouped.groupby("controller"):
        controller_data = controller_data.copy()

        controller_data["scenario"] = pandas.Categorical(
            controller_data["scenario"],
            categories=scenario_order,
            ordered=True
        )

        controller_data = controller_data.sort_values("scenario")

        plt.plot(
            controller_data["scenario"],
            controller_data["average_speed"],
            marker="o",
            linewidth=2,
            markersize=7,
            label=format_controller_name(controller)
        )

    plt.title("Average Speed vs Vehicle Density")
    plt.xlabel("Traffic Scenario / Vehicle Density")
    plt.ylabel("Average Speed")
    plt.legend(title="Controller")

    plt.tight_layout()

    output_path = PLOTS_DIR / "average_speed_vs_density.png"

    plt.savefig(
        output_path,
        dpi=300,
        bbox_inches="tight"
    )

    plt.close()

    print(f"Saved: {output_path}")


def plot_max_queue_length(df):
    scenario_order = get_scenario_order(df)

    grouped = (
        df.groupby(["scenario", "controller"])["max_queue_length"]
        .mean()
        .unstack()
        .reindex(scenario_order)
    )

    ax = grouped.plot(
        kind="bar",
        figsize=(10, 6),
        width=0.8
    )

    ax.set_title("Maximum Queue Length by Scenario and Controller")
    ax.set_xlabel("Traffic Scenario")
    ax.set_ylabel("Maximum Queue Length (vehicles)")

    ax.legend(
        title="Controller",
        labels=[
            format_controller_name(controller)
            for controller in grouped.columns
        ]
    )

    plt.xticks(rotation=0)
    plt.tight_layout()

    output_path = PLOTS_DIR / "max_queue_length.png"

    plt.savefig(
        output_path,
        dpi=300,
        bbox_inches="tight"
    )

    plt.close()

    print(f"Saved: {output_path}")


def plot_average_queue_length(df):
    scenario_order = get_scenario_order(df)

    grouped = (
        df.groupby(["scenario", "controller"])["average_queue_length"]
        .mean()
        .unstack()
        .reindex(scenario_order)
    )

    ax = grouped.plot(
        kind="bar",
        figsize=(10, 6),
        width=0.8
    )

    ax.set_title("Average Queue Length by Scenario and Controller")
    ax.set_xlabel("Traffic Scenario")
    ax.set_ylabel("Average Queue Length (vehicles)")

    ax.legend(
        title="Controller",
        labels=[
            format_controller_name(controller)
            for controller in grouped.columns
        ]
    )

    plt.xticks(rotation=0)
    plt.tight_layout()

    output_path = PLOTS_DIR / "average_queue_length.png"

    plt.savefig(
        output_path,
        dpi=300,
        bbox_inches="tight"
    )

    plt.close()

    print(f"Saved: {output_path}")


def plot_throughput(df):
    scenario_order = get_scenario_order(df)

    grouped = (
        df.groupby(["scenario", "controller"])["throughput"]
        .mean()
        .unstack()
        .reindex(scenario_order)
    )

    ax = grouped.plot(
        kind="bar",
        figsize=(10, 6),
        width=0.8
    )

    ax.set_title("Throughput by Scenario and Controller")
    ax.set_xlabel("Traffic Scenario")
    ax.set_ylabel("Throughput (vehicles)")

    ax.legend(
        title="Controller",
        labels=[
            format_controller_name(controller)
            for controller in grouped.columns
        ]
    )

    plt.xticks(rotation=0)
    plt.tight_layout()

    output_path = PLOTS_DIR / "throughput.png"

    plt.savefig(
        output_path,
        dpi=300,
        bbox_inches="tight"
    )

    plt.close()

    print(f"Saved: {output_path}")


def main():
    """Generate all experiment comparison plots."""

    PLOTS_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    prepare_plot_style()

    df = load_results()

    print(f"Loaded {len(df)} experiment result(s).")
    print(
        "Controllers:",
        ", ".join(sorted(df["controller"].unique()))
    )

    plot_average_waiting_time(df)
    plot_average_queue_length(df)
    plot_average_speed_vs_density(df)
    plot_max_queue_length(df)
    plot_throughput(df)

    print("Visualization complete!")


if __name__ == "__main__":
    main()
