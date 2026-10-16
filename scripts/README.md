# Scripts usage manual

This manual describes the runnable Python scripts in this folder and gives a starting command for each one.

PyCharm starts Markdown Run commands with `scripts/` as the working directory. Each example changes to the repository root before running the script.

The examples use PowerShell syntax. To run one from an already-open repository-root terminal, remove the leading `Set-Location ..;`.

Activate the project virtual environment and make sure SUMO is available on `PATH` before running SUMO commands.

On Windows PowerShell, the commands below use `python`, as do the examples in the root README.

In Windows PowerShell, run `.\helpme.bat` from the repository root to list the available script commands.

On Linux or macOS, use `./helpme`.

Add `--full` to open this detailed manual in the terminal.

The Windows command pages the full manual with `more`.

The Linux and macOS command uses `less` when it is installed and otherwise prints the full manual with `cat`.

Most scripts accept `--help` to show all options.

Some scripts need SUMO or project dependencies before they can start, so run the setup check first.

```powershell
Set-Location ..; python scripts/inspection/check_setup.py
```

Experiment commands can take a long time and append evaluation rows to `results/experiments.csv` unless an output path is specified.

Training commands can save model checkpoints, while demand and inspection commands can write generated files.

## Demand

| Script | What it does | Example |
| --- | --- | --- |
| [`generate_traffic_demand.py`](demand/generate_traffic_demand.py) | Creates synthetic low, medium, and high traffic demand files. | `Set-Location ..; python scripts/demand/generate_traffic_demand.py --all --seed 42` |
| [`validate_traffic_demand.py`](demand/validate_traffic_demand.py) | Runs demand scenarios and reports whether their traffic files behave as expected. | `Set-Location ..; python scripts/demand/validate_traffic_demand.py --all --seed 42` |

Demand generation writes files under `sumo/skopje` by default.

Use `--help` to see options for selecting scenarios, duration, output directory, and whether existing files may be overwritten.

## Experiments

| Script | What it does | Example |
| --- | --- | --- |
| [`run_deep_marl.py`](experiments/run_deep_marl.py) | Trains or evaluates a shared-parameter PPO controller for the selected corridor. | `Set-Location ..; python scripts/experiments/run_deep_marl.py train --scenario medium --seed 42 --episodes 300` |
| [`run_deep_rl_demo.py`](experiments/run_deep_rl_demo.py) | Runs a short Gymnasium/SUMO-RL compatibility demo; it is not a benchmark evaluation. | `Set-Location ..; python scripts/experiments/run_deep_rl_demo.py --algorithm ppo --scenario medium --timesteps 128 --episode-seconds 600` |
| [`run_imported_actuated_experiment.py`](experiments/run_imported_actuated_experiment.py) | Evaluates the imported SUMO actuated signal programs for one demand scenario. | `Set-Location ..; python scripts/experiments/run_imported_actuated_experiment.py --scenario medium --seed 42` |
| [`run_imported_actuated_suite.py`](experiments/run_imported_actuated_suite.py) | Evaluates the imported actuated controller across demand scenarios. | `Set-Location ..; python scripts/experiments/run_imported_actuated_suite.py --seed 42` |
| [`run_multi_agent_q_learning.py`](experiments/run_multi_agent_q_learning.py) | Trains or evaluates tabular Q-learning controllers for multiple selected lights. | `Set-Location ..; python scripts/experiments/run_multi_agent_q_learning.py train --scenario medium --seed 42 --episodes 50 --checkpoint checkpoints/marl_medium.json` |
| [`run_q_learning.py`](experiments/run_q_learning.py) | Trains or evaluates a tabular Q-learning controller for one traffic light. | `Set-Location ..; python scripts/experiments/run_q_learning.py train --agent-id A19 --scenario medium --seed 42 --episodes 50 --checkpoint checkpoints/a19_medium.json` |
| [`run_random_agents.py`](experiments/run_random_agents.py) | Runs the random-agent SUMO-RL benchmark on the bundled grid network. | `Set-Location ..; python scripts/experiments/run_random_agents.py --seconds 600` |
| [`run_selected_corridor.py`](experiments/run_selected_corridor.py) | Runs a short simulation of the audited corridor with its original programs. | `Set-Location ..; python scripts/experiments/run_selected_corridor.py --seconds 600` |
| [`run_skopje_simulation.py`](experiments/run_skopje_simulation.py) | Starts the organized Skopje network with its original signal programs. | `Set-Location ..; python scripts/experiments/run_skopje_simulation.py --seconds 600` |
| [`run_static_fixed_time_experiment.py`](experiments/run_static_fixed_time_experiment.py) | Evaluates the fixed-green-time baseline for one demand scenario. | `Set-Location ..; python scripts/experiments/run_static_fixed_time_experiment.py --scenario medium --seed 42` |
| [`run_static_fixed_time_suite.py`](experiments/run_static_fixed_time_suite.py) | Evaluates the fixed-time baseline over selected scenarios and seeds. | `Set-Location ..; python scripts/experiments/run_static_fixed_time_suite.py --seeds 42` |
| [`run_traffic_scenario.py`](experiments/run_traffic_scenario.py) | Runs a demand scenario using the network's original signal programs. | `Set-Location ..; python scripts/experiments/run_traffic_scenario.py --scenario medium --seed 42 --seconds 600` |

Training examples above start new training runs and may take considerable time.

Use `--help` to see how to resume or evaluate training, set run duration, choose agents, and select output paths.

## Analysis

| Script | What it does | Example |
| --- | --- | --- |
| [`experiment_matrix.py`](analysis/experiment_matrix.py) | Shows which controller, scenario, and seed combinations have full, partial, or missing results. | `Set-Location ..; python scripts/analysis/experiment_matrix.py results/experiments.csv` |
| [`generate_waiting_time_chart.py`](analysis/generate_waiting_time_chart.py) | Generates the waiting-time comparison SVG from the experiment CSV. | `Set-Location ..; python scripts/analysis/generate_waiting_time_chart.py` |
| [`merge_results.py`](analysis/merge_results.py) | Merges another results CSV into the project results file; `--dry-run` previews changes. | `Set-Location ..; python scripts/analysis/merge_results.py other_machine.csv --dry-run` |
| [`summarize_candidates.py`](analysis/summarize_candidates.py) | Prints computed comparisons for the audited corridor candidates. | `Set-Location ..; python scripts/analysis/summarize_candidates.py` |
| [`summarize_experiments.py`](analysis/summarize_experiments.py) | Summarizes recorded evaluation results by controller and scenario. | `Set-Location ..; python scripts/analysis/summarize_experiments.py` |
| [`training_curve.py`](analysis/training_curve.py) | Reads a training log and extracts reward values, optionally saving them as CSV. | `Set-Location ..; python scripts/analysis/training_curve.py logs/deep_marl_local_medium_seed42.log --csv results/training_curve.csv` |
| [`visualize_results.py`](analysis/visualize_results.py) | Creates the project's result plots from the experiment data. | `Set-Location ..; python scripts/analysis/visualize_results.py` |

The chart and plotting scripts write visualizations under `results/` by default.

Use `--help` for custom CSV and output paths where supported.

## Inspection

| Script | What it does | Example |
| --- | --- | --- |
| [`audit_traffic_lights.py`](inspection/audit_traffic_lights.py) | Audits traffic-light definitions and writes the checked inventory used by the project. | `Set-Location ..; python scripts/inspection/audit_traffic_lights.py` |
| [`check_gym_wrapper.py`](inspection/check_gym_wrapper.py) | Exercises the Gymnasium wrapper against a short SUMO episode. | `Set-Location ..; python scripts/inspection/check_gym_wrapper.py --scenario low --episode-seconds 60 --cycles 2` |
| [`check_setup.py`](inspection/check_setup.py) | Checks the local Python and SUMO setup needed to run the project. | `Set-Location ..; python scripts/inspection/check_setup.py` |
| [`generate_agent_labels.py`](inspection/generate_agent_labels.py) | Generates SUMO POI label files for the audited corridor candidates. | `Set-Location ..; python scripts/inspection/generate_agent_labels.py` |
| [`generate_candidate_selections.py`](inspection/generate_candidate_selections.py) | Generates Netedit selection and review files for the candidate corridors. | `Set-Location ..; python scripts/inspection/generate_candidate_selections.py` |
| [`inspect_multi_agent_environment.py`](inspection/inspect_multi_agent_environment.py) | Prints observations and environment details for selected agents during a simulation. | `Set-Location ..; python scripts/inspection/inspect_multi_agent_environment.py --scenario medium --agents A19,A26 --seconds 60` |
| [`inspect_skopje_network.py`](inspection/inspect_skopje_network.py) | Prints network statistics and can refresh the checked network documentation. | `Set-Location ..; python scripts/inspection/inspect_skopje_network.py --write-documentation` |
| [`inspect_traffic_agent.py`](inspection/inspect_traffic_agent.py) | Inspects one or all selected agents during a SUMO simulation. | `Set-Location ..; python scripts/inspection/inspect_traffic_agent.py --scenario medium --agent A19 --seconds 60` |
| [`open_candidate_in_netedit.py`](inspection/open_candidate_in_netedit.py) | Opens a candidate corridor in SUMO Netedit for visual review. | `Set-Location ..; python scripts/inspection/open_candidate_in_netedit.py --candidate 1` |
| [`run_candidate_review.py`](inspection/run_candidate_review.py) | Runs a candidate corridor simulation for visual or report-based review. | `Set-Location ..; python scripts/inspection/run_candidate_review.py --candidate 1 --seconds 600` |
| [`show_agent_graph.py`](inspection/show_agent_graph.py) | Prints the audited adjacency graph of the selected traffic-light agents. | `Set-Location ..; python scripts/inspection/show_agent_graph.py` |
| [`show_selected_corridor.py`](inspection/show_selected_corridor.py) | Prints the selected corridor's traffic-light IDs and connections. | `Set-Location ..; python scripts/inspection/show_selected_corridor.py` |

`inspect_skopje_network.py --write-documentation` regenerates `traffic_lights.csv` and `network_summary.md`.

The label and candidate-selection generators write files used for SUMO and Netedit review.

## Finding command options

Pass `--help` after a script path to list its available options.

For example:

```powershell
Set-Location ..; python scripts/experiments/run_q_learning.py --help
Set-Location ..; python scripts/experiments/run_q_learning.py train --help
```

The setup checker and several print-only inspection scripts do not define command-line options, so run them without `--help`.
