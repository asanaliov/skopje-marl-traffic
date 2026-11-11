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

## Recoded intersections

One approach per phase: all lanes of that approach `G`, everything else `r`,
no permissive `g`; 20 s green and 3 s yellow (placeholder timings, to be
replaced with real ones).

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

Phase strings: `phases_simple_real_signals.txt`. Per-light verdicts are in the
`notes` column of the real-signals audit.
