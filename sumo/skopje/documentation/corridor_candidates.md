# Skopje traffic-light corridor candidates

This report audits all imported traffic-light controllers without modifying the SUMO network.
No candidate is selected automatically.

## Computed facts

### Neighbor-detection method

- The audit follows directed, passenger-compatible SUMO edge connections from each controller's outgoing edges.
- A search branch stops when it first reaches a different traffic-light controller, so a recorded path does not pass through another controller.
- Searches are limited to 1500 m of network path distance to keep the graph local and avoid long residential detours.
- Network distance is the sum of SUMO edge lengths, not straight-line distance.
- A relationship is marked as a direct corridor only when every edge on the path has the same non-empty network road name.
- The x and y audit columns are centroids of controlled junction nodes in SUMO network coordinates.

### Graph summary

- Audited controllers: 33.
- Directed neighbor relationships: 191.
- Bidirectional neighbor pairs: 72.
- Named direct-corridor pairs: 40.
- Connected components: 1.
- Isolated controllers: 0.

### Phase-program audit

- Phase counts range from 4 to 9.
- Structurally broken phase programs detected: 0.
- Overly complex programs above 10 phases: 0.
- Phase states and durations for every controller are stored in the audit CSV.

### Connected groups

- Group 1 has 33 controllers: A1 (`170654261`), A2 (`170654263`), A3 (`170654265`), A4 (`170737064`), A5 (`1851607207`), A6 (`1854222176`), A7 (`3741536617`), A8 (`497329028`), A9 (`GS_12432953582`), A10 (`GS_12540644073`), A11 (`GS_12997198858`), A12 (`GS_170662452`), A13 (`GS_1858669160`), A14 (`GS_287495829`), A15 (`GS_cluster_12136663392_12136663393`), A16 (`GS_cluster_12597592292_12900568847`), A17 (`GS_cluster_12960190508_12960190509`), A18 (`GS_cluster_170638629_170642149_170723177_418949594`), A19 (`GS_cluster_170640546_170645388_170684654_170684655`), A20 (`GS_cluster_170664726_3563678918`), A21 (`GS_cluster_170712177_1848310997`), A22 (`GS_cluster_170743760_170745068_1839000773_1839000952`), A23 (`GS_cluster_170750136_1839001105`), A24 (`GS_cluster_1839000563_1839000611_1839000738_365292561`), A25 (`GS_cluster_2414241934_2593819789`), A26 (`GS_cluster_511207145_8301921419`), A27 (`cluster_11246615210_11246615211_11246615212_12136646778_#7more`), A28 (`cluster_11414205726_170662453_1880528858_2385220521_#5more`), A29 (`cluster_12549999855_4127480432_4537363482_4537363483_#2more`), A30 (`cluster_12549999856_2458486828_3830563710_6206171929_#3more`), A31 (`cluster_1848691745_2054895221_4138700168_5324765220_#3more`), A32 (`cluster_287496085_3830563709_6221854337_6221854340_#2more`), A33 (`joinedS_1839677183_440376701`).

### Isolated controllers

- No isolated controllers were detected by the chosen method.

### Controller overview

| Agent | Traffic-light ID | Nodes | Phases | Max lanes | Max speed | Graph neighbors | Roads | Warnings |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| A1 | `170654261` | 1 | 6 | 3 | 13.89 m/s | 11 | Митрополит Теодосиј Гологанов; Франклин Рузвелт | None |
| A2 | `170654263` | 1 | 4 | 2 | 13.89 m/s | 6 | Њуделхиска; Митрополит Теодосиј Гологанов | None |
| A3 | `170654265` | 1 | 8 | 4 | 13.89 m/s | 7 | Брадфордска; Булевар 8-ми Септември; Митрополит Теодосиј Гологанов | Wizard reported actuated links without a controlling detector.; Controlled edge shorter than 5 m: -379723256#1, 379723256#0. |
| A4 | `170737064` | 1 | 6 | 2 | 13.89 m/s | 4 | Брадфордска; Козле; Ловќенска | None |
| A5 | `1851607207` | 1 | 4 | 2 | 13.89 m/s | 6 | 9-ти Мај; Митрополит Теодосиј Гологанов | None |
| A6 | `1854222176` | 1 | 6 | 2 | 22.22 m/s | 1 | Булевар Никола Карев; Македонско-косовска бригада; Славеј Планина | Controlled edge shorter than 5 m: -316893005, -669859843, 316893005, 669859843. |
| A7 | `3741536617` | 1 | 4 | 2 | 13.89 m/s | 8 | Илинден; Наум Наумовски Борче | Controlled edge shorter than 5 m: 175080710#0. |
| A8 | `497329028` | 1 | 4 | 2 | 13.89 m/s | 6 | Анкарска; Митрополит Теодосиј Гологанов | None |
| A9 | `GS_12432953582` | 1 | 4 | 3 | 13.89 m/s | 6 | Васил Главинов; Даме Груев; Димитрие Чуповски | Controlled edge shorter than 5 m: -42874773#1, 42874773#0. |
| A10 | `GS_12540644073` | 1 | 4 | 3 | 13.89 m/s | 5 | Коста Солев (Кочо Рацин); Кочо Рацин; Св. Кирил и Методиј | None |
| A11 | `GS_12997198858` | 1 | 4 | 2 | 13.89 m/s | 9 | Народен Фронт; Св. Кирил и Методиј | None |
| A12 | `GS_170662452` | 1 | 6 | 2 | 13.89 m/s | 12 | Орце Николов; Франклин Рузвелт | None |
| A13 | `GS_1858669160` | 1 | 4 | 2 | 13.89 m/s | 8 | Илинден; Ленинова | None |
| A14 | `GS_287495829` | 1 | 6 | 2 | 22.22 m/s | 6 | Никола Тесла; Орце Николов | None |
| A15 | `GS_cluster_12136663392_12136663393` | 1 | 8 | 3 | 13.89 m/s | 4 | 11-ти Октомври; Коста Солев (Кочо Рацин); Кочо Рацин | Wizard reported actuated links without a controlling detector. |
| A16 | `GS_cluster_12597592292_12900568847` | 1 | 6 | 3 | 22.22 m/s | 2 | Бледски договор; Илинден | None |
| A17 | `GS_cluster_12960190508_12960190509` | 1 | 8 | 3 | 22.22 m/s | 3 | Антон Попов; Бихаќка; Железничка; Кочо Рацин | Wizard reported actuated links without a controlling detector. |
| A18 | `GS_cluster_170638629_170642149_170723177_418949594` | 1 | 4 | 3 | 13.89 m/s | 8 | Булевар Блаже Конески; Булевар Партизански одреди; Васил Главинов | None |
| A19 | `GS_cluster_170640546_170645388_170684654_170684655` | 1 | 9 | 4 | 13.89 m/s | 12 | Булевар Партизански одреди; Булевар Свети Климент Охридски | Wizard reported actuated links without a controlling detector. |
| A20 | `GS_cluster_170664726_3563678918` | 1 | 8 | 3 | 13.89 m/s | 10 | Булевар Водњанска; Булевар Свети Климент Охридски; Св. Кирил и Методиј | None |
| A21 | `GS_cluster_170712177_1848310997` | 1 | 8 | 3 | 13.89 m/s | 8 | Булевар Свети Климент Охридски; Илинден | Wizard reported actuated links without a controlling detector. |
| A22 | `GS_cluster_170743760_170745068_1839000773_1839000952` | 1 | 8 | 3 | 13.89 m/s | 7 | Булевар 8-ми Септември; Илинден | Controlled edge shorter than 5 m: 671704459#0. |
| A23 | `GS_cluster_170750136_1839001105` | 1 | 6 | 3 | 22.22 m/s | 6 | Илинден; Никола Тесла | None |
| A24 | `GS_cluster_1839000563_1839000611_1839000738_365292561` | 1 | 8 | 4 | 13.89 m/s | 11 | Булевар 8-ми Септември; Булевар Партизански одреди | None |
| A25 | `GS_cluster_2414241934_2593819789` | 1 | 4 | 3 | 13.89 m/s | 15 | Булевар Партизански одреди; Франклин Рузвелт | None |
| A26 | `GS_cluster_511207145_8301921419` | 1 | 9 | 3 | 13.89 m/s | 12 | Булевар Свети Климент Охридски; Димитрие Чуповски; Митрополит Теодосиј Гологанов | Controlled edge shorter than 5 m: 1303162784, 1303162785. |
| A27 | `cluster_11246615210_11246615211_11246615212_12136646778_#7more` | 1 | 8 | 3 | 13.89 m/s | 6 | 11-ти Октомври; Даме Груев; Стив Наумов | None |
| A28 | `cluster_11414205726_170662453_1880528858_2385220521_#5more` | 1 | 6 | 3 | 13.89 m/s | 3 | Илинден; Франклин Рузвелт | None |
| A29 | `cluster_12549999855_4127480432_4537363482_4537363483_#2more` | 1 | 4 | 3 | 13.89 m/s | 8 | Булевар Партизански одреди; Ленинова | None |
| A30 | `cluster_12549999856_2458486828_3830563710_6206171929_#3more` | 1 | 4 | 3 | 13.89 m/s | 6 | Булевар Партизански одреди; Ленинова | None |
| A31 | `cluster_1848691745_2054895221_4138700168_5324765220_#3more` | 1 | 8 | 3 | 13.89 m/s | 4 | Булевар Водњанска; Васил Ѓоргов; Железничка | Controlled edge shorter than 5 m: 16661485#2. |
| A32 | `cluster_287496085_3830563709_6221854337_6221854340_#2more` | 1 | 6 | 3 | 13.89 m/s | 10 | Булевар Партизански одреди; Костурски Херои; Мајаковски | None |
| A33 | `joinedS_1839677183_440376701` | 2 | 4 | 2 | 13.89 m/s | 8 | Булевар Блаже Конески; Илинден | Controller spans 2 controlled junction nodes. |

### Program and network warnings

- A3 (`170654265`): Wizard reported actuated links without a controlling detector.; Controlled edge shorter than 5 m: -379723256#1, 379723256#0.
- A6 (`1854222176`): Controlled edge shorter than 5 m: -316893005, -669859843, 316893005, 669859843.
- A7 (`3741536617`): Controlled edge shorter than 5 m: 175080710#0.
- A9 (`GS_12432953582`): Controlled edge shorter than 5 m: -42874773#1, 42874773#0.
- A15 (`GS_cluster_12136663392_12136663393`): Wizard reported actuated links without a controlling detector.
- A17 (`GS_cluster_12960190508_12960190509`): Wizard reported actuated links without a controlling detector.
- A19 (`GS_cluster_170640546_170645388_170684654_170684655`): Wizard reported actuated links without a controlling detector.
- A21 (`GS_cluster_170712177_1848310997`): Wizard reported actuated links without a controlling detector.
- A22 (`GS_cluster_170743760_170745068_1839000773_1839000952`): Controlled edge shorter than 5 m: 671704459#0.
- A26 (`GS_cluster_511207145_8301921419`): Controlled edge shorter than 5 m: 1303162784, 1303162785.
- A31 (`cluster_1848691745_2054895221_4138700168_5324765220_#3more`): Controlled edge shorter than 5 m: 16661485#2.
- A33 (`joinedS_1839677183_440376701`): Controller spans 2 controlled junction nodes.

## Recommendations for manual selection

These candidates are connected graph subsets generated for manual comparison, not final experiment selections.
The ranking prefers controlled edges with more lanes, higher speed limits, named direct-corridor links, and stronger graph connectivity.

### Candidate 1

- Agents: A9, A18, A19, A20, A24, A25, A26, A29.
- Traffic-light IDs: `GS_12432953582`, `GS_cluster_170638629_170642149_170723177_418949594`, `GS_cluster_170640546_170645388_170684654_170684655`, `GS_cluster_170664726_3563678918`, `GS_cluster_1839000563_1839000611_1839000738_365292561`, `GS_cluster_2414241934_2593819789`, `GS_cluster_511207145_8301921419`, `cluster_12549999855_4127480432_4537363482_4537363483_#2more`.
- Named direct-corridor links inside the subset: 8.
- Mean detected neighbor distance inside the subset: 588.43 m.
- Largest controlled-edge lane count: 4.
- Highest controlled-edge speed limit: 13.89 m/s.
- Repeated direct-corridor road names from the network: Булевар Партизански одреди, Булевар Свети Климент Охридски, Васил Главинов, Димитрие Чуповски.
- Controllers requiring warning review: A9, A19, A26.
- Why it could work for MARL: the controllers form one connected neighbor subgraph, allowing local interactions to be studied without using all 33 controllers.
- Manual review needed: verify signal phases, allowed turns, lane continuity, queue interactions, and whether the named corridors match the intended study area in netedit.

### Candidate 2

- Agents: A1, A3, A19, A24, A25, A29, A30, A32.
- Traffic-light IDs: `170654261`, `170654265`, `GS_cluster_170640546_170645388_170684654_170684655`, `GS_cluster_1839000563_1839000611_1839000738_365292561`, `GS_cluster_2414241934_2593819789`, `cluster_12549999855_4127480432_4537363482_4537363483_#2more`, `cluster_12549999856_2458486828_3830563710_6206171929_#3more`, `cluster_287496085_3830563709_6221854337_6221854340_#2more`.
- Named direct-corridor links inside the subset: 8.
- Mean detected neighbor distance inside the subset: 687.70 m.
- Largest controlled-edge lane count: 4.
- Highest controlled-edge speed limit: 13.89 m/s.
- Repeated direct-corridor road names from the network: Булевар Партизански одреди, Франклин Рузвелт, Булевар 8-ми Септември.
- Controllers requiring warning review: A3, A19.
- Why it could work for MARL: the controllers form one connected neighbor subgraph, allowing local interactions to be studied without using all 33 controllers.
- Manual review needed: verify signal phases, allowed turns, lane continuity, queue interactions, and whether the named corridors match the intended study area in netedit.

### Candidate 3

- Agents: A1, A3, A16, A22, A23, A24, A25, A32.
- Traffic-light IDs: `170654261`, `170654265`, `GS_cluster_12597592292_12900568847`, `GS_cluster_170743760_170745068_1839000773_1839000952`, `GS_cluster_170750136_1839001105`, `GS_cluster_1839000563_1839000611_1839000738_365292561`, `GS_cluster_2414241934_2593819789`, `cluster_287496085_3830563709_6221854337_6221854340_#2more`.
- Named direct-corridor links inside the subset: 7.
- Mean detected neighbor distance inside the subset: 790.31 m.
- Largest controlled-edge lane count: 4.
- Highest controlled-edge speed limit: 22.22 m/s.
- Repeated direct-corridor road names from the network: Илинден, Булевар 8-ми Септември, Булевар Партизански одреди, Франклин Рузвелт.
- Controllers requiring warning review: A3, A22.
- Why it could work for MARL: the controllers form one connected neighbor subgraph, allowing local interactions to be studied without using all 33 controllers.
- Manual review needed: verify signal phases, allowed turns, lane continuity, queue interactions, and whether the named corridors match the intended study area in netedit.

## Decision status

No final 6-to-10-controller subset has been selected.
Use the manual netedit checklist before accepting or rejecting a candidate.
