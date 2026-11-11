# Reproducible Synthetic Traffic Demand for Skopje

## Purpose and data status

The project uses synthetic passenger demand so fixed-program and future learning controllers can eventually be compared under repeatable load levels.
No official, measured, or calibrated Skopje traffic-count dataset is claimed or included.
The scenario names low, medium, high, peak, and stress describe experimental load levels only.
They are not measured real-world Skopje traffic categories.

Every scenario uses the complete unchanged Skopje network and its original SUMO traffic-light programs.
The selected experimental corridor remains Candidate 1 with agents A9, A18, A19, A20, A24, A25, A26, and A29.
Most generated trips traverse this corridor, while background trips preserve activity in the wider network.

## Canonical scenarios

| Scenario | Duration | Vehicles | Corridor share | Minimum selected agents crossed | Departures | Rerouting |
| --- | ---: | ---: | ---: | ---: | --- | ---: |
| Low | 3600 s | 900 | 70% | 1 | even | 0 |
| Medium | 3600 s | 1800 | 80% | 2 | even | 0 |
| High | 3600 s | 3000 | 85% | 2 | even | 0 |
| Peak | 3600 s | 4600 | 88% | 2 | rush-hour profile | 50% |
| Stress | 3600 s | 5400 | 88% | 2 | rush-hour profile | 50% |

All canonical scenarios use passenger vehicles, a minimum planned route length of 300 m, and seed 42.

The exact planned splits are:

- Low: 630 corridor trips and 270 background trips.
- Medium: 1,440 corridor trips and 360 background trips.
- High: 2,550 corridor trips and 450 background trips.
- Peak: 4,048 corridor trips and 552 background trips.
- Stress: 4,752 corridor trips and 648 background trips.

Low, medium and high spread departures evenly across the hour and keep every
vehicle on its pre-computed route. Peak and stress are described below.

## Peak scenario: weekday rush hour

Peak represents a weekday morning or afternoon rush hour on the corridor. It is
synthetic: shaped by published facts about Skopje peak traffic and by on-site
knowledge of the corridor, not calibrated to measured counts. It was tuned on
the `real_signals` network, the one the deep MARL controllers are trained on.

Compared with high:

- **Volume:** 4,600 vehicles in the hour, 1.5 times high.
- **Corridor focus:** 88% of trips cross at least two selected agents. A21,
  an agent only on `real_signals`, also counts (`extra_corridor_agents`), so
  demand loads it on both networks.
- **Time profile:** the hour is split into quarter-hours that receive 22%, 27%,
  30% and 21% of departures (`departure_profile`). The busiest quarter runs at
  the equivalent of 5,520 vehicles per hour. The peak hour factor is
  1 / (4 × 0.30) ≈ 0.83, sharper than the HCM urban default of 0.92.
- **Street weights:** corridor routes are steered onto Bulevar Partizanski
  odredi (mostly 3 lanes per direction) and Ilinden (which loads A21), weight 8
  each, and away from Bulevar Vodnjanska (mostly 2), weight 0.05
  (`street_weights`). A route is favoured if it uses any favoured street; each
  avoided street multiplies in. In the planned routes 77% of trips use
  Partizanski, 16% Ilinden and 5% Vodnjanska.
- **Rerouting:** half of the vehicles pick the fastest route under current
  traffic when they depart (`rerouting_probability`, written into the SUMO
  config as `device.rerouting.probability`). Commuters in a daily rush hour
  adapt their routes to congestion through experience and navigation apps;
  fixed shortest-path routes overload single streets. 50% worked better than
  100%, where every driver switches to the same alternative at once.

### Choosing the volume

Imported actuated control on `real_signals`, seeds 42–44, full hour plus the
600 s cooldown; teleports and vehicles still running at the end, averaged.
First sweep, with Partizanski and Vodnjanska weighted only:

| Vehicles | No rerouting | 50% rerouting |
| ---: | --- | --- |
| 3,400 | 2 / 5 (0.1%) | 1 / 2 (0.1%) |
| 3,800 | 31 / 99 (2.6%) | 5 / 3 (0.1%) |
| 4,200 | 148 / 791 (19%) | 13 / 53 (1.3%) |
| 4,600 | 195 / 1,108 (24%) | 16 / 78 (1.7%) |
| 5,000 | 499 / 1,922 (38%) | 53 / 338 (6.8%) |
| 5,400 | 672 / 2,342 (43%) | 122 / 762 (14%) |

Without rerouting the network gridlocks just above 3,800. Adding Ilinden and
A21 to the route mix sends more traffic into A19 from the north and lowers the
limit slightly (50% rerouting):

| Vehicles | Teleports / left | Per seed |
| ---: | --- | --- |
| **4,600** | **8 / 20 (0.4%)** | 8/14, 6/24, 10/22 |
| 4,800 | 36 / 191 (4.0%) | 74/394, 21/91, 14/88 |
| 5,000 | 23 / 171 (3.4%) | 31/293, 21/109, 16/111 |

4,600 is the highest volume at which every seed clears. At 4,800 and above a
run can tip into gridlock by chance (seed 42), which would make controller
comparisons depend on the seed rather than on control. Corridor share 95%, a
flatter departure profile, mid-trip rerouting and milder street weights were
also tried and did not raise the limit.

Baselines at 4,600 on `real_signals`:

| Controller | Seed | Avg. waiting (s) | Avg. queue | Throughput | Teleports | Left |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Static fixed-time | 42 | 20.58 | 63.71 | 4,349 | 35 | 249 |
| Static fixed-time | 43 | 22.03 | 64.32 | 4,318 | 49 | 273 |
| Static fixed-time | 44 | 25.66 | 63.16 | 4,199 | 98 | 394 |
| Imported actuated | 42 | 11.57 | 30.12 | 4,586 | 8 | 14 |
| Imported actuated | 43 | 11.96 | 29.99 | 4,576 | 6 | 24 |
| Imported actuated | 44 | 11.99 | 29.48 | 4,578 | 10 | 22 |

Actuated clears on every seed; static fixed-time is at its limit (5–9% of
vehicles still running at the end).

Peak is not teleport-free: SUMO teleports a vehicle blocked for 300 s, which
slightly flatters waiting time, so teleports and vehicles left must be reported
next to every peak result.

### Caveats

- **Vodnjanska is under-loaded on purpose.** CUKS morning reports regularly
  list Kliment Ohridski and Kiril i Metodij as congested toward Vodnjanska, so
  the real street is busy at peak. Cutting its share moves load onto
  Partizanski, which the agents control, and lifts the network's capacity.
  This is a modelling choice, not a measurement.
- **Rerouting is an assumption about driver behaviour**, not measured; 50% is
  the share that gave the highest clean volume.
- **Agent load is uneven.** Planned vehicles per agent on `real_signals`: A19
  2,372, A26 1,936, A18 1,923, A25 1,361, A9 744, A24 687, A21 392, A20 335.
  A21 and A20 stay light: through traffic on Ilinden crosses only A21 and does
  not qualify as a corridor trip, and Vodnjanska (A20) is avoided on purpose.
- The peak-hour bus lane on Partizanski is not modelled; on site, cars use it.

## Stress scenario: past capacity

Stress is peak with 5,400 vehicles, past what the network clears in the
cooldown. It tests how controllers degrade, not which one is best: at this
volume about 70% of teleports happen on streets no agent controls, while
soboren (A19) itself starts to gridlock. Report teleports at the agents
separately from the rest.

Baselines on `real_signals`:

| Controller | Seed | Avg. waiting (s) | Avg. queue | Throughput | Teleports | Left |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Static fixed-time | 42 | 26.08 | 73.84 | 4,815 | 87 | 582 |
| Static fixed-time | 43 | 26.15 | 74.93 | 4,781 | 85 | 612 |
| Static fixed-time | 44 | 33.47 | 82.92 | 4,340 | 182 | 1032 |
| Imported actuated | 42 | 15.48 | 49.82 | 5,111 | 25 | 287 |
| Imported actuated | 43 | 23.67 | 51.23 | 4,580 | 148 | 812 |
| Imported actuated | 44 | 14.11 | 43.17 | 5,302 | 14 | 98 |

Seed-to-seed spread is large here (actuated: 98 to 812 vehicles left), as
expected past capacity; use more seeds before drawing conclusions from stress.

### Evidence used

- Measured peak flows at central Skopje intersections are far above what this
  simulated network can carry. Loop-detector counts from the city's Traffic
  Management Control Centre for 2017, on seven signalised intersections on a
  congested corridor in the wider centre (the paper does not name the
  streets), give 1,477 to 5,110 vehicles per hour in the 07:20–08:20 morning
  peak, 3,175 on average. The peak scenario plans about 1,220 vehicles per hour
  through each selected agent on average and about 2,370 through the busiest
  (A19). Those intersections are not these agents, so the
  counts are a scale reference, not a calibration target. They do show that
  the synthetic scenarios are conservative and that the imported network
  saturates at a fraction of real capacity, most likely because of imported
  signal timings, OpenStreetMap lane data, and shortest-path routing.
  The same work found Skopje's adaptive UTOPIA control beat fixed-time control
  on queues and throughput in VISSIM.
  ([Pavleski, Koltovska Nechoska, Ivanjko, ELMAR-2017](https://eprints.uklo.edu.mk/id/eprint/5737/);
  [Pavleski, Koltovska Nechoska, Ivanjko, TTS 2018, DOI 10.20544/TTS2018.P21](https://eprints.uklo.edu.mk/id/eprint/5736/1/ttsconference2018.pdf))

- Skopje's Sustainable Urban Mobility Plan work reports that the city is
  severely congested every working day in the morning and afternoon peaks.
  Its household survey found that 56% of morning-peak trips are made as a car
  driver, compared with roughly a third of trips across the whole day, and its
  traffic counts were taken specifically in the morning and afternoon peaks.
  ([Creating Infrastructure for Urban Mobility: Case Study of Skopje](https://www.researchgate.net/publication/327578299_Creating_Infrastructure_for_Urban_Mobility_Case_Study_of_Skopje);
  [CIVITAS case study](https://civitas.eu/resources/civitas-case-study-planning-a-sustainable-urban-transport-system-in-skopje))
- Partizanski Odredi is a main artery with recurring rush-hour bottlenecks.
  In a public debate on removing one lane in each direction for other uses,
  the estimated capacity loss was about 30%, so the boulevard already runs
  close to capacity at peak. ([Free Press](https://www.slobodenpecat.mk/en/dali-plasticharska-i-ushte-nekolku-bulevari-kje-go-izbegnat-okoto-na-sejf-siti/))
- Skopje's traffic control centre (CUKS) records vehicle counts around the
  clock at 92 signalised intersections, and a 2026 air-quality study used hourly
  counts from 79 loop-detector sites. Neither dataset is published, so neither
  could be used here. ([City of Skopje traffic sector](https://skopje.gov.mk/mk/skopje/administracija/sektor-soobrakjaj/);
  [Urban Science 10(5):250](https://doi.org/10.3390/urbansci10050250))
- Skopje passed 155,000 registered passenger cars around 2020, and North
  Macedonia imported a record 69,400 vehicles in 2025, so peak demand is
  growing, not stable. ([Meta.mk](https://meta.mk/en/tag/pre-owned-cars/))

If CUKS counts for the eight selected intersections become available, the
volume and the quarter-hour shares are the two values to calibrate first.

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
- Low, medium, and high distribute demand evenly across the hour. Peak uses a rush-hour profile, but its shares are informed estimates, not measured ones.
- Passenger cars are the only generated vehicle class.
- Origin and destination sampling does not model observed neighborhood travel demand.
- SUMO shortest-path routing does not represent route choice learned from real drivers.
- The 600-second validation covers only the first part of each 3,600-second scenario.
- Queue observations in this document are local smoke-test diagnostics and should not be mixed with the experiment metrics in `results/experiments.csv`.

## Future calibration

If an authoritative Skopje traffic-count dataset becomes available, future work can calibrate entry flows, turning proportions, hourly profiles, vehicle classes, and origin-destination weights.
Measured data should be documented with its source, date, coverage, uncertainty, and license.
Calibrated scenarios should be added separately so these reproducible synthetic baselines remain available.
