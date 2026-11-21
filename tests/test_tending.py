"""Checks for the instrument tending chores (tending/), in the style of tests/test_tasks.py. No model, no network.

Run: python -m unittest -v tests.test_tending   (from the project folder)
The scripted expert checks take several minutes and run only with TENDING_EXPERT=1 in the environment.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path

import mujoco
import numpy as np

import labbench.take as lt
import tending
from labbench.oracle import Step, at_rest_problems, place, play, yaw_tilt_quat
from labbench.sim import HOME, STEP_S, TABLE_Z
from labbench.tasks import TASKS
from tending import dispenser as D
from tending.__main__ import show_aimed, take
from tending.expert import ArmIK, BottleSwirler, PlateMover, down_rot, min_jerk, play_expert

## The 2 plate chores.
NAMES = ("dispenser_plate_in", "dispenser_plate_out")
ALL = NAMES + ("cell_bottle_swirl", "plate_in_with_swirl")
MIN_TRAPS = {"dispenser_plate_in": 6, "dispenser_plate_out": 7, "cell_bottle_swirl": 8, "plate_in_with_swirl": 9}
SEEDS = (0, 1, 2)
LABBENCH_CODE = "92c256eb309b"
## The colliding geoms of the dispenser and carrier bodies on seed 0 of dispenser_plate_in: (body, name, geom type,
## size, pos, contype, conaffinity, friction). The drawn parts must leave them exactly as they are.
EXPECTED_COLLIDERS = [
    ("dispenser", "dispenser_deck", 6, [0.21, 0.16, 0.027], [0.0, -0.09025, 0.027], 1, 1, [1.6, 0.01, 0.001]),
    ("dispenser", "dispenser_housing", 6, [0.21, 0.062625, 0.18455], [0.0, -0.187625, 0.27545], 1, 1,
     [1.6, 0.01, 0.001]),
    ("dispenser", "dispenser_side_l", 6, [0.06455, 0.062625, 0.01845], [0.14545, -0.187625, 0.07245], 1, 1,
     [1.6, 0.01, 0.001]),
    ("dispenser", "dispenser_side_r", 6, [0.06455, 0.062625, 0.01845], [-0.14545, -0.187625, 0.07245], 1, 1,
     [1.6, 0.01, 0.001]),
    ("dispenser", "dispenser_slot_back", 6, [0.0809, 0.002625, 0.01845], [0.0, -0.247625, 0.07245], 1, 1,
     [1.6, 0.01, 0.001]),
    ("carrier", "carrier_floor", 6, [0.0759, 0.05475, 0.003], [0.0, 0.0, 0.057], 1, 1, [1.6, 0.01, 0.001]),
    ("carrier", "", 6, [0.008, 0.002, 0.0025], [-0.0619, -0.04675, 0.0625], 1, 1, [1.6, 0.01, 0.001]),
    ("carrier", "", 6, [0.002, 0.008, 0.0025], [-0.0679, -0.04075, 0.0625], 1, 1, [1.6, 0.01, 0.001]),
    ("carrier", "", 6, [0.008, 0.002, 0.0025], [-0.0619, 0.04675, 0.0625], 1, 1, [1.6, 0.01, 0.001]),
    ("carrier", "", 6, [0.002, 0.008, 0.0025], [-0.0679, 0.04075, 0.0625], 1, 1, [1.6, 0.01, 0.001]),
    ("carrier", "", 6, [0.008, 0.002, 0.0025], [0.0619, -0.04675, 0.0625], 1, 1, [1.6, 0.01, 0.001]),
    ("carrier", "", 6, [0.002, 0.008, 0.0025], [0.0679, -0.04075, 0.0625], 1, 1, [1.6, 0.01, 0.001]),
    ("carrier", "", 6, [0.008, 0.002, 0.0025], [0.0619, 0.04675, 0.0625], 1, 1, [1.6, 0.01, 0.001]),
    ("carrier", "", 6, [0.002, 0.008, 0.0025], [0.0679, 0.04075, 0.0625], 1, 1, [1.6, 0.01, 0.001]),
]
## Traps of plate_in_with_swirl in which the bottle is not kept swirling while the plate is on its way (the arms
## take turns, or the bottle only shakes or slides): every other part of the pass rule holds at the end, so the
## together rule alone must be what fails them.
TURN_TAKING = ("bottle swirled first, plate loaded afterwards with the bottle resting",
               "plate parked on the deck while the bottle swirls, then loaded with the bottle resting",
               "plate lifted and set back on the mat, bottle swirled, then plate loaded with the bottle resting",
               "plate lifted while the bottle swirls, then carried slowly with the bottle resting",
               "bottle swirled first, then only shaken in a straight line while the plate is carried",
               "plate carried while the bottle swirls, then left hanging over the nest with the bottle resting",
               "bottle swirled first, then slid in circles on the instrument deck while the plate is carried")


def drive(bench, q_from, q_to, seconds, grip=1.0):
    """Move the left arm in joint space (right arm home), scoring every step.
    @return Whether any robot part touched the plate on any step."""
    n = round(seconds / STEP_S)
    touched = False
    for i in range(1, n + 1):
        q = q_from + (q_to - q_from) * min_jerk(i / n)
        bench.env.step(np.r_[q, grip], HOME)
        bench.tracker.update()
        touched = touched or bench.world.held("plate")
    return touched


def place_spot(name, specs):
    """(x, y, height of the surface) where the chore's plate belongs."""
    if name == "dispenser_plate_in":
        return specs["nest"]["x"], specs["nest"]["y"], specs["nest"]["floor"]
    return specs["mat"]["x"], specs["mat"]["y"], TABLE_Z


def let_go_above(name, specs, height):
    """The oracle's lift and carry, then the plate held `height` above its place for 0.5 s and let go."""
    x, y, f = place_spot(name, specs)
    return TASKS[name].oracle(specs)[:2] + [
        Step("plate", lambda w: (np.array([x, y, f + height]), yaw_tilt_quat(0.0)), pin_s=0.5, settle_s=3.0)]


class SlowMover(PlateMover):
    """The expert's left arm with its carry and lowering slowed by `factor` (the plate moves under 2.6 mm a step at
    a factor of 4)."""

    def __init__(self, bench, factor):
        super().__init__(bench)
        self.factor = factor

    def line_move(self, pos_goal, rot_goal, seconds):
        if self.phase in ("carry", "lower"):
            seconds *= self.factor
        yield from super().line_move(pos_goal, rot_goal, seconds)


def two_arms(seed, factor, lead_s, swirl_while):
    """Both arms of the expert on plate_in_with_swirl, under the real physics, with the plate carried `factor` times
    slower, the left arm starting after `lead_s`, and the right arm swirling for as long as the left arm's phase is
    in `swirl_while` (and at least 5 turns). Stops 1 s after success, or 2 s after both arms are at rest.
    @return The bench, still open."""
    bench = lt.set_bench("plate_in_with_swirl", seed)
    env, world, tracker = bench.env, bench.world, bench.tracker
    mover, swirler = SlowMover(bench, factor), BottleSwirler(bench)

    def left():
        for _ in range(round(lead_s / STEP_S)):
            yield HOME.copy()
        yield from mover.actions("plate_in_with_swirl")

    plans = (left(), swirler.swirl(keep_going=lambda: mover.phase in swirl_while, min_turns=5))
    tracker.t0, rested = world.time, 0
    while world.time - tracker.t0 < bench.task.seconds:
        env.step(*(next(plan) for plan in plans))
        tracker.update()
        rested = rested + 1 if mover.phase == swirler.phase == "rest" else 0
        if tracker.success_at is not None and world.time - tracker.t0 - tracker.success_at >= 1.0:
            break
        if rested * STEP_S >= 2.0:
            break
    return bench


def end_state_good(name, bench):
    """Every part of the success test except the drop rule holds right now."""
    w, n = bench.world, bench.specs["nest"]
    if name == "dispenser_plate_in":
        return D.seated_strict("plate", n)(w) and D.hands_clear(n)(w)
    return D.on_mat_flat("plate", bench.specs["mat"])(w) and D.carrier_empty("plate", n)(w)


class TendingChecks(unittest.TestCase):
    def test_code_id_unchanged(self):
        self.assertEqual(lt.CODE_ID, LABBENCH_CODE)
        self.assertEqual(lt._fingerprint(), LABBENCH_CODE)

    def test_registered(self):
        for name in ALL:
            self.assertIn(name, TASKS)
            self.assertEqual(TASKS[name].family, "instrument tending")
        self.assertRegex(tending.TENDING_ID, r"^[0-9a-f]{12}$")
        self.assertEqual(tending.TENDING_ID, tending._fingerprint())

    def test_scene_is_still_at_rest(self):
        for name in ALL:
            for seed in SEEDS:
                with self.subTest(task=name, seed=seed):
                    bench = lt.set_bench(name, seed)
                    try:
                        self.assertEqual(at_rest_problems(bench), [])
                    finally:
                        bench.env.close()

    def test_oracle_scores_success(self):
        for name in ALL:
            task = TASKS[name]
            for seed in SEEDS:
                with self.subTest(task=name, seed=seed):
                    bench = lt.set_bench(name, seed)
                    try:
                        self.assertEqual(play(bench, task.oracle(bench.specs)), [])
                        self.assertTrue(bench.tracker.summary()["success"])
                        self.assertEqual(bench.tracker.summary()["progress"], 1.0)
                    finally:
                        bench.env.close()

    def test_traps_do_not_score_success(self):
        for name in ALL:
            task = TASKS[name]
            bench = lt.set_bench(name, 0)
            traps = list(task.traps(bench.specs))
            bench.env.close()
            self.assertGreaterEqual(len(traps), MIN_TRAPS[name])
            for trap in traps:
                for seed in SEEDS[:2]:
                    with self.subTest(task=name, trap=trap, seed=seed):
                        bench = lt.set_bench(name, seed)
                        try:
                            self.assertEqual(play(bench, task.traps(bench.specs)[trap]), [])
                            self.assertFalse(bench.tracker.summary()["success"])
                        finally:
                            bench.env.close()

    def _hand_parked(self, seed, target_offset, phi):
        """Lift the plate and pass it over the carrier (the oracle's first 2 steps, so the required stages are
        reached), set it aside on the table, park the left hand at nest + target_offset, seat the plate by hand,
        hold 3 s, then send the hand home.
        @return (bench, tcp in travel, any pad in travel, summary with the hand parked, summary after going home)."""
        bench = lt.set_bench("dispenser_plate_in", seed)
        env, world, nest = bench.env, bench.world, bench.specs["nest"]
        self.assertEqual(play(bench, TASKS["dispenser_plate_in"].oracle(bench.specs)[:2]), [])
        place(env, "plate", np.array([-0.15, 0.10, D.TABLE_Z + 0.002]), yaw_tilt_quat(0.0))
        ik = ArmIK(env, "left")
        target = np.array([nest["x"], nest["y"], nest["floor"]]) + np.asarray(target_offset)
        q, ep, _ = ik.solve(target, down_rot(phi), np.array([0.0, 1.0, 1.0, 0.0, 0.0, 0.0]))
        self.assertLess(ep, 1e-3)
        q0 = np.asarray(env.state()["left"][:6], float)
        drive(bench, q0, q, 3.0)
        tcp_in = D.in_travel(nest, world.tcp("left"))
        pad_in = any(D.in_travel(nest, p) for p in D.hand_points(world)[2:])
        place(env, "plate", np.array([nest["x"], nest["y"], nest["floor"] + 0.002]), yaw_tilt_quat(0.0))
        drive(bench, q, q, 3.0)
        self.assertFalse(world.held("plate"))
        parked = bench.tracker.summary()
        drive(bench, q, HOME[:6].copy(), 3.0)
        drive(bench, HOME[:6].copy(), HOME[:6].copy(), 2.0)
        return bench, tcp_in, pad_in, parked, bench.tracker.summary()

    def test_hand_in_travel_blocks_success(self):
        """A seated plate with the left tcp inside the carrier's travel box does not pass until the hand leaves."""
        for seed in SEEDS[:2]:
            with self.subTest(seed=seed):
                bench, tcp_in, _, parked, home = self._hand_parked(seed, (0.086, 0.0, 0.025), 0.0)
                try:
                    self.assertTrue(tcp_in)
                    self.assertIsNotNone(parked["stages"]["plate_seated"])
                    self.assertFalse(parked["success"])
                    self.assertTrue(home["success"])
                finally:
                    bench.env.close()

    def test_finger_in_travel_blocks_success(self):
        """The tcp just outside the box but fingertip pads inside it still blocks success."""
        for seed in SEEDS[:2]:
            with self.subTest(seed=seed):
                bench, tcp_in, pad_in, parked, home = self._hand_parked(seed, (0.0, 0.078, 0.030), 0.0)
                try:
                    self.assertFalse(tcp_in)
                    self.assertTrue(pad_in)
                    self.assertIsNotNone(parked["stages"]["plate_seated"])
                    self.assertFalse(parked["success"])
                    self.assertTrue(home["success"])
                finally:
                    bench.env.close()

    def test_release_height_rule(self):
        """A plate held 15 mm above its place and let go passes; 30 mm is a drop (the rule is 20 mm), both chores."""
        for name in NAMES:
            for seed in SEEDS[:2]:
                for height, ok in ((0.015, True), (0.03, False)):
                    with self.subTest(task=name, seed=seed, height=height):
                        bench = lt.set_bench(name, seed)
                        try:
                            self.assertEqual(play(bench, let_go_above(name, bench.specs, height)), [])
                            self.assertTrue(end_state_good(name, bench))
                            self.assertEqual(bench.tracker.summary()["success"], ok)
                        finally:
                            bench.env.close()

    def test_drop_then_touch_fails(self):
        """Drop the plate from 5 cm onto its place, touch its top with the open left fingertips, send the arm home:
        the drop still stands, though the end state is otherwise right."""
        for name in NAMES:
            for seed in SEEDS[:2]:
                with self.subTest(task=name, seed=seed):
                    bench = lt.set_bench(name, seed)
                    try:
                        self.assertEqual(play(bench, let_go_above(name, bench.specs, 0.05)), [])
                        self.assertFalse(bench.tracker.summary()["success"])
                        x, y, _ = place_spot(name, bench.specs)
                        top = bench.world.pos("plate")[2] + D.PLATE_H
                        ik = ArmIK(bench.env, "left")
                        # an IK start away from HOME, so the tap lands on the plate
                        start = np.array([0.0, 1.0, 1.0, 0.0, 0.0, 0.0])
                        q_up, e1, _ = ik.solve(np.array([x, y, top + 0.06]), down_rot(np.pi / 2), start)
                        q_tap, e2, _ = ik.solve(np.array([x, y, top + 0.0085]), down_rot(np.pi / 2), q_up)
                        self.assertLess(max(e1, e2), 2e-3)
                        drive(bench, np.asarray(bench.env.state()["left"][:6], float), q_up, 2.0)
                        touched = drive(bench, q_up, q_tap, 1.5) | drive(bench, q_tap, q_tap, 0.3)
                        drive(bench, q_tap, q_up, 1.0)
                        drive(bench, q_up, HOME[:6].copy(), 2.0)
                        drive(bench, HOME[:6].copy(), HOME[:6].copy(), 2.5)
                        self.assertTrue(touched)
                        self.assertTrue(end_state_good(name, bench))
                        self.assertFalse(bench.tracker.summary()["success"])
                    finally:
                        bench.env.close()

    def test_arm_release_height(self):
        """The scripted expert with its gripper opened 10 mm above the place passes; 30 mm above fails as a drop
        but still earns the last stage. Seed 0, both chores, the real arm and gripper."""
        with tempfile.TemporaryDirectory() as tmp:
            for name in NAMES:
                for gap, ok in ((0.010, True), (0.030, False)):
                    with self.subTest(task=name, gap=gap):
                        s = play_expert(name, 0, tmp, video=False, say=lambda *a: None, release_gap=gap)
                        self.assertIsNone(s["error"])
                        self.assertIsNotNone(list(s["stages"].values())[-1])
                        self.assertEqual(s["success"], ok)

    def test_show_camera_aimed_and_restored(self):
        original = lt.set_bench
        with show_aimed():
            bench = lt.set_bench("dispenser_plate_in", 0, show=True)
            try:
                m = bench.env.model
                nest = bench.specs["nest"]
                self.assertTrue(np.allclose(m.cam_pos[m.camera("show").id],
                                            (D.SHOW_POS[0], D.SHOW_POS[1], D.TABLE_Z + D.SHOW_POS[2])))
                self.assertTrue(np.allclose(m.body_pos[m.body("show_look").id][:2],
                                            (nest["x"] + D.SHOW_LOOK[0], nest["y"] + D.SHOW_LOOK[1])))
                self.assertAlmostEqual(float(m.cam_fovy[m.camera("show").id]), D.SHOW_FOVY)
            finally:
                bench.env.close()
        self.assertIs(lt.set_bench, original)

    def test_take_hold_stamps(self):
        with tempfile.TemporaryDirectory() as tmp:
            summary = take("dispenser_plate_out", 0, policy="hold", seconds=2, out_root=tmp, show=True,
                           say=lambda *a: None)
            saved = json.loads((Path(summary["dir"]) / "summary.json").read_text())
            self.assertIsNone(saved["error"])
            self.assertEqual(saved["versions"]["tending"], tending.TENDING_ID)
            self.assertEqual(saved["versions"]["code"], LABBENCH_CODE)
            self.assertFalse(saved["success"])
            self.assertTrue((Path(summary["dir"]) / "show.mp4").stat().st_size > 0)

    def test_turn_taking_fails_only_on_overlap(self):
        """In the turn-taking, shaking and sliding traps the plate ends seated, the bottle swirled and home, so only
        the together rule stops them; the oracle, with both moving together, passes it."""
        task = TASKS["plate_in_with_swirl"]
        for seed in SEEDS[:2]:
            for trap in (None,) + TURN_TAKING:
                with self.subTest(trap=trap, seed=seed):
                    bench = lt.set_bench("plate_in_with_swirl", seed)
                    try:
                        steps = task.oracle(bench.specs) if trap is None else task.traps(bench.specs)[trap]
                        self.assertEqual(play(bench, steps), [])
                        w, success = bench.world, bench.tracker.success
                        spot = (bench.specs["spot"]["x"], bench.specs["spot"]["y"])
                        self.assertTrue(D.seated_strict("plate", bench.specs["nest"])(w))
                        self.assertTrue(D.bottle_home(spot)(w))
                        self.assertTrue(success.swirl(w)["swirled"])
                        self.assertEqual(D.overlap_ok(success.overlap(w)), trap is None)
                        self.assertEqual(bench.tracker.summary()["success"], trap is None)
                    finally:
                        bench.env.close()

    def test_deck_slide_is_not_a_hold(self):
        """Sliding the bottle in circles on the instrument's raised deck fails because the bottle rests on it: with
        the support test switched off, the same script would pass (seed 0)."""
        trap = "bottle slid in circles on the instrument deck, never lifted"
        original = D.supported
        for support in (True, False):
            with self.subTest(support=support):
                if not support:
                    D.supported = lambda w, name: False
                try:
                    bench = lt.set_bench("cell_bottle_swirl", 0)
                    try:
                        problems = play(bench, TASKS["cell_bottle_swirl"].traps(bench.specs)[trap])
                        self.assertEqual(problems, [] if support else ["step 151 (bottle): success is True, expected False"])
                        self.assertEqual(bench.tracker.summary()["success"], not support)
                    finally:
                        bench.env.close()
                finally:
                    D.supported = original

    def test_arms_taking_turns_with_a_slow_carry_fail(self):
        """The real arms (seed 0): the right arm swirls only until the left arm's carry starts, then sets the bottle
        home; the left arm starts 8 s late and carries and lowers the plate 4 times slower than the expert. The
        plate ends seated and the bottle swirled and home, but the bottle rested for most of the carry: no pass."""
        bench = two_arms(0, 4.0, 8.0, ("start", "reach", "descend", "close", "lift"))
        try:
            w, success = bench.world, bench.tracker.success
            spot = (bench.specs["spot"]["x"], bench.specs["spot"]["y"])
            self.assertTrue(D.seated_strict("plate", bench.specs["nest"])(w))
            self.assertTrue(D.bottle_home(spot)(w))
            self.assertTrue(success.swirl(w)["swirled"])
            over = success.overlap(w)
            self.assertTrue(over["closed"])
            self.assertLess(over["steps_swirl"], 0.5 * over["steps"])
            self.assertLess(over["path_swirl"], 0.5 * over["path"])
            self.assertFalse(bench.tracker.summary()["success"])
        finally:
            bench.env.close()

    def test_slow_carry_while_swirling_passes(self):
        """The real arms (seed 0): the expert with the plate carried and lowered 5 times slower (under 2.1 mm a
        step), the right arm swirling the whole time. That is what the chore asks, so it passes."""
        bench = two_arms(0, 5.0, 1.5, ("start", "reach", "descend", "close", "lift", "carry", "lower", "release"))
        try:
            over = bench.tracker.success.overlap(bench.world)
            self.assertTrue(D.overlap_ok(over), over)
            self.assertTrue(bench.tracker.summary()["success"])
        finally:
            bench.env.close()

    def test_look_keeps_colliders(self):
        """The look adds no collision: the instrument's colliding geoms are exactly the recorded ones (so every
        other geom on it is drawn only), and on the bottle only labbench's wall and cap collide, with labbench's
        sizes and its 0.16 kg (so the drawn medium weighs nothing)."""
        for name in ALL:
            with self.subTest(task=name):
                bench = lt.set_bench(name, 0)
                try:
                    m = bench.env.model
                    found = []
                    for body in ("dispenser", "carrier"):
                        bid = m.body(body).id
                        for g in range(m.ngeom):
                            if m.geom_bodyid[g] != bid:
                                continue
                            if m.geom_contype[g] or m.geom_conaffinity[g]:
                                found.append((body, m.geom(g).name, int(m.geom_type[g]), m.geom_size[g].tolist(),
                                              m.geom_pos[g].tolist(), int(m.geom_contype[g]),
                                              int(m.geom_conaffinity[g]), m.geom_friction[g].tolist()))
                    self.assertEqual(len(found), len(EXPECTED_COLLIDERS))
                    for got, want in zip(found, EXPECTED_COLLIDERS):
                        self.assertEqual(got[:3], want[:3])
                        self.assertEqual(got[5:7], want[5:7])
                        for a, b in ((got[3], want[3]), (got[4], want[4]), (got[7], want[7])):
                            self.assertTrue(np.allclose(a, b, atol=1e-6), (got, want))
                    bid = m.body("bottle").id
                    colliding = {m.geom(g).name: m.geom_size[g][:2].tolist() for g in range(m.ngeom)
                                 if m.geom_bodyid[g] == bid and (m.geom_contype[g] or m.geom_conaffinity[g])}
                    self.assertEqual(set(colliding), {"bottle_wall", "bottle_cap"})
                    self.assertTrue(np.allclose(colliding["bottle_wall"], [0.025, 0.041]))
                    self.assertTrue(np.allclose(colliding["bottle_cap"], [0.019, 0.009]))
                    self.assertAlmostEqual(float(m.body_mass[bid]), 0.16, places=6)
                finally:
                    bench.env.close()

    def test_line_adds_no_force(self):
        """The bottle's line is a tendon that only draws: 300 steps of the right arm grasping, lifting and
        swirling the bottle give the same state to the last bit with and without it."""
        def run():
            bench = lt.set_bench("cell_bottle_swirl", 0)
            try:
                self.assertEqual(bench.env.model.ntendon, 1 if D.draw_line is original else 0)
                plan = BottleSwirler(bench).swirl(min_turns=2)
                rows = []
                for _ in range(300):
                    bench.env.step(HOME, next(plan))
                    rows.append(bench.env.data.qpos.copy())
                return np.array(rows)
            finally:
                bench.env.close()

        original = D.draw_line
        with_line = run()
        D.draw_line = lambda *args, **kwargs: None
        try:
            without = run()
        finally:
            D.draw_line = original
        self.assertEqual(float(np.abs(with_line - without).max()), 0.0)

    def test_cameras_see_the_work(self):
        """At the start the look hides at most a tenth of the carrier, plate and bottle from the model cameras that
        see them: rendered by segmentation with the look drawn and with it hidden."""
        wanted = (("top", "carrier"), ("top", "plate"), ("top", "bottle"), ("left", "carrier"), ("right", "bottle"))
        for seed in range(5):
            bench = lt.set_bench("dispenser_plate_in", seed)
            m, d = bench.env.model, bench.env.data
            inst = m.body("dispenser").id
            look = [g for g in range(m.ngeom) if m.geom_bodyid[g] == inst and not m.geom_contype[g]]
            targets = {k: [g for g in range(m.ngeom) if m.geom_bodyid[g] == m.body(k).id]
                       for k in ("carrier", "plate", "bottle")}
            renderer = mujoco.Renderer(m, height=480, width=640)
            renderer.enable_segmentation_rendering()
            try:
                counts = {}
                for hide in (False, True):
                    option = mujoco.MjvOption()
                    alpha = m.geom_rgba[look, 3].copy()
                    if hide:
                        m.geom_rgba[look, 3] = 0
                        option.flags[mujoco.mjtVisFlag.mjVIS_TENDON] = 0
                    for cam, k in wanted:
                        renderer.update_scene(d, camera=cam, scene_option=option)
                        seg = renderer.render()[60:420]  # the crop env.images uses
                        geom = seg[..., 1] == mujoco.mjtObj.mjOBJ_GEOM
                        counts[(cam, k, hide)] = int((geom & np.isin(seg[..., 0], targets[k])).sum())
                    m.geom_rgba[look, 3] = alpha
                for cam, k in wanted:
                    with self.subTest(seed=seed, camera=cam, target=k):
                        self.assertGreater(counts[(cam, k, True)], 0)
                        self.assertGreaterEqual(counts[(cam, k, False)] / counts[(cam, k, True)], 0.9)
                self.assertGreaterEqual(counts[("top", "bottle", False)], 300)
                self.assertGreaterEqual(counts[("right", "bottle", False)], 5000)  # the whole bottle, not its cap
            finally:
                renderer.close()
                bench.env.close()

    def test_show_view_frames_the_scene(self):
        """The aimed show camera frames the instrument's front, the nest, the mat, the bottle and both arms."""
        for seed in range(5):
            with self.subTest(seed=seed):
                bench = lt.set_bench("plate_in_with_swirl", seed, show=True)
                try:
                    self.assertTrue(D.aim_show(bench))
                    m, d, w = bench.env.model, bench.env.data, bench.world
                    n, mat = bench.specs["nest"], bench.specs["mat"]
                    cam = m.camera("show").id
                    points = {
                        "housing top left": (n["x"] + D.WIDTH / 2, n["y"] + D.FACE_Y, TABLE_Z + D.HEIGHT),
                        "housing top right": (n["x"] - D.WIDTH / 2, n["y"] + D.FACE_Y, TABLE_Z + D.HEIGHT),
                        "deck front left": (n["x"] + D.WIDTH / 2, n["y"] + D.FRONT_Y, TABLE_Z),
                        "deck front right": (n["x"] - D.WIDTH / 2, n["y"] + D.FRONT_Y, TABLE_Z),
                        "nest": (n["x"], n["y"], n["floor"]), "mat": (mat["x"], mat["y"], TABLE_Z),
                        "bottle base": w.pos("bottle"), "bottle top": w.pos("bottle") + np.array([0, 0, 0.1]),
                        "left base": d.body("left_base").xpos, "right base": d.body("right_base").xpos,
                        "left tcp": w.tcp("left"), "right tcp": w.tcp("right"),
                    }
                    rot, eye = d.cam_xmat[cam].reshape(3, 3), d.cam_xpos[cam]
                    f = 360 / np.tan(np.radians(m.cam_fovy[cam]) / 2)
                    for label, p in points.items():
                        v = rot.T @ (np.asarray(p, float) - eye)
                        u, row = 640 + f * v[0] / -v[2], 360 - f * v[1] / -v[2]
                        self.assertLess(v[2], 0, label)
                        self.assertTrue(0 <= u < 1280 and 0 <= row < 720, f"{label} at {u:.0f}, {row:.0f}")
                finally:
                    bench.env.close()

    def test_take_hold_stamps_swirl(self):
        with tempfile.TemporaryDirectory() as tmp:
            summary = take("cell_bottle_swirl", 0, policy="hold", seconds=2, out_root=tmp, show=False,
                           say=lambda *a: None)
            saved = json.loads((Path(summary["dir"]) / "summary.json").read_text())
            self.assertIsNone(saved["error"])
            self.assertEqual(saved["versions"]["tending"], tending.TENDING_ID)
            self.assertEqual(saved["versions"]["code"], LABBENCH_CODE)
            self.assertFalse(saved["success"])

    @unittest.skipUnless(os.environ.get("TENDING_EXPERT") == "1", "set TENDING_EXPERT=1 to run (a few minutes)")
    def test_expert_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ALL:
                runs = [play_expert(name, seed, tmp, video=False, say=lambda *a: None) for seed in range(5)]
                passed = [s["success"] for s in runs]
                with self.subTest(task=name, passed=passed):
                    self.assertGreaterEqual(sum(passed), 4)
                for s in runs:
                    if not s["success"]:
                        continue
                    with self.subTest(task=name, seed=s["seed"]):
                        if name in ("cell_bottle_swirl", "plate_in_with_swirl"):
                            self.assertGreaterEqual(s["swirl"]["path_m"], D.SWIRL_PATH)
                        if name == "plate_in_with_swirl":
                            o = s["overlap"]
                            self.assertGreaterEqual(s["both_arms_moving_s"], 3.0)
                            self.assertTrue(o["ok"])
                            self.assertGreaterEqual(o["swirling_s"], 0.5 * o["window_s"])
                            self.assertGreaterEqual(o["plate_path_while_swirling_m"], 0.5 * o["plate_path_m"])
                        if name in ("cell_bottle_swirl", "plate_in_with_swirl"):
                            self.assertLess(s["deepest_bottle_robot_contact"]["mm"], 2.0)
                        self.assertEqual(s["last_phase"]["left" if name != "cell_bottle_swirl" else "right"], "rest")

    @unittest.skipUnless(os.environ.get("TENDING_EXPERT") == "1", "set TENDING_EXPERT=1 to run (a few minutes)")
    def test_look_clears_the_arms(self):
        """Every drawn part of the instrument stays at least 10 mm from both arms' visual meshes and from the
        plate during the scripted expert's takes (seed 0), so nothing seen passes through anything that moves.
        Distances by mj_geomDistance, after a bounding sphere filter."""
        for name in ("dispenser_plate_in", "dispenser_plate_out", "plate_in_with_swirl"):
            state = {"best": 1.0}

            def watch(bench):
                m, d, w = bench.env.model, bench.env.data, bench.world
                if "look" not in state:
                    inst = m.body("dispenser").id
                    state["look"] = [g for g in range(m.ngeom) if m.geom_bodyid[g] == inst and not m.geom_contype[g]]
                    plate = m.body("plate").id
                    arms = sorted(g for g in w.robot_geoms if not m.geom_contype[g])  # the arms' visual meshes
                    state["movers"] = arms + [g for g in range(m.ngeom) if m.geom_bodyid[g] == plate]
                    state["ft"] = np.zeros(6)
                look, movers = state["look"], state["movers"]
                gap = (np.linalg.norm(d.geom_xpos[look][:, None] - d.geom_xpos[movers][None], axis=2)
                       - m.geom_rbound[look][:, None] - m.geom_rbound[movers][None])
                for i, j in zip(*np.nonzero(gap < 0.03)):
                    dist = mujoco.mj_geomDistance(m, d, look[i], movers[j], 0.05, state["ft"])
                    state["best"] = min(state["best"], dist)

            with tempfile.TemporaryDirectory() as tmp:
                s = play_expert(name, 0, tmp, video=False, say=lambda *a: None, on_step=watch)
            with self.subTest(task=name, closest_mm=round(state["best"] * 1000, 1)):
                self.assertTrue(s["success"])
                self.assertGreaterEqual(state["best"], 0.010)


if __name__ == "__main__":
    unittest.main()
