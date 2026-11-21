# Tending tasks: Dream-1 zero-shot on 3 held-out layouts

The scored run registered in [PROTOCOL.md](PROTOCOL.md), which was committed before the first take. Model
`dreamlabs/dream-1-beta` (Dream-1), plain wording, layouts 100 to 102, 1 take per task and layout, run on
2026-11-21. Simulation only.

**Result: 0 passes in 12 takes.** [results.md](results.md) has the table per task (0 of 3 each; the exact 95% range
for the true rate still runs up to 71%). All 12 takes completed on their first attempt: no errors, no refusals, no
reruns, and nothing departed from the protocol. 681 model calls, an estimated 0.95 USD at 0.0014 USD per call.

| Layout | Task | Stages reached | Passed | Model calls | What the replay measures |
|---|---|---|---|---:|---|
| 100 | 16 `dispenser_plate_in` | 0 of 3 | no | 63 | Nothing touched. |
| 100 | 17 `dispenser_plate_out` | 0 of 3 | no | 63 | Plate touched on 10 of 3000 steps, moved up to 2 mm across the table, tilted up to 7.2 degrees. Bottle not touched. |
| 100 | 18 `cell_bottle_swirl` | 0 of 3 | no | 38 | Nothing touched. |
| 100 | 19 `plate_in_with_swirl` | 0 of 5 | no | 63 | Nothing touched. |
| 101 | 16 `dispenser_plate_in` | 0 of 3 | no | 63 | Plate touched on 34 of 3000 steps, moved up to 6 mm across the table, tilted up to 0.7 degrees. Bottle not touched. |
| 101 | 17 `dispenser_plate_out` | 0 of 3 | no | 63 | Nothing touched. |
| 101 | 18 `cell_bottle_swirl` | 0 of 3 | no | 38 | Nothing touched. |
| 101 | 19 `plate_in_with_swirl` | 0 of 5 | no | 63 | Nothing touched. |
| 102 | 16 `dispenser_plate_in` | 0 of 3 | no | 63 | Plate touched on 87 of 3000 steps, moved up to 22 mm across the table, tilted up to 0.4 degrees. Bottle not touched. |
| 102 | 17 `dispenser_plate_out` | 1 of 3 | no | 63 | Plate touched on 207 of 3000 steps, moved up to 154 mm across the table, tilted up to 46.1 degrees, lowest corner up to 42 mm up. Bottle not touched. |
| 102 | 18 `cell_bottle_swirl` | 0 of 3 | no | 38 | Nothing touched. |
| 102 | 19 `plate_in_with_swirl` | 0 of 5 | no | 63 | Plate touched on 350 of 3000 steps, moved up to 68 mm across the table, tilted up to 3.0 degrees. Bottle not touched. |

"Touched" means some part of the robot was within 1 mm of the object on that 0.05 s step. Moves, rises and tilts are
the largest over the take, measured from where the object stood when the model's first command ran. The numbers in
the last column are in the `motion` block of that take's `replay.json`, except the step count (the take's steps
after the 33 camera priming steps, from `trace.json`). Stages and calls are in `summary.json`.

## What happened

- **In 7 of the 12 takes the robot touched neither the plate nor the bottle.** The bottle was not touched in
  any take, so no swirl was ever started.
- **Loading (task 16):** on 2 of 3 layouts the robot reached the plate and pushed it along the mat (up to
  22 mm). It never lifted it.
- **Unloading (task 17), layout 102:** a step-by-step replay shows the left hand gripping 1 end of the plate and
  tipping it up. The other end slid on the carrier floor and up a corner guide until the plate came free at about
  30 degrees of tilt. The hand carried it out at 27 to 46 degrees, lowered it until its low end touched the mat,
  and let go. The plate then fell flat, its raised end from about 95 mm up, and came to rest wholly on the mat
  (every corner at least 10 mm inside the edges) with the carrier empty. That is the last stage (reached at
  71.75 s). The 2 stages before it ask for a level lift and a level pass over the mat (tilt under 10 degrees), and
  the pass rule needs both: while the tilt was under 10 degrees the lowest corner never rose more than 0.1 mm. So
  this take is not a pass. The drop rule did not count a drop, because it follows the plate's lowest corner, which
  was already on the mat when the hand let go. No liquid is simulated here; the level rule stands in for what a
  filled plate needs.
- **Both at once (task 19):** on 1 layout the right hand pushed the plate 68 mm along the mat, partly off it, and
  never lifted it; the bottle was never touched.

The scripted reference, which reads object positions from the simulator, passes all 4 tasks on these 3 layouts, so
the tasks can be done here. The first look on a practice layout is in
[../2026-11-19-tending-first-look](../2026-11-19-tending-first-look/README.md).

## Files and replay

Each take folder holds `summary.json` (the score and the versions), `replies.jsonl` (per model call: time, gripper
range, hand positions), `actions.f64le` (every command sent to the arms), `trace.json` (its step counts, sha256s and
code versions), and `replay.json` (what the replay found). The videos are too large for git. To replay all 12 takes
offline and score them again (a few minutes, no network):

```bash
python scripts/tending_replay.py runs/2026-11-21-tending-zero-shot
```

All 12 replays agree with the recorded scores. The takes ran with labbench `92c256eb309b`, tending `ba4601eda5dc`,
dreamlabs 1.0.42 and mujoco 4.0.1.
