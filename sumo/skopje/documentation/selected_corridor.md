# Selected Experimental Corridor for Skopje Traffic Control

## Official selection

Candidate 1 is the official selected experimental corridor.
The selection date is not separately recorded in the existing review documentation.
The reproducible runtime review was completed on 2026-07-18.

The full Skopje network remains active and unchanged during corridor experiments.
Only the eight traffic lights listed below are selected as future reinforcement-learning agents.
Every other traffic light retains its original SUMO traffic-light program.

## Selected agents and controllers

| Agent | SUMO traffic-light controller ID | Controlled junction ID | Road names |
| --- | --- | --- | --- |
| A9 | `GS_12432953582` | `12432953582` | Васил Главинов; Даме Груев; Димитрие Чуповски |
| A18 | `GS_cluster_170638629_170642149_170723177_418949594` | `cluster_170638629_170642149_170723177_418949594` | Булевар Блаже Конески; Булевар Партизански одреди; Васил Главинов |
| A19 | `GS_cluster_170640546_170645388_170684654_170684655` | `cluster_170640546_170645388_170684654_170684655` | Булевар Партизански одреди; Булевар Свети Климент Охридски |
| A20 | `GS_cluster_170664726_3563678918` | `cluster_170664726_3563678918` | Булевар Водњанска; Булевар Свети Климент Охридски; Св. Кирил и Методиј |
| A24 | `GS_cluster_1839000563_1839000611_1839000738_365292561` | `cluster_1839000563_1839000611_1839000738_365292561` | Булевар 8-ми Септември; Булевар Партизански одреди |
| A25 | `GS_cluster_2414241934_2593819789` | `cluster_2414241934_2593819789` | Булевар Партизански одреди; Франклин Рузвелт |
| A26 | `GS_cluster_511207145_8301921419` | `cluster_511207145_8301921419` | Булевар Свети Климент Охридски; Димитрие Чуповски; Митрополит Теодосиј Гологанов |
| A29 | `cluster_12549999855_4127480432_4537363482_4537363483_#2more` | `cluster_12549999855_4127480432_4537363482_4537363483_#2more` | Булевар Партизански одреди; Ленинова |

These mappings come from `traffic_light_audit.csv` and are validated against the complete SUMO network.

## Neighbor adjacency

The adjacency list contains only directed relationships for which both endpoints belong to Candidate 1.

- A9: A18, A19, A20, A26
- A18: A9, A19, A20, A26
- A19: A9, A18, A26
- A20: A26
- A24: A25
- A25: A20, A24, A26, A29
- A26: A9, A18, A19, A20, A25, A29
- A29: A19, A20, A25, A26

The graph has 27 directed neighbor relationships and 11 bidirectional neighbor pairs.
It is connected when the directed relationships are treated as an undirected graph.

## Directed network distances

| Source | Target | Network distance |
| --- | --- | ---: |
| A9 | A18 | 173.35 m |
| A9 | A19 | 477.56 m |
| A9 | A20 | 881.55 m |
| A9 | A26 | 213.53 m |
| A18 | A9 | 185.18 m |
| A18 | A19 | 167.75 m |
| A18 | A20 | 1487.05 m |
| A18 | A26 | 399.35 m |
| A19 | A9 | 376.35 m |
| A19 | A18 | 194.82 m |
| A19 | A26 | 275.62 m |
| A20 | A26 | 188.45 m |
| A24 | A25 | 662.48 m |
| A25 | A20 | 1392.49 m |
| A25 | A24 | 616.20 m |
| A25 | A26 | 1220.00 m |
| A25 | A29 | 782.13 m |
| A26 | A9 | 211.14 m |
| A26 | A18 | 441.30 m |
| A26 | A19 | 261.27 m |
| A26 | A20 | 178.28 m |
| A26 | A25 | 1277.26 m |
| A26 | A29 | 470.49 m |
| A29 | A19 | 172.46 m |
| A29 | A20 | 643.08 m |
| A29 | A25 | 995.37 m |
| A29 | A26 | 452.41 m |

Distances are directed passenger-network path distances from `traffic_light_neighbors.csv`.
The distance from one controller to another may differ from the reverse distance because legal paths and road geometry differ by direction.

## Known warnings

| Agent | Warning |
| --- | --- |
| A9 | Controlled edge shorter than 5 m: `-42874773#1`, `42874773#0`. |
| A19 | The wizard reported actuated links without a controlling detector. |
| A26 | Controlled edge shorter than 5 m: `1303162784`, `1303162785`. |

No audit warning is currently recorded for A18, A20, A24, A25, or A29.

## Selection rationale

- Candidate 1 forms a connected central Skopje network.
- It includes several important multi-lane roads, including sections of Булевар Партизански одреди and Булевар Свети Климент Охридски.
- Its intersections are sufficiently close for meaningful coordination, with several direct relationships below 500 m.
- Multiple agents have several neighboring selected agents, which creates useful coordination choices rather than a single isolated pair.
- The eight-agent scale is manageable for the first fixed-time, independent RL, and coordinated MARL comparison.
- The 600-second review completed without a persistent deadlock.

## Runtime-review findings

The fixed-program review ran the complete scenario for 600 seconds with seed 42 and sampled the selected controllers every 60 seconds.
It completed with 295 vehicles arrived and 185 vehicles still active.
The review collected 10 samples per selected controller.
Temporary queues appeared at several controllers, but the sampled queues at A19 and A26 later decreased.
No persistent candidate queue, collision warning, teleport warning, or simulation failure appeared in the captured output.
SUMO reported that bus stop `12387262086` was too short for one bus on lane `1339140549_0`, which is a separate scenario warning rather than evidence of a selected-controller failure.
This evidence supports scenario stability only and does not establish traffic-control performance.

## Candidate 1 screenshot

![Candidate 1 labeled network](screenshots/candidate1/01_candidate1.png)

The labeled overview shows the selected junctions in the context of the complete Skopje network.

## Known limitations

- A9 and A26 have short controlled-edge warnings that require care when lane-level observations are designed.
- A19 has a wizard detector warning and still needs a focused detector and phase review.
- Demand is synthetic and does not represent measured Skopje traffic volumes.
- Phase-by-phase visual conflict checks are incomplete for A9, A19, and A26.
- Close-up lane and turn reviews are incomplete for A18, A20, A24, A25, and A29.

The earlier project-status checklist below this report's original review is superseded by the current repository state.
Demand scenarios and controller experiments have since been implemented; see the top-level README and `traffic_demand.md` for current evidence.
