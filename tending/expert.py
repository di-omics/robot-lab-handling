"""A scripted expert for the 4 chores: waypoints plus inverse kinematics, driven through env.step under the real
physics. It proves the chores can be done by this robot; it is not a policy and it reads true poses.

The left arm moves plates (PlateMover); the right arm swirls the cell bottle (BottleSwirler). Each arm is its own
generator of 7-vector commands, so in the two-arm chore both run in the same control loop and really move at the
same time. The plate grasp follows the measured plate grasp of the bench's scripted demonstrations: from above,
across the plate's 85.5 mm short side (the open fingers leave 93.6 mm), gripper ramped closed over 0.6 s to a
command of 0.6. The bottle grasp is from above around its 50 mm body, tcp 50 mm above the table, gripper ramped to
0.25. The IK helpers are an adapted copy of the demonstrations' expert, not an import of it.
"""

import json
import time
from pathlib import Path

import mujoco
import numpy as np

from labbench import __version__ as LABBENCH_VERSION
from labbench.sim import HOME, STEP_S, TABLE_Z
from labbench.take import CODE_ID, set_bench
from labbench.video import Mp4

from . import TENDING_ID
from . import dispenser as D

## tcp height above the plate underside at the grasp: the fingertips stop about 3 mm above it.
GRASP_Z = 0.013
## Plate underside above the table while carried.
CARRY_Z = 0.13
## Plate underside above its place when the gripper opens.
RELEASE_GAP = 0.002
GRIP_CLOSED = 0.6
## IK start poses tried besides the current one.
IK_SEEDS = (np.array([0.0, 1.0, 1.0, 0.0, 0.0, 0.0]), np.array([0.0, 1.2, 1.2, -0.5, 0.0, 0.0]))


def down_rot(phi):
    """tcp orientation pointing straight down, its jaw axis turned phi about vertical."""
    c, s = np.cos(phi), np.sin(phi)
    return np.array([[-c, -s, 0.0], [-s, c, 0.0], [0.0, 0.0, -1.0]])


def min_jerk(s):
    s = np.clip(s, 0.0, 1.0)
    return s ** 3 * (10 - 15 * s + 6 * s * s)


def mat_quat(rot):
    q = np.empty(4)
    mujoco.mju_mat2Quat(q, np.asarray(rot, dtype=float).flatten())
    return q


def quat_mat(q):
    r = np.empty(9)
    mujoco.mju_quat2Mat(r, np.asarray(q, dtype=float))
    return r.reshape(3, 3)


def slerp(q0, q1, t):
    q0, q1 = np.asarray(q0, float), np.asarray(q1, float)
    dot = float(q0 @ q1)
    if dot < 0:
        q1, dot = -q1, -dot
    if dot > 0.9995:
        q = q0 + t * (q1 - q0)
        return q / np.linalg.norm(q)
    th = np.arccos(dot)
    return (np.sin((1 - t) * th) * q0 + np.sin(t * th) * q1) / np.sin(th)


def wrap(a):
    return (a + np.pi) % (2 * np.pi) - np.pi


def rotz(a):
    c, s = np.cos(a), np.sin(a)
    return np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])


class ArmIK:
    """Damped least squares IK for one arm's tcp site, on a private copy of the simulation state."""

    def __init__(self, env, side):
        m = env.model
        self.m = m
        self.d = mujoco.MjData(m)
        self.d.qpos[:] = env.data.qpos
        self.site = m.site(f"{side}_tcp").id
        joints = [m.joint(f"{side}_joint{i}") for i in range(1, 7)]
        self.qadr = np.array([j.qposadr[0] for j in joints])
        self.dadr = np.array([j.dofadr[0] for j in joints])
        self.lo = np.array([j.range[0] for j in joints])
        self.hi = np.array([j.range[1] for j in joints])
        self._jp = np.zeros((3, m.nv))
        self._jr = np.zeros((3, m.nv))

    def fk(self, q):
        self.d.qpos[self.qadr] = q
        mujoco.mj_kinematics(self.m, self.d)
        mujoco.mj_comPos(self.m, self.d)
        return self.d.site_xpos[self.site].copy(), self.d.site_xmat[self.site].reshape(3, 3).copy()

    def solve(self, pos, rot, q0, iters=200, damping=0.02):
        """@return (joint angles, position error m, orientation error rad)."""
        q = np.clip(np.asarray(q0, float).copy(), self.lo, self.hi)
        ep = er = None
        for _ in range(iters):
            p, r = self.fk(q)
            ep = pos - p
            er = 0.5 * sum(np.cross(r[:, i], rot[:, i]) for i in range(3))
            if np.linalg.norm(ep) < 1e-4 and np.linalg.norm(er) < 1e-3:
                break
            mujoco.mj_jacSite(self.m, self.d, self._jp, self._jr, self.site)
            jac = np.vstack([self._jp[:, self.dadr], self._jr[:, self.dadr]])
            dq = jac.T @ np.linalg.solve(jac @ jac.T + damping ** 2 * np.eye(6), np.r_[ep, er])
            big = np.abs(dq).max()
            if big > 0.15:
                dq *= 0.15 / big
            q = np.clip(q + dq, self.lo, self.hi)
        return q, float(np.linalg.norm(ep)), float(np.linalg.norm(er))


class ExpertFailed(RuntimeError):
    pass


class Arm:
    """One arm's scripted moves. Each move is a generator that yields the arm's 7-vector command (6 joints and the
    gripper) once per control step."""

    side = "left"

    def __init__(self, bench):
        self.bench, self.env, self.world = bench, bench.env, bench.world
        self.ik = ArmIK(self.env, self.side)
        self.q = np.asarray(self.env.state()[self.side][:6], float)
        self.grip = 1.0
        self.phase = "start"
        self.log = []

    def _cmd(self):
        return np.r_[self.q, self.grip]

    def _solve(self, pos, rot, seeds=()):
        best = None
        for seed in (self.q, *seeds):
            q, ep, er = self.ik.solve(pos, rot, seed)
            if best is None or ep + 0.1 * er < best[1] + 0.1 * best[2]:
                best = (q, ep, er)
            if ep < 5e-4 and er < 5e-3:
                break
        q, ep, er = best
        if ep > 2e-3 or er > 2e-2:
            raise ExpertFailed(f"{self.side} {self.phase}: no IK ({ep * 1000:.1f} mm, {np.degrees(er):.1f} deg)")
        return q

    def joint_move(self, q_goal, seconds):
        q0 = self.q.copy()
        n = max(1, round(seconds / STEP_S))
        for i in range(1, n + 1):
            self.q = q0 + (q_goal - q0) * min_jerk(i / n)
            yield self._cmd()

    def line_move(self, pos_goal, rot_goal, seconds):
        """Straight line of the tcp with the orientation slerped, solved by IK every step."""
        p0, r0 = self.ik.fk(self.q)
        a, b = mat_quat(r0), mat_quat(rot_goal)
        n = max(1, round(seconds / STEP_S))
        for i in range(1, n + 1):
            s = min_jerk(i / n)
            self.q = self._solve(p0 + (pos_goal - p0) * s, quat_mat(slerp(a, b, s)))
            yield self._cmd()

    def gripper(self, value, seconds, hold_s=0.3):
        start = self.grip
        n = max(1, round(seconds / STEP_S))
        for i in range(1, n + 1):
            self.grip = float(start + (value - start) * i / n)
            yield self._cmd()
        yield from self.hold(hold_s)

    def hold(self, seconds):
        for _ in range(max(1, round(seconds / STEP_S))):
            yield self._cmd()

    def go_home_and_rest(self, seconds=2.2):
        self.phase = "home"
        yield from self.joint_move(HOME[:6].copy(), seconds)
        self.phase = "rest"
        while True:
            yield from self.hold(STEP_S)


class PlateMover(Arm):
    """The left arm: carries the plate to a place, lets go, and goes home."""

    side = "left"

    def __init__(self, bench, release_gap=RELEASE_GAP):
        super().__init__(bench)
        self.release_gap = release_gap

    def move_plate(self, goal_xy, goal_z, goal_yaw, lift_first=0.0):
        """Pick the plate where it is and set it down with its underside at goal_z, centred on goal_xy, turned to
        goal_yaw; then let go, rise, go home and stay there.
        @param lift_first Go straight up this far first (to clear the nest guides before moving sideways).
        """
        w = self.world
        pp = w.pos("plate")
        yaw = np.radians(w.yaw_deg("plate"))
        top = pp[2] + D.PLATE_H
        hover = np.r_[pp[:2], top + 0.07]
        options = []
        for phi in (wrap(yaw), wrap(yaw + np.pi)):  # either way round across the short side; keep the wrist easy
            try:
                q = self._solve(hover, down_rot(phi), seeds=IK_SEEDS)
            except ExpertFailed:
                continue
            options.append((abs(q[5]), phi, q))
        if not options:
            raise ExpertFailed("no IK above the plate")
        _, phi, q_hover = min(options, key=lambda o: o[0])

        self.phase = "reach"
        yield from self.joint_move(q_hover, 2.4)
        self.phase = "descend"
        grasp = np.r_[pp[:2], pp[2] + GRASP_Z]
        yield from self.line_move(np.r_[grasp[:2], top + 0.02], down_rot(phi), 1.0)
        yield from self.line_move(grasp, down_rot(phi), 1.2)
        yield from self.hold(0.3)
        self.phase = "close"
        yield from self.gripper(GRIP_CLOSED, 0.6)
        self.phase = "lift"
        if lift_first:
            yield from self.line_move(grasp + np.r_[0, 0, lift_first], down_rot(phi), 0.8)
        yield from self.line_move(np.r_[grasp[:2], TABLE_Z + CARRY_Z + GRASP_Z], down_rot(phi), 1.2)
        yield from self.hold(0.3)

        # Where the plate really sits in the hand, from the simulated tcp; plan the carry around that.
        site = self.env.data.site(f"{self.side}_tcp")
        real_tcp, real_rot = site.xpos.copy(), site.xmat.reshape(3, 3).copy()
        in_hand_pos = real_rot.T @ (w.pos("plate") - real_tcp)
        in_hand_rot = real_rot.T @ w.rot("plate")
        self.log.append({"plate_in_hand_mm": (in_hand_pos * 1000).round(1).tolist()})
        hand_rot = rotz(goal_yaw) @ in_hand_rot.T
        offset = hand_rot @ in_hand_pos
        place = np.r_[goal_xy, goal_z + self.release_gap]
        above = place + np.r_[0, 0, 0.06]
        high = above + np.r_[0, 0, 0.02]

        self.phase = "carry"
        yield from self.line_move(high - offset, hand_rot, 2.6)
        yield from self.hold(0.3)
        for _ in range(2):  # trim the measured position and yaw error of the plate itself
            err = high - w.pos("plate")
            yaw_err = wrap(goal_yaw - np.radians(w.yaw_deg("plate")))
            hand_rot = rotz(yaw_err) @ hand_rot
            yield from self.line_move(self.ik.fk(self.q)[0] + np.r_[err[:2], 0.0], hand_rot, 0.5)
            yield from self.hold(0.2)
        offset = hand_rot @ in_hand_pos
        trim = self.ik.fk(self.q)[0] - (high - offset)
        self.log.append({"trim_mm": (trim * 1000).round(1).tolist(),
                         "yaw_err_deg": round(float(np.degrees(wrap(goal_yaw - np.radians(w.yaw_deg("plate"))))), 2)})

        self.phase = "lower"
        yield from self.line_move(above - offset + trim, hand_rot, 0.8)
        yield from self.line_move(place - offset + trim, hand_rot, 1.6)
        yield from self.hold(0.3)
        self.phase = "release"
        yield from self.gripper(1.0, 0.6)
        self.phase = "retreat"
        yield from self.line_move(self.ik.fk(self.q)[0] + np.r_[0, 0, 0.08], hand_rot, 1.2)
        yield from self.go_home_and_rest(2.2)

    def actions(self, task_name):
        """The plate move a chore asks for: into the nest (dispenser_plate_in, plate_in_with_swirl) or onto the
        mat (dispenser_plate_out)."""
        specs = self.bench.specs
        if task_name in ("dispenser_plate_in", "plate_in_with_swirl"):
            n = specs["nest"]
            yaw = np.radians(self.world.yaw_deg("plate"))
            if abs(wrap(yaw - n["yaw"])) > np.pi / 2:
                raise ExpertFailed("the plate starts the wrong way round; this expert does not turn it")
            yield from self.move_plate((n["x"], n["y"]), n["floor"], n["yaw"])
        elif task_name == "dispenser_plate_out":
            m = specs["mat"]
            yaw = np.radians(self.world.yaw_deg("plate"))
            yield from self.move_plate((m["x"], m["y"]), TABLE_Z, np.round(wrap(yaw) / np.pi) * np.pi, lift_first=0.03)
        else:
            raise ExpertFailed(f"no plate move for {task_name}")


class BottleSwirler(Arm):
    """The right arm: picks the cell bottle up from above, swirls it in small circles, and sets it back.

    Measured in design probes: the 0.25 grip squeezes with about 13.5 N per finger, the bottle slips at most about
    1 mm in the hand, and its centre runs a circle of about 22 to 24 mm for the tcp's 25 mm.
    """

    side = "right"
    ## IK starts tried on every solve; the best result is kept.
    STARTS = (np.array([0.0, 1.0, 1.0, 0.0, 0.0, 0.0]), np.zeros(6))
    GRASP_Z = 0.05  # tcp height above the table at the grasp
    GRIP = 0.25
    LIFT = 0.03

    def __init__(self, bench):
        super().__init__(bench)
        self.turns = 0.0

    def _solve(self, pos, rot, seeds=()):
        best = None
        for seed in (self.q, *self.STARTS):
            q, ep, er = self.ik.solve(pos, rot, seed)
            if best is None or ep + 0.1 * er < best[1] + 0.1 * best[2]:
                best = (q, ep, er)
        q, ep, er = best
        if ep > 2e-3 or er > 2e-2:
            raise ExpertFailed(f"{self.side} {self.phase}: no IK ({ep * 1000:.1f} mm, {np.degrees(er):.1f} deg)")
        return q

    def swirl(self, keep_going=lambda: False, min_turns=6.0, r=0.025, hz=0.8, ramp_s=1.0):
        """Grasp, lift 3 cm, swirl the tcp on a circle of radius r at hz turns a second (speed ramped up and down
        over ramp_s), set the bottle back where it was, let go, rise and go home.
        @param keep_going Asked every step once min_turns are done; the swirl winds down when it says False.
        """
        rot = down_rot(0.0)
        bp = self.world.pos("bottle")
        grasp = np.r_[bp[:2], TABLE_Z + self.GRASP_Z]
        self.phase = "reach"
        yield from self.joint_move(self._solve(grasp + np.r_[0, 0, 0.09], rot), 2.4)
        self.phase = "descend"
        yield from self.line_move(grasp, rot, 1.5)
        yield from self.hold(0.3)
        self.phase = "close"
        yield from self.gripper(self.GRIP, 0.6)
        self.phase = "lift"
        c = grasp + np.r_[0, 0, self.LIFT]
        yield from self.line_move(c, rot, 1.0)
        self.phase = "to_start"
        yield from self.line_move(c + np.r_[r, 0, 0], rot, 0.6)
        self.phase = "swirl"
        omega, t, th, stopping = 2 * np.pi * hz, 0.0, 0.0, None
        while True:
            t += STEP_S
            if stopping is None and th / (2 * np.pi) >= min_turns and not keep_going():
                stopping = t
            k = min(1.0, t / ramp_s) if stopping is None else max(0.0, 1.0 - (t - stopping) / ramp_s)
            if stopping is not None and k <= 0.0:
                break
            th += omega * k * STEP_S
            self.q = self._solve(c + r * np.r_[np.cos(th), np.sin(th), 0.0], rot)
            yield self._cmd()
        self.turns = th / (2 * np.pi)
        self.log.append({"swirl_turns_commanded": round(self.turns, 2)})
        self.phase = "to_centre"
        yield from self.line_move(c, rot, 0.6)
        self.phase = "lower"
        yield from self.line_move(grasp + np.r_[0, 0, 0.002], rot, 1.2)
        yield from self.hold(0.3)
        self.phase = "release"
        yield from self.gripper(1.0, 0.6)
        self.phase = "retreat"
        yield from self.line_move(grasp + np.r_[0, 0, 0.08], rot, 1.2)
        yield from self.go_home_and_rest(2.0)


def deepest_contact(env, body, among=None):
    """The deepest contact of any geom of `body` with anything (or with a geom in `among` only), as (depth in m,
    the other geom's name or id). MuJoCo contacts are soft, so a fraction of a millimetre is normal; much more
    means parts pass through."""
    m, d = env.model, env.data
    best = (0.0, "")
    for i in range(d.ncon):
        c = d.contact[i]
        a, b = c.geom1, c.geom2
        if body not in (m.geom_bodyid[a], m.geom_bodyid[b]) or -c.dist <= best[0]:
            continue
        other = b if m.geom_bodyid[a] == body else a
        if among is not None and other not in among:
            continue
        best = (-float(c.dist), m.geom(other).name or f"geom {other} of {m.body(m.geom_bodyid[other]).name}")
    return best


## In the two-arm chore the left arm waits this long at home first, so the right arm is already swirling when the
## plate leaves the mat.
LEAD_S = 1.5


def arm_plans(bench, task_name, release_gap=RELEASE_GAP):
    """The generators that drive each arm for a chore, (left or None, right or None), and the arm objects.
    None means that arm stays at home. In plate_in_with_swirl the right arm keeps swirling until the left arm has
    let go of the plate and started to rise."""
    mover, swirler = PlateMover(bench, release_gap), BottleSwirler(bench)
    if task_name in ("dispenser_plate_in", "dispenser_plate_out"):
        return mover.actions(task_name), None, mover, None
    if task_name == "cell_bottle_swirl":
        return None, swirler.swirl(min_turns=6), None, swirler
    if task_name == "plate_in_with_swirl":
        def left():
            for _ in range(round(LEAD_S / STEP_S)):
                yield HOME.copy()
            yield from mover.actions(task_name)
        right = swirler.swirl(keep_going=lambda: mover.phase not in ("retreat", "home", "rest"), min_turns=5)
        return left(), right, mover, swirler
    raise ExpertFailed(f"no expert for {task_name}")


def play_expert(task_name, seed, out_root, video=True, say=print, release_gap=RELEASE_GAP, on_step=None):
    """Play the scripted expert on one seeded bench and score it.
    @param out_root The take folder <YYYYmmdd-HHMMSS>-<task>-s<seed>-expert is made inside it.
    @param video Also write show.mp4 (1280 x 720, 10 frames a second, the view across the bench).
    @param release_gap How far above its place the plate's underside is when the gripper opens, m. Changed only by
        the checks that a release from too high counts as a drop.
    @param on_step Called as on_step(bench) after every control step (for checks that watch the whole take).
    @return The summary dict, also written to <take dir>/summary.json.
    The take ends 1 s after success once every arm that moved is back home and at rest (so the video's last frame
    shows the finished bench), or at the chore's time limit.
    """
    bench = set_bench(task_name, seed, show=True)  # show=True also makes the offscreen buffer 1280 x 720
    D.aim_show(bench)
    env, world, tracker, task = bench.env, bench.world, bench.tracker, bench.task
    gap = "" if release_gap == RELEASE_GAP else f"-gap{release_gap * 1000:g}mm"
    out = Path(out_root) / f"{time.strftime('%Y%m%d-%H%M%S')}-{task_name}-s{seed}-expert{gap}"
    out.mkdir(parents=True)
    renderer = mujoco.Renderer(env.model, height=720, width=1280) if video else None
    movie = Mp4(out / "show.mp4", 1280, 720, round(1 / (2 * STEP_S))) if video else None
    tracker.t0 = world.time
    bodies = {k: env.model.body(k).id for k in ("plate", "bottle")}
    deepest = {k: (0.0, "", 0.0) for k in ("plate", "bottle", "bottle_robot")}
    error, steps, both = None, 0, 0
    wall0 = time.monotonic()
    mover = swirler = None
    try:
        left_plan, right_plan, mover, swirler = arm_plans(bench, task_name, release_gap)
        last_tcp = {s: world.tcp(s) for s in ("left", "right")}
        active = [a for a, plan in ((mover, left_plan), (swirler, right_plan)) if plan is not None]
        while True:
            left = next(left_plan) if left_plan is not None else HOME.copy()
            right = next(right_plan) if right_plan is not None else HOME.copy()
            env.step(left, right)
            tracker.update()
            tcp = {s: world.tcp(s) for s in ("left", "right")}
            both += all(np.linalg.norm(tcp[s] - last_tcp[s]) > 0.001 for s in tcp)
            last_tcp = tcp
            for key, body, among in (("plate", bodies["plate"], None), ("bottle", bodies["bottle"], None),
                                     ("bottle_robot", bodies["bottle"], world.robot_geoms)):
                depth, other = deepest_contact(env, body, among)
                if depth > deepest[key][0]:
                    deepest[key] = (depth, other, world.time - tracker.t0)
            if on_step is not None:
                on_step(bench)
            if movie is not None and steps % 2 == 0:
                renderer.update_scene(env.data, camera="show")
                movie.add(renderer.render())
            steps += 1
            clock = world.time - tracker.t0
            if (tracker.success_at is not None and clock - tracker.success_at >= 1.0
                    and all(a.phase == "rest" for a in active)):
                break
            if clock >= task.seconds:
                break
    except ExpertFailed as e:
        error = f"ExpertFailed: {e}"
    finally:
        if movie is not None:
            movie.close()
            renderer.close()
    summary = {
        "task": task_name, "title": task.title, "prompt": task.prompt, "seed": seed, "policy": "expert",
        "seconds_allowed": float(task.seconds), "sim_s": round(world.time - tracker.t0, 2),
        **tracker.summary(),
        "objects": {n: {"pos": world.pos(n).round(4).tolist(), "tilt_deg": round(world.tilt_deg(n), 1)}
                    for n in task.movable},
        "layout": {k: [round(float(v), 4) for v in vals] for k, vals in bench.layout.items()},
        "error": error, "release_gap_mm": round(release_gap * 1000, 1),
        **{f"deepest_{k}_contact": {"mm": round(v[0] * 1000, 2), "with": v[1], "at_s": round(v[2], 2)}
           for k, v in deepest.items()},
        "both_arms_moving_s": round(both * STEP_S, 2),
        "expert_log": {"left": mover.log if mover else [], "right": swirler.log if swirler else []},
        "last_phase": {"left": mover.phase if mover else None, "right": swirler.phase if swirler else None},
        "wall_s": round(time.monotonic() - wall0, 1),
        "dir": str(out),
        "versions": {"labbench": LABBENCH_VERSION, "code": CODE_ID, "tending": TENDING_ID, "mujoco": mujoco.__version__},
    }
    meter = getattr(tracker.success, "swirl", None)
    if meter is not None:
        st = meter(world)
        summary["swirl"] = {"path_m": round(st["best_path"], 3), "turns": round(st["best_turns"], 2),
                            "max_tilt_deg": round(st["max_tilt_deg"], 2), "spilled": st["spilled"],
                            "swirled": st["swirled"]}
        spot = bench.specs["spot"]
        summary["bottle_end_mm_from_spot"] = round(
            float(np.linalg.norm(world.pos("bottle")[:2] - np.array([spot["x"], spot["y"]]))) * 1000, 1)
    over = getattr(tracker.success, "overlap", None)
    if over is not None:
        st = over(world)
        summary["overlap"] = {"window_s": round(st["steps"] * STEP_S, 2),
                              "swirling_s": round(st["steps_swirl"] * STEP_S, 2),
                              "plate_path_m": round(st["path"], 3), "plate_path_while_swirling_m": round(st["path_swirl"], 3),
                              "closed": st["closed"], "ok": bool(D.overlap_ok(st))}
    (out / "summary.json").write_text(json.dumps(summary, indent=2))
    env.close()
    say(f"expert: {task_name} seed {seed}: success={summary['success']}  steps "
        f"{summary['stages_reached']}/{summary['stages_total']}  sim {summary['sim_s']} s  -> {out}")
    return summary
