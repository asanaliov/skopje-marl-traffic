# Candidate 3 visual review

This sheet contains computed audit facts and leaves all visual scores blank.
No candidate is selected by this document.

## Candidate definition

- Agents: A1, A3, A16, A22, A23, A24, A25, A32.
- Traffic-light IDs: `170654261`, `170654265`, `GS_cluster_12597592292_12900568847`, `GS_cluster_170743760_170745068_1839000773_1839000952`, `GS_cluster_170750136_1839001105`, `GS_cluster_1839000563_1839000611_1839000738_365292561`, `GS_cluster_2414241934_2593819789`, `cluster_287496085_3830563709_6221854337_6221854340_#2more`.
- Description: Connected candidate spanning audited northern and central controller relationships.
- Selection file: `sumo/skopje/selections/candidate_3.txt`.

## Controller facts

| Agent | Traffic-light ID | Junction node IDs | Road names | Phases | Warnings |
| --- | --- | --- | --- | ---: | --- |
| A1 | `170654261` | 170654261 | Митрополит Теодосиј Гологанов; Франклин Рузвелт | 6 | None |
| A3 | `170654265` | 170654265 | Брадфордска; Булевар 8-ми Септември; Митрополит Теодосиј Гологанов | 8 | Wizard reported actuated links without a controlling detector.; Controlled edge shorter than 5 m: -379723256#1, 379723256#0. |
| A16 | `GS_cluster_12597592292_12900568847` | cluster_12597592292_12900568847 | Бледски договор; Илинден | 6 | None |
| A22 | `GS_cluster_170743760_170745068_1839000773_1839000952` | cluster_170743760_170745068_1839000773_1839000952 | Булевар 8-ми Септември; Илинден | 8 | Controlled edge shorter than 5 m: 671704459#0. |
| A23 | `GS_cluster_170750136_1839001105` | cluster_170750136_1839001105 | Илинден; Никола Тесла | 6 | None |
| A24 | `GS_cluster_1839000563_1839000611_1839000738_365292561` | cluster_1839000563_1839000611_1839000738_365292561 | Булевар 8-ми Септември; Булевар Партизански одреди | 8 | None |
| A25 | `GS_cluster_2414241934_2593819789` | cluster_2414241934_2593819789 | Булевар Партизански одреди; Франклин Рузвелт | 4 | None |
| A32 | `cluster_287496085_3830563709_6221854337_6221854340_#2more` | cluster_287496085_3830563709_6221854337_6221854340_#2more | Булевар Партизански одреди; Костурски Херои; Мајаковски | 6 | None |

## Candidate neighbor adjacency

- A1 -> A3 (716.59 m), A24 (1119.41 m), A25 (522.07 m).
- A3 -> A1 (716.49 m), A24 (500.62 m), A25 (1111.07 m).
- A16 -> A22 (242.81 m), A24 (741.79 m).
- A22 -> A16 (225.11 m), A23 (397.94 m), A24 (504.31 m).
- A23 -> A22 (413.41 m).
- A24 -> A1 (1185.12 m), A3 (511.62 m), A22 (463.06 m), A23 (860.27 m), A25 (662.48 m).
- A25 -> A1 (522.46 m), A22 (1074.63 m), A23 (1471.84 m), A24 (616.20 m).
- A32 -> A22 (1427.99 m), A24 (1095.36 m), A25 (301.05 m).

## Directed neighbor distances

| Source | Target | Network distance | Direct corridor | Bidirectional |
| --- | --- | ---: | --- | --- |
| A1 | A3 | 716.59 m | no | yes |
| A1 | A24 | 1119.41 m | no | yes |
| A1 | A25 | 522.07 m | yes | yes |
| A3 | A1 | 716.49 m | no | yes |
| A3 | A24 | 500.62 m | no | yes |
| A3 | A25 | 1111.07 m | no | no |
| A16 | A22 | 242.81 m | yes | yes |
| A16 | A24 | 741.79 m | no | no |
| A22 | A16 | 225.11 m | yes | yes |
| A22 | A23 | 397.94 m | yes | yes |
| A22 | A24 | 504.31 m | yes | yes |
| A23 | A22 | 413.41 m | yes | yes |
| A24 | A1 | 1185.12 m | no | yes |
| A24 | A3 | 511.62 m | yes | yes |
| A24 | A22 | 463.06 m | yes | yes |
| A24 | A23 | 860.27 m | no | no |
| A24 | A25 | 662.48 m | yes | yes |
| A25 | A1 | 522.46 m | yes | yes |
| A25 | A22 | 1074.63 m | no | no |
| A25 | A23 | 1471.84 m | no | no |
| A25 | A24 | 616.20 m | yes | yes |
| A32 | A22 | 1427.99 m | no | no |
| A32 | A24 | 1095.36 m | no | no |
| A32 | A25 | 301.05 m | yes | no |

## Launch commands

Generate the candidate agent-label POIs:

```powershell
python scripts/generate_agent_labels.py
```

Open the complete network with the candidate selection in Netedit:

```powershell
python scripts/open_candidate_in_netedit.py --candidate 3
```

After Netedit opens, press F9, open the POI visualization settings, enable Show ID, enable constant text size, and increase the text size if labels such as A9 and A18 are too small.

Observe the original demand and signal programs in SUMO-GUI:

```powershell
python scripts/run_candidate_review.py --candidate 3 --seconds 600 --gui
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
