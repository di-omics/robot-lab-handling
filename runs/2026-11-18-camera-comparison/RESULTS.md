# Plate placement in simulation

Put the plate on the black tray. Three layouts were assigned to each policy under the frozen 150-second limit. A pass requires stable, hands-off placement. The stage timestamps show partial progress.

| Policy | Passes | Exact 95% interval | Controller |
| --- | ---: | --- | --- |
| Codex | 2/3 | 9.4% to 99.2% | Camera-guided Cartesian commands |
| Fable | Unscored (3 interrupted) | · | Camera-guided Cartesian commands |
| Dream-1 | 0/3 | 0.0% to 70.8% | 48 joint actions per call |

| Layout | Policy | Pass | Lifted at | Over tray at | In tray at | Passed at | Simulated duration | Commands or calls |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 100 | Codex | Yes | 15.1 s | 18.5 s | 79.7 s | 80.7 s | 81.7 s | 37 commands |
| 100 | Fable | Interrupted | · | · | · | · | 3.0 s | 1 commands |
| 100 | Dream-1 | No | · | · | · | · | 150.0 s | 63 calls |
| 101 | Codex | Yes | 16.1 s | 19.6 s | 69.9 s | 70.9 s | 71.9 s | 40 commands |
| 101 | Fable | Interrupted | · | · | · | · | 3.0 s | 1 commands |
| 101 | Dream-1 | No | 67.8 s | · | · | · | 150.0 s | 63 calls |
| 102 | Codex | No | 21.7 s | 24.1 s | · | · | 150.0 s | 21 commands |
| 102 | Fable | Interrupted | · | · | · | · | 5.5 s | 2 commands |
| 102 | Dream-1 | No | 43.0 s | · | · | · | 150.0 s | 63 calls |

Dream received nine RGB frames per camera, joint angles and gripper state per call. Codex and Fable received current RGB views, robot proprioception and a calibrated pixel-to-plane inverse-kinematics controller. Each language model started with a fresh context on each seed. The three layouts estimate this one task imprecisely. The controller difference limits conclusions about the underlying models.

Dream layout 101 had 1 interrupted attempt before the recorded completion. The frozen protocol permits one same-layout infrastructure retry.

Claude Fable 5.2 was stopped by the operator before terminal scoring on all three layouts. Its partial traces are archived. There is no Fable success rate or ranking from this pilot.

[Paired protocol](PROTOCOL.md) · [Actor instructions](ACTOR.md) · [Terminal records and source digests](results.json)
