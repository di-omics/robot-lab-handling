# Camera-guided YAM simulation

Use one process per take. From the benchmark root, start the simulator in a separate terminal or background job. The output directory must be new. The example uses a practice seed.

```sh
~/dream-env/bin/python -m camera_env --listen --task plate_to_tray --seed 0 --actor example --out /tmp/yam-practice-take
```

From the same project, a fresh shell can read the current observation or submit one action. A read leaves simulation time fixed. The client waits for the action to complete before printing its next observation.

```sh
~/dream-env/bin/python -m camera_env.client /tmp/yam-practice-take
~/dream-env/bin/python -m camera_env.client /tmp/yam-practice-take '{"left":{"uv":[320,180],"plane":0,"z":0.15,"yaw":0,"grip":1},"seconds":2}'
~/dream-env/bin/python -m camera_env.client /tmp/yam-practice-take '{"left":{"z":0.16},"seconds":1}'
~/dream-env/bin/python -m camera_env.client /tmp/yam-practice-take '{"left":{"grip":0.5},"seconds":1}'
~/dream-env/bin/python -m camera_env.client /tmp/yam-practice-take '{"seconds":1}'
~/dream-env/bin/python -m camera_env.client /tmp/yam-practice-take '{"done":true}'
```

Omit `--listen` to use JSON lines on standard input. That mode emits an initial observation, an observation after each action and a separate terminal message. Closing standard input before termination marks the take interrupted.

## Observations

Each reply gives the prompt, simulated clock, allowance and paths to three unannotated RGB PNG files from the station's overhead and wrist cameras. Each PNG measures 640 × 360 pixels. The convenience JPEG shows the complete overhead image and half-size wrist views. For each hand the reply gives six measured joint angles in radians, measured normalized gripper opening, forward-kinematic TCP coordinates in metres and the projected TCP pixel on the overhead view. Scores are available only after completion.

## Commands

- `left` and `right` can appear in one command. An omitted arm holds its previous actuator targets.
- `xyz` takes a world-frame [x, y, height] triple in metres. Height is measured from the table. At rest the left TCP has positive x and the right TCP has negative x. Positive y points toward the overhead camera's mounting side. The calibrated image projection accounts for the camera's pitch.
- `uv` is an overhead [column, row] in the original 640 × 360 crop. `plane` is the operator's estimated height in metres of the feature at that pixel and defaults to table height. Calibration maps the pixel ray to world x and y on that plane. `z` separately sets the requested TCP height. A standalone `z` moves vertically. Unknown feature heights and occlusions remain visual estimation problems.
- `yaw` points the hand straight down and selects the gripper heading in degrees. At zero the fingers close along world y. At 90° they close along world x. Without a yaw command the controller retains its commanded orientation.
- `grip` ranges from 0 (closed) to 1 (open). Robot kinematics and the gripper target follow a smooth trajectory over `seconds`. The control rate is 20 Hz and each command allows 0.05 to 30 seconds, bounded by the remaining take time. The default duration is one second. Joint limits and contacts can prevent a target from being reached. Inspect the measured TCP after each command. The allowable input range is wider than the robot's physical reach.
- A command containing only `seconds` holds the robot at its last actuator targets. `{"done":true}` holds through the time budget or frozen success condition. One process runs one take without a reset command.

## Evidence and comparison

The adapter reuses the benchmark's seeded reset, 33-step pre-roll, frozen scorer, simulation step and time budget. It uses no Dream service. Cartesian inverse kinematics reads only the named arm joints and TCP. Pixel projection uses the RGB renderer's camera geometry and the operator's chosen plane. The measured gripper opening supplies normal robot proprioception. Each policy sees one synchronized frame per camera per observation. Dream-1 saw nine frames per camera and produced joint chunks directly.

Each run records its configuration and code identifiers, raw observation frames, human-readable camera mosaics, accepted action log, a 4 fps three-camera MP4 and a terminal summary. The socket client uses an observation index to reject a command that races with a previously accepted command. Read the latest observation after a disconnected call before deciding the next action.
