# Can the reader use the plate?

**Status: a plan. Nothing here has been run. No reader, plate or real robot has been used, and the trial sheet
holds 0 results.**

This is the plan for the first check of this repo's plate chore on a real bench. A robot, or a person, puts a dry
microplate in the carrier of a plate reader, and the reader itself says whether the handoff worked. The plan tests
the camera and the robot separately, and counts the hands-on time that each usable read costs.

## The question

Can a plate that a robot puts down be used by the instrument it was meant for? The study measures 3 things:

1. **The reader.** Does the reader give a valid result on the first try?
2. **The camera.** Can a camera tell, before the reader runs, which placements will fail?
3. **The time.** How many hands-on minutes does 1 usable read cost, resets and rescues included?

## Why ask the reader

- **What the simulator's rule checks.** `plate_to_tray` passes when the centre of the plate's underside is within
  5 mm of the pocket centre on each axis and between 2 mm below and 6 mm above the tray floor, the plate is tilted
  5 degrees or less, its heading is under 8 degrees off the tray's, no robot part touches it (within 1 mm) and it
  moves under 0.03 m/s, all held for 1.5 s, within 150 s ([labbench/score.py](../labbench/score.py),
  [labbench/tasks.py](../labbench/tasks.py)). The tray is drawn like a reader drawer: a pocket with corner guides
  and 3 mm of clearance on each side ([labbench/props.py](../labbench/props.py)).
- **What it cannot know.** The rule does not ask which surface carries the plate, and it compares headings modulo a
  half turn: it accepts a plate propped on a corner guide or turned 180 degrees
  ([tending/dispenser.py](../tending/dispenser.py) says both). The simulated plate has no A1 mark, so "the right way
  round" in the [task table](../README.md#the-tasks) means the long side along the tray; a real plate turned half a
  turn has A1 in the wrong corner. Above all, the rule cannot know if a real reader would take the plate and read it.
- **Dream-1 on plate chores.** In this repo's zero-shot baseline, Dream-1, a general robot model, passed
  `plate_to_tray` on 0 of 3 layouts (exact 95% range 0 to 71%), and 0 of 18 takes across the 6 plate chores
  ([results](../runs/2026-11-18-zero-shot/results.md)).
- **Cameras, in simulation.**
  [robot-lab-judge](https://github.com/di-omics/robot-lab-judge/blob/b444aa0010fa02b3d633ae402677854ea8e11e89/README.md)
  scored vision checks on its dev split, 475 simulated scenes of 10 chores (283 true passes, 192 true fails), with
  truth from this repo's frozen rules. The dev split is for choosing prompts and thresholds, not a final number.
  The scenes are still renders with both arms at home
  ([how they were made](https://github.com/di-omics/robot-lab-judge/blob/b444aa0010fa02b3d633ae402677854ea8e11e89/docs/scene-set.md)).
  Balanced accuracy is the mean of pass recall and fail recall; 0.50 is a coin flip.
  - The best zero-shot judge, LFM3-VL-2B with thinking on (`LiquidAI/LFM3-VL-2B-MLX-8bit`), shown the last frame
    as the top view over both wrist views (the input of `lfm3_3view` below; no top-view-only number is published),
    waved through 25 of 192 failed scenes (9 to 19%), for a balanced accuracy of 0.65
    ([board](https://github.com/di-omics/robot-lab-judge/blob/b444aa0010fa02b3d633ae402677854ea8e11e89/results/simset_dev/board.md)).
  - A linear probe, 1 logistic regression per chore on frozen SigLIP 2 features of 8 zoomed crops of the top view,
    fitted on scenes from the same simulator (`frozen/siglip2-lfm2.5-vl-450m/fine-logreg`), waved through 10 of
    192 (3 to 9%), for 0.95. It tests whether the pictures hold the answer. It is not a judge for new settings.
  - The same saved probe, with no refit, on the same pictures shifted 3 pixels right and 2 down, dimmed 5% and
    saved as JPEG at quality 75, waved through 65 of 192 (27 to 41%), for 0.70
    ([table](https://github.com/di-omics/robot-lab-judge/blob/b444aa0010fa02b3d633ae402677854ea8e11e89/results/frozen/perturbed.md),
    [the changes](https://github.com/di-omics/robot-lab-judge/blob/b444aa0010fa02b3d633ae402677854ea8e11e89/tools/probe_perturbed.py)).

A pass by the simulator and a pass by a camera are both guesses about the next instrument. Here the reader decides.

## The pass rule, written first

A bench trial passes only if, on its first attempt, the reader loads the plate and gives the expected
orientation-specific reference reading, within preset limits, with no alarm, and with no person reseating the
plate or helping in any other way.
Simulated trials have no reader; they are scored by `placement_pass` and `seated_pass` (experiment 2).

| Condition | Recorded in | A failure reads |
|---|---|---|
| The trial ran to its end | `status` | anything but `done` is not scored as a read |
| The reader takes the plate | `first_read`, `read_fault` | `invalid`, `no_load` (also a robot that never delivered it) |
| No alarm; readings within the preset limits; A1 where it should be | `first_read`, `read_fault` | `invalid`, with `alarm`, `out_of_limits` or `reversed` (anything else: `other`) |
| No reseating by a person and no other help | `interventions` | any count above 0 |

- **Usable read:** `status` is `done`, `first_read` is `valid` and `interventions` is 0. This is "a valid result
  on the first try". **Valid with help:** done and valid, with 1 or more interventions; counted, not usable.
  **Reader-confirmed failure:** done and not usable.
- **Intervention:** each time a person touches the plate, the robot or the reader between the start of the trial
  and the end of the first read. Placing the plate by hand (camera study, manual handoff) is the trial itself.

## The 3 experiments

| # | Experiment | Where | Arms | Units | Trials |
|---|---|---|---|---|---|
| 1 | `camera` | bench, plates placed by hand, no robot | `hand_nominal`, `hand_challenge` | 3 days x 8 layouts x 2 placements | 48 |
| 2 | `teaching_sim` | simulation, this repo | `dream1_demos_0`, `dream1_demos_5`, `dream1_demos_20`, `dream1_demos_50` | 4 models x 30 layouts | 120 |
| 3 | `hardware` | 2-arm YAM station and reader | `dream1_demos_0`, `dream1_demos_50` | 2 models x 12 starts | 24 |
| 3 | `hardware` | the same bench | `manual` | 1 timed manual handoff per start | 12 |
| | all | | | | 204 |

### 1. Can the camera tell a usable handoff?

A person places a dry plate in the reader's carrier, the cameras take their pictures, and the reader runs. No
robot is needed, so this can start before any robot arrives.

- **Design.** 3 separate days, 8 fresh layouts a day. At each layout, 2 placements: 1 nominal and 1 permitted
  challenge from 1 of 2 families, `orientation` or `seating`: 24 pairs, 48 placements. The exact challenge inside
  a family is chosen in the first bench session and written in the row's `notes`.
- **Order.** Layouts in number order; a sha256 deal (tag `handoff-study-1`) gives each day 2 layouts of each of the
  4 combinations: orientation or seating, nominal or challenge first.
- **Blinding and calibration.** The same overhead and wrist views are captured for every placement, with no score
  overlay and no instrument result in view. The reader's operator cannot see any camera verdict. Thresholds and
  the orientation-specific well map are frozen on separate manual calibration cases, not among the 48.
- **Unverified.** A placement outside the permitted envelope, or with its reference missing, skips the reader and
  is `unverified`, with a reason; verdicts on it are counted apart. A challenge placement may still read fine.
- **4 sources, kept apart by kind,** each on 2 captures, `original` and `relit` (the same placement photographed
  again under a modest lighting change):
  - rule: `marker_rule`, a fixed marker-and-geometry rule on the top view;
  - linear probe: `probe_siglip2_crops`, the probe on frozen SigLIP 2 features of top-view crops, fitted in
    simulation (the robot-lab-judge row `frozen/siglip2-lfm2.5-vl-450m/fine-logreg`);
  - zero-shot judges: LFM3-VL-2B, thinking on, as `lfm3_top` (top view only) and `lfm3_3view` (top and 2 wrist views).
- **Outcome.** Each source says `release` (send the plate on), `hold` (stop it) or `none` (no usable answer). The
  false-release rate is releases on reader-confirmed failures, over those failures: the costly error. Beside it:
  good reads blocked, holds, decision coverage, and pairs with both placements right.

### 2. How much teaching buys a better transfer?

- **The dose test of [sim_demos/PROPOSAL.md](../sim_demos/PROPOSAL.md), plus 1 outcome;** its side checks and
  hand-opening readout are not in this sheet. Dream-1 untrained (`dream1_demos_0`) and fine-tuned on the first 5, 20
  and 50 demonstrations: nested sets, 500 steps each, the same settings; only the number of demonstrations changes.
- **Test.** Each model on the same 30 unseen layouts, seeds 42000 to 42029, 1 take each, with the sentence "Put
  the plate on the black tray." and the 150 s limit: 120 attempts. The layouts are new draws from the jitter the
  demonstrations cover (the plate within 1.2 cm and 7 degrees): new placements inside the trained range.
- **2 outcomes, reported separately.** `placement_pass` is this repo's frozen `plate_to_tray` rule. `seated_pass`
  is a stricter check that the tray floor, not a corner guide, carries the plate. `plate_to_tray` has none yet; the
  tending chores use a stricter geometric test, `seated_strict` in [tending/dispenser.py](../tending/dispenser.py).
- **Status.** It needs 3 paid fine-tunes ($100 each for 500 steps) and the 120 test takes (estimated at $11):
  about $311 in all by the proposal's estimate, and a yes from the account owner. None has been started, and $0
  has been spent.

### 3. Does the robot leave a plate the reader can use?

- **Design.** On a 2-arm YAM station with the reader: the base model (`dream1_demos_0`) and the 50-demonstration
  fine-tune of experiment 2 (`dream1_demos_50`), both fixed in advance, each on the same 12 fresh starts, `S01`
  to `S12`, a new set that is not the camera study's layouts. 24 attempts. Plus a timed manual handoff on each
  start (`manual`, 12).
- **Order.** Starts in number order, 2 robot attempts each after a fresh reset; the same hash deals 6 starts to
  `dream1_demos_0` first.
- **Outcome.** A usable read on the first unassisted attempt, and hands-on minutes per usable read, resets and
  rescues included (see The scorer). Every assigned start is logged, with interruptions and their reasons.

## The trial sheet

| File | Holds | Today |
|---|---|---|
| [trials.csv](trials.csv) | 1 row per trial | 204 rows, all `planned` |
| [verdicts.csv](verdicts.csv) | 1 row per camera verdict: `trial_id, source, capture, verdict, score, model_id, notes`; `score` is optional, the source's own number | header only |
| [setup_time.csv](setup_time.csv) | teaching and calibration time: `date, activity, minutes, arm, notes`; `date` is `YYYY-MM-DD`; `minutes` is a plain number such as `45` or `1.5`; `activity` is `teaching`, `calibration` or `other`; `arm` is blank (all arms) or an arm name from the table of experiments | header only |

| Column of `trials.csv` | Kind | Values |
|---|---|---|
| `trial_id` | design | `C-D1-L3-N`, `C-D1-L3-C` (camera: day 1, layout 3, nominal or challenge); `T-000-42000` (demonstrations in 3 digits, then the seed); `H-000-S01`, `H-050-S01`; `M-S01` |
| `experiment`, `arm`, `challenge` | design | as in the table of experiments; `challenge` is `none`, or on a camera challenge row `orientation` or `seating` |
| `day`, `layout` | design | 1 to 3 on camera rows, blank otherwise; camera `D1-L3`, simulation the seed, hardware and manual the start `S01` |
| `pair` | design | what matched comparisons share: the camera layout, the seed, or the start |
| `order` | design | run order in a block: 1 to 16 each camera day, 1 to 24 on the robot, 1 to 12 manual, 1 to 120 in simulation |
| `date`, `operator` | result | `YYYY-MM-DD`; a short code, 1 to 6 lower-case letters then 1 to 3 digits, such as `op1`, never a name |
| `first_read`, `read_fault` | result | bench rows only: `valid` or `invalid`; when invalid `no_load`, `alarm`, `out_of_limits`, `reversed` or `other` |
| `interventions`, `hands_on_s` | result | bench rows only: a whole number, 0 or more; seconds of hands-on time, the reset before the trial and any rescue included |
| `placement_pass`, `seated_pass` | result | `1` or `0`, simulated rows only; `seated_pass` 1 needs `placement_pass` 1. Once the seated check exists, fill `seated_pass` on every done row (`0` where `placement_pass` is 0), so both rates count the same rows |
| `first_failed_stage`, `reason`, `notes` | result | a lower-case token, blank when nothing failed (a usable read, or `placement_pass` 1 with no `seated_pass` 0); why a trial was unverified, interrupted or excluded; free text |

| `status` | Means | The row also needs |
|---|---|---|
| `planned` | not run yet | nothing: every other result cell stays blank |
| `done` | ran to its end and has an outcome | bench: `date`, `operator`, `first_read`, `interventions`, `hands_on_s`, and `read_fault` when invalid; simulation: `date`, `operator`, `placement_pass` (`seated_pass` stays blank only while its check does not exist) |
| `unverified` | camera only: photographed, not put through the reader (outside the permitted envelope, or the reference was missing) | `date`, `operator`, `reason`; no time and no interventions |
| `interrupted` | started, then stopped by something outside the pass rule (power, a software crash, the reader out of service) | `date`, `operator`, `reason`; on the bench also `interventions` and `hands_on_s` |
| `excluded` | removed before it ran | `reason`; no time and no interventions |

Outcome cells (`first_read`, `read_fault`, `placement_pass`, `seated_pass`, `first_failed_stage`) go on `done` rows
only. Fill each row's cells in ASCII, and time every bench trial that ends `done` or `interrupted`, camera
placements included; an `unverified` or `excluded` row takes no time. An interrupted trial keeps its row and stays
among the assigned trials; a re-run would need a new trial id (item 10 below).
In `verdicts.csv` each source gets 1 row for every trial and capture it was given, with the exact model or rule
version in `model_id`; with no usable answer the verdict is `none`, never a missing row.

## The scorer

```bash
python -m handoff_study sheet [--dir DIR] [--check]          # write the planned sheet, or check it
python -m handoff_study score [--dir DIR] [--write] [--json]  # validate, then print the report
python -m unittest -v tests.test_handoff_study               # the tests, no simulator needed
```

Run them from a clone of this repo; DIR, where the sheets and the report live, is this folder unless given.
`sheet` writes `trials.csv`, all planned, and the 2 other files with a header only; it refuses to overwrite a sheet
that holds any result, and `--check` fails if the design columns of `trials.csv` differ from `design.py`. `score`
validates the 3 files, lists every problem by row, and prints the report as Markdown; `--write` also writes
`results.md` and `results.json`, and `--json` prints the data. The header gives the scorer id (first 12 hex digits
of a sha256 over this package's `.py` files, as `tending` makes its id), the design id (the same over the planned
design columns) and trials assigned and done. Ranges are exact (Clopper-Pearson), 95%, two-sided, no p-values;
minutes are added exactly and rounded half up to 0.1. The footer always prints 4 caveats: the ranges treat trials
as independent; the 2 placements of a camera pair share a layout and a day; original and relit pictures show the
same placements; the sizes are those of a feasibility pilot.

| Table | Per | What it reports |
|---|---|---|
| Q1, the reader | experiment and arm | Trials assigned, planned, done, unverified, interrupted and excluded. On the bench: usable reads as k of done with the exact range; valid with help; invalid; a tally of `read_fault` over the done trials, and of `first_failed_stage` over the failures (a failure with a blank stage shows as `not recorded`). In simulation: `placement_pass` k of done; `seated_pass` k of the rows that have one (`not recorded` when none has); the stage tally over the rows with a 0. |
| Q2, the camera | experiment, source and capture | False releases r of the failures F, and good reads blocked b of the usable reads G, each with its range; releases, holds and no decision; decision coverage; missing; pairs both right. How each is counted is listed under this table. |
| Q3, the time | experiment and arm with any `hands_on_s` | Attempts with time (done and interrupted), hands-on minutes in all, interventions in all, attempts with 1 or more interventions, usable reads, and hands-on minutes per usable read: the minutes of all those attempts over the usable reads. With 0 usable reads it prints the minutes and "0 usable reads", never a division by 0. `setup_time.csv` is summed apart, by activity and arm (a blank arm shows as `all`). |
| Paired, 50 demonstrations against 0 | seed or start | Both pass, only 50, only 0, neither, incomplete. Simulation uses `placement_pass` (and `seated_pass` where both rows have it), the bench a usable read. |

How Q2 counts:

- **Over done trials with a verdict.** A false release is `release` on a reader-confirmed failure; a good read
  blocked is `hold` on a usable read. Decision coverage is releases plus holds, of the trials with a verdict.
- **Missing.** Done trials of the experiment with no verdict from that source on that capture (on hardware the
  manual handoffs too). The rates leave missing trials out: 2 sources are sure to be compared on the same trials
  when neither has any missing.
- **Pairs both right,** camera study only. A pair is complete when both placements of a layout are done and have
  a verdict, and right when both verdicts are right: `release` on a usable read or `hold` on a failure; `none`
  never is.
- **Kept apart.** Each kind of source (rule, probe, zero_shot, other) has its own table, and `original` and
  `relit` are never pooled. Verdicts on unverified placements are counted apart; verdicts on interrupted trials
  are not scored, and a line under each table counts them.
- **Also printed.** F, r, G and b per camera day. Per source, the same verdict on the original and the relit
  picture of 1 placement, k of the done trials with both.

Simulation and bench are never pooled. [results.md](results.md) is the report as the sheets stand: 0 trials run.

## What is done and what is planned

| Piece | State | Where |
|---|---|---|
| 50 scripted demonstrations of `plate_to_tray`, each scored a success by the bench | done, in simulation | [sim_demos/NOTES.md](../sim_demos/NOTES.md) |
| Their checks: Dream's dataset check, replay 50 of 50, gripper held open 0 of 50, dose sets of 5, 20 and 50 | done, in simulation | [sim_demos/PROPOSAL.md](../sim_demos/PROPOSAL.md) |
| Camera numbers: 3 small zero-shot models and 3 linear probes on 475 scenes, and 2 of the probes on slightly changed pictures | done, in simulation | [board](https://github.com/di-omics/robot-lab-judge/blob/b444aa0010fa02b3d633ae402677854ea8e11e89/results/simset_dev/board.md), [perturbed.md](https://github.com/di-omics/robot-lab-judge/blob/b444aa0010fa02b3d633ae402677854ea8e11e89/results/frozen/perturbed.md) |
| Trial sheet, scorer and tests | written, 0 results | this folder |
| 1. Camera against reader: 48 placements | planned | |
| 2. Teaching dose: 3 fine-tunes, 120 simulated attempts | planned, waiting for a yes on the spend; the `seated_pass` check for `plate_to_tray` is not in this repo yet | [sim_demos/PROPOSAL.md](../sim_demos/PROPOSAL.md) |
| 3. Robot to reader: 24 attempts and 12 manual handoffs | planned, needs a reader, a YAM station and the 50-demonstration fine-tune of experiment 2 | |

## To fix before the first trial

1. The exact reader, carrier and dry reference plate. The simulated plate is a 96 deep-well plate, 44 mm tall; if
   the physical plate differs, the change is documented and versioned before testing.
2. The reference pattern and its limits. It must tell an A1 reversal: a plate turned half a turn reads `reversed`.
3. The permitted challenges in each family, and the envelope outside which a placement is `unverified`.
4. The lighting change for the `relit` capture.
5. The marker rule: its markers, its geometry and its limits.
6. The bench-camera versions of the probe and the 2 zero-shot judges: crops, prompt, model build and threshold.
7. Which stops are failures and which interruptions; if picking up a dropped plate is an intervention; stage names.
8. The sentence and the time limit for robot attempts on the bench (the simulation uses "Put the plate on the
   black tray." and 150 s), when a robot attempt counts as ended with no delivery (`no_load`), and whether the
   robot may adjust the plate itself before the first read.
9. When the manual handoff at a start runs: before, between or after its 2 robot attempts.
10. Whether an interrupted trial is run again: a re-run needs a new trial id in the design.
11. Whether the cameras also judge the trials of experiment 3. The scorer accepts verdicts on its robot attempts
    and on its manual handoffs alike, and reports them in 1 row per source and capture for the whole experiment:
    the 2 models and the manual handoffs are not split.

Then all of these are frozen in a protocol file, with the design id the scorer prints, before the first trial, the
way [PROTOCOL.md](../PROTOCOL.md) was for the scored runs.

## Order of work

| When | What |
|---|---|
| First session | Identify the reader, carrier and dry reference plate. Try 3 good and 3 permitted borderline placements outside the study. Check that the reference pattern tells an A1 reversal. Choose the challenges. |
| Week 1 | Freeze the limits, the camera sources, the reference-read procedure and the layout list. Check that the simulated plate matches the physical one, or document and version the change. Run `sheet --check` and record the design id. |
| Weeks 2 and 3 | The 48 camera placements and, after a yes on the spend, the 120 simulated attempts. Once a YAM station is available and the 50-demonstration fine-tune exists, the 24 hardware attempts in the sheet's order with fresh resets, and the 12 manual handoffs. |
| Week 4 | The report: false releases by source and lighting, handoff success against the number of demonstrations, hands-on minutes per usable read, and matched pictures of a false release and a correct hold. |
| After that | A capped 50 mL tube in a rack, once the plate endpoint works, with its own score. |
| Assumes | Access to a plate reader and a YAM station, and a yes on the fine-tune spend. |

## Limits

- **Pilot sizes.** The exact 95% ranges stay wide. On 12 starts per model, 0 of 12 is 0 to 26%, 12 of 12 is 74 to
  100%, and 6 of 12, the widest, is 21 to 79%. On 30 simulated layouts, 0 of 30 is 0 to 12% and 15 of 30 is 31 to
  69%. The false-release rate divides by the reader-confirmed failures, not known in advance: with 24 failures,
  0 false releases is still 0 to 14% and 12 is 29 to 71%; fewer are wider. A feasibility pilot, not an acceptance
  test.
- **Exact ranges treat trials as independent.** They are not quite: the 2 placements of a pair share a layout and
  a day, and the original and relit pictures show the same placements.
- **The probe was fitted in simulation.** It is not a judge for a real camera: on slightly changed simulator
  pictures its false passes rose from 10 to 65 of 192. No source here has been scored on a real camera frame.
- **1 reader, 1 dry plate, no liquid.** A filled plate, another plate or another reader may behave differently.
- **The demonstrations are scripted in simulation,** from true poses, with no noise and no mistakes. The
  50-demonstration model may do no better than the base model on real arms, or worse.

## Papers that shaped the design

- Du et al., [Vision-Language Models as Success Detectors](https://proceedings.mlr.press/v232/du23b.html): success
  detection as a visual question. Here cameras will answer it on shared pictures; the reader will settle the outcome.
- [FailBench](https://arxiv.org/abs/2609.03611) (preprint): contact failures that are hard to see. Hence the
  `seating` challenges on the bench and the stricter seating check planned for simulation.
- [RoboColosseum](https://arxiv.org/abs/2611.02497) (preprint): blinded comparisons of robot policies on real
  robots, a 2-arm YAM among them; rankings agreed only weakly across robots and poorly predicted results after
  fine-tuning. Here the 2 models will be compared on real arms, on the same 12 starts, in a balanced order.
- [TAPESTRY](https://tapestry-wam.github.io/): names novel placements, novel primitives and novel compositions as
  distinct kinds of unseen test. The main claim here will rest on held-out placements, the tube task on its own score.
