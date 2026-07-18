# Candidate 2 visual review

This sheet contains computed audit facts and leaves all visual scores blank.
No candidate is selected by this document.

## Candidate definition

- Agents: A1, A3, A19, A24, A25, A29, A30, A32.
- Traffic-light IDs: `170654261`, `170654265`, `GS_cluster_170640546_170645388_170684654_170684655`, `GS_cluster_1839000563_1839000611_1839000738_365292561`, `GS_cluster_2414241934_2593819789`, `cluster_12549999855_4127480432_4537363482_4537363483_#2more`, `cluster_12549999856_2458486828_3830563710_6206171929_#3more`, `cluster_287496085_3830563709_6221854337_6221854340_#2more`.
- Description: Connected candidate centered on the audited east-west controller relationships.
- Selection file: `sumo/skopje/selections/candidate_2.txt`.

## Controller facts

| Agent | Traffic-light ID | Junction node IDs | Road names | Phases | Warnings |
| --- | --- | --- | --- | ---: | --- |
| A1 | `170654261` | 170654261 | Митрополит Теодосиј Гологанов; Франклин Рузвелт | 6 | None |
| A3 | `170654265` | 170654265 | Брадфордска; Булевар 8-ми Септември; Митрополит Теодосиј Гологанов | 8 | Wizard reported actuated links without a controlling detector.; Controlled edge shorter than 5 m: -379723256#1, 379723256#0. |
| A19 | `GS_cluster_170640546_170645388_170684654_170684655` | cluster_170640546_170645388_170684654_170684655 | Булевар Партизански одреди; Булевар Свети Климент Охридски | 9 | Wizard reported actuated links without a controlling detector. |
| A24 | `GS_cluster_1839000563_1839000611_1839000738_365292561` | cluster_1839000563_1839000611_1839000738_365292561 | Булевар 8-ми Септември; Булевар Партизански одреди | 8 | None |
| A25 | `GS_cluster_2414241934_2593819789` | cluster_2414241934_2593819789 | Булевар Партизански одреди; Франклин Рузвелт | 4 | None |
| A29 | `cluster_12549999855_4127480432_4537363482_4537363483_#2more` | cluster_12549999855_4127480432_4537363482_4537363483_#2more | Булевар Партизански одреди; Ленинова | 4 | None |
| A30 | `cluster_12549999856_2458486828_3830563710_6206171929_#3more` | cluster_12549999856_2458486828_3830563710_6206171929_#3more | Булевар Партизански одреди; Ленинова | 4 | None |
| A32 | `cluster_287496085_3830563709_6221854337_6221854340_#2more` | cluster_287496085_3830563709_6221854337_6221854340_#2more | Булевар Партизански одреди; Костурски Херои; Мајаковски | 6 | None |

## Candidate neighbor adjacency

- A1 -> A3 (716.59 m), A24 (1119.41 m), A25 (522.07 m), A29 (1302.17 m).
- A3 -> A1 (716.49 m), A24 (500.62 m), A25 (1111.07 m).
- A19 -> A30 (160.09 m).
- A24 -> A1 (1185.12 m), A3 (511.62 m), A25 (662.48 m).
- A25 -> A1 (522.46 m), A24 (616.20 m), A29 (782.13 m).
- A29 -> A1 (1167.65 m), A19 (172.46 m), A25 (995.37 m).
- A30 -> A19 (480.12 m), A32 (446.96 m).
- A32 -> A19 (916.20 m), A24 (1095.36 m), A25 (301.05 m), A30 (688.34 m).

## Directed neighbor distances

| Source | Target | Network distance | Direct corridor | Bidirectional |
| --- | --- | ---: | --- | --- |
| A1 | A3 | 716.59 m | no | yes |
| A1 | A24 | 1119.41 m | no | yes |
| A1 | A25 | 522.07 m | yes | yes |
| A1 | A29 | 1302.17 m | no | yes |
| A3 | A1 | 716.49 m | no | yes |
| A3 | A24 | 500.62 m | no | yes |
| A3 | A25 | 1111.07 m | no | no |
| A19 | A30 | 160.09 m | yes | yes |
| A24 | A1 | 1185.12 m | no | yes |
| A24 | A3 | 511.62 m | yes | yes |
| A24 | A25 | 662.48 m | yes | yes |
| A25 | A1 | 522.46 m | yes | yes |
| A25 | A24 | 616.20 m | yes | yes |
| A25 | A29 | 782.13 m | yes | yes |
| A29 | A1 | 1167.65 m | no | yes |
| A29 | A19 | 172.46 m | yes | no |
| A29 | A25 | 995.37 m | no | yes |
| A30 | A19 | 480.12 m | no | yes |
| A30 | A32 | 446.96 m | yes | yes |
| A32 | A19 | 916.20 m | no | no |
| A32 | A24 | 1095.36 m | no | no |
| A32 | A25 | 301.05 m | yes | no |
| A32 | A30 | 688.34 m | no | yes |

## Launch commands

Open the complete network with the candidate selection in Netedit:

```powershell
python scripts/open_candidate_in_netedit.py --candidate 2
```

Observe the original demand and signal programs in SUMO-GUI:

```powershell
python scripts/run_candidate_review.py --candidate 2 --seconds 600 --gui
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
