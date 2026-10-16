# Script usage

PyCharm currently runs the Markdown commands with `scripts/` as the working directory, so these script paths are relative to that folder.

Run the examples with the project virtual environment activated and SUMO available on `PATH`.

From a terminal opened at the repository root, add `scripts/` before each script path and use root-relative paths for input and output files.

## Demand

| Script | What it does | Example |
| --- | --- | --- |
| [`generate_traffic_demand.py`](scripts/demand/generate_traffic_demand.py) | Creates synthetic low, medium, and high traffic demand files. | `python demand/generate_traffic_demand.py --all --seed 42` |
| [`validate_traffic_demand.py`](scripts/demand/validate_traffic_demand.py) | Runs demand scenarios and reports whether their traffic files behave as expected. | `python demand/validate_traffic_demand.py --all --seed 42` |

Demand generation writes files under `sumo/skopje` by default.

Use `--help` to see options for selecting scenarios, duration, output directory, and whether existing files may be overwritten.

## Experiments

| Script | What it does | Example |
| --- | --- | --- |
| [`run_deep_marl.py`](scripts/experiments/run_deep_marl.py) | Trains or evaluates a shared-parameter PPO controller for the selected corridor. | `python experiments/run_deep_marl.py train --scenario medium --seed 42 --episodes 300` |
| [`run_deep_rl_demo.py`](scripts/experiments/run_deep_rl_demo.py) | Runs a short Gymnasium/SUMO-RL compatibility demo; it is not a benchmark evaluation. | `python experiments/run_deep_rl_demo.py --algorithm ppo --scenario medium --timesteps 128 --episode-seconds 600` |
| [`run_imported_actuated_experiment.py`](scripts/experiments/run_imported_actuated_experiment.py) | Evaluates the imported SUMO actuated signal programs for one demand scenario. | `python experiments/run_imported_actuated_experiment.py --scenario medium --seed 42` |
| [`run_imported_actuated_suite.py`](scripts/experiments/run_imported_actuated_suite.py) | Evaluates the imported actuated controller across demand scenarios. | `python experiments/run_imported_actuated_suite.py --seed 42` |
| [`run_multi_agent_q_learning.py`](scripts/experiments/run_multi_agent_q_learning.py) | Trains or evaluates tabular Q-learning controllers for multiple selected lights. | `python experiments/run_multi_agent_q_learning.py train --scenario medium --seed 42 --episodes 50 --checkpoint ../checkpoints/marl_medium.json` |
| [`run_q_learning.py`](scripts/experiments/run_q_learning.py) | Trains or evaluates a tabular Q-learning controller for one traffic light. | `python experiments/run_q_learning.py train --agent-id A19 --scenario medium --seed 42 --episodes 50 --checkpoint ../checkpoints/a19_medium.json` |
| [`run_random_agents.py`](scripts/experiments/run_random_agents.py) | Runs the random-agent SUMO-RL benchmark on the bundled grid network. | `python experiments/run_random_agents.py --seconds 600` |
| [`run_selected_corridor.py`](scripts/experiments/run_selected_corridor.py) | Runs a short simulation of the audited corridor with its original programs. | `python experiments/run_selected_corridor.py --seconds 600` |
| [`run_skopje_simulation.py`](scripts/experiments/run_skopje_simulation.py) | Starts the organized Skopje network with its original signal programs. | `python experiments/run_skopje_simulation.py --seconds 600` |
| [`run_static_fixed_time_experiment.py`](scripts/experiments/run_static_fixed_time_experiment.py) | Evaluates the fixed-green-time baseline for one demand scenario. | `python experiments/run_static_fixed_time_experiment.py --scenario medium --seed 42` |
| [`run_static_fixed_time_suite.py`](scripts/experiments/run_static_fixed_time_suite.py) | Evaluates the fixed-time baseline over selected scenarios and seeds. | `python experiments/run_static_fixed_time_suite.py --seeds 42` |
| [`run_traffic_scenario.py`](scripts/experiments/run_traffic_scenario.py) | Runs a demand scenario using the network's original signal programs. | `python experiments/run_traffic_scenario.py --scenario medium --seed 42 --seconds 600` |

Training examples above start new training runs and may take considerable time.

Use `--help` to see how to resume or evaluate training, set run duration, choose agents, and select output paths.

## Analysis

| Script | What it does | Example |
| --- | --- | --- |
| [`experiment_matrix.py`](scripts/analysis/experiment_matrix.py) | Shows which controller, scenario, and seed combinations have full, partial, or missing results. | `python analysis/experiment_matrix.py ../results/experiments.csv` |
| [`generate_waiting_time_chart.py`](scripts/analysis/generate_waiting_time_chart.py) | Generates the waiting-time comparison SVG from the experiment CSV. | `python analysis/generate_waiting_time_chart.py` |
| [`merge_results.py`](scripts/analysis/merge_results.py) | Merges another results CSV into the project results file; `--dry-run` previews changes. | `python analysis/merge_results.py ../other_machine.csv --dry-run` |
| [`summarize_candidates.py`](scripts/analysis/summarize_candidates.py) | Prints computed comparisons for the audited corridor candidates. | `python analysis/summarize_candidates.py` |
| [`summarize_experiments.py`](scripts/analysis/summarize_experiments.py) | Summarizes recorded evaluation results by controller and scenario. | `python analysis/summarize_experiments.py` |
| [`training_curve.py`](scripts/analysis/training_curve.py) | Reads a training log and extracts reward values, optionally saving them as CSV. | `python analysis/training_curve.py ../logs/deep_marl_local_medium_seed42.log --csv ../results/training_curve.csv` |
| [`visualize_results.py`](scripts/analysis/visualize_results.py) | Creates the project's result plots from the experiment data. | `python analysis/visualize_results.py` |

The chart and plotting scripts write visualizations under `results/` by default.

Use `--help` for custom CSV and output paths where supported.

## Inspection

| Script | What it does | Example |
| --- | --- | --- |
| [`audit_traffic_lights.py`](scripts/inspection/audit_traffic_lights.py) | Audits traffic-light definitions and writes the checked inventory used by the project. | `python inspection/audit_traffic_lights.py` |
| [`check_gym_wrapper.py`](scripts/inspection/check_gym_wrapper.py) | Exercises the Gymnasium wrapper against a short SUMO episode. | `python inspection/check_gym_wrapper.py --scenario low --episode-seconds 60 --cycles 2` |
| [`check_setup.py`](scripts/inspection/check_setup.py) | Checks the local Python and SUMO setup needed to run the project. | `python inspection/check_setup.py` |
| [`generate_agent_labels.py`](scripts/inspection/generate_agent_labels.py) | Generates SUMO POI label files for the audited corridor candidates. | `python inspection/generate_agent_labels.py` |
| [`generate_candidate_selections.py`](scripts/inspection/generate_candidate_selections.py) | Generates Netedit selection and review files for the candidate corridors. | `python inspection/generate_candidate_selections.py` |
| [`inspect_multi_agent_environment.py`](scripts/inspection/inspect_multi_agent_environment.py) | Prints observations and environment details for selected agents during a simulation. | `python inspection/inspect_multi_agent_environment.py --scenario medium --agents A19,A26 --seconds 60` |
| [`inspect_skopje_network.py`](scripts/inspection/inspect_skopje_network.py) | Prints network statistics and can refresh the checked network documentation. | `python inspection/inspect_skopje_network.py --write-documentation` |
| [`inspect_traffic_agent.py`](scripts/inspection/inspect_traffic_agent.py) | Inspects one or all selected agents during a SUMO simulation. | `python inspection/inspect_traffic_agent.py --scenario medium --agent A19 --seconds 60` |
| [`open_candidate_in_netedit.py`](scripts/inspection/open_candidate_in_netedit.py) | Opens a candidate corridor in SUMO Netedit for visual review. | `python inspection/open_candidate_in_netedit.py --candidate 1` |
| [`run_candidate_review.py`](scripts/inspection/run_candidate_review.py) | Runs a candidate corridor simulation for visual or report-based review. | `python inspection/run_candidate_review.py --candidate 1 --seconds 600` |
| [`show_agent_graph.py`](scripts/inspection/show_agent_graph.py) | Prints the audited adjacency graph of the selected traffic-light agents. | `python inspection/show_agent_graph.py` |
| [`show_selected_corridor.py`](scripts/inspection/show_selected_corridor.py) | Prints the selected corridor's traffic-light IDs and connections. | `python inspection/show_selected_corridor.py` |

`inspect_skopje_network.py --write-documentation` regenerates `traffic_lights.csv` and `network_summary.md`.

The label and candidate-selection generators write files used for SUMO and Netedit review.

## Finding command options

Pass `--help` after a script path to list its available options.

For example:

```powershell
python experiments/run_q_learning.py --help
python experiments/run_q_learning.py train --help
```

The setup checker and several print-only inspection scripts do not define command-line options, so run them without `--help`.
