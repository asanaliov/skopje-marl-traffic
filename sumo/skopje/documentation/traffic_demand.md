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
| Peak | 3600 s | 3300 | 88% | 2 |

All canonical scenarios use passenger vehicles, a minimum planned route length of 300 m, and seed 42.
The requested values proved usable in real duarouter and SUMO validation, so no vehicle count or share was adjusted.

The exact planned splits are:

- Low: 630 corridor trips and 270 background trips.
- Medium: 1,440 corridor trips and 360 background trips.
- High: 2,550 corridor trips and 450 background trips.
- Peak: 2,904 corridor trips and 396 background trips.

Low, medium, and high spread departures evenly across the hour.
Peak uses a rush-hour departure profile instead; see the next section.

## Peak scenario: weekday rush hour

The peak scenario represents a weekday morning or afternoon rush hour on the
corridor (Partizanski Odredi, Sv. Kliment Ohridski, 8-mi Septemvri, Vasil
Glavinov). It is still synthetic: it is shaped by published facts about Skopje
peak traffic, not calibrated to measured counts on these intersections.

What it changes compared with high:

- **Volume:** 3,300 vehicles in the hour, 1.1 times high.
- **Corridor focus:** 88% of trips cross at least two selected agents, because
  rush-hour commuting concentrates on the central boulevards.
- **Time profile:** departures are not uniform. The hour is split into four
  quarter-hours that receive 22%, 27%, 30%, and 21% of departures. The busiest
  quarter therefore runs at the equivalent of 3,960 vehicles per hour, 1.32
  times the uniform high rate. The peak hour factor is 1 / (4 × 0.30) ≈ 0.83,
  a sharper peak than the HCM default of 0.92 for urban streets, which suits a
  corridor that is congested every working day.

### Choosing the volume

The volume was chosen by testing the two baselines over the full hour plus the
600-second cooldown, not by matching real counts:

| Vehicles | Static fixed-time (seed 42) | Imported actuated (seed 42) |
| ---: | --- | --- |
| 4,200 | 321 teleports, 1,735 vehicles left | 421 teleports, 1,710 vehicles left |
| 3,600 | 130 teleports, 952 vehicles left | 131 teleports, 441 vehicles left |
| 3,300 | 58 teleports, 203 vehicles left | 45 teleports, 142 vehicles left |

At 4,200 every controller gridlocks, so the scenario stops measuring control
quality. At 3,300 the network is oversaturated during the busiest quarter but
recovers, and the two baselines separate clearly:

| Controller | Seed | Avg. waiting (s) | Avg. queue | Max queue | Throughput | Teleports | Left |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Static fixed-time | 42 | 16.72 | 44.48 | 112 | 3,097 | 58 | 203 |
| Static fixed-time | 43 | 17.01 | 44.86 | 104 | 3,118 | 42 | 182 |
| Static fixed-time | 44 | 17.64 | 44.49 | 110 | 3,082 | 55 | 218 |
| Imported actuated | 42 | 11.50 | 17.37 | 74 | 3,158 | 45 | 142 |
| Imported actuated | 43 | 10.79 | 14.89 | 62 | 3,256 | 38 | 44 |
| Imported actuated | 44 | 10.49 | 16.03 | 57 | 3,284 | 31 | 16 |

Unlike low, medium, and high, peak is not teleport-free: about 1–2% of vehicles
are teleported even under actuated control. SUMO teleports a vehicle that has
been blocked for 300 s, which removes it from the queue and slightly flatters
waiting time and queue length. Teleport count and vehicles left must therefore
be reported next to every peak result.

The profile is stored as `departure_profile` on the scenario and recorded in
the generated metadata. Scenarios without a profile keep the original even
schedule, and their generated files are byte-identical to before.

### Evidence used

- Measured peak flows at central Skopje intersections are far above what this
  simulated network can carry. Loop-detector counts from the city's Traffic
  Management Control Centre for 2017, on seven signalised intersections around
  Kuzman Josifovski Pitu boulevard (the east entry to the centre, beside the
  railway and bus station), give 1,477 to 5,110 vehicles per hour in the
  07:20–08:20 morning peak, 3,175 on average. The peak scenario puts about 960
  vehicles per hour through each selected agent on average and about 2,200
  through the busiest (A26). That corridor is not in this network, so the
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
