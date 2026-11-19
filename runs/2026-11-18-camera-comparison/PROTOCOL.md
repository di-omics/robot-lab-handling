# Camera policy comparison on plate placement

Registered November 18, 2026 before the first Codex or Fable take. Dream ran earlier. Plate placement was selected because it was the task in the handoff. This is a task-specific pilot.

| Design choice | Fixed value |
| --- | --- |
| Task instruction | Put the plate on the black tray. |
| Layouts | Frozen plate_to_tray seeds 100, 101 and 102, one scored take per policy per seed |
| Clock and outcome | Frozen 150 s simulator limit, stage and pass logic, bench code 92c256eb309b |
| Codex and Fable | Fresh model context for each seed, common actor instructions, same wrapper revision and generic controls |
| Observations | Current overhead and two wrist RGB views, robot proprioception, elapsed simulated time and fixed camera calibration |
| Actions | Commands to move a gripper, set its opening, wait or finish. The common wrapper implements inverse kinematics and advances physics. |
| Dream baseline | Existing dreamlabs/dream-1-beta summaries with protocol-authorized error retries, no new Dream requests from this comparison |
| Disclosure | Dream used 9 frames per camera plus joint state and emitted 48 joint actions per call. The language-model policies use Cartesian commands and may inspect their RGB images. |
| Denominator | Report each layout, any missing attempts or infrastructure errors, and exact 95% binomial intervals on complete series. No best-of selection. |

The policy may use the shared interface documentation, task instruction, its own prior actions within the take, RGB observations and robot-only feedback. It may measure pixels in those images. Object coordinates, other takes, expert demonstrations, rewards before termination, source inspection and benchmark-specific scripted policies are excluded. No policy receives the gripper hint from the handoff. A genuine software failure may be retried once from the same seed, with both attempts disclosed. Early stopping is permitted. Wall time includes model and tool latency and is separate from simulation time.
