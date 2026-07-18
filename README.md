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
Traffic-light cleanup, manual intersection review, demand modeling, baseline evaluation, and multi-agent reinforcement learning are still pending.

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

## Current status

The initial package structure, shared configuration, setup checker, random-agent integration smoke test, and first imported Skopje scenario are in place.
Traffic-light cleanup, calibrated demand, and reinforcement-learning training algorithms are not implemented yet.
