# Tending tasks: a first look at Dream-1

This folder holds 1 completed take per instrument tending task (see [tending/](../../tending/README.md)) from the
model `dreamlabs/dream-1-beta` (Dream-1), run on 2026-11-19 on practice layout 0 with the plain wording (the
sentence on each task card). It is a first look, not a scored run: 1 practice layout and 1 take per task show where
the model starts on these tasks, not a pass rate. Each take can be replayed offline, with no model call.

| Task | Stages reached | Passed | Simulated seconds | Model calls |
|---|---|---|---:|---:|
| `dispenser_plate_in` | 0 of 3 | no | 150.0 | 63 |
| `dispenser_plate_out` | 0 of 3 | no | 150.0 | 63 |
| `cell_bottle_swirl` | 0 of 3 | no | 90.05 | 38 |
| `plate_in_with_swirl` | 0 of 5 | no | 150.0 | 63 |

What the replays measure (the `motion` block of each `replay.json`), over the steps after the camera priming
(3000 for a 150 s take, 1801 for `cell_bottle_swirl`), from each object's pose at the end of the priming, which is
the pose the stages measure from. A height is that of the object's origin, the centre of its underside, unless a
corner is named. A step counts as touched when any part of the robot is within 1 mm of the object.

- Loading (`dispenser_plate_in`, and `plate_in_with_swirl`): the plate was touched on 0 steps and moved under 0.1 mm.
- Unloading (`dispenser_plate_out`): the plate was touched on 256 of 3000 steps and tipped up to 41.6 degrees. Its
  lowest underside corner rose at most 41 mm, but only while tilted 10 degrees or more; while under 10 degrees it
  rose less than 0.1 mm. The lift stage needs that corner more than 25 mm up with a tilt under 10 degrees. The
  plate moved up to 56 mm sideways and ended 29 mm sideways from where it started, 4 mm higher, tilted 5.4 degrees.
- Swirl (`cell_bottle_swirl`): the bottle was touched on 13 of 1801 steps, rose at most 0.4 mm and moved under 1 mm
  sideways. The lift stage needs the underside more than 10 mm up with the bottle resting on nothing.
- Both at once (`plate_in_with_swirl`): the bottle was touched on 210 of 3000 steps, moved up to 9.5 mm sideways
  and rose at most 0.8 mm, again short of the 10 mm a hold needs.

Attempts and cost: 10 attempts in all, 4 completed (the 4 here). 6 ended early and have no score: 3 on an
infrastructure interruption after 1 model reply each, 1 stopped by hand before the first reply, and 2 when the
model service returned an error with the detail "expired", after 9 and 2 replies. 247 model requests were reserved
(241 action replies received), an estimated 0.3458 USD at 0.0014 USD per request. The videos (too large for
git) and the 6 takes that ended early are not here.

## Files

- `<task>/actions.f64le`: the joint targets the simulator was given, float64 little-endian, 1 row of 14 values per
  0.05 s step (left0 to left6, then right0 to right6). The first 33 rows fill the camera windows before the first
  model call; the rest are the model's commands as the simulator received them.
- `<task>/recorded.json`: the live take's summary, trimmed to what a replay needs (the title, the folder path, the
  wall-clock timings and 2 other fields are left out), plus `actions_sha256`, `steps` and `priming_steps`.
- `<task>/replay.json`: what [scripts/tending_replay.py](../../scripts/tending_replay.py) wrote: the replayed
  result, the `motion` block, the code versions, and `agrees` or what differs.

## How to replay

From the repo root, with the same Python as the rest of the repo (1 to 2 minutes for all 4, no network):

```bash
python scripts/tending_replay.py runs/2026-11-19-tending-first-look
python scripts/tending_replay.py runs/2026-11-19-tending-first-look/cell_bottle_swirl
```

The script rebuilds each task on its layout, steps every row with the stage tracker attached as in a live take
(its clock starts after the priming rows), and checks the action file's sha256 and row count, the labbench and
tending fingerprints, every stage time, pass and pass time, and each object's final position (to 0.1 mm) and tilt
(to 0.1 degree) against `recorded.json`, and exits with status 1 if any check fails. The takes were recorded with
labbench `92c256eb309b`, tending `ba4601eda5dc` and mujoco 4.0.1. Any change to the actions fails the sha256 check;
if the recorded hash is changed too, the physics checks catch only a change that moves an object.
