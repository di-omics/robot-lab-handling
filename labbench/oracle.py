"""Scoring checks without a robot: move the labware by hand (teleport), and see that the score says the right thing.

Every task card carries two scripts:
- an oracle: the labware is moved through the task the way a success would look, and each stage must be reached
  at the right moment, ending in success;
- traps: end states that look close but are wrong (a tube lying across the rack, a plate next to the tray).
  None of them may score as success.

A scoring rule that never fires, or fires on the wrong thing, is worse than none, so these run before any model.
"""

from dataclasses import dataclass, field
from typing import Callable, Optional

import mujoco
import numpy as np

from .sim import HOME, STEP_S


def mat_to_quat(rotation):
    quat = np.empty(4)
    mujoco.mju_mat2Quat(quat, np.asarray(rotation, dtype=float).flatten())
    return quat


def yaw_tilt_quat(yaw=0.0, roll=0.0, pitch=0.0):
    """Quaternion for a turn about vertical, after tipping about x (roll) and y (pitch). Radians."""
    q = np.empty(4)
    mujoco.mju_euler2Quat(q, np.array([roll, pitch, yaw], dtype=float), "xyz")
    return q


def place(env, name, pos, quat=None):
    """Put a movable prop somewhere, at rest."""
    joint = env.data.joint(f"{name}_free")
    joint.qpos[:3] = pos
    if quat is not None:
        joint.qpos[3:7] = quat
    joint.qvel[:] = 0
    mujoco.mj_forward(env.model, env.data)


@dataclass
class Step:
    """One scripted move of one prop."""

    prop: str
    pose: Callable  # world -> (position, quaternion or None)
    pin_s: float = 0.0  # hold the prop exactly there for this long (as if a hand held it)
    settle_s: float = 0.0  # then let physics run this long
    expect: list = field(default_factory=list)  # stages that must be reached by the end of the step
    not_yet: list = field(default_factory=list)  # stages that must still be unreached
    success: Optional[bool] = None  # what the task's success must be at the end of the step
    note: str = ""


def play(bench, steps):
    """Run scripted steps on a bench. @return A list of problems; empty means the scoring behaved."""
    env, tracker, world = bench.env, bench.tracker, bench.world
    problems = []

    def tick():
        env.step(HOME, HOME)
        tracker.update()

    for index, step in enumerate(steps):
        pos, quat = step.pose(world)
        place(env, step.prop, pos, quat)
        for _ in range(round(step.pin_s / STEP_S)):
            place(env, step.prop, pos, quat)
            tick()
        for _ in range(round(step.settle_s / STEP_S)):
            tick()
        label = f"step {index + 1} ({step.note or step.prop})"
        for name in step.expect:
            if tracker.reached.get(name) is None:
                problems.append(f"{label}: stage '{name}' was not reached")
        for name in step.not_yet:
            if tracker.reached.get(name) is not None:
                problems.append(f"{label}: stage '{name}' was reached too early")
        if step.success is not None and (tracker.success_at is not None) != step.success:
            problems.append(f"{label}: success is {tracker.success_at is not None}, expected {step.success}")
    return problems


def at_rest_problems(bench, seconds=2.0, max_drift=0.003):
    """Nothing may move or score while the robot holds still at the start."""
    env, tracker, world = bench.env, bench.tracker, bench.world
    start = {n: world.pos(n) for n in bench.task.movable}
    start_tilt = {n: world.tilt_deg(n) for n in bench.task.movable}
    for _ in range(round(seconds / STEP_S)):
        env.step(HOME, HOME)
        tracker.update()
    problems = []
    for n in bench.task.movable:
        drift = float(np.linalg.norm(world.pos(n) - start[n]))
        if drift > max_drift:
            problems.append(f"'{n}' drifted {drift * 1000:.1f} mm at rest")
        if abs(world.tilt_deg(n) - start_tilt[n]) > 3:
            problems.append(f"'{n}' tipped {world.tilt_deg(n) - start_tilt[n]:.1f} deg at rest")
    reached = [n for n, t in tracker.reached.items() if t is not None]
    if reached:
        problems.append(f"stages reached with nothing done: {reached}")
    if tracker.success_at is not None:
        problems.append("success with nothing done")
    return problems
