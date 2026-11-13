# Real-signals network (issue #65)

`skopje_real_signals.net.xml.gz` is the Skopje network with the Candidate 1
signal programs recoded to real Skopje behaviour. The original
`skopje_initial.net.xml.gz` is unchanged, so every earlier result, checkpoint
and audit stays valid.

## Selecting a network

Set `SKOPJE_NETWORK` (default `original`). Everything that depends on the
signal programs follows it:

| | `original` | `real_signals` |
| --- | --- | --- |
| Net file | `network/skopje_initial.net.xml.gz` | `network/skopje_real_signals.net.xml.gz` |
| Scenario configs | `config/scenarios/` | `config/scenarios_real_signals/` |
| Audit (phase counts) | `traffic_light_audit.csv` | `traffic_light_audit_real_signals.csv` |
| Results | `results/experiments.csv` | `results/real_signals/experiments.csv` |
| Checkpoints | `checkpoints/` | `checkpoints/real_signals/` |

PowerShell: `$env:SKOPJE_NETWORK = "real_signals"`; bash: `export SKOPJE_NETWORK=real_signals`.
Then run the usual commands from `scripts.md` unchanged:

    python scripts/experiments/run_static_fixed_time_experiment.py --scenario medium --seed 42
    python scripts/experiments/run_imported_actuated_experiment.py --scenario medium --seed 42
    python scripts/experiments/run_deep_marl.py train --scenario medium --seed 42
    python scripts/experiments/run_attention_ppo.py train --scenario medium --seed 42

Why separate: an agent's observation is lane features plus a one-hot of its
current phase, so its length is `lanes * features + 1 + phase_count`. A model
trained on one network cannot be loaded on the other, and baseline rows would
not be comparable. After adding demand scenarios (for example `peak`), run
`python scripts/setup/make_real_signals_configs.py` to create their configs.

## Kuzman junction (A26)

OSM split the Kuzman junction into the light plus five give-way junctions
0-9 m away (one right-before-left). A stub holds one car, so a single stopped
car blocked the junction box and the right-before-left junction could deadlock;
every high-demand gridlock under rl control started there. The build joins them
into one junction (`JOINS`), keeping A26's light id so the agent numbering does
not change. Routes over the removed stubs are repaired by
`make_real_signals_configs.py`. Actuated, seeds 42-44: medium 7.46 s, high
12.36 s mean trip waiting.

## Junction blockers

At an unsignalized give-way junction with a steady stream on the main road
(Leninova into Mitropolit Teodosij Gologanov, just past A26), SUMO's driver
waits for a gap forever and blocks the junction until it teleports; real
drivers squeeze in or avoid the street. Every real_signals config sets
`ignore-junction-blocker` to 30 s so others pass such a car after 30 s. It
applies to every controller: actuated high moved by under 0.1 s, while an rl
policy that ran long greens went from 311-892 vehicles left to 114-146.

## Recoded intersections

One approach per phase: all lanes of that approach `G`, everything else `r`,
no permissive `g`; 20 s green and 3 s yellow (placeholder timings, to be
replaced with real ones). Under actuated control every agent green runs
7–60 s, the same minimum and maximum the rl agents get, so both controllers
work within identical limits (was 5–50 s before 2026-11-12). 7 s is a common
practice value, not a measured Skopje one; pedestrian clearance is not
modelled.

| Agent | Phases before | Phases now | Notes |
| --- | ---: | ---: | --- |
| A9 | 4 | 6 | 3 approaches |
| A18 | 4 | 6 | 3 approaches |
| A19 | 9 | 8 | 4 approaches |
| A20 | 8 | 8 | 4 approaches (was 8 mixed phases) |
| A24 | 8 | 8 | 4 approaches |
| A25 | 4 | 8 | 4 approaches |
| A26 | 9 | 8 | 4 approaches |
| A29 | 4 | 3 | pedestrian crossing: side-road right turn yields (`g`), boulevard right turn `G`, U-turn `r`; only the carriageway toward A19 is modelled |

The real_signals corridor has 8 agents: A9, A18, A19, A20, **A21**, A24, A25,
A26. A29 keeps a program but is **not an agent**: it is a pedestrian light and
no pedestrians are simulated, so an RL agent there would only learn to skip
the crossing. A21 (Sv. Kliment Ohridski x Ilinden) replaces it: a full
signalised junction about 230 m north of A19 that feeds it directly. The
original network keeps its 8 agents (with A29) and all earlier results.

Phase strings: `phases_simple_real_signals.txt`. Per-light verdicts are in the
`notes` column of the real-signals audit.

## Road corrections (checked on site, 2026-11-11)

The network is rebuilt from the #72 recode (`real_signals_patches/base.net.xml.gz`)
by one script; the result is only written if all its checks pass:

    python scripts/setup/build_real_signals_network.py
    python scripts/setup/make_real_signals_configs.py

| File | What it changes |
| --- | --- |
| `lanes.edg.xml` | lane counts, the Dame Gruev lane drops, two slip roads removed |
| `approach_turns.con.xml` | lane-by-lane turns checked on site (A24 from the south, three A21 approaches, Dame Gruev) |
| `pedestrian_turns.con.xml` | every turn at A29, Leninova (A30) and Silbo (A32) taken off the signal |

The build re-guesses the connections of every edge whose lanes change and of
the edges feeding it (an edge patch alone keeps the old lane connections and
leaves dead lanes). It then regenerates the programs of the lights whose links
changed: agents get the #72 rule (one approach per phase, all its links `G`,
20 s green / 3 s yellow placeholder, 7–60 s actuated bounds; the other #72
agents keep their phases and get the same bounds), pedestrian lights stop only the boulevard
through lanes (`GGG` 5–50 s, `yyy` 3 s, `rrr` 5–15 s). It fails if the rule does
not reproduce the existing #72 programs, if any other light changes, if a new
dead lane appears, or if a program does not cover its links.

Most wrong lanes were edges named `*-AddedOnRampEdge` / `*-AddedOffRampEdge`:
netconvert's `--ramps.guess` treated the boulevards as motorways and added a
lane for about 94 m. The rest came from on-site checks, with OpenStreetMap
lane tags (`lanes`, `turn:lanes`; SUMO edge ids are OSM way ids) as a second
source where nobody had been on site. Where the two disagreed, the site check
won (A26 → A20, the A19, A24 and A25 approaches, Vasil Glavinov).

Junction changes:

- **A19 from A18**: 4 lanes to the stop line, right lane straight + right. The
  right-turn slip road before the light does not exist and is removed.
- **A24 from the south (8-mi Septemvri)**: 2 lanes, widening to 4 for the last
  ~35 m (right / straight / straight / left). The slip road is removed.
- **A25 from A19 (Partizanski)**: 4 lanes to the stop line (straight + right /
  straight / straight + left / left). The right-turn slip road before the light
  (`189939446`, `1109113537`) does not exist and is removed.
- **A21**: approaches set as checked on site (Kliment Ohridski northbound
  straight / straight + left / left with a right slip road before the light;
  Ilinden westbound straight / straight / left at the light, its right lane
  being a separate right-only road onto Kliment Ohridski northbound (checked on site); Kliment Ohridski
  southbound straight + right / straight / straight + left; Ilinden eastbound 4
  lanes). One approach per phase; the Ilinden-eastbound right-turn arrow also
  runs in the Ilinden-westbound phase, the one phase where SUMO's conflict
  matrix shows it crosses nothing.
- **Dame Gruev** south of A9: 4 lanes, 3 from ~50 m, 2 from ~120 m.

Removing the slip roads and splitting Dame Gruev breaks 3–5% of the routes in
the shared demand files. `make_real_signals_configs.py` repairs them for this
network only (removed edges, and edges only reachable through them, dropped; gaps
filled with the shortest connecting path; departures and origins unchanged) into
`demand/scenarios_real_signals/`, and only the real_signals configs point there.

Effect on `high` (seeds 42–44, imported actuated): mean trip waiting 84 s → 84 s,
teleports 1.3 → 2.0, vehicles left at the end 1.3 → 0.7, so the corrected
layout carries `high` about as well as the #72 network. Demand limits found on
the original network still need re-checking here.

Not modelled: the peak-hour bus lane on Partizanski (cars use it in practice);
Bel Kamen, which OSM now shows as one-way.
