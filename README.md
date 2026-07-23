# Multi-Agent Reinforcement Learning for Adaptive Traffic Light Control in Skopje

This project will study adaptive traffic-signal control in Skopje with SUMO and multi-agent reinforcement learning, with the goal of comparing traffic efficiency under progressively more coordinated control strategies.

## Planned comparison

- Fixed-time control
- Independent reinforcement learning
- Coordinated multi-agent reinforcement learning

## Windows setup

Open the project in PyCharm and select the existing `.venv` as the project interpreter.
SUMO must be installed separately on Windows.
Set `SUMO_HOME` to the SUMO installation directory and add its `bin` directory to `PATH`.

Run these commands in PowerShell from the project root:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

Check the interpreter, SUMO tools, and Python dependencies:

```powershell
python scripts/check_setup.py
```

## Random-agent smoke test

Place the grid4x4 benchmark files at `sumo\benchmark\grid4x4\grid4x4.net.xml` and `sumo\benchmark\grid4x4\grid4x4_1.rou.xml`.
If the downloaded files use different names, edit the two filename constants near the top of `scripts\run_random_agents.py`.

Run a short headless simulation:

```powershell
python scripts/run_random_agents.py --seconds 300
```

Add `--gui` to view the simulation:

```powershell
python scripts/run_random_agents.py --gui --seconds 300
```

## Skopje OSM Scenario

The complete original SUMO OSM Web Wizard output is preserved under `sumo/skopje/source/wizard_initial/`.
The organized scenario is split across `sumo/skopje/network/`, `sumo/skopje/demand/`, `sumo/skopje/config/`, `sumo/skopje/polygons/`, and `sumo/skopje/additional/`.

The road geometry and map shapes come from OpenStreetMap.
The initial passenger demand was generated synthetically by the wizard and does not represent measured Skopje traffic volumes.

Inspect the imported network without starting SUMO:

```powershell
python scripts/inspect_skopje_network.py
```

Run a 10-minute visual smoke test with the original SUMO traffic-light programs:

```powershell
python scripts/run_skopje_simulation.py --gui --seconds 600
```

Omit `--gui` for a headless run.
This is only the first imported Skopje network.
Traffic-light cleanup, measured-demand calibration, baseline evaluation, and multi-agent reinforcement learning are still pending.

## Traffic-Light Network Audit

The traffic-light audit computes directed network paths between controllers without changing the imported SUMO network.
It records signal phases, controlled edges, lane and speed information, network-path neighbors, and conservative named-road corridor relationships.

Regenerate the audit CSV files and corridor recommendations:

```powershell
python scripts/audit_traffic_lights.py
```

Print the generated directed agent adjacency list:

```powershell
python scripts/show_agent_graph.py
```

Inspect the wider network statistics and traffic-light connected components:

```powershell
python scripts/inspect_skopje_network.py
```

The audit prepares connected subsets of 6 to 10 intersections for the first multi-agent reinforcement-learning experiment.
Candidate groups remain recommendations until their roads, turns, lanes, and signal programs are checked manually in netedit.

## Candidate Corridor Review

The candidate review tools compare the three audited 8-controller subsets without modifying the complete imported network, its demand, or its original traffic-light programs.
The generated Netedit selections highlight each candidate's controlled junctions, controlled passenger edges, and passenger-compatible paths between candidate neighbors.

Regenerate deterministic selection files and candidate review sheets:

```powershell
python scripts/generate_candidate_selections.py
```

Generate POI labels from the audited agent coordinates:

```powershell
python scripts/generate_agent_labels.py
```

Print the computed candidate comparison table:

```powershell
python scripts/summarize_candidates.py
```

Open Candidate 1 with its selection in Netedit:

```powershell
python scripts/open_candidate_in_netedit.py --candidate 1
```

After Netedit opens, press F9 and open the POI visualization settings.
Enable Show ID and constant text size, then increase the text size if labels such as A9 and A18 are too small.

Observe Candidate 1 under the original demand and signal programs in SUMO-GUI:

```powershell
python scripts/run_candidate_review.py --candidate 1 --seconds 600 --gui
```

Replace `1` with `2` or `3` to review the other candidates.

## Selected Experimental Corridor

Candidate 1 was manually reviewed and selected as the official experimental corridor.
Its selected agents are A9, A18, A19, A20, A24, A25, A26, and A29.
The full Skopje network remains active, and only these eight traffic lights are future learning agents.
All other traffic lights retain their original fixed SUMO programs.

Inspect the selected mappings and graph:

```powershell
python scripts/show_selected_corridor.py
```

Run the complete scenario headlessly without learning actions:

```powershell
python scripts/run_selected_corridor.py --seconds 600
```

Run the same fixed-program smoke test in SUMO-GUI:

```powershell
python scripts/run_selected_corridor.py --gui --seconds 600
```

See `sumo/skopje/documentation/selected_corridor.md` for the audited controller mappings, directed neighbor distances, review evidence, warnings, and limitations.

## Synthetic Traffic-Demand Scenarios

Low, medium, and high synthetic demand scenarios use the same complete Skopje network with different passenger-vehicle volumes.
Most generated trips traverse the selected corridor, while background trips retain wider-network traffic.
These scenarios are synthetic experimental loads and are not official or measured Skopje traffic data.
Seed 42 is the canonical committed example.

Generate all canonical scenarios:

```powershell
python scripts/generate_traffic_demand.py --all --seed 42
```

Validate the generated files and run each scenario headlessly:

```powershell
python scripts/validate_traffic_demand.py --all --seed 42
```

Review the medium scenario visually:

```powershell
python scripts/run_traffic_scenario.py --scenario medium --seed 42 --gui
```

Fixed-time, independent RL, and coordinated MARL comparisons are not implemented yet.
See `sumo/skopje/documentation/traffic_demand.md` for generation details, validation results, limitations, and reproducibility guarantees.

## Traffic-Agent Interface

The selected agents can observe queue lengths, vehicle counts, mean accumulated waiting times, and mean speeds for their controlled incoming lanes.
Their only actions are `KEEP` and `NEXT_GREEN`.
The safe action wrapper preserves the immediate yellow and all-red phases from each original SUMO program and never jumps directly between conflicting greens.
Pure local rewards and optional future neighbor-aware and global corridor reward helpers are defined separately from experiment metrics.
No learning algorithm is implemented yet.

Inspect A19 in the canonical medium scenario:

```powershell
python scripts/inspect_traffic_agent.py --scenario medium --seed 42 --agent A19
```

Inspect all eight selected agents:

```powershell
python scripts/inspect_traffic_agent.py --scenario medium --seed 42 --all
```

Inspect the high-demand scenario in SUMO-GUI:

```powershell
python scripts/inspect_traffic_agent.py --scenario high --seed 42 --all --gui
```

See `sumo/skopje/documentation/traffic_agent_interface.md` for the feature ordering, phase structures, timing policy, safe-transition rules, reward formulas, and limitations.

## Current status

The initial package structure, shared configuration, setup checker, random-agent integration smoke test, and first imported Skopje scenario are in place.
Traffic-light cleanup, calibrated real-world demand, and reinforcement-learning training algorithms are not implemented yet.
