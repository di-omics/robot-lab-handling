# How many demonstrations does a model need for plate placement?

Dream-1 completed two of three assigned plate-placement layouts and passed neither. A scripted expert with access to simulated object poses completed all 50 demonstration layouts. Dream's local validator accepted the three-camera dataset, which contains 10,049 frames at 10 fps, or 16.75 minutes. This experiment asks whether a model trained on those examples can seat the plate when it must locate it from its own observations. [Demonstration measurements](NOTES.md)

## Proposed experiment

Train independent copies of the same Dream-1 checkpoint with 5, 20 and 50 demonstrations. Use nested training subsets, 500 training steps per copy and the same optimization settings. Freeze the test protocol before evaluating any trained checkpoint. Test the three checkpoints and the pretrained baseline on the same 30 held-out layouts, seeds 42000 through 42029. Each take uses the plain instruction, 150 simulated seconds and the existing hands-off placement rule. Report each layout and the exact 95% interval around each checkpoint's pass count. Keep the stage times for lift, carry and seating.

The plate is 85.5 mm wide and the fully open gripper spans 93.6 mm in the simulated collision geometry. The original Dream traces frequently contained partly closed commands. Those traces motivate a test of opening at the moment of approach. Measuring the opening at comparable distances from the plate would distinguish an early close from a correct close after contact. The action logs alone have not established the cause of the failures.

Optional transfer checks would test the 50-demonstration checkpoint on two other plate tasks and two tube tasks, ten layouts per task. Fix the tasks, seeds and pass criteria before running them.

## Resource estimate

At the proposed budget of $0.20 per training step, one 500-step checkpoint costs $100 in training and all three cost $300. This estimate excludes inference and real-hardware evaluation. The demonstration generation, dataset validation and camera-guided pilot used local simulation. The training and held-out evaluation remain proposed.

The demonstration layouts vary by limited pose jitter. Success on the proposed held-out seeds would measure generalization within that simulator distribution. A future physical evaluation would need real camera images, calibration checks and independent scoring of dry labware on the YAM station.
