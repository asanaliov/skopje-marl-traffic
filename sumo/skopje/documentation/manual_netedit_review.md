# Manual netedit review checklist

Use this checklist before choosing or modifying the first Skopje traffic-light subset.
Do not mark an item complete until it has been checked visually in netedit or during an appropriate SUMO run.

## Map and road network

- [ ] Confirm that the selected map area matches the intended Skopje study area.
- [ ] Confirm that the intended major roads are present.
- [ ] Check lane counts on each candidate corridor and intersection approach.
- [ ] Check one-way directions.
- [ ] Check vehicle-class permissions where they affect candidate corridors.
- [ ] Check allowed turns for every candidate intersection.
- [ ] Check for disconnected lanes or missing connections.
- [ ] Identify extremely short road segments.
- [ ] Identify intersections that should be merged.
- [ ] Identify irrelevant residential streets that should not remain in the experiment network.

## Traffic-light programs

- [ ] Confirm every traffic-light location against the visible intersection geometry.
- [ ] Check that every intended approach is controlled.
- [ ] Check yellow transitions.
- [ ] Check all-red transitions where they are needed.
- [ ] Check phase states for conflicting movements.
- [ ] Check inferred actuated programs and detector warnings.
- [ ] Check multi-node or joined traffic-light controllers.

## Simulation behavior

- [ ] Observe vehicle queues on every candidate approach.
- [ ] Check for deadlocks or vehicles that cannot complete an allowed movement.
- [ ] Check for unrealistic teleporting or repeated route errors.
- [ ] Check that short edges can hold expected queues without blocking unrelated intersections.

## Candidate comparison

Review all three candidates before selecting the experimental corridor.
Review Candidate 1 first because it avoids the known A3 detector and short-edge warning case and the A33 multi-node controller warning case.
This ordering is only a practical review sequence and does not select Candidate 1.
Candidate 1 still contains the documented A9, A19, and A26 warnings, which require visual inspection.

Candidate definitions:

- Candidate 1: A9, A18, A19, A20, A24, A25, A26, A29.
- Candidate 2: A1, A3, A19, A24, A25, A29, A30, A32.
- Candidate 3: A1, A3, A16, A22, A23, A24, A25, A32.

Complete these checks separately for every candidate:

- [ ] The candidate forms one understandable geographic corridor.
- [ ] The selected roads appear to be important roads.
- [ ] The intersections are not excessively far apart.
- [ ] Each agent has meaningful neighboring agents.
- [ ] Traffic can move in both useful directions through the candidate.
- [ ] Lane counts look reasonable in the visible road geometry.
- [ ] Turns are correctly connected.
- [ ] Traffic-light phases do not show conflicting green movements.
- [ ] Yellow transitions exist where required.
- [ ] Short edges do not cause vehicles to block intersections.
- [ ] Queues do not permanently deadlock during the review run.
- [ ] The candidate is easy to explain in the project presentation.

Record only manually observed scores in the individual candidate review sheets under `sumo/skopje/documentation/candidate_reviews/`.

| Candidate | Netedit reviewed | SUMO-GUI reviewed | Main concerns | Decision notes |
| --- | --- | --- | --- | --- |
| Candidate 1 | | | | |
| Candidate 2 | | | | |
| Candidate 3 | | | | |

## Review record

- Selected candidate:
- Accepted traffic-light IDs:
- Rejected traffic-light IDs:
- Manual corrections required:
- Screenshots taken:
- Reviewer:
- Review date:
