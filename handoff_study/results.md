# Results: can the reader use the plate?

Written by `python -m handoff_study score --write` from trials.csv, verdicts.csv and setup_time.csv in
this folder. Do not edit it by hand. Bench and simulation results sit in separate tables and are never
pooled.

Scorer `fbff7c29e4dd`. Design `cbb71bf79743`. Trials assigned: 204. Done: 0.

**0 trials have been run.** All 204 rows of trials.csv are planned. Camera verdicts: 0.
Setup time entries: 0. There is nothing to score yet.

| Experiment | Arm | Where | Trials assigned |
|---|---|---|---|
| camera | hand_nominal | bench | 24 |
| camera | hand_challenge | bench | 24 |
| teaching_sim | dream1_demos_0 | simulation | 30 |
| teaching_sim | dream1_demos_5 | simulation | 30 |
| teaching_sim | dream1_demos_20 | simulation | 30 |
| teaching_sim | dream1_demos_50 | simulation | 30 |
| hardware | dream1_demos_0 | bench | 12 |
| hardware | dream1_demos_50 | bench | 12 |
| hardware | manual | bench | 12 |

## Caveats

- Every range is the exact (Clopper-Pearson) 95% range, two-sided. It treats trials as independent.
- The 2 placements of a camera pair share a layout and a day, so they are not independent.
- Original and relit pictures show the same placements: 2 looks at 1 placement, not 2 placements.
- The sizes are those of a feasibility pilot: 48 placements, 120 simulated attempts, 24 robot attempts,
  12 manual handoffs.
