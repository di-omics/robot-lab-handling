"""The 4 instrument tending chores as labbench task cards: layouts, scene builds, scoring, oracles and traps.

Every chore uses 1 A1-marked microplate, the washer-dispenser with its carrier at the load position, a gray mat in
the left arm's usual pick area, and the cell bottle on its green spot on the right arm's side, with its line to the
pump. The plate always starts the right way round, so a robot only has to keep it so.

- dispenser_plate_in, dispenser_plate_out: the left arm's plate chores. The bottle is scenery there and is not
  scored.
- cell_bottle_swirl: swirl the bottle and put it back (no liquid is simulated: the swirl is scored as motion).
- plate_in_with_swirl: load the plate while the other hand keeps the bottle swirling.
"""

import numpy as np

from labbench import props
from labbench.oracle import Step, place, yaw_tilt_quat
from labbench.score import Stage
from labbench.sim import STEP_S, TABLE_Z
from labbench.tasks import Task

from . import dispenser as D

FAMILY = "instrument tending"
## Nominal nest centre in the world, before the per-seed jitter.
NEST_XY = (0.17, -0.075)
MAT_XY, MAT_HALF, MAT_RGBA = (0.14, 0.095), (0.095, 0.07), ".42 .45 .52 1"
## Nominal centre of the cell bottle's spot, and its jitter in x and y. Within the right arm's reach, seen whole by
## the overhead camera and by the right wrist camera from the arm's home pose, at least 13 cm clear of the deck.
BOTTLE_XY, BOTTLE_JIT = (-0.22, -0.15), 0.010


def _instrument(rng):
    """Nest centre jittered by up to 15 mm across and 10 mm in depth."""
    return (NEST_XY[0] + rng.uniform(-0.015, 0.015), NEST_XY[1] + rng.uniform(-0.010, 0.010))


def _mat(rng):
    """Mat centre jittered by up to 15 mm across and 10 mm in depth (it stays at least 8 mm clear of the deck)."""
    return (MAT_XY[0] + rng.uniform(-0.015, 0.015), MAT_XY[1] + rng.uniform(-0.010, 0.010))


def _bottle(rng):
    """Bottle spot jittered by up to 10 mm each way. Drawn after everything else, so the earlier draws, and with
    them the plate, mat and instrument of every seed, are the same as before the bottle was added."""
    return (BOTTLE_XY[0] + rng.uniform(-BOTTLE_JIT, BOTTLE_JIT), BOTTLE_XY[1] + rng.uniform(-BOTTLE_JIT, BOTTLE_JIT))


def layout_in(rng):
    """Instrument and mat jittered; plate on the mat, off its centre by up to 12 and 8 mm, turned up to 0.15 rad;
    the bottle on its spot."""
    d, m = _instrument(rng), _mat(rng)
    lay = {"dispenser": d,
           "plate": (m[0] + rng.uniform(-0.012, 0.012), m[1] + rng.uniform(-0.008, 0.008), rng.uniform(-0.15, 0.15)),
           "mat": m}
    lay["bottle"] = _bottle(rng)
    return lay


def layout_out(rng):
    """Instrument and mat jittered; plate seated in the nest, within 1 mm and 0.005 rad; the bottle on its spot."""
    d, m = _instrument(rng), _mat(rng)
    lay = {"dispenser": d,
           "plate": (d[0] + rng.uniform(-0.001, 0.001), d[1] + rng.uniform(-0.001, 0.001), rng.uniform(-0.005, 0.005)),
           "mat": m}
    lay["bottle"] = _bottle(rng)
    return lay


def _build(world, lay, plate_z):
    nest = D.build_instrument(world, *lay["dispenser"])
    mat = props.mat(world, "mat", *lay["mat"], half=MAT_HALF, rgba=MAT_RGBA)
    x, y, yaw = lay["plate"]
    plate = D.a1_plate(world, "plate", x, y, yaw=yaw, z=plate_z)
    bx, by = lay["bottle"]
    bottle = D.cell_bottle(world, bx, by, nest)
    return {"nest": nest, "mat": mat, "plate": plate, "bottle": bottle, "spot": {"x": bx, "y": by}}


def build_in(world, lay):
    return _build(world, lay, TABLE_Z)


def build_out(world, lay):
    return _build(world, lay, TABLE_Z + D.FLOOR)


def scoring_in(specs, z0):
    """Stages: lifted, over the carrier, seated. Success: seated, hands clear of the travel box, not dropped, after
    a lift and a pass over the carrier. Lifted and over test the lowest corner of a nearly level plate."""
    n = specs["nest"]
    seated, clear, kept = D.seated_strict("plate", n), D.hands_clear(n), D.no_drop("plate")
    stages = [Stage("plate_lifted", D.lifted_flat("plate", z0["plate"])),
              Stage("plate_over_carrier", D.over_flat("plate", n["x"], n["y"], (0.03, 0.03), n["floor"])),
              Stage("plate_seated", seated)]
    # kept() runs first on every tick so it never misses a fall.
    return stages, (lambda w: kept(w) and seated(w) and clear(w)), ["plate_lifted", "plate_over_carrier"]


def scoring_out(specs, z0):
    """Stages: lifted, over the mat, flat on the mat. Success: flat on the mat, carrier empty, not dropped, after a
    lift and a pass over the mat. Lifted and over test the lowest corner of a nearly level plate, so tipping the
    plate out of the nest and pushing it along the table to the mat earns neither."""
    n, m = specs["nest"], specs["mat"]
    flat, empty, kept = D.on_mat_flat("plate", m), D.carrier_empty("plate", n), D.no_drop("plate")
    stages = [Stage("plate_lifted", D.lifted_flat("plate", z0["plate"])),
              Stage("plate_over_mat", D.over_flat("plate", m["x"], m["y"], (0.04, 0.04), TABLE_Z)),
              Stage("plate_on_mat", flat)]
    return stages, (lambda w: kept(w) and flat(w) and empty(w)), ["plate_lifted", "plate_over_mat"]


# Poses for the scripted checks.


def _at(x, y, z, yaw=0.0, roll=0.0, pitch=0.0):
    return lambda w: (np.array([x, y, z]), yaw_tilt_quat(yaw, roll, pitch))


def _raised(by=0.06):
    return lambda w: (w.pos("plate") + np.array([0.0, 0.0, by]), None)


def _carried_to(x, y, surface, drop):
    """Lift, carry over the place, hold the plate `drop` metres above the surface, then let go."""
    return [Step("plate", _raised(), pin_s=1.0),
            Step("plate", _at(x, y, surface + 0.06), pin_s=1.0),
            Step("plate", _at(x, y, surface + drop), pin_s=0.5, settle_s=3.0, success=False)]


def _tipped(cx, cy, base_z, theta):
    """The plate with one end raised by theta about its -x short edge, which stays down at base_z."""
    hx = D.PLATE_HALF[0]
    return _at(cx - hx + hx * np.cos(theta), cy, base_z + hx * np.sin(theta), pitch=-theta)


def _tipped_and_pushed(n, m):
    """Never lifted: one end raised in the nest, slid off onto the table in front of the deck, pushed along the
    table to the mat, one end raised on the mat, laid flat. Each pin stands in for a hand holding it there."""
    y0 = n["y"] + D.FRONT_Y + 0.05
    steps = [Step("plate", _tipped(n["x"], n["y"], n["floor"], np.radians(45)), pin_s=0.8),
             Step("plate", _at(n["x"], y0, TABLE_Z + 0.0005), pin_s=0.3)]
    for k in range(1, 6):
        t = k / 5
        steps.append(Step("plate", _at(n["x"] + (m["x"] - n["x"]) * t, y0 + (m["y"] - y0) * t, TABLE_Z + 0.0005),
                          pin_s=0.2))
    return steps + [Step("plate", _tipped(m["x"], m["y"], TABLE_Z, np.radians(30)), pin_s=0.8),
                    Step("plate", _at(m["x"], m["y"], TABLE_Z + 0.0005), pin_s=0.3, settle_s=3.0,
                         not_yet=["plate_lifted", "plate_over_mat"], success=False)]


def oracle_in(specs):
    n = specs["nest"]
    x, y, f = n["x"], n["y"], n["floor"]
    return [Step("plate", _raised(), pin_s=1.0, expect=["plate_lifted"], not_yet=["plate_over_carrier"], success=False),
            Step("plate", _at(x, y, f + 0.06), pin_s=1.0, expect=["plate_over_carrier"], not_yet=["plate_seated"],
                 success=False),
            Step("plate", _at(x, y, f + 0.002), pin_s=0.1, settle_s=3.0, expect=["plate_seated"], success=True)]


def traps_in(specs):
    n = specs["nest"]
    x, y, f = n["x"], n["y"], n["floor"]
    return {
        "plate turned half a turn in the nest": [
            Step("plate", _at(x, y, f + 0.002, np.pi), settle_s=3.0, not_yet=["plate_seated"], success=False)],
        "one end resting on the corner guides, tilted": [
            Step("plate", _at(x + 0.008, y, f + 0.0035, pitch=-0.04), settle_s=3.0, not_yet=["plate_seated"],
                 success=False)],
        "plate flat on top of the guides": [
            Step("plate", _at(x + 0.003, y + 0.003, f + D.GUIDE_H + 0.001, np.radians(5)), settle_s=3.0,
                 not_yet=["plate_seated"], success=False)],
        "plate on the carrier beside the nest": [
            Step("plate", _at(x, y + 0.05, f + D.GUIDE_H + 0.001), settle_s=3.0, not_yet=["plate_seated"],
                 success=False)],
        "plate dropped from 3 cm into the nest": _carried_to(x, y, f, 0.03),
        "plate dropped from 6 cm into the nest": _carried_to(x, y, f, 0.06),
    }


def oracle_out(specs):
    m = specs["mat"]
    return [Step("plate", _raised(), pin_s=1.0, expect=["plate_lifted"], not_yet=["plate_over_mat"], success=False),
            Step("plate", _at(m["x"], m["y"], TABLE_Z + 0.06), pin_s=1.0, expect=["plate_over_mat"],
                 not_yet=["plate_on_mat"], success=False),
            Step("plate", _at(m["x"], m["y"], TABLE_Z + 0.002), pin_s=0.1, settle_s=3.0, expect=["plate_on_mat"],
                 success=True)]


def traps_out(specs):
    n, m = specs["nest"], specs["mat"]
    return {
        "plate lifted and put back on the carrier": [
            Step("plate", _raised(), pin_s=1.0),
            Step("plate", _at(n["x"], n["y"], n["floor"] + 0.002), settle_s=3.0, not_yet=["plate_on_mat"],
                 success=False)],
        # The pin stands in for whatever it leans on: a pinned plate reads as let go and at rest.
        "plate on the mat but leaning on something": [
            Step("plate", _at(m["x"], m["y"], TABLE_Z + 0.032, roll=np.radians(25)), pin_s=2.5,
                 not_yet=["plate_on_mat"], success=False)],
        "plate on the table off the mat": [
            Step("plate", _at(m["x"] + 0.17, m["y"], TABLE_Z + 0.002), settle_s=2.5, not_yet=["plate_on_mat"],
                 success=False)],
        "plate half off the mat": [
            Step("plate", _at(m["x"] + 0.08, m["y"], TABLE_Z + 0.002), settle_s=2.5, not_yet=["plate_on_mat"],
                 success=False)],
        "plate dropped from 3 cm onto the mat": _carried_to(m["x"], m["y"], TABLE_Z, 0.03),
        "plate dropped from 6 cm onto the mat": _carried_to(m["x"], m["y"], TABLE_Z, 0.06),
        "plate tipped out of the nest and pushed to the mat, never lifted": _tipped_and_pushed(n, m),
    }


# The cell bottle chores.


def scoring_swirl(specs, z0):
    """Stages: lifted (off the bench and under 20 degrees of tilt), swirled, home. Success: never spilled, swirled,
    and home (upright on its spot, let go, at rest), after a lift and a swirl. success.swirl is the meter, for
    summaries and checks."""
    spot = (specs["spot"]["x"], specs["spot"]["y"])
    meter, home = D.swirl_meter("bottle", z0["bottle"]), D.bottle_home(spot)
    stages = [Stage("bottle_lifted", lambda w: meter(w)["lifted"] and w.tilt_deg("bottle") < D.SWIRL_MAX_TILT),
              Stage("bottle_swirled", lambda w: meter(w)["swirled"]),
              Stage("bottle_home", lambda w: meter(w)["swirled"] and home(w))]

    def success(w):
        st = meter(w)  # first, so it sees every step
        return not st["spilled"] and st["swirled"] and home(w)

    success.swirl = meter
    return stages, success, ["bottle_lifted", "bottle_swirled"]


def scoring_pair(specs, z0):
    """Everything dispenser_plate_in asks, plus: the bottle was swirled, never spilled, ends home, and was swirling
    for at least half of the time between the plate's first lift and its being seated, and over at least half of
    the plate's travel in that time (see dispenser.overlap_meter). success.swirl and success.overlap are the 2
    meters, for summaries and checks."""
    n = specs["nest"]
    spot = (specs["spot"]["x"], specs["spot"]["y"])
    seated, clear, kept = D.seated_strict("plate", n), D.hands_clear(n), D.no_drop("plate")
    meter, home = D.swirl_meter("bottle", z0["bottle"]), D.bottle_home(spot)
    over = D.overlap_meter(meter, z0["plate"], seated)
    stages = [Stage("plate_lifted", lambda w: bool(over(w)) and D.lifted_flat("plate", z0["plate"])(w)),
              Stage("plate_over_carrier", D.over_flat("plate", n["x"], n["y"], (0.03, 0.03), n["floor"])),
              Stage("plate_seated", seated),
              Stage("bottle_swirled", lambda w: meter(w)["swirled"]),
              Stage("bottle_home", lambda w: meter(w)["swirled"] and home(w))]

    def success(w):
        k, o, st = kept(w), D.overlap_ok(over(w)), meter(w)  # the stateful tests first, every step
        return k and o and not st["spilled"] and st["swirled"] and seated(w) and clear(w) and home(w)

    success.swirl, success.overlap = meter, over
    return stages, success, ["plate_lifted", "plate_over_carrier", "bottle_swirled"]


def _spot(specs):
    return specs["spot"]["x"], specs["spot"]["y"]


def _bottle_at(x, y, z, roll=0.0):
    return lambda w: (np.array([x, y, z]), yaw_tilt_quat(0.0, roll, 0.0))


def _with_plate(bottle_pose, plate_pose):
    """A bottle pose that also pins the plate, so one Step moves both props (play() calls the pose once a Step)."""
    if plate_pose is None:
        return bottle_pose

    def pose(w):
        place(w.env, "plate", *plate_pose(w))
        return bottle_pose(w)
    return pose


def swirl_steps(spot, turns=6.0, r=0.025, hz=0.8, lift=0.04, roll=0.0, z=None, plate_poses=None):
    """The bottle pinned on a circle of radius r about its spot, hz turns a second, one Step per control step.
    @param plate_poses Optional plate poses, one per Step from the first, pinned alongside; the plate is free after.
    """
    zz = TABLE_Z + lift if z is None else z
    steps = []
    for k in range(round(turns / hz / STEP_S)):
        th = 2 * np.pi * hz * k * STEP_S
        bp = _bottle_at(spot[0] + r * np.cos(th), spot[1] + r * np.sin(th), zz, roll)
        pp = plate_poses[k] if plate_poses and k < len(plate_poses) else None
        steps.append(Step("bottle", _with_plate(bp, pp), pin_s=STEP_S))
    return steps


def _clear(step, success=None):
    """The same move with no expectations (for a script that strings oracle moves into a trap)."""
    return Step(step.prop, step.pose, step.pin_s, step.settle_s, success=success, note=step.note)


def _down(spot, success=False):
    return Step("bottle", _bottle_at(spot[0], spot[1], TABLE_Z + 0.002), settle_s=3.0, success=success)


def oracle_swirl(specs):
    sp = _spot(specs)
    sw = swirl_steps(sp)
    last = sw[-1]
    sw[-1] = Step(last.prop, last.pose, last.pin_s, expect=["bottle_swirled"], not_yet=["bottle_home"], success=False)
    return ([Step("bottle", _bottle_at(*sp, TABLE_Z + 0.04), pin_s=1.0, expect=["bottle_lifted"],
                  not_yet=["bottle_swirled"], success=False)]
            + sw + [Step("bottle", _bottle_at(*sp, TABLE_Z + 0.002), settle_s=3.0, expect=["bottle_home"], success=True)])


def traps_swirl(specs):
    sp = _spot(specs)
    up = Step("bottle", _bottle_at(*sp, TABLE_Z + 0.04), pin_s=0.5)
    out_and_back = [Step("bottle", _bottle_at(sp[0], sp[1] - 0.01 * k, TABLE_Z + 0.04), pin_s=STEP_S)
                    for k in list(range(1, 31)) + list(range(29, -1, -1))]
    shake = [Step("bottle", _bottle_at(sp[0] + 0.05 * np.sin(2 * np.pi * 0.8 * k * STEP_S), sp[1], TABLE_Z + 0.04),
                  pin_s=STEP_S) for k in range(160)]
    return {
        "bottle lifted and put back, no swirl": [Step("bottle", _bottle_at(*sp, TABLE_Z + 0.04), pin_s=2.0), _down(sp)],
        "bottle carried 30 cm away and back in a straight line": [up] + out_and_back + [_down(sp)],
        "bottle swirled at 45 degrees of tilt": swirl_steps(sp, lift=0.07, roll=np.radians(45)) + [_down(sp)],
        "bottle swirled, then left lying down": swirl_steps(sp) + [
            Step("bottle", _bottle_at(*sp, TABLE_Z + 0.026, np.pi / 2), settle_s=3.0, success=False)],
        "bottle swirled, then put down 10 cm off its spot": swirl_steps(sp) + [
            Step("bottle", _bottle_at(sp[0], sp[1] - 0.10, TABLE_Z + 0.002), settle_s=3.0, success=False)],
        "bottle swirled by sliding it on the bench, never lifted": swirl_steps(sp, z=TABLE_Z + 0.0005) + [_down(sp)],
        "bottle shaken back and forth in a straight line, never circled": [up] + shake + [_down(sp)],
        "bottle slid in circles on the instrument deck, never lifted": _deck_circles(specs) + [_down(sp)],
    }


def _deck_circles(specs, turns=6.0, plate_poses=None):
    """The bottle stood on the instrument's deck to the right (-x) of the carrier and slid round in 25 mm circles
    there, resting on the deck the whole time: 54 mm above the bench, yet never held."""
    n = specs["nest"]
    return swirl_steps((n["x"] - 0.15, n["y"] - 0.03), turns=turns, z=TABLE_Z + D.DECK_TOP + 0.0005,
                       plate_poses=plate_poses)


def _plate_path(specs):
    """74 plate poses for the two-arm oracle: 20 steps 6 cm above its start, 40 steps on a straight line to 6 cm
    above the nest, 10 held there, then 4 at 2 mm above the nest floor, reached in one jump as oracle_in does (a
    gradual descent by script would read as a fall to no_drop)."""
    n = specs["nest"]
    start = {}

    def p0(w):
        if not start:
            start["p"] = w.pos("plate") + np.array([0.0, 0.0, 0.06])
            start["yaw"] = np.radians(w.yaw_deg("plate"))
        return start["p"]

    above = np.array([n["x"], n["y"], n["floor"] + 0.06])
    poses = [lambda w: (p0(w), yaw_tilt_quat(start.get("yaw", 0.0) if start else 0.0))] * 20
    poses += [lambda w, k=k: (p0(w) + (above - p0(w)) * k / 40, yaw_tilt_quat(0.0)) for k in range(1, 41)]
    poses += [lambda w: (above, yaw_tilt_quat(0.0))] * 10
    poses += [lambda w: (np.array([n["x"], n["y"], n["floor"] + 0.002]), yaw_tilt_quat(0.0))] * 4
    return poses


def oracle_pair(specs):
    sp = _spot(specs)
    path = _plate_path(specs)
    sw = swirl_steps(sp, turns=7, plate_poses=path)
    last = sw[-1]
    sw[-1] = Step(last.prop, last.pose, last.pin_s, expect=["plate_seated", "bottle_swirled"], not_yet=["bottle_home"],
                  success=False)
    return ([Step("bottle", _bottle_at(*sp, TABLE_Z + 0.04), pin_s=0.3, not_yet=["plate_lifted"])] + sw
            + [Step("bottle", _bottle_at(*sp, TABLE_Z + 0.002), settle_s=3.0, expect=["bottle_home"], success=True)])


def _load_plate(specs, success=False):
    """oracle_in's 3 moves of the plate, with no expectations; the last one's success as given."""
    steps = oracle_in(specs)
    return [_clear(s) for s in steps[:-1]] + [_clear(steps[-1], success)]


def _swirl_then_rest(sp):
    """The bottle swirled by script, then set back on its spot and left there."""
    return [_clear(s) for s in oracle_swirl({"spot": {"x": sp[0], "y": sp[1]}})[:-1]] + [
        Step("bottle", _bottle_at(*sp, TABLE_Z + 0.002), settle_s=2.0)]


def traps_pair(specs):
    sp, n = _spot(specs), specs["nest"]
    park = (n["x"] + 0.145, n["y"] - 0.03, n["floor"] - D.SLAB_T)  # on the deck, right of the carrier
    return {
        "plate loaded, bottle never touched": _load_plate(specs),
        "bottle swirled first, plate loaded afterwards with the bottle resting": _swirl_then_rest(sp) + _load_plate(specs),
        "plate seated while the bottle is still in the hand":
            [Step("bottle", _bottle_at(*sp, TABLE_Z + 0.04), pin_s=0.3)]
            + swirl_steps(sp, turns=7, plate_poses=_plate_path(specs))
            + [Step("bottle", _bottle_at(*sp, TABLE_Z + 0.04), pin_s=3.0, success=False)],
        "plate parked on the deck while the bottle swirls, then loaded with the bottle resting":
            [Step("plate", _raised(), pin_s=1.0), Step("plate", _at(park[0], park[1], park[2] + 0.06), pin_s=0.5),
             Step("plate", _at(park[0], park[1], park[2] + 0.002), settle_s=1.0)]
            + _swirl_then_rest(sp) + _load_plate(specs),
        "plate lifted and set back on the mat, bottle swirled, then plate loaded with the bottle resting":
            _lift_and_back() + _swirl_then_rest(sp) + _load_plate(specs),
        "plate lifted while the bottle swirls, then carried slowly with the bottle resting": _slow_carry(specs),
        "bottle swirled first, then only shaken in a straight line while the plate is carried":
            [Step("bottle", _bottle_at(*sp, TABLE_Z + 0.04), pin_s=0.3)] + swirl_steps(sp, turns=5)
            + [Step("bottle", _with_plate(_bottle_at(sp[0] + 0.025 * np.cos(2 * np.pi * 0.8 * k * STEP_S), sp[1],
                                                     TABLE_Z + 0.04), pp), pin_s=STEP_S)
               for k, pp in enumerate(_plate_path(specs))]
            + [_down(sp)],
        "plate carried while the bottle swirls, then left hanging over the nest with the bottle resting":
            _rushed_then_hanging(specs),
        "bottle swirled first, then slid in circles on the instrument deck while the plate is carried":
            [Step("bottle", _bottle_at(*sp, TABLE_Z + 0.04), pin_s=0.3)] + swirl_steps(sp, turns=5)
            + _deck_circles(specs, turns=3.2, plate_poses=_plate_path(specs)) + [_down(sp)],
    }


def _rushed_then_hanging(specs):
    """The plate lifted and carried to 6 cm above the nest while the bottle swirls 5 turns; the bottle goes home
    while the plate hangs there for 10 s more; then the plate is seated in one jump. Most of the plate's travel is
    swirled, but not most of the time, so only the time part of the together rule fails it."""
    sp, n = _spot(specs), specs["nest"]
    path = _plate_path(specs)
    above = np.array([n["x"], n["y"], n["floor"] + 0.06])
    hang = lambda w: (above, yaw_tilt_quat(0.0))
    sw = swirl_steps(sp, turns=5)
    steps = [Step("bottle", _bottle_at(*sp, TABLE_Z + 0.04), pin_s=0.3)]
    steps += swirl_steps(sp, turns=5, plate_poses=path[:70] + [hang] * (len(sw) - 70))
    steps += [Step("bottle", _with_plate(_bottle_at(*sp, TABLE_Z + 0.002), hang), pin_s=STEP_S) for _ in range(10)]
    steps.append(Step("plate", hang, pin_s=10.0))
    steps.append(Step("plate", lambda w: (np.array([n["x"], n["y"], n["floor"] + 0.002]), yaw_tilt_quat(0.0)),
                      pin_s=0.1, settle_s=3.0, success=False))
    return steps


def _slow_carry(specs):
    """Turn-taking with a slow carry: the bottle swirls 6 turns; on its last 5 steps the plate is lifted 6 cm (one
    jump) and held; the bottle goes home and rests; the plate hangs still for 2.5 s, is carried 2 mm a step to 6 cm
    above the nest, and seated in one jump. Under a rule that counted only the plate's fast steps this passed."""
    sp, n = _spot(specs), specs["nest"]
    start = {}

    def lifted(w):
        if not start:
            start["p"] = w.pos("plate") + np.array([0.0, 0.0, 0.06])
            start["yaw"] = np.radians(w.yaw_deg("plate"))
        return start["p"], yaw_tilt_quat(start["yaw"])

    sw = swirl_steps(sp, turns=6.0)
    sw = sw[:-5] + swirl_steps(sp, turns=6.0, plate_poses=[lifted] * len(sw))[-5:]
    steps = [Step("bottle", _bottle_at(*sp, TABLE_Z + 0.04), pin_s=1.0)] + sw
    steps += [Step("bottle", _with_plate(_bottle_at(*sp, TABLE_Z + 0.002), lifted), pin_s=STEP_S) for _ in range(10)]
    steps.append(Step("plate", lifted, pin_s=2.0))
    above = np.array([n["x"], n["y"], n["floor"] + 0.06])
    for k in range(1, 121):  # 2 mm a step for a carry of up to 0.24 m

        def carry(w, k=k):
            a = lifted(w)[0]
            d = above - a
            f = min(1.0, k * 0.002 / max(float(np.linalg.norm(d)), 1e-9))
            return a + d * f, yaw_tilt_quat(start["yaw"])

        steps.append(Step("plate", carry, pin_s=STEP_S))
    steps.append(Step("plate", lambda w: (above, yaw_tilt_quat(0.0)), pin_s=0.5))
    steps.append(Step("plate", lambda w: (np.array([n["x"], n["y"], n["floor"] + 0.002]), yaw_tilt_quat(0.0)),
                      pin_s=0.1, settle_s=3.0, success=False))
    return steps


def _lift_and_back(by=0.06):
    """The plate held `by` above where it lies, then set back 2 mm above the same place and let go. Set back in
    one jump, as oracle_in seats a plate, so no_drop reads a script and not a fall."""
    start = {}

    def up(w):
        start.setdefault("p", w.pos("plate"))
        return start["p"] + np.array([0.0, 0.0, by]), None

    return [Step("plate", up, pin_s=1.0),
            Step("plate", lambda w: (start["p"] + np.array([0.0, 0.0, 0.002]), None), settle_s=1.0)]


PLATE_IN = Task(
    name="dispenser_plate_in",
    title="Load a plate onto the dispenser carrier",
    prompt="Put the plate on the dispenser's plate carrier.",
    variants={
        "terse": "Plate onto the dispenser carrier.",
        "precise": ("Pick up the white 96-well plate from the gray mat and set it flat in the pocket of the dispenser's "
                    "plate carrier, blue A1 corner at the back left, then lift your hand up and away from the carrier."),
    },
    seconds=150,
    layout=layout_in, build=build_in, scoring=scoring_in, movable=("plate", "bottle"), oracle=oracle_in,
    traps=traps_in, family=FAMILY,
    rule=("The plate sits flat in the carrier nest, A1 at the back left, hands off and clear of the carrier travel. "
          "A plate dropped into the nest does not count."),
)

PLATE_OUT = Task(
    name="dispenser_plate_out",
    title="Unload the dispenser carrier",
    prompt="Take the plate off the dispenser's plate carrier and put it on the gray mat.",
    variants={
        "terse": "Plate from the dispenser carrier to the mat.",
        "precise": ("Lift the white 96-well plate straight up out of the dispenser's plate carrier and set it down flat "
                    "on the gray mat, then let go."),
    },
    seconds=150,
    layout=layout_out, build=build_out, scoring=scoring_out, movable=("plate", "bottle"), oracle=oracle_out,
    traps=traps_out, family=FAMILY,
    rule=("The plate rests flat and wholly on the gray mat, hands off, and the carrier is empty. "
          "A plate dropped onto the mat does not count."),
)

CELL_BOTTLE_SWIRL = Task(
    name="cell_bottle_swirl",
    title="Swirl the cell bottle",
    prompt="Swirl the cell bottle to keep the cells mixed, then put it back.",
    variants={
        "terse": "Swirl the cell bottle, then put it back.",
        "precise": ("Lift the cell bottle with the orange cap a little off the bench, swirl it gently in small circles "
                    "for a few seconds while keeping it upright, then set it back upright on its green spot and let go."),
    },
    seconds=90,
    layout=layout_in, build=build_in, scoring=scoring_swirl, movable=("bottle", "plate"), oracle=oracle_swirl,
    traps=traps_swirl, family=FAMILY,
    rule=("The bottle was lifted and swirled in small circles, kept nearly upright and near where it was picked up, "
          "then set back upright on its green spot and let go. Tipping it past 30 degrees at any time is a spill and "
          "cannot pass. No liquid is simulated."),
)

PLATE_IN_WITH_SWIRL = Task(
    name="plate_in_with_swirl",
    title="Load the dispenser while swirling the cell bottle",
    prompt="Load the plate onto the dispenser's plate carrier while your other hand keeps the cell bottle swirling.",
    variants={
        "terse": "Plate onto the carrier; keep the cell bottle swirling meanwhile.",
        "precise": ("With your left hand, set the white 96-well plate from the gray mat flat in the pocket of the "
                    "dispenser's plate carrier, blue A1 corner at the back left. With your right hand, lift the cell "
                    "bottle a little and keep swirling it in small circles the whole time the plate is moving, then "
                    "set the bottle back upright on its green spot. Let go of both."),
    },
    seconds=150,
    layout=layout_in, build=build_in, scoring=scoring_pair, movable=("plate", "bottle"), oracle=oracle_pair,
    traps=traps_pair, family=FAMILY,
    rule=("Everything dispenser_plate_in asks, and between the plate first leaving the mat and being seated the "
          "bottle was held and swirling for at least half of the time and over at least half of the plate's travel; "
          "the bottle was swirled, never spilled, and ends upright on its spot with hands off. No liquid is "
          "simulated."),
)

CHORES = (PLATE_IN, PLATE_OUT, CELL_BOTTLE_SWIRL, PLATE_IN_WITH_SWIRL)
