# Reproducible Synthetic Traffic Demand for Skopje

## Purpose and data status

The project uses synthetic passenger demand so fixed-program and future learning controllers can eventually be compared under repeatable load levels.
No official, measured, or calibrated Skopje traffic-count dataset is claimed or included.
The scenario names low, medium, and high describe experimental load levels only.
They are not measured real-world Skopje traffic categories.

Every scenario uses the complete unchanged Skopje network and its original SUMO traffic-light programs.
The selected experimental corridor remains Candidate 1 with agents A9, A18, A19, A20, A24, A25, A26, and A29.
Most generated trips traverse this corridor, while background trips preserve activity in the wider network.

## Canonical scenarios

| Scenario | Duration | Vehicles | Corridor share | Minimum selected agents crossed |
| --- | ---: | ---: | ---: | ---: |
| Low | 3600 s | 900 | 70% | 1 |
| Medium | 3600 s | 1800 | 80% | 2 |
| High | 3600 s | 3000 | 85% | 2 |

All canonical scenarios use passenger vehicles, a minimum planned route length of 300 m, and seed 42.
The requested values proved usable in real duarouter and SUMO validation, so no vehicle count or share was adjusted.

The exact planned splits are:

- Low: 630 corridor trips and 270 background trips.
- Medium: 1,440 corridor trips and 360 background trips.
- High: 2,550 corridor trips and 450 background trips.

## Route-generation method

The generator loads the real compressed Skopje network through sumolib.
It considers only non-internal edges that allow the SUMO `passenger` vehicle class.
Selected controlled incoming edges are loaded from `traffic_light_audit.csv` rather than copied into source code.

Corridor origins and destinations are sampled from west, east, south, and north boundary zones with a seeded `random.Random` instance.
Origin and destination zones differ so the candidate pool remains geographically and directionally diverse.
Corridor routes begin on a boundary edge before the first selected controlled edge and end after the last selected controlled edge.
Background routes use the wider passenger-compatible network and remain below the scenario corridor-crossing requirement.

For each origin and destination pair, sumolib finds the shortest passenger path.
The generator rejects identical endpoints, internal or incompatible edges, disconnected pairs, short paths, and paths that do not meet the selected-agent requirement.
Accepted origin and destination pairs are unique within a generated scenario.
Generation uses bounded attempts and reports all rejected pair attempts.

The trips XML records the validated intermediate path as SUMO `via` edges.
This prevents duarouter from replacing a planned path with a different equal-cost path that changes selected-agent coverage.
Duarouter still validates every connection and produces the committed `.rou.xml` route file.
The normalized route writer removes timestamp comments and writes stable XML.

## Selected-agent crossing detection

A route crosses a selected agent when it contains one of that agent's audited controlled incoming edges.
Agents are counted only once per route even if multiple controlled incoming edges for the same agent occur.
Corridor routes must cross at least the number of selected agents specified in the scenario table.
Background routes are not required to cross a selected traffic light.

## Reproducibility

Seed 42 is committed as the canonical example because it provides one stable reference for collaboration and regression testing.
The same scenario, seed, network, audit data, generator version, and SUMO version produce byte-identical trips and normalized route files.
Vehicle IDs are sequential, departures are sorted, and route selection uses stable edge ordering.
The metadata timestamp records when generation occurred and is intentionally excluded from byte-identity comparisons.

Each metadata file records the network SHA-256 checksum, selected agents, planned split, duration, route statistics, crossing distribution, generator version, and a synthetic-demand notice.
Generated files for arbitrary seeds are ignored by Git, while canonical seed-42 files remain trackable.

## Canonical generation results

| Scenario | Planned route minimum | Planned route mean | Planned route maximum | Rejected pairs |
| --- | ---: | ---: | ---: | ---: |
| Low | 301.57 m | 2213.99 m | 4991.12 m | 1,037 |
| Medium | 354.81 m | 2542.89 m | 6208.65 m | 2,775 |
| High | 328.07 m | 2585.77 m | 6208.65 m | 4,851 |

Duarouter completed successfully for all 5,700 generated vehicles.
Static validation confirmed the exact requested corridor shares after routing.

## 600-second SUMO validation

The validation runner used headless SUMO, seed 42, the generated scenario configs, and the original traffic-light programs.
It did not issue traffic-light actions and did not import the teammate-owned experiment metrics.

| Scenario | Departed | Arrived | Active | Teleports | Final halted | Selected maximum-queue score | Selected-agent coverage |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Low | 149 | 81 | 68 | 0 | 3 | 6 | 8/8 |
| Medium | 299 | 148 | 151 | 0 | 18 | 18 | 8/8 |
| High | 500 | 194 | 306 | 0 | 39 | 30 | 8/8 |

The selected maximum-queue score is the sum of each selected agent's maximum queue across ten 60-second samples.
It is a local calibration diagnostic, not an experiment metric.

Low traffic moved mostly freely and selected queues remained at or below one vehicle in the samples.
Medium traffic reached every selected agent and produced temporary queues, including a maximum sampled queue of nine at A20.
High traffic reached every selected agent and produced more overall selected congestion than medium while vehicles continued completing routes.
No scenario reported a route error, teleport, persistent deadlock, or catastrophic gridlock during the 600-second validation window.

## Commands

Generate all canonical scenarios:

```powershell
python scripts/demand/generate_traffic_demand.py --all --seed 42
```

Use `--overwrite` when intentionally regenerating existing canonical files:

```powershell
python scripts/demand/generate_traffic_demand.py --all --seed 42 --overwrite
```

Validate all generated scenarios for 600 seconds:

```powershell
python scripts/demand/validate_traffic_demand.py --all --seed 42 --seconds 600
```

Review the medium scenario headlessly:

```powershell
python scripts/experiments/run_traffic_scenario.py --scenario medium --seed 42
```

Review the medium scenario in SUMO-GUI:

```powershell
python scripts/experiments/run_traffic_scenario.py --scenario medium --seed 42 --gui
```

## Limitations

- Vehicle counts and corridor shares are initial experimental calibration values rather than observed traffic counts.
- Demand is distributed across the full hour and does not model measured rush-hour profiles.
- Passenger cars are the only generated vehicle class.
- Origin and destination sampling does not model observed neighborhood travel demand.
- SUMO shortest-path routing does not represent route choice learned from real drivers.
- The 600-second validation covers only the first part of each 3,600-second scenario.
- Queue observations in this document are local smoke-test diagnostics and should not be mixed with the experiment metrics in `results/experiments.csv`.

## Future calibration

If an authoritative Skopje traffic-count dataset becomes available, future work can calibrate entry flows, turning proportions, hourly profiles, vehicle classes, and origin-destination weights.
Measured data should be documented with its source, date, coverage, uncertainty, and license.
Calibrated scenarios should be added separately so these reproducible synthetic baselines remain available.
