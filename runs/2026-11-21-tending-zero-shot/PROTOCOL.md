# Protocol: Dream-1 zero-shot on the instrument tending tasks

Written 2026-11-21 and committed before any take of this run. Code: labbench `92c256eb309b`, tending `ba4601eda5dc`.
A take whose summary carries another fingerprint is not part of this run.

## What is scored

- **Model:** `dreamlabs/dream-1-beta` through its API, joint control, 48 actions per call. Zero-shot: no
  fine-tuning and no examples of these tasks.
- **Inputs:** as in the first protocol ([PROTOCOL.md](../../PROTOCOL.md)): 3 cameras (the last 9 frames of each,
  0.2 s apart), the joint angles and gripper openings, and one sentence.
- **Tasks and wording:** the 4 instrument tending tasks, with the plain wording on each task card (table below).
- **Layouts:** seeds 100, 101 and 102. No model has been run on these tasks on these layouts.
- **Takes:** 1 per task and layout, 12 in all, in this order: layout 100 (tasks 16, 17, 18, 19), then 101, then
  102. No take is added or dropped after results are seen.
- **Errors:** a take that stops on a software, network or service error has no score. It stays in the run folder
  (a take that never wrote a summary stays in `unfinished/`, which git leaves out, and is listed in `results.md`),
  it is reported, and the same task and layout is run again, up to 3 attempts in all. A take stopped by hand is
  kept and reported, but it is not 1 of the 3 attempts. If the service refuses the sentence, that counts as a
  stopped attempt and is reported as a refusal. A task and layout whose 3 attempts all stop is reported as not
  completed and is left out of the pass count.
- **Human assists:** none. Nothing is reset, moved or nudged during a take.
- **Time:** the simulator advances only while actions run. A take ends at the task's time limit, or 1 s after the
  pass rule has held for 1.5 s.
- **Cost:** estimated at $0.0014 per model call. The run stops before a take that could bring the estimate past
  $1.50. The run also stops after a take that made more calls than 48-action chunks need.

## What was known before the run

- **Scripted checks on these 3 layouts**, run offline on 2026-11-21 before this file was written: the bench is at
  rest at the start, the oracle passes, every trap fails, and the scripted reference (which reads object positions
  from the simulator) passes all 4 tasks on all 3 layouts. Nothing was changed afterwards.
- **A first look with the same model on practice layout 0** on 2026-11-19, 1 completed take per task: 0 of 4, no
  stage reached ([record](../2026-11-19-tending-first-look/README.md)). The tasks and the rules were not changed
  after it: this run uses the fingerprint those takes carry.

## Reporting

- Passes as k of n per task with the exact 95% range for the true rate, and stage progress (partial credit) in its
  own column. With 3 takes that range is very wide (0 of 3 still allows up to 71%), so 3 takes sort a task into
  fails, sometimes works or works, and no finer.
- Per take: date, model ID, library version, both code fingerprints, calls and estimated cost.
- Every command sent to the arms is recorded (`actions.f64le` in each take folder), so each take can be replayed
  and scored again offline: `python scripts/tending_replay.py runs/2026-11-21-tending-zero-shot`.
- Anything that departs from this file is listed in [DEVIATIONS.md](../../DEVIATIONS.md).

## How it is run

```bash
python scripts/tending_run.py --out runs/2026-11-21-tending-zero-shot --seeds 100,101,102 --max-cost 1.50
```

1 take at a time. The script calls the same take code as the first protocol and only adds the recording.

## Tasks and pass rules

The rule that counts is the code in `tending/chores.py` and `tending/dispenser.py`;
[tending/README.md](../../tending/README.md) gives every number. This table says the same in words. A stage counts
once its test has held for 0.5 s.

<table>
<tr><th>#</th><th>Task</th><th>The robot is told</th><th>Passes when</th><th>Time limit</th>
<th>Stages (partial credit)</th></tr>
<tr><td>16</td><td><code>dispenser_plate_in</code></td><td>Put the plate on the dispenser's plate carrier.</td>
<td>The plate sits flat in the carrier pocket with A1 at the back left, let go, both hands out of the carrier's
travel, after a level lift and a level pass over the carrier; a dropped plate fails.</td><td>150 s</td>
<td>plate_lifted, plate_over_carrier, plate_seated</td></tr>
<tr><td>17</td><td><code>dispenser_plate_out</code></td>
<td>Take the plate off the dispenser's plate carrier and put it on the gray mat.</td>
<td>The plate lies flat and wholly on the gray mat, let go, with the carrier empty, after a level lift and a level
pass over the mat; a dropped plate fails.</td><td>150 s</td>
<td>plate_lifted, plate_over_mat, plate_on_mat</td></tr>
<tr><td>18</td><td><code>cell_bottle_swirl</code></td>
<td>Swirl the cell bottle to keep the cells mixed, then put it back.</td>
<td>The bottle was lifted and swirled (3 turns or more, tilt under 20 degrees, within 120 mm of its pick point), then
set back upright on its green spot and let go; a tilt past 30 degrees at any time fails.</td><td>90 s</td>
<td>bottle_lifted, bottle_swirled, bottle_home</td></tr>
<tr><td>19</td><td><code>plate_in_with_swirl</code></td>
<td>Load the plate onto the dispenser's plate carrier while your other hand keeps the cell bottle swirling.</td>
<td>Everything task 16 asks, the bottle swirled and home as in task 18, and the bottle swirling for at least half
of the time and half of the plate's travel between the plate leaving the mat and being seated.</td><td>150 s</td>
<td>plate_lifted, plate_over_carrier, plate_seated, bottle_swirled, bottle_home</td></tr>
</table>
