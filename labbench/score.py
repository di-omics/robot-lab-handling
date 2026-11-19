"""Scoring: what happened to the labware, read straight from the simulator.

A task is a list of stages (partial credit, like "tube lifted") and one success test (the bench is in the state
the scientist asked for, and the robot has let go). A stage counts once its test has held for a short time
without a break, so a flicker of contact noise never scores.
"""

from dataclasses import dataclass
from typing import Callable

import numpy as np

from .sim import STEP_S


class World:
    """Read-only view of the simulated bench for the scoring tests."""

    def __init__(self, env):
        self.env = env
        m = env.model
        roots = {m.body(f"{side}_base").id for side in ("left", "right")}
        ## Every geom that belongs to an arm or a gripper.
        self.robot_geoms = {g for g in range(m.ngeom) if m.body_rootid[m.geom_bodyid[g]] in roots}
        self._speed = {}
        self._last = {}

    @property
    def time(self):
        return float(self.env.data.time)

    def pos(self, name):
        """World position of a prop's origin (the centre of its underside)."""
        return self.env.data.body(name).xpos.copy()

    def rot(self, name):
        """A prop's rotation matrix; its third column is the prop's own up."""
        return self.env.data.body(name).xmat.reshape(3, 3).copy()

    def tilt_deg(self, name, reference=None):
        """Angle between a prop's up axis and vertical (or another prop's up axis), degrees."""
        up = self.rot(name)[:, 2]
        ref = np.array([0.0, 0.0, 1.0]) if reference is None else self.rot(reference)[:, 2]
        return float(np.degrees(np.arccos(np.clip(up @ ref, -1.0, 1.0))))

    def yaw_deg(self, name):
        """Heading of a prop's x axis about vertical, degrees."""
        x = self.rot(name)[:, 0]
        return float(np.degrees(np.arctan2(x[1], x[0])))

    def local(self, frame, point):
        """A world point in a prop's own frame."""
        return self.rot(frame).T @ (np.asarray(point) - self.pos(frame))

    def tcp(self, side):
        """World position of an arm's grasp point (between the fingers)."""
        return self.env.data.site(f"{side}_tcp").xpos.copy()

    def speed(self, name):
        """How fast a prop's origin moved over the last control step, m/s."""
        return self._speed.get(name, 0.0)

    def held(self, name):
        """Whether any part of a robot is touching the prop right now."""
        m, d = self.env.model, self.env.data
        body = m.body(name).id
        for i in range(d.ncon):
            c = d.contact[i]
            if c.dist > 0.001:
                continue
            a, b = c.geom1, c.geom2
            if (m.geom_bodyid[a] == body and b in self.robot_geoms) or (m.geom_bodyid[b] == body and a in self.robot_geoms):
                return True
        return False

    def released(self, name, max_speed=0.03):
        """The robot is not touching the prop and the prop is at rest."""
        return not self.held(name) and self.speed(name) < max_speed

    def track(self, names):
        """Update the speed estimates; call once after every control step."""
        for name in names:
            p = self.pos(name)
            if name in self._last:
                self._speed[name] = float(np.linalg.norm(p - self._last[name]) / STEP_S)
            self._last[name] = p


@dataclass
class Stage:
    """One step of partial credit."""

    name: str
    test: Callable[[World], bool]
    hold_s: float = 0.5


class Tracker:
    """Follows one take: which stages were reached and when, and whether the task ended in success."""

    SUCCESS_HOLD_S = 1.5

    def __init__(self, world, stages, success, movable, requires=()):
        self.world, self.stages, self.success, self.movable = world, stages, success, list(movable)
        ## Stages that must have been reached for the end state to count (for example: carried, not pushed).
        self.requires = tuple(requires)
        self._run = {s.name: 0 for s in stages}
        self.reached = {s.name: None for s in stages}
        self._success_run = 0
        self.success_at = None  # sim time when success had first held for SUCCESS_HOLD_S
        self.success_now = False
        self.t0 = world.time

    def prime(self):
        """Evaluate every test once at the start, so a test that remembers where things began sees the true start."""
        for s in self.stages:
            s.test(self.world)
        self.success(self.world)

    def update(self):
        w = self.world
        w.track(self.movable)
        now = round(w.time - self.t0, 2)
        for s in self.stages:
            self._run[s.name] = self._run[s.name] + 1 if s.test(w) else 0
            if self.reached[s.name] is None and self._run[s.name] * STEP_S >= s.hold_s:
                self.reached[s.name] = now
        self.success_now = bool(self.success(w)) and all(self.reached[n] is not None for n in self.requires)
        self._success_run = self._success_run + 1 if self.success_now else 0
        if self.success_at is None and self._success_run * STEP_S >= self.SUCCESS_HOLD_S:
            self.success_at = now

    def summary(self):
        hit = [n for n, t in self.reached.items() if t is not None]
        return {
            "stages": self.reached,
            "stages_reached": len(hit),
            "stages_total": len(self.stages),
            "progress": round(len(hit) / len(self.stages), 3) if self.stages else 0.0,
            "success": self.success_at is not None,
            "success_at_s": self.success_at,
            "success_at_end": self.success_now,
        }


# Shared tests, used by several tasks.


def lifted(name, start_z, by=0.03):
    """The prop's underside is at least `by` above where it started."""
    return lambda w: w.pos(name)[2] > start_z + by


def in_rack_well(tube, rack, rack_spec, tol=0.010):
    """The tube stands in one of the rack's wells, let go and at rest."""

    def test(w):
        p = w.local(rack, w.pos(tube))
        if not (-0.004 < p[2] < rack_spec["floor"] + 0.012):
            return False
        if w.tilt_deg(tube, rack) > 15:
            return False
        if not any(abs(p[0] - wx) < tol and abs(p[1] - wy) < tol for wx, wy in rack_spec["wells"]):
            return False
        return w.released(tube)

    return test


def inside_box(name, spec, margin=0.0, top=None):
    """The prop's origin is inside a tray or bin footprint and below its rim, let go and at rest."""

    def test(w):
        p = w.pos(name)
        hx, hy = spec["half"]
        if abs(p[0] - spec["x"]) > hx - margin or abs(p[1] - spec["y"]) > hy - margin:
            return False
        if p[2] > (spec["rim"] if top is None else top):
            return False
        return w.released(name)

    return test


def resting_on(name, spec, margin=0.005, max_tilt=12.0, z_tol=0.012):
    """The prop stands on a platform or mat: inside its footprint, underside at its top, upright, let go, at rest."""

    def test(w):
        p = w.pos(name)
        hx, hy = spec["half"]
        if abs(p[0] - spec["x"]) > hx - margin or abs(p[1] - spec["y"]) > hy - margin:
            return False
        if abs(p[2] - spec["top"]) > z_tol or w.tilt_deg(name) > max_tilt:
            return False
        return w.released(name)

    return test


def over(name, spec, margin=0.0, clear=0.01):
    """The prop is above a fixed target's footprint and clear of its top (in the hand or just let go)."""

    def test(w):
        p = w.pos(name)
        hx, hy = spec["half"]
        return abs(p[0] - spec["x"]) < hx - margin and abs(p[1] - spec["y"]) < hy - margin and p[2] > spec["top"] + clear

    return test


def seated_in_nest(plate, plate_spec, nest, nest_spec, table_z):
    """The plate sits flat in the tray's pocket, the right way round, let go and at rest."""
    slack_x = nest_spec["half"][0] - plate_spec["half"][0] + 0.002
    slack_y = nest_spec["half"][1] - plate_spec["half"][1] + 0.002
    floor = nest_spec["floor"] - table_z

    def test(w):
        p = w.local(nest, w.pos(plate))
        if abs(p[0]) > slack_x or abs(p[1]) > slack_y or not (floor - 0.002 < p[2] < floor + 0.006):
            return False
        if w.tilt_deg(plate) > 5:
            return False
        turn = (w.yaw_deg(plate) - w.yaw_deg(nest) + 90) % 180 - 90
        return abs(turn) < 8 and w.released(plate)

    return test


def stacked_on(top, bottom, bottom_spec, table_z, xy_tol=0.025, max_turn=12.0):
    """`top` sits squarely on `bottom`, the same way round (or turned half a turn), and `bottom` sits on the
    table; both let go and at rest."""

    def test(w):
        if abs(w.pos(bottom)[2] - table_z) > 0.006:
            return False
        rel = w.local(bottom, w.pos(top))
        if abs(rel[0]) > xy_tol or abs(rel[1]) > xy_tol or abs(rel[2] - bottom_spec["height"]) > 0.008:
            return False
        turn = (w.yaw_deg(top) - w.yaw_deg(bottom) + 90) % 180 - 90
        if abs(turn) > max_turn:
            return False
        if w.tilt_deg(top) > 8 or w.tilt_deg(bottom) > 8:
            return False
        return w.released(top) and w.released(bottom)

    return test


def lifted_level(name, start_z, by=0.02, max_tilt=15.0):
    """Lifted and still level: what two hands (or one very good one) give you."""
    return lambda w: w.pos(name)[2] > start_z + by and w.tilt_deg(name) < max_tilt


def _to_axis(point, a, b):
    """Distance from a point to the segment a-b."""
    ab = b - a
    t = np.clip((point - a) @ ab / (ab @ ab), 0.0, 1.0)
    return float(np.linalg.norm(point - (a + t * ab)))


def in_hand_of(name, spec, side, table_z, near=0.035, far=0.09, lift=0.03):
    """The prop is off the table at one arm's grasp point, and the other arm's grasp point is away from it."""
    other = "left" if side == "right" else "right"

    def test(w):
        a = w.pos(name)
        b = a + w.rot(name)[:, 2] * spec["height"]
        return a[2] > table_z + lift and _to_axis(w.tcp(side), a, b) < near and _to_axis(w.tcp(other), a, b) > far

    return test


def on_shelf(plate, hotel, level, out_front=0.03, side=0.012):
    """The plate lies on one shelf of the hotel (the shelf top is at world height `level`): lined up between the
    side walls, at most `out_front` short of fully in, flat, let go and at rest."""

    def test(w):
        p = w.pos(plate)
        if abs(p[0] - hotel["x"]) > side or not (hotel["y"] - 0.012 < p[1] < hotel["y"] + out_front):
            return False
        if not (level - 0.004 < p[2] < level + 0.008) or w.tilt_deg(plate) > 6:
            return False
        return w.released(plate)

    return test


def lined_up_at_shelf(plate, hotel, level, reach=0.22):
    """The plate is in front of the hotel at the height of one shelf, ready to slide in (or part way in)."""

    def test(w):
        p = w.pos(plate)
        return abs(p[0] - hotel["x"]) < 0.03 and hotel["y"] + 0.03 < p[1] < hotel["y"] + reach and abs(p[2] - level) < 0.025

    return test


def inside_footprint(name, spec, slack_x, slack_y, z_tol=0.012, max_tilt=8.0):
    """A wide prop (a rack) sits on the floor of a box: its centre within the slack the box leaves, flat, let go."""

    def test(w):
        p = w.pos(name)
        if abs(p[0] - spec["x"]) > slack_x or abs(p[1] - spec["y"]) > slack_y:
            return False
        if abs(p[2] - spec["floor"]) > z_tol or w.tilt_deg(name) > max_tilt:
            return False
        return w.released(name)

    return test
