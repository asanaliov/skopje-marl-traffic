# Skopje initial network summary

## Files

- Network file used: `sumo/skopje/network/skopje_initial.net.xml.gz`.
- Passenger route input used: `sumo/skopje/demand/skopje_initial.trips.xml`.
- Public-transport route file used: `sumo/skopje/demand/skopje_initial.rou.xml`.
- Polygons exist: yes.
- The current passenger traffic demand is synthetic.

## Network statistics

- Nodes: 790.
- Edges: 1591.
- Lanes: 2153.
- Traffic-light controllers: 33.
- Traffic-light-controlled junctions: 34.
- Passenger-compatible edges: 1588.

## Traffic-light IDs

- `170654261`
- `170654263`
- `170654265`
- `170737064`
- `1851607207`
- `1854222176`
- `3741536617`
- `497329028`
- `GS_12432953582`
- `GS_12540644073`
- `GS_12997198858`
- `GS_170662452`
- `GS_1858669160`
- `GS_287495829`
- `GS_cluster_12136663392_12136663393`
- `GS_cluster_12597592292_12900568847`
- `GS_cluster_12960190508_12960190509`
- `GS_cluster_170638629_170642149_170723177_418949594`
- `GS_cluster_170640546_170645388_170684654_170684655`
- `GS_cluster_170664726_3563678918`
- `GS_cluster_170712177_1848310997`
- `GS_cluster_170743760_170745068_1839000773_1839000952`
- `GS_cluster_170750136_1839001105`
- `GS_cluster_1839000563_1839000611_1839000738_365292561`
- `GS_cluster_2414241934_2593819789`
- `GS_cluster_511207145_8301921419`
- `cluster_11246615210_11246615211_11246615212_12136646778_#7more`
- `cluster_11414205726_170662453_1880528858_2385220521_#5more`
- `cluster_12549999855_4127480432_4537363482_4537363483_#2more`
- `cluster_12549999856_2458486828_3830563710_6206171929_#3more`
- `cluster_1848691745_2054895221_4138700168_5324765220_#3more`
- `cluster_287496085_3830563709_6221854337_6221854340_#2more`
- `joinedS_1839677183_440376701`

## Known limitations

- OpenStreetMap imports may need manual corrections.
- Traffic-light programs may have been inferred by SUMO during import.
- Synthetic traffic is not real traffic-count data for Skopje.
- Some small roads may need removal from the experiment network.
- Some major intersections need manual inspection in netedit.
- The wizard error log reports missing controlling detectors for some actuated links and one bus stop that is too short.

## Next cleanup tasks

- Inspect major signalized intersections and their phases in netedit.
- Identify small or irrelevant roads that can be removed safely.
- Check inferred signal programs against intersection geometry.
- Define a reduced network before demand modeling and baseline work.
