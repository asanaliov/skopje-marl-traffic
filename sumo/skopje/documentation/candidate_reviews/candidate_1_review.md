# Candidate 1 visual review

This sheet contains computed audit facts and leaves all visual scores blank.
No candidate is selected by this document.

## Candidate definition

- Agents: A9, A18, A19, A20, A24, A25, A26, A29.
- Traffic-light IDs: `GS_12432953582`, `GS_cluster_170638629_170642149_170723177_418949594`, `GS_cluster_170640546_170645388_170684654_170684655`, `GS_cluster_170664726_3563678918`, `GS_cluster_1839000563_1839000611_1839000738_365292561`, `GS_cluster_2414241934_2593819789`, `GS_cluster_511207145_8301921419`, `cluster_12549999855_4127480432_4537363482_4537363483_#2more`.
- Description: Central connected candidate with audited links on several named multi-lane corridors.
- Selection file: `sumo/skopje/selections/candidate_1.txt`.

## Controller facts

| Agent | Traffic-light ID | Junction node IDs | Road names | Phases | Warnings |
| --- | --- | --- | --- | ---: | --- |
| A9 | `GS_12432953582` | 12432953582 | Васил Главинов; Даме Груев; Димитрие Чуповски | 4 | Controlled edge shorter than 5 m: -42874773#1, 42874773#0. |
| A18 | `GS_cluster_170638629_170642149_170723177_418949594` | cluster_170638629_170642149_170723177_418949594 | Булевар Блаже Конески; Булевар Партизански одреди; Васил Главинов | 4 | None |
| A19 | `GS_cluster_170640546_170645388_170684654_170684655` | cluster_170640546_170645388_170684654_170684655 | Булевар Партизански одреди; Булевар Свети Климент Охридски | 9 | Wizard reported actuated links without a controlling detector. |
| A20 | `GS_cluster_170664726_3563678918` | cluster_170664726_3563678918 | Булевар Водњанска; Булевар Свети Климент Охридски; Св. Кирил и Методиј | 8 | None |
| A24 | `GS_cluster_1839000563_1839000611_1839000738_365292561` | cluster_1839000563_1839000611_1839000738_365292561 | Булевар 8-ми Септември; Булевар Партизански одреди | 8 | None |
| A25 | `GS_cluster_2414241934_2593819789` | cluster_2414241934_2593819789 | Булевар Партизански одреди; Франклин Рузвелт | 4 | None |
| A26 | `GS_cluster_511207145_8301921419` | cluster_511207145_8301921419 | Булевар Свети Климент Охридски; Димитрие Чуповски; Митрополит Теодосиј Гологанов | 9 | Controlled edge shorter than 5 m: 1303162784, 1303162785. |
| A29 | `cluster_12549999855_4127480432_4537363482_4537363483_#2more` | cluster_12549999855_4127480432_4537363482_4537363483_#2more | Булевар Партизански одреди; Ленинова | 4 | None |

## Candidate neighbor adjacency

- A9 -> A18 (173.35 m), A19 (477.56 m), A20 (881.55 m), A26 (213.53 m).
- A18 -> A9 (185.18 m), A19 (167.75 m), A20 (1487.05 m), A26 (399.35 m).
- A19 -> A9 (376.35 m), A18 (194.82 m), A26 (275.62 m).
- A20 -> A26 (188.45 m).
- A24 -> A25 (662.48 m).
- A25 -> A20 (1392.49 m), A24 (616.20 m), A26 (1220.00 m), A29 (782.13 m).
- A26 -> A9 (211.14 m), A18 (441.30 m), A19 (261.27 m), A20 (178.28 m), A25 (1277.26 m), A29 (470.49 m).
- A29 -> A19 (172.46 m), A20 (643.08 m), A25 (995.37 m), A26 (452.41 m).

## Directed neighbor distances

| Source | Target | Network distance | Direct corridor | Bidirectional |
| --- | --- | ---: | --- | --- |
| A9 | A18 | 173.35 m | yes | yes |
| A9 | A19 | 477.56 m | no | yes |
| A9 | A20 | 881.55 m | no | no |
| A9 | A26 | 213.53 m | yes | yes |
| A18 | A9 | 185.18 m | yes | yes |
| A18 | A19 | 167.75 m | yes | yes |
| A18 | A20 | 1487.05 m | no | no |
| A18 | A26 | 399.35 m | no | yes |
| A19 | A9 | 376.35 m | no | yes |
| A19 | A18 | 194.82 m | yes | yes |
| A19 | A26 | 275.62 m | yes | yes |
| A20 | A26 | 188.45 m | yes | yes |
| A24 | A25 | 662.48 m | yes | yes |
| A25 | A20 | 1392.49 m | no | no |
| A25 | A24 | 616.20 m | yes | yes |
| A25 | A26 | 1220.00 m | no | yes |
| A25 | A29 | 782.13 m | yes | yes |
| A26 | A9 | 211.14 m | yes | yes |
| A26 | A18 | 441.30 m | no | yes |
| A26 | A19 | 261.27 m | yes | yes |
| A26 | A20 | 178.28 m | yes | yes |
| A26 | A25 | 1277.26 m | no | yes |
| A26 | A29 | 470.49 m | no | yes |
| A29 | A19 | 172.46 m | yes | no |
| A29 | A20 | 643.08 m | no | no |
| A29 | A25 | 995.37 m | no | yes |
| A29 | A26 | 452.41 m | no | yes |

## Launch commands

Open the complete network with the candidate selection in Netedit:

```powershell
python scripts/open_candidate_in_netedit.py --candidate 1
```

Observe the original demand and signal programs in SUMO-GUI:

```powershell
python scripts/run_candidate_review.py --candidate 1 --seconds 600 --gui
```

## Manual scoring

Leave scores blank until the candidate has been reviewed visually.

| Criterion | Score 1-5 | Notes |
| --- | --- | --- |
| Main-road relevance | | |
| Geographic continuity | | |
| Intersection spacing | | |
| Traffic-light quality | | |
| Lane and turn correctness | | |
| Manageable complexity | | |
| Coordination potential | | |
| Visual clarity for presentation | | |
| Deadlock-free simulation | | |
| Overall suitability | | |
