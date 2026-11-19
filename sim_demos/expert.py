"""A scripted expert for the plate_to_tray chore.

The left hand points straight down, opens fully, comes down over the deep-well plate with its fingers across the
plate's short side (85.5 mm, inside a 93.7 mm finger gap at full open), closes, lifts, carries the plate over the
black tray, lowers it into the pocket and lets go. The right arm stays at home.

How it moves: waypoints for the grasp point (the `left_tcp` site), straight lines between them with a smooth
(minimum jerk) time profile, and inverse kinematics on the simulator's own model at every 50 ms control step. The
joint targets go through env.step under the real physics, exactly as a model's actions would. Nothing is moved by
hand: the plate moves only because the fingers hold it.

What a real robot would not have: the expert reads the true poses of the plate and the tray from the simulator,
and before lowering it reads where the plate actually sits in the hand and corrects for it.
"""

import numpy as np
import mujoco

from labbench.sim import HOME, STEP_S, TABLE_Z

## Grasp point height above the plate's underside when the fingers close. The finger tips reach 10 mm past the grasp
## point, so the tips stop 12 mm above the table and the pads take the walls from 12 mm up to the top (44 mm).
GRASP_Z = 0.022
## How high the plate is carried, underside above the table (varied by 1 cm per episode).
CARRY_Z = 0.09
## Gap between the plate's underside and the tray floor when the fingers open.
RELEASE_GAP = 0.003
## The gripper command that holds the plate. Each finger is a position servo (1000 N/m, at most 22 N). Commanding 0
## saturates both fingers at 22 N, and two equal saturated pushes leave the plate free to drift sideways until one
## finger reaches its stop (4.4 mm in a test), so the fingers can no longer open clear of it. Commanding 0.6 grips
## with about 15 N per finger, below the limit, so the two fingers act as springs that keep the plate centred.
GRIP_CLOSED = 0.6


def down_rot(phi):
    """The hand pointing straight down (grasp point z axis = world -z), its fingers closing along (-sin phi, cos phi, 0).
    With phi = the plate's yaw, the fingers close across the plate's short side."""
    c, s = np.cos(phi), np.sin(phi)
    return np.array([[-c, -s, 0.0], [-s, c, 0.0], [0.0, 0.0, -1.0]])


def min_jerk(s):
    """Smooth 0 to 1 time profile: zero speed and acceleration at both ends."""
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
    theta = np.arccos(dot)
    return (np.sin((1 - t) * theta) * q0 + np.sin(t * theta) * q1) / np.sin(theta)


def yaw_of(rot):
    return float(np.arctan2(rot[1, 0], rot[0, 0]))


def wrap(a):
    return (a + np.pi) % (2 * np.pi) - np.pi


class ArmIK:
    """Damped least squares IK for one arm's grasp point, on a private copy of the simulator state (the live
    simulation is never touched). Uses the simulator's own kinematics, so there is no model mismatch."""

    def __init__(self, env, side):
        m = env.model
        self.m, self.side = m, side
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
        """Grasp point position and rotation for six joint angles."""
        self.d.qpos[self.qadr] = q
        mujoco.mj_kinematics(self.m, self.d)
        mujoco.mj_comPos(self.m, self.d)
        return self.d.site_xpos[self.site].copy(), self.d.site_xmat[self.site].reshape(3, 3).copy()

    def solve(self, pos, rot, q0, iters=200, tol_pos=1e-4, tol_rot=1e-3, damping=0.02):
        """Joint angles that put the grasp point at `pos` with rotation `rot`, starting from `q0`.
        @return (q, error in metres, error in radians)."""
        q = np.clip(np.asarray(q0, dtype=float).copy(), self.lo, self.hi)
        ep = er = None
        for _ in range(iters):
            p, r = self.fk(q)
            ep = pos - p
            er = 0.5 * sum(np.cross(r[:, i], rot[:, i]) for i in range(3))
            if np.linalg.norm(ep) < tol_pos and np.linalg.norm(er) < tol_rot:
                break
            mujoco.mj_jacSite(self.m, self.d, self._jp, self._jr, self.site)
            jac = np.vstack([self._jp[:, self.dadr], self._jr[:, self.dadr]])
            err = np.r_[ep, er]
            dq = jac.T @ np.linalg.solve(jac @ jac.T + damping ** 2 * np.eye(6), err)
            biggest = np.abs(dq).max()
            if biggest > 0.15:
                dq *= 0.15 / biggest
            q = np.clip(q + dq, self.lo, self.hi)
        return q, float(np.linalg.norm(ep)), float(np.linalg.norm(er))


class ExpertFailed(RuntimeError):
    """The expert could not plan a move (no IK solution); the episode is dropped."""


class PlateToTray:
    """The expert for `plate_to_tray`. Iterate actions(bench) for (left, right) joint targets, one per 50 ms step;
    the caller runs env.step with them. `phase` names what the expert is doing, for the logs."""

    side = "left"

    def __init__(self, bench, rng=None):
        """@param rng Optional numpy Generator: varies speed, hover, grasp and carry heights a little per episode, so
            the demonstrations are not 50 copies of one motion. None gives the middle values."""
        self.bench, self.env, self.world = bench, bench.env, bench.world
        self.ik = ArmIK(self.env, self.side)
        pick = (lambda lo, hi: float(rng.uniform(lo, hi))) if rng is not None else (lambda lo, hi: (lo + hi) / 2)
        self.speed = pick(0.85, 1.15)  # 1.0 = the durations written below
        self.hover_z = pick(0.06, 0.08)
        self.grasp_z = pick(GRASP_Z - 0.002, GRASP_Z + 0.002)
        self.carry_z = pick(CARRY_Z - 0.01, CARRY_Z + 0.01)
        self.settings = {"speed": round(self.speed, 3), "hover_mm": round(self.hover_z * 1000, 1),
                         "grasp_mm": round(self.grasp_z * 1000, 1), "carry_mm": round(self.carry_z * 1000, 1)}
        self.q = np.asarray(self.env.state()[self.side][:6], dtype=float)  # last joint command, warm start for IK
        self.grip = 1.0
        self.phase = "start"
        self.log = []

    # Motions. Each yields (left, right) targets, one per control step.

    def _cmd(self):
        left = np.r_[self.q, self.grip]
        return left, HOME.copy()

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
            raise ExpertFailed(f"{self.phase}: no IK solution (off by {ep * 1000:.1f} mm, {np.degrees(er):.1f} deg)")
        return q

    def joint_move(self, q_goal, seconds):
        q0 = self.q.copy()
        n = max(1, round(seconds / self.speed / STEP_S))
        for i in range(1, n + 1):
            self.q = q0 + (q_goal - q0) * min_jerk(i / n)
            yield self._cmd()

    def line_move(self, pos_goal, rot_goal, seconds):
        """Straight line for the grasp point, rotation turned smoothly, IK at every step."""
        p0, r0 = self.ik.fk(self.q)
        q0, q1 = mat_quat(r0), mat_quat(rot_goal)
        n = max(1, round(seconds / self.speed / STEP_S))
        for i in range(1, n + 1):
            s = min_jerk(i / n)
            self.q = self._solve(p0 + (pos_goal - p0) * s, quat_mat(slerp(q0, q1, s)))
            yield self._cmd()

    def gripper(self, value, seconds, hold_s=0.3):
        """Open or close the fingers over `seconds`, then wait `hold_s`. A one-step close drives each finger at its
        full 22 N and slams it into the plate at about 1.5 m/s (3 mm per 2 ms physics step), fast enough to sink
        into the plate's 4 mm wall and hook its top edge; a ramp touches the wall at a few cm/s."""
        start = self.grip
        n = max(1, round(seconds / STEP_S))
        for i in range(1, n + 1):
            self.grip = float(start + (value - start) * i / n)
            yield self._cmd()
        yield from self.hold(hold_s)

    def hold(self, seconds):
        for _ in range(max(1, round(seconds / STEP_S))):
            yield self._cmd()

    # The chore.

    def actions(self):
        w = self.world
        tray = self.bench.specs["tray"]
        plate_pos = w.pos("plate")
        plate_yaw = np.radians(w.yaw_deg("plate"))
        # The fingers close along (-sin phi, cos phi): phi = plate yaw, or half a turn more, whichever keeps the
        # last wrist joint nearer the middle of its range.
        top = plate_pos[2] + 0.044
        hover = np.r_[plate_pos[:2], top + self.hover_z]
        options = []
        for phi in (plate_yaw, plate_yaw + np.pi):
            phi = wrap(phi)
            try:
                q = self._solve(hover, down_rot(phi), seeds=(np.array([0.0, 1.0, 1.0, 0.0, 0.0, 0.0]),
                                                           np.array([0.0, 1.2, 1.2, -0.5, 0.0, 0.0])))
            except ExpertFailed:
                continue
            options.append((abs(q[5]), phi, q))
        if not options:
            raise ExpertFailed("no IK solution above the plate")
        _, phi, q_hover = min(options, key=lambda o: o[0])

        self.phase = "reach"
        yield from self.joint_move(q_hover, 2.4)
        self.phase = "descend"
        grasp = np.r_[plate_pos[:2], plate_pos[2] + self.grasp_z]
        yield from self.line_move(np.r_[grasp[:2], top + 0.02], down_rot(phi), 1.0)
        yield from self.line_move(grasp, down_rot(phi), 1.2)
        yield from self.hold(0.3)
        self.phase = "close"
        yield from self.gripper(GRIP_CLOSED, 0.6)
        self.phase = "lift"
        lift = np.r_[grasp[:2], plate_pos[2] + self.grasp_z + self.carry_z]
        yield from self.line_move(lift, down_rot(phi), 1.4)
        yield from self.hold(0.3)

        # Where the plate sits in the hand now (it may have shifted while the fingers closed).
        p_tcp, r_tcp = self.ik.fk(self.q)  # commanded hand pose
        real_tcp = self.env.data.site(f"{self.side}_tcp").xpos.copy()
        real_rot = self.env.data.site(f"{self.side}_tcp").xmat.reshape(3, 3).copy()
        plate_in_hand_pos = real_rot.T @ (w.pos("plate") - real_tcp)
        plate_in_hand_rot = real_rot.T @ w.rot("plate")
        self.log.append({"plate_in_hand_mm": (plate_in_hand_pos * 1000).round(1).tolist(),
                         "tcp_lag_mm": ((p_tcp - real_tcp) * 1000).round(1).tolist()})

        # The plate's goal: centred on the tray, its long side along the tray's (either way round), underside just
        # above the tray floor. The hand goal follows from where the plate sits in the hand.
        plate_yaw_now = yaw_of(w.rot("plate"))
        goal_yaw = tray["yaw"] + np.round(wrap(plate_yaw_now - tray["yaw"]) / np.pi) * np.pi
        c, s = np.cos(goal_yaw), np.sin(goal_yaw)
        goal_plate_rot = np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])
        hand_rot = goal_plate_rot @ plate_in_hand_rot.T
        offset = hand_rot @ plate_in_hand_pos

        def hand_for(plate_xyz):
            return plate_xyz - offset

        place = np.r_[tray["x"], tray["y"], tray["floor"] + RELEASE_GAP]
        above = place + np.r_[0.0, 0.0, 0.06]
        self.phase = "carry"
        yield from self.line_move(hand_for(above + np.r_[0, 0, 0.02]), hand_rot, 2.6)
        yield from self.hold(0.3)
        # Correct for the steady sag of the arm under the plate's weight: aim the plate, not the hand.
        for _ in range(2):
            err = (above + np.r_[0, 0, 0.02]) - w.pos("plate")
            target = self.ik.fk(self.q)[0] + np.r_[err[:2], 0.0]
            yield from self.line_move(target, hand_rot, 0.5)
            yield from self.hold(0.2)
        trim = self.ik.fk(self.q)[0] - hand_for(above + np.r_[0, 0, 0.02])
        self.log.append({"carry_trim_mm": (trim * 1000).round(1).tolist()})
        self.phase = "lower"
        yield from self.line_move(hand_for(above) + trim, hand_rot, 0.8)
        yield from self.line_move(hand_for(place) + trim, hand_rot, 1.6)
        yield from self.hold(0.3)
        self.phase = "release"
        yield from self.gripper(1.0, 0.6)
        self.phase = "retreat"
        up = self.ik.fk(self.q)[0] + np.r_[0.0, 0.0, 0.08]
        yield from self.line_move(up, hand_rot, 1.2)
        self.phase = "home"
        yield from self.joint_move(HOME[:6].copy(), 2.2)
        self.phase = "rest"
        while True:
            yield from self.hold(STEP_S)
