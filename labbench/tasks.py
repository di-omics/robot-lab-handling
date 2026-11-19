"""The task cards: what is on the bench, what the robot is told, and how the result is scored.

Positions use the station frame: x + is the left arm's side, y + points toward the arm bases, the table top is
at TABLE_Z. Every take jitters the start positions by a seed, so 5 takes are 5 slightly different benches.

Each card has:
- prompt: the request in a scientist's plain words, plus optional other wordings (variants);
- stages: partial credit, in the order a success passes through them;
- success: the end state asked for, with the robot's hands off;
- oracle and traps: scripted checks of the scoring itself (see oracle.py).
"""

from dataclasses import dataclass
from typing import Callable

import numpy as np

from . import props
from .oracle import Step, mat_to_quat, yaw_tilt_quat
from .score import (Stage, in_hand_of, in_rack_well, inside_box, inside_footprint, lifted, lifted_level,
                    lined_up_at_shelf, on_shelf, over, resting_on, seated_in_nest, stacked_on)
from .sim import TABLE_Z


## The control instruction: neither object exists on any bench here. A model that still does the task is not
## following the words.
WRONG_OBJECT = "Put the banana in the bowl."


@dataclass
class Task:
    name: str
    title: str  # what a scientist would call the chore
    prompt: str  # what the robot is told, in a scientist's plain words
    seconds: float  # simulated time allowed
    layout: Callable  # rng -> dict of start poses
    build: Callable  # (world element, layout) -> dict of prop specs
    scoring: Callable  # (specs, start heights) -> (stages, success test[, stages success requires])
    movable: tuple  # names of the props that can move, for tracking
    oracle: Callable = None  # specs -> scripted steps that must end in success
    traps: Callable = None  # specs -> {name: scripted steps that must NOT end in success}
    variants: dict = None  # other wordings of the same request, by name ("precise", ...)
    family: str = "move and sort"
    rule: str = ""  # the pass rule in plain words (the code in `scoring` is the rule that counts)

    def wording(self, variant="plain"):
        """The prompt for a variant. "plain" is the task card's own prompt. "wrong_object" is the same control
        sentence for every task: it names things that are not on the bench, to see whether the model listens."""
        if variant == "plain":
            return self.prompt
        if variant == "wrong_object":
            return WRONG_OBJECT
        return self.variants[variant]


def _jit(rng, x, y, r=0.015):
    return (x + rng.uniform(-r, r), y + rng.uniform(-r, r))


# Poses for the scripted checks (oracle.py).


def _raised(name, by=0.06):
    """Straight up from where the prop is now."""
    return lambda w: (w.pos(name) + np.array([0.0, 0.0, by]), None)


def _at(x, y, z, yaw=0.0, roll=0.0, pitch=0.0):
    return lambda w: (np.array([x, y, z]), yaw_tilt_quat(yaw, roll, pitch))


def _on_table(x, y, yaw=0.0, roll=0.0, lift=0.002):
    return _at(x, y, TABLE_Z + lift, yaw, roll)


def _in_well(rack_spec, k, drop=0.004):
    """Standing in well k of the rack, wherever the rack is now."""

    def pose(w):
        wx, wy = rack_spec["wells"][k]
        return w.pos("rack") + w.rot("rack") @ np.array([wx, wy, rack_spec["floor"] + drop]), mat_to_quat(w.rot("rack"))

    return pose


def _onto(base, base_spec, dx=0.0, dy=0.0, gap=0.002):
    """Sitting on top of another movable prop, lined up with it."""
    return lambda w: (w.pos(base) + w.rot(base) @ np.array([dx, dy, base_spec["height"] + gap]), mat_to_quat(w.rot(base)))


def _in_tray(spec, dx=0.0, dy=0.0):
    """Standing on the floor of a tray or bin."""
    return _at(spec["x"] + dx, spec["y"] + dy, spec["floor"] + 0.002)


# 1. Falcon tubes into a tube rack.


def _tubes_to_rack_layout(rng):
    return {
        "rack": (*_jit(rng, 0.0, -0.04, 0.01), rng.uniform(-0.1, 0.1)),
        "tube_a": _jit(rng, 0.16, 0.09),
        "tube_b": _jit(rng, -0.14, 0.09),
    }


def _tubes_to_rack_build(world, lay):
    x, y, yaw = lay["rack"]
    return {
        "rack": props.tube_rack(world, "rack", x, y, nx=3, ny=2, yaw=yaw),
        "tube_a": props.falcon_tube(world, "tube_a", *lay["tube_a"]),
        "tube_b": props.falcon_tube(world, "tube_b", *lay["tube_b"], cap_rgba=".15 .35 .8 1"),
    }


def _tubes_to_rack_scoring(specs, z0):
    racked = {t: in_rack_well(t, "rack", specs["rack"]) for t in ("tube_a", "tube_b")}
    stages = []
    for t in ("tube_a", "tube_b"):
        stages.append(Stage(f"{t}_lifted", lifted(t, z0[t])))
        stages.append(Stage(f"{t}_in_rack", racked[t]))
    return stages, lambda w: all(test(w) for test in racked.values())


def _tubes_to_rack_oracle(specs):
    rack = specs["rack"]
    return [
        Step("tube_a", _raised("tube_a"), pin_s=1.0, expect=["tube_a_lifted"],
             not_yet=["tube_a_in_rack", "tube_b_lifted", "tube_b_in_rack"], success=False, note="tube A held up"),
        Step("tube_a", _in_well(rack, 0), settle_s=2.5, expect=["tube_a_in_rack"], not_yet=["tube_b_in_rack"],
             success=False, note="tube A into a corner well"),
        Step("tube_b", _raised("tube_b"), pin_s=1.0, expect=["tube_b_lifted"], not_yet=["tube_b_in_rack"],
             success=False, note="tube B held up"),
        Step("tube_b", _in_well(rack, 5), settle_s=3.5, expect=["tube_b_in_rack"], success=True,
             note="tube B into the opposite corner well"),
    ]


def _tubes_to_rack_traps(specs):
    rack = specs["rack"]

    def across_the_rim(w):  # lying flat on top of the rack
        top = w.pos("rack") + w.rot("rack") @ np.array([-0.05, 0.0, rack["height"] + 0.017])
        return top, yaw_tilt_quat(0.0, 0.0, np.pi / 2)

    def hovering_over_well(w):  # in the right spot but never let down
        wx, wy = rack["wells"][2]
        return w.pos("rack") + w.rot("rack") @ np.array([wx, wy, rack["height"] + 0.03]), mat_to_quat(w.rot("rack"))

    return {
        "one tube racked, the other left on the table": [
            Step("tube_a", _in_well(rack, 1), settle_s=4.0, expect=["tube_a_in_rack"], not_yet=["tube_b_in_rack"],
                 success=False),
        ],
        "tube lying across the top of the rack": [
            Step("tube_a", across_the_rim, settle_s=4.0, not_yet=["tube_a_in_rack"], success=False),
        ],
        "tube held over a well, never let down": [
            Step("tube_a", hovering_over_well, pin_s=4.0, not_yet=["tube_a_in_rack"], success=False),
        ],
        "both tubes standing beside the rack": [
            Step("tube_a", _on_table(0.10, -0.04), settle_s=2.0, not_yet=["tube_a_in_rack"], success=False),
            Step("tube_b", _on_table(-0.10, -0.04), settle_s=2.0, not_yet=["tube_b_in_rack"], success=False),
        ],
    }


# 2. A reagent bottle onto a shelf.


def _bottle_layout(rng):
    return {"bottle": _jit(rng, -0.12, 0.09), "shelf": _jit(rng, -0.21, -0.06, 0.01)}


def _bottle_build(world, lay):
    return {
        "bottle": props.bottle(world, "bottle", *lay["bottle"]),
        "shelf": props.platform(world, "shelf", *lay["shelf"]),
    }


def _bottle_scoring(specs, z0):
    on_shelf = resting_on("bottle", specs["shelf"])
    stages = [
        Stage("bottle_lifted", lifted("bottle", z0["bottle"])),
        Stage("bottle_over_shelf", over("bottle", specs["shelf"])),
        Stage("bottle_on_shelf", on_shelf),
    ]
    return stages, on_shelf


def _bottle_oracle(specs):
    s = specs["shelf"]
    return [
        Step("bottle", _raised("bottle"), pin_s=1.0, expect=["bottle_lifted"], not_yet=["bottle_over_shelf"], success=False),
        Step("bottle", _at(s["x"], s["y"], s["top"] + 0.05), pin_s=1.0, expect=["bottle_over_shelf"],
             not_yet=["bottle_on_shelf"], success=False, note="held over the shelf"),
        Step("bottle", _at(s["x"], s["y"], s["top"] + 0.002), settle_s=3.0, expect=["bottle_on_shelf"], success=True,
             note="set down on the shelf"),
    ]


def _bottle_traps(specs):
    s = specs["shelf"]
    return {
        "bottle lying on its side on the shelf": [
            Step("bottle", _at(s["x"], s["y"], s["top"] + 0.028, 0.0, np.pi / 2), settle_s=4.0,
                 not_yet=["bottle_on_shelf"], success=False),
        ],
        "bottle on the table next to the shelf": [
            Step("bottle", _on_table(s["x"] + s["half"][0] + 0.05, s["y"]), settle_s=2.5, not_yet=["bottle_on_shelf"],
                 success=False),
        ],
        "bottle held over the shelf, never set down": [
            Step("bottle", _at(s["x"], s["y"], s["top"] + 0.04), pin_s=4.0, not_yet=["bottle_on_shelf"], success=False),
        ],
    }


# 3. A deep-well plate onto a reader tray.


def _plate_layout(rng):
    return {"plate": (*_jit(rng, 0.14, 0.07, 0.012), rng.uniform(-0.12, 0.12)), "tray": (*_jit(rng, 0.0, -0.07, 0.008), 0.0)}


def _plate_build(world, lay):
    return {
        "plate": props.deep_well_plate(world, "plate", *lay["plate"]),
        "tray": props.plate_nest(world, "tray", *lay["tray"]),
    }


def _plate_scoring(specs, z0):
    tray = specs["tray"]
    seated = seated_in_nest("plate", specs["plate"], "tray", tray, TABLE_Z)
    above = {"x": tray["x"], "y": tray["y"], "half": (0.03, 0.03), "top": tray["floor"]}
    stages = [
        Stage("plate_lifted", lifted("plate", z0["plate"], by=0.025)),
        Stage("plate_over_tray", over("plate", above, clear=0.015)),
        Stage("plate_in_tray", seated),
    ]
    return stages, seated


def _plate_oracle(specs):
    t = specs["tray"]
    return [
        Step("plate", _raised("plate"), pin_s=1.0, expect=["plate_lifted"], not_yet=["plate_over_tray"], success=False),
        Step("plate", _at(t["x"], t["y"], t["floor"] + 0.06, t["yaw"]), pin_s=1.0, expect=["plate_over_tray"],
             not_yet=["plate_in_tray"], success=False, note="held over the tray"),
        Step("plate", _at(t["x"], t["y"], t["floor"] + 0.002, t["yaw"]), settle_s=3.0, expect=["plate_in_tray"],
             success=True, note="set into the tray"),
    ]


def _plate_traps(specs):
    t = specs["tray"]
    return {
        "plate turned a quarter turn, sitting across the tray": [
            Step("plate", _at(t["x"], t["y"], t["floor"] + 0.02, t["yaw"] + np.pi / 2), settle_s=4.0,
                 not_yet=["plate_in_tray"], success=False),
        ],
        "plate half on the tray": [
            Step("plate", _at(t["x"] + 0.045, t["y"], t["floor"] + 0.02, t["yaw"]), settle_s=4.0,
                 not_yet=["plate_in_tray"], success=False),
        ],
        "plate on the table beside the tray": [
            Step("plate", _on_table(t["x"] + 0.19, t["y"]), settle_s=2.5, not_yet=["plate_in_tray"], success=False),
        ],
    }


# 4. Sort tubes by cap colour.


def _sort_layout(rng):
    spots = [_jit(rng, 0.05, 0.11, 0.01), _jit(rng, -0.05, 0.11, 0.01)]
    if rng.random() < 0.5:  # half the benches have each tube nearer the wrong tray
        spots.reverse()
    return {"tube_red": spots[0], "tube_blue": spots[1], "tray_left": (0.20, -0.10), "tray_right": (-0.20, -0.10)}


def _sort_build(world, lay):
    return {
        "tube_red": props.falcon_tube(world, "tube_red", *lay["tube_red"], cap_rgba=".85 .15 .12 1"),
        "tube_blue": props.falcon_tube(world, "tube_blue", *lay["tube_blue"], cap_rgba=".12 .3 .85 1"),
        "tray_left": props.open_tray(world, "tray_left", *lay["tray_left"]),
        "tray_right": props.open_tray(world, "tray_right", *lay["tray_right"]),
    }


def _sort_scoring(specs, z0):
    red_ok = inside_box("tube_red", specs["tray_left"])
    blue_ok = inside_box("tube_blue", specs["tray_right"])
    stages = [
        Stage("red_lifted", lifted("tube_red", z0["tube_red"])),
        Stage("red_in_left_tray", red_ok),
        Stage("blue_lifted", lifted("tube_blue", z0["tube_blue"])),
        Stage("blue_in_right_tray", blue_ok),
    ]
    return stages, lambda w: red_ok(w) and blue_ok(w)


def _sort_oracle(specs):
    return [
        Step("tube_red", _raised("tube_red"), pin_s=1.0, expect=["red_lifted"], not_yet=["red_in_left_tray"], success=False),
        Step("tube_red", _in_tray(specs["tray_left"]), settle_s=2.5, expect=["red_in_left_tray"],
             not_yet=["blue_in_right_tray"], success=False),
        Step("tube_blue", _raised("tube_blue"), pin_s=1.0, expect=["blue_lifted"], not_yet=["blue_in_right_tray"], success=False),
        Step("tube_blue", _in_tray(specs["tray_right"]), settle_s=3.5, expect=["blue_in_right_tray"], success=True),
    ]


def _sort_traps(specs):
    left, right = specs["tray_left"], specs["tray_right"]
    return {
        "tubes in the wrong trays": [
            Step("tube_red", _in_tray(right), settle_s=2.5, not_yet=["red_in_left_tray"], success=False),
            Step("tube_blue", _in_tray(left), settle_s=3.5, not_yet=["blue_in_right_tray"], success=False),
        ],
        "both tubes in the left tray": [
            Step("tube_red", _in_tray(left, dx=0.025), settle_s=2.5, expect=["red_in_left_tray"], success=False),
            Step("tube_blue", _in_tray(left, dx=-0.025), settle_s=3.5, not_yet=["blue_in_right_tray"], success=False),
        ],
    }


# 5. Used tubes into the waste bin.


def _waste_layout(rng):
    return {"tube_a": _jit(rng, 0.15, 0.10), "tube_b": _jit(rng, -0.13, 0.09), "bin": _jit(rng, 0.0, -0.06, 0.01)}


def _waste_build(world, lay):
    return {
        "tube_a": props.falcon_tube(world, "tube_a", *lay["tube_a"], capped=False, liquid_rgba=".75 .78 .8 .5"),
        "tube_b": props.falcon_tube(world, "tube_b", *lay["tube_b"], capped=False, liquid_rgba=".75 .78 .8 .5"),
        "bin": props.waste_bin(world, "bin", *lay["bin"]),
    }


def _waste_scoring(specs, z0):
    binned = {t: inside_box(t, specs["bin"]) for t in ("tube_a", "tube_b")}
    stages = []
    for t in ("tube_a", "tube_b"):
        stages.append(Stage(f"{t}_lifted", lifted(t, z0[t])))
        stages.append(Stage(f"{t}_in_bin", binned[t]))
    return stages, lambda w: all(test(w) for test in binned.values())


def _waste_oracle(specs):
    b = specs["bin"]
    return [
        Step("tube_a", _raised("tube_a"), pin_s=1.0, expect=["tube_a_lifted"], not_yet=["tube_a_in_bin"], success=False),
        Step("tube_a", _at(b["x"] + 0.03, b["y"], b["floor"] + 0.03), settle_s=3.0, expect=["tube_a_in_bin"],
             not_yet=["tube_b_in_bin"], success=False, note="dropped into the bin"),
        Step("tube_b", _raised("tube_b"), pin_s=1.0, expect=["tube_b_lifted"], not_yet=["tube_b_in_bin"], success=False),
        Step("tube_b", _at(b["x"] - 0.03, b["y"], b["floor"] + 0.03), settle_s=4.0, expect=["tube_b_in_bin"], success=True),
    ]


def _waste_traps(specs):
    b = specs["bin"]
    return {
        "one tube in the bin, one left out": [
            Step("tube_a", _at(b["x"], b["y"], b["floor"] + 0.03), settle_s=4.0, expect=["tube_a_in_bin"],
                 not_yet=["tube_b_in_bin"], success=False),
        ],
        "tubes dropped next to the bin": [
            Step("tube_a", _on_table(b["x"] + b["half"][0] + 0.05, b["y"]), settle_s=2.0, not_yet=["tube_a_in_bin"], success=False),
            Step("tube_b", _on_table(b["x"] - b["half"][0] - 0.05, b["y"]), settle_s=2.0, not_yet=["tube_b_in_bin"], success=False),
        ],
    }


# 6. Stack two tip boxes.


def _stack_layout(rng):
    return {
        "box_a": (*_jit(rng, -0.13, 0.07, 0.012), rng.uniform(-0.15, 0.15)),
        "box_b": (*_jit(rng, 0.03, -0.05, 0.012), rng.uniform(-0.15, 0.15)),
    }


def _stack_build(world, lay):
    return {
        "box_a": props.tip_box(world, "box_a", *lay["box_a"]),
        "box_b": props.tip_box(world, "box_b", *lay["box_b"], rgba=".25 .45 .75 1"),
    }


def _stack_scoring(specs, z0):
    a_on_b = stacked_on("box_a", "box_b", specs["box_b"], TABLE_Z)
    b_on_a = stacked_on("box_b", "box_a", specs["box_a"], TABLE_Z)

    def above(top, bottom):
        def test(w):
            rel = w.local(bottom, w.pos(top))
            return abs(rel[0]) < 0.03 and abs(rel[1]) < 0.03 and rel[2] > specs[bottom]["height"] + 0.005

        return test

    a_above, b_above = above("box_a", "box_b"), above("box_b", "box_a")
    up_a, up_b = lifted("box_a", z0["box_a"]), lifted("box_b", z0["box_b"])

    def stacked(w):
        return a_on_b(w) or b_on_a(w)

    stages = [
        Stage("a_box_lifted", lambda w: up_a(w) or up_b(w)),
        Stage("box_over_the_other", lambda w: a_above(w) or b_above(w)),
        Stage("boxes_stacked", stacked),
    ]
    return stages, stacked


def _stack_oracle(specs):
    return [
        Step("box_a", _raised("box_a"), pin_s=1.0, expect=["a_box_lifted"], not_yet=["box_over_the_other"], success=False),
        Step("box_a", _onto("box_b", specs["box_b"], gap=0.04), pin_s=1.0, expect=["box_over_the_other"],
             not_yet=["boxes_stacked"], success=False, note="held over the other box"),
        Step("box_a", _onto("box_b", specs["box_b"]), settle_s=3.0, expect=["boxes_stacked"], success=True),
    ]


def _stack_traps(specs):
    return {
        "boxes side by side": [
            Step("box_a", lambda w: (w.pos("box_b") + np.array([0.0, 0.10, 0.002]), mat_to_quat(w.rot("box_b"))),
                 settle_s=2.5, not_yet=["boxes_stacked"], success=False),
        ],
        "stacked 5 cm off centre": [
            Step("box_a", _onto("box_b", specs["box_b"], dx=0.05), settle_s=4.0, not_yet=["boxes_stacked"], success=False),
        ],
    }


# 7. Carry a full rack with both hands.


def _carry_layout(rng):
    return {"rack": (*_jit(rng, 0.0, 0.08, 0.01), rng.uniform(-0.08, 0.08)), "mat": (0.0, -0.08)}


def _carry_build(world, lay):
    return {
        "mat": props.mat(world, "mat", *lay["mat"], half=(0.13, 0.065), rgba=".42 .45 .52 1"),
        "rack": props.carry_rack(world, "rack", *lay["rack"]),
    }


def _carry_scoring(specs, z0):
    m = specs["mat"]
    spot = {"x": m["x"], "y": m["y"], "half": (0.03, 0.03), "top": TABLE_Z}
    on_mat = resting_on("rack", spot, margin=0.0, max_tilt=5.0, z_tol=0.006)
    stages = [
        Stage("rack_lifted_level", lifted_level("rack", z0["rack"])),
        Stage("rack_over_mat", over("rack", spot, clear=0.01)),
        Stage("rack_on_mat", on_mat),
    ]
    return stages, on_mat, ["rack_lifted_level"]  # pushed along the table does not count: it has to be carried


def _carry_oracle(specs):
    m = specs["mat"]
    return [
        Step("rack", _raised("rack", by=0.04), pin_s=1.0, expect=["rack_lifted_level"], not_yet=["rack_over_mat"], success=False),
        Step("rack", _at(m["x"], m["y"], TABLE_Z + 0.04), pin_s=1.0, expect=["rack_over_mat"], not_yet=["rack_on_mat"],
             success=False, note="carried over the mat"),
        Step("rack", _at(m["x"], m["y"], TABLE_Z + 0.002), settle_s=3.0, expect=["rack_on_mat"], success=True),
    ]


def _carry_traps(specs):
    m = specs["mat"]
    return {
        "pushed across the table onto the mat, never lifted": [
            Step("rack", _at(m["x"], m["y"], TABLE_Z + 0.002), settle_s=3.5, expect=["rack_on_mat"],
                 not_yet=["rack_lifted_level"], success=False),
        ],
        "lifted by one end, badly tilted, then set on the mat": [
            Step("rack", lambda w: (w.pos("rack") + np.array([0.0, 0.0, 0.08]), yaw_tilt_quat(0.0, 0.0, 0.5)), pin_s=1.5,
                 not_yet=["rack_lifted_level"], success=False),
            Step("rack", _at(m["x"], m["y"], TABLE_Z + 0.002), settle_s=3.5, expect=["rack_on_mat"], success=False),
        ],
        "carried, but set down beside the mat": [
            Step("rack", _raised("rack", by=0.04), pin_s=1.0, expect=["rack_lifted_level"], success=False),
            Step("rack", _at(m["x"] + 0.12, m["y"], TABLE_Z + 0.002), settle_s=3.0, not_yet=["rack_on_mat"], success=False),
        ],
    }


# 8. Hand a tube from one arm to the other.


def _handover_layout(rng):
    return {"tube": _jit(rng, 0.36, -0.10, 0.01), "tray": (-0.36, -0.10)}


def _handover_build(world, lay):
    return {
        "tube": props.falcon_tube(world, "tube", *lay["tube"]),
        "tray": props.open_tray(world, "tray", *lay["tray"]),
    }


def _handover_scoring(specs, z0):
    in_tray = inside_box("tube", specs["tray"])
    stages = [
        Stage("tube_lifted", lifted("tube", z0["tube"])),
        Stage("right_hand_has_it", in_hand_of("tube", specs["tube"], "right", TABLE_Z)),
        Stage("tube_in_tray", in_tray),
    ]
    return stages, in_tray, ["right_hand_has_it"]  # the request is a hand-over, not a long reach


def _handover_oracle(specs):
    tube, tray = specs["tube"], specs["tray"]

    def at_right_hand(w):  # lying along x through the right arm's grasp point, between its open fingers
        return w.tcp("right") - np.array([tube["height"] / 2, 0.0, 0.0]), yaw_tilt_quat(0.0, 0.0, np.pi / 2)

    return [
        Step("tube", _raised("tube"), pin_s=1.0, expect=["tube_lifted"], not_yet=["right_hand_has_it"], success=False),
        Step("tube", at_right_hand, pin_s=1.0, expect=["right_hand_has_it"], not_yet=["tube_in_tray"], success=False,
             note="at the right hand, left hand away"),
        Step("tube", _in_tray(tray), settle_s=3.0, expect=["tube_in_tray"], success=True),
    ]


def _handover_traps(specs):
    tray = specs["tray"]
    return {
        "put straight into the tray with no hand-over": [
            Step("tube", _raised("tube"), pin_s=1.0, expect=["tube_lifted"], success=False),
            Step("tube", _in_tray(tray), settle_s=3.5, expect=["tube_in_tray"], not_yet=["right_hand_has_it"], success=False),
        ],
        "tube set down next to the tray": [
            Step("tube", _on_table(tray["x"] + tray["half"][0] + 0.06, tray["y"]), settle_s=2.5, not_yet=["tube_in_tray"],
                 success=False),
        ],
    }


# 9. A plate into a hotel, at three shelf heights.

SHELF_WORDS = ("bottom", "middle", "top")


def _hotel_layout(rng):
    return {"plate": (*_jit(rng, 0.16, 0.07, 0.01), np.pi / 2 + rng.uniform(-0.08, 0.08)), "hotel": (0.16, -0.16)}


def _hotel_build(world, lay):
    return {
        "hotel": props.plate_hotel(world, "hotel", *lay["hotel"]),
        "plate": props.microplate(world, "plate", *lay["plate"]),
    }


def _hotel_scoring(k):
    def scoring(specs, z0):
        hotel = specs["hotel"]
        level = hotel["levels"][k]
        placed = on_shelf("plate", hotel, level)
        stages = [
            Stage("plate_lifted", lifted("plate", z0["plate"], by=0.02)),
            Stage("plate_lined_up_at_shelf", lined_up_at_shelf("plate", hotel, level)),
            Stage("plate_on_shelf", placed),
        ]
        return stages, placed

    return scoring


def _hotel_oracle(k):
    def oracle(specs):
        h = specs["hotel"]
        level = h["levels"][k]
        return [
            Step("plate", _raised("plate", by=0.04), pin_s=1.0, expect=["plate_lifted"], success=False),
            Step("plate", _at(h["x"], h["y"] + 0.14, level + 0.006, np.pi / 2), pin_s=1.0,
                 expect=["plate_lined_up_at_shelf"], not_yet=["plate_on_shelf"], success=False, note="held in front of the shelf"),
            Step("plate", _at(h["x"], h["y"] + 0.004, level + 0.002, np.pi / 2), settle_s=3.0, expect=["plate_on_shelf"],
                 success=True, note="slid onto the shelf"),
        ]

    return oracle


def _hotel_traps(k):
    def traps(specs):
        h = specs["hotel"]
        wrong = h["levels"][(k + 1) % 3]
        return {
            "plate on the wrong shelf": [
                Step("plate", _at(h["x"], h["y"] + 0.004, wrong + 0.002, np.pi / 2), settle_s=3.0,
                     not_yet=["plate_on_shelf"], success=False),
            ],
            "plate left on the table in front of the hotel": [
                Step("plate", _on_table(h["x"], h["y"] + 0.16, np.pi / 2), settle_s=2.5, not_yet=["plate_on_shelf"],
                     success=False),
            ],
            "plate only a third of the way in": [
                Step("plate", _at(h["x"], h["y"] + 0.085, h["levels"][k] + 0.002, np.pi / 2), settle_s=3.0,
                     not_yet=["plate_on_shelf"], success=False),
            ],
        }

    return traps


def _hotel_task(k):
    word = SHELF_WORDS[k]
    return Task(
        name=f"plate_to_hotel_{word}", title=f"Put a plate on the {word} shelf of the hotel", family="plates",
        rule=f"The plate lies flat on the {word} shelf, at most 3 cm short of fully in, hands off. Another shelf does not count.",
        prompt=f"Put the plate on the {word} shelf.",
        variants={"terse": f"Plate on the {word} shelf.",
                  "precise": f"Pick up the white plate and slide it onto the {word} shelf of the gray plate hotel."},
        seconds=180, layout=_hotel_layout, build=_hotel_build, scoring=_hotel_scoring(k),
        movable=("plate",), oracle=_hotel_oracle(k), traps=_hotel_traps(k),
    )


# 10. Stack two assay plates.


def _plates_layout(rng):
    return {
        "plate_a": (*_jit(rng, -0.12, 0.07, 0.012), rng.uniform(-0.12, 0.12)),
        "plate_b": (*_jit(rng, 0.04, -0.04, 0.012), rng.uniform(-0.12, 0.12)),
    }


def _plates_build(world, lay):
    return {
        "plate_a": props.microplate(world, "plate_a", *lay["plate_a"]),
        "plate_b": props.microplate(world, "plate_b", *lay["plate_b"]),
    }


def _plates_scoring(specs, z0):
    a_on_b = stacked_on("plate_a", "plate_b", specs["plate_b"], TABLE_Z, xy_tol=0.012)
    b_on_a = stacked_on("plate_b", "plate_a", specs["plate_a"], TABLE_Z, xy_tol=0.012)

    def above(top, bottom):
        def test(w):
            rel = w.local(bottom, w.pos(top))
            return abs(rel[0]) < 0.03 and abs(rel[1]) < 0.03 and rel[2] > specs[bottom]["height"] + 0.005

        return test

    a_above, b_above = above("plate_a", "plate_b"), above("plate_b", "plate_a")
    up_a, up_b = lifted("plate_a", z0["plate_a"], by=0.02), lifted("plate_b", z0["plate_b"], by=0.02)

    def stacked(w):
        return a_on_b(w) or b_on_a(w)

    stages = [
        Stage("a_plate_lifted", lambda w: up_a(w) or up_b(w)),
        Stage("plate_over_the_other", lambda w: a_above(w) or b_above(w)),
        Stage("plates_stacked", stacked),
    ]
    return stages, stacked


def _plates_oracle(specs):
    return [
        Step("plate_a", _raised("plate_a"), pin_s=1.0, expect=["a_plate_lifted"], not_yet=["plate_over_the_other"], success=False),
        Step("plate_a", _onto("plate_b", specs["plate_b"], gap=0.04), pin_s=1.0, expect=["plate_over_the_other"],
             not_yet=["plates_stacked"], success=False),
        Step("plate_a", _onto("plate_b", specs["plate_b"]), settle_s=3.0, expect=["plates_stacked"], success=True),
    ]


def _plates_traps(specs):
    return {
        "plates side by side": [
            Step("plate_a", lambda w: (w.pos("plate_b") + np.array([0.0, 0.10, 0.002]), mat_to_quat(w.rot("plate_b"))),
                 settle_s=2.5, not_yet=["plates_stacked"], success=False),
        ],
        "stacked 3 cm off": [
            Step("plate_a", _onto("plate_b", specs["plate_b"], dx=0.03), settle_s=3.5, not_yet=["plates_stacked"], success=False),
        ],
        "stacked crosswise": [
            Step("plate_a", lambda w: (w.pos("plate_b") + np.array([0.0, 0.0, specs["plate_b"]["height"] + 0.002]),
                                       yaw_tilt_quat(w.yaw_deg("plate_b") * np.pi / 180 + np.pi / 2)),
                 settle_s=3.5, not_yet=["plates_stacked"], success=False),
        ],
    }


# 11. Take the top plate off a stack.


def _unstack_layout(rng):
    return {"stack": (*_jit(rng, 0.15, 0.07, 0.01), rng.uniform(-0.1, 0.1)), "tray": (*_jit(rng, 0.0, -0.07, 0.008), 0.0)}


def _unstack_build(world, lay):
    x, y, yaw = lay["stack"]
    h = 0.0144
    return {
        "plate_1": props.microplate(world, "plate_1", x, y, yaw),
        "plate_2": props.microplate(world, "plate_2", x, y, yaw, z=TABLE_Z + h + 0.0005),
        "plate_3": props.microplate(world, "plate_3", x, y, yaw, z=TABLE_Z + 2 * h + 0.001, rgba=".97 .97 .96 1"),
        "tray": props.plate_nest(world, "tray", *lay["tray"]),
    }


def _unstack_scoring(specs, z0):
    tray = specs["tray"]
    seated = seated_in_nest("plate_3", specs["plate_3"], "tray", tray, TABLE_Z)
    above = {"x": tray["x"], "y": tray["y"], "half": (0.03, 0.03), "top": tray["floor"]}
    start = {}

    def rest_in_place(w):
        for n in ("plate_1", "plate_2"):
            start.setdefault(n, w.pos(n))
            if np.linalg.norm(w.pos(n)[:2] - start[n][:2]) > 0.03 or abs(w.pos(n)[2] - start[n][2]) > 0.006:
                return False
        return True

    def only_top_lifted(w):
        rest_in_place(w)  # remember where the rest of the stack started
        return w.pos("plate_3")[2] > z0["plate_3"] + 0.02 and w.pos("plate_2")[2] < z0["plate_2"] + 0.008

    stages = [
        Stage("top_plate_lifted_alone", only_top_lifted),
        Stage("plate_over_tray", over("plate_3", above, clear=0.015)),
        Stage("plate_in_tray", seated),
    ]
    return stages, lambda w: seated(w) and rest_in_place(w)


def _unstack_oracle(specs):
    t = specs["tray"]
    return [
        Step("plate_3", _raised("plate_3", by=0.05), pin_s=1.0, expect=["top_plate_lifted_alone"], success=False),
        Step("plate_3", _at(t["x"], t["y"], t["floor"] + 0.06, t["yaw"]), pin_s=1.0, expect=["plate_over_tray"],
             not_yet=["plate_in_tray"], success=False),
        Step("plate_3", _at(t["x"], t["y"], t["floor"] + 0.002, t["yaw"]), settle_s=3.0, expect=["plate_in_tray"], success=True),
    ]


def _unstack_traps(specs):
    t = specs["tray"]
    return {
        "top plate in the tray, but the rest of the stack knocked away": [
            Step("plate_2", lambda w: (w.pos("plate_1") + np.array([0.0, 0.12, 0.002]), None), settle_s=1.5, success=False),
            Step("plate_3", _at(t["x"], t["y"], t["floor"] + 0.002, t["yaw"]), settle_s=3.5, expect=["plate_in_tray"],
                 success=False),
        ],
        "two plates carried to the tray together": [
            Step("plate_2", _at(t["x"], t["y"], t["floor"] + 0.002, t["yaw"]), settle_s=0.0),
            Step("plate_3", _at(t["x"], t["y"], t["floor"] + 0.002 + 0.0146, t["yaw"]), settle_s=3.5,
                 not_yet=["plate_in_tray"], success=False),
        ],
    }


# 12. Small tubes into a rack.


def _epp_layout(rng):
    return {
        "rack": (*_jit(rng, 0.0, -0.03, 0.01), rng.uniform(-0.1, 0.1)),
        "epp_a": (*_jit(rng, -0.13, 0.10, 0.012), rng.uniform(0, np.pi)),
        "epp_b": (*_jit(rng, -0.16, 0.06, 0.012), rng.uniform(0, np.pi)),
        "epp_c": (*_jit(rng, 0.15, 0.09, 0.012), rng.uniform(0, np.pi)),
    }


def _epp_build(world, lay):
    x, y, yaw = lay["rack"]
    specs = {"rack": props.micro_rack(world, "rack", x, y, yaw=yaw)}
    for n in ("epp_a", "epp_b", "epp_c"):
        specs[n] = props.eppendorf(world, n, *lay[n])
    return specs


def _epp_scoring(specs, z0):
    racked = {t: in_rack_well(t, "rack", specs["rack"], tol=0.004) for t in ("epp_a", "epp_b", "epp_c")}
    stages = []
    for t in racked:
        stages.append(Stage(f"{t}_lifted", lifted(t, z0[t], by=0.03)))
        stages.append(Stage(f"{t}_in_rack", racked[t]))
    return stages, lambda w: all(test(w) for test in racked.values())


def _epp_oracle(specs):
    rack = specs["rack"]
    steps = []
    for i, t in enumerate(("epp_a", "epp_b", "epp_c")):
        last = i == 2
        steps.append(Step(t, _raised(t, by=0.06), pin_s=1.0, expect=[f"{t}_lifted"], not_yet=[f"{t}_in_rack"], success=False))
        steps.append(Step(t, _in_well(rack, i * 9, drop=0.002), settle_s=4.0 if last else 2.5, expect=[f"{t}_in_rack"],
                          success=True if last else False))
    return steps


def _epp_traps(specs):
    rack = specs["rack"]

    def on_top(w):  # lying across the top of the rack
        return w.pos("rack") + w.rot("rack") @ np.array([-0.02, 0.0, rack["height"] + 0.008]), yaw_tilt_quat(0.0, 0.0, np.pi / 2)

    return {
        "two tubes racked, one left out": [
            Step("epp_a", _in_well(rack, 0, drop=0.002), settle_s=2.5, expect=["epp_a_in_rack"]),
            Step("epp_b", _in_well(rack, 5, drop=0.002), settle_s=3.5, expect=["epp_b_in_rack"], not_yet=["epp_c_in_rack"], success=False),
        ],
        "tube lying on top of the rack": [
            Step("epp_a", on_top, settle_s=3.5, not_yet=["epp_a_in_rack"], success=False),
        ],
    }


# 13. A loaded rack into a box.


def _box_layout(rng):
    return {"rack": (*_jit(rng, -0.10, 0.07, 0.01), rng.uniform(-0.1, 0.1)), "box": _jit(rng, 0.10, -0.10, 0.008)}


def _box_build(world, lay):
    x, y, yaw = lay["rack"]
    rack = props.tube_rack(world, "rack", x, y, nx=3, ny=2, yaw=yaw)
    c, s = np.cos(yaw), np.sin(yaw)
    spots = []
    for k in (0, 5):
        wx, wy = rack["wells"][k]
        spots.append((x + c * wx - s * wy, y + s * wx + c * wy))
    return {
        "box": props.storage_box(world, "box", *lay["box"]),
        "rack": rack,
        "tube_a": props.falcon_tube(world, "tube_a", *spots[0], z=TABLE_Z + rack["floor"] + 0.001),
        "tube_b": props.falcon_tube(world, "tube_b", *spots[1], z=TABLE_Z + rack["floor"] + 0.001),
    }


def _box_scoring(specs, z0):
    box, rack = specs["box"], specs["rack"]
    slack_x = box["half"][0] - rack["length"] / 2 + 0.004
    slack_y = box["half"][1] - rack["width"] / 2 + 0.004
    in_box = inside_footprint("rack", box, slack_x, slack_y)
    tubes_ok = [in_rack_well(t, "rack", rack) for t in ("tube_a", "tube_b")]
    above = {"x": box["x"], "y": box["y"], "half": (0.04, 0.04), "top": box["rim"]}

    def done(w):
        return in_box(w) and all(test(w) for test in tubes_ok)

    stages = [
        Stage("rack_lifted_level", lifted_level("rack", z0["rack"], by=0.03, max_tilt=20.0)),
        Stage("rack_over_box", over("rack", above, clear=0.0)),
        Stage("rack_in_box_tubes_still_racked", done),
    ]
    return stages, done


def _box_oracle(specs):
    box, rack = specs["box"], specs["rack"]
    return [
        Step("rack", _raised("rack", by=0.05), pin_s=1.0, expect=["rack_lifted_level"], not_yet=["rack_over_box"], success=False),
        Step("rack", _at(box["x"], box["y"], box["rim"] + 0.02), pin_s=1.0, expect=["rack_over_box"], success=False),
        Step("rack", _at(box["x"], box["y"], box["floor"] + 0.002), settle_s=1.5, not_yet=["rack_in_box_tubes_still_racked"], success=False,
             note="rack in the box, tubes not yet back in it"),
        Step("tube_a", _in_well(rack, 0), settle_s=1.5, success=False),
        Step("tube_b", _in_well(rack, 5), settle_s=3.5, expect=["rack_in_box_tubes_still_racked"], success=True),
    ]


def _box_traps(specs):
    box, rack = specs["box"], specs["rack"]
    return {
        "rack in the box, tubes spilled on the table": [
            Step("rack", _at(box["x"], box["y"], box["floor"] + 0.002), settle_s=4.0,
                 not_yet=["rack_in_box_tubes_still_racked"], success=False),
        ],
        "rack set down next to the box": [
            Step("rack", _at(box["x"] - box["half"][0] - 0.09, box["y"], TABLE_Z + 0.002), settle_s=1.0),
            Step("tube_a", _in_well(rack, 0), settle_s=1.0),
            Step("tube_b", _in_well(rack, 5), settle_s=3.0, not_yet=["rack_in_box_tubes_still_racked"], success=False),
        ],
    }


TASKS = {
    "tubes_to_rack": Task(
        name="tubes_to_rack", title="Rack the tubes", family="move and sort",
        rule="Both 50 mL tubes stand in wells of the rack, hands off.",
        prompt="Put the tubes in the rack.",
        variants={"terse": "Rack the tubes.", "precise": "Pick up each tube and place it upright into an empty well of the blue rack."},
        seconds=240, layout=_tubes_to_rack_layout, build=_tubes_to_rack_build, scoring=_tubes_to_rack_scoring,
        movable=("rack", "tube_a", "tube_b"), oracle=_tubes_to_rack_oracle, traps=_tubes_to_rack_traps,
    ),
    "bottle_to_shelf": Task(
        name="bottle_to_shelf", title="Put a reagent bottle on the shelf", family="move and sort",
        rule="The bottle stands upright on the platform, hands off.",
        prompt="Put the bottle on the gray platform.",
        variants={"terse": "Bottle on the platform.", "precise": "Pick up the white bottle with the blue cap and stand it upright on top of the gray platform."},
        seconds=120, layout=_bottle_layout, build=_bottle_build, scoring=_bottle_scoring,
        movable=("bottle",), oracle=_bottle_oracle, traps=_bottle_traps,
    ),
    "plate_to_tray": Task(
        name="plate_to_tray", title="Load a plate onto the reader tray", family="move and sort",
        rule="The deep-well plate sits flat in the tray pocket, the right way round, hands off.",
        prompt="Put the plate on the black tray.",
        variants={"terse": "Plate on the tray.", "precise": "Pick up the white deep well plate and set it flat inside the black tray, lined up with its corners."},
        seconds=150, layout=_plate_layout, build=_plate_build, scoring=_plate_scoring,
        movable=("plate",), oracle=_plate_oracle, traps=_plate_traps,
    ),
    "sort_by_cap": Task(
        name="sort_by_cap", title="Sort tubes by cap colour", family="move and sort",
        rule="The red tube is in the left tray and the blue tube is in the right tray, hands off.",
        prompt="Put the red tube in the left tray and the blue tube in the right tray.",
        variants={"terse": "Red tube left tray, blue tube right tray.", "precise": "Pick up the tube with the red cap and put it in the tray on the left. Then pick up the tube "
                             "with the blue cap and put it in the tray on the right."},
        seconds=240, layout=_sort_layout, build=_sort_build, scoring=_sort_scoring,
        movable=("tube_red", "tube_blue"), oracle=_sort_oracle, traps=_sort_traps,
    ),
    "tubes_to_waste": Task(
        name="tubes_to_waste", title="Bin the used tubes", family="move and sort",
        rule="Both open tubes are inside the bin, hands off.",
        prompt="Throw the used tubes into the waste bin.",
        variants={"terse": "Bin the tubes.", "precise": "Pick up each open tube and drop it into the yellow bin."},
        seconds=240, layout=_waste_layout, build=_waste_build, scoring=_waste_scoring,
        movable=("tube_a", "tube_b"), oracle=_waste_oracle, traps=_waste_traps,
    ),
    "stack_tip_boxes": Task(
        name="stack_tip_boxes", title="Stack the tip boxes", family="stock and tidy",
        rule="One tip box sits squarely on the other, the same way round, hands off.",
        prompt="Stack the two tip boxes.",
        variants={"terse": "Stack the boxes.", "precise": "Pick up one tip box and set it squarely on top of the other tip box."},
        seconds=150, layout=_stack_layout, build=_stack_build, scoring=_stack_scoring,
        movable=("box_a", "box_b"), oracle=_stack_oracle, traps=_stack_traps,
    ),
    "rack_carry": Task(
        name="rack_carry", title="Carry a full rack with both hands", family="two hands",
        rule="The rack rests on the mat after a level lift. A rack pushed along the table does not count.",
        prompt="Pick up the tube rack with both hands and put it on the gray mat.",
        variants={"terse": "Both hands: rack onto the mat.", "precise": "Grip the green tube rack by its two end handles, one with each gripper, lift it level, "
                             "and set it down on the gray mat."},
        seconds=150, layout=_carry_layout, build=_carry_build, scoring=_carry_scoring,
        movable=("rack",), oracle=_carry_oracle, traps=_carry_traps,
    ),
    "tube_handover": Task(
        name="tube_handover", title="Pass a tube from hand to hand", family="two hands",
        rule="The tube is in the right tray, and the right hand held it on the way. A long reach by the left arm does not count.",
        prompt="Pick up the tube with the left hand, pass it to the right hand, and put it in the tray on the right.",
        variants={"terse": "Pass the tube to the right hand, then into the tray.",
                  "plain_goal": "Move the tube into the tray on the right."},
        seconds=180, layout=_handover_layout, build=_handover_build, scoring=_handover_scoring,
        movable=("tube",), oracle=_handover_oracle, traps=_handover_traps,
    ),
    **{t.name: t for t in (_hotel_task(k) for k in (2, 1, 0))},
    "stack_plates": Task(
        name="stack_plates", title="Stack two assay plates", family="plates",
        rule="One plate sits on the other with edges lined up (within 12 mm), hands off.",
        prompt="Stack the two plates.",
        variants={"terse": "Stack the plates.", "precise": "Pick up one white plate and set it exactly on top of the other plate, edges lined up."},
        seconds=150, layout=_plates_layout, build=_plates_build, scoring=_plates_scoring,
        movable=("plate_a", "plate_b"), oracle=_plates_oracle, traps=_plates_traps,
    ),
    "unstack_plate": Task(
        name="unstack_plate", title="Take the top plate off a stack", family="plates",
        rule="The top plate sits flat in the tray, and the other two plates are still stacked where they started.",
        prompt="Take the top plate off the stack and put it on the black tray.",
        variants={"terse": "Top plate onto the tray.", "precise": "Lift only the top plate from the stack of white plates and set it flat inside the black tray. "
                             "Leave the other plates where they are."},
        seconds=150, layout=_unstack_layout, build=_unstack_build, scoring=_unstack_scoring,
        movable=("plate_1", "plate_2", "plate_3"), oracle=_unstack_oracle, traps=_unstack_traps,
    ),
    "small_tubes_to_rack": Task(
        name="small_tubes_to_rack", title="Rack the 1.5 mL tubes", family="tubes",
        rule="All three 1.5 mL tubes stand in holes of the rack, hands off.",
        prompt="Put the small tubes in the rack.",
        variants={"terse": "Rack the small tubes.", "precise": "Pick up each small tube lying on the table and stand it in a hole of the pink rack, cap up."},
        seconds=300, layout=_epp_layout, build=_epp_build, scoring=_epp_scoring,
        movable=("rack", "epp_a", "epp_b", "epp_c"), oracle=_epp_oracle, traps=_epp_traps,
    ),
    "rack_into_box": Task(
        name="rack_into_box", title="Put a loaded rack in a box", family="tubes",
        rule="The rack sits flat on the floor of the box with both tubes still in its wells, hands off.",
        prompt="Put the tube rack in the box.",
        variants={"terse": "Rack in the box.", "precise": "Pick up the blue rack with its two tubes, keep it level, and set it down inside the brown box."},
        seconds=180, layout=_box_layout, build=_box_build, scoring=_box_scoring,
        movable=("rack", "tube_a", "tube_b"), oracle=_box_oracle, traps=_box_traps,
    ),
}
