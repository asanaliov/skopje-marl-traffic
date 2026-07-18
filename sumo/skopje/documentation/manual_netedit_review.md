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

## Review record

- Selected candidate:
- Accepted traffic-light IDs:
- Rejected traffic-light IDs:
- Manual corrections required:
- Screenshots taken:
- Reviewer:
- Review date:
