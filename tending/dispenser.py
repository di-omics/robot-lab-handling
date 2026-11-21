"""The washer-dispenser: a static instrument with its plate carrier out at the load position, drawn as a cell
seeder (pump, cassette, dispense head, keypad, wash manifold), the A1-marked plate, the cell bottle with its line to
the pump, and the scoring tests these chores need.

Frames and units follow labbench: metres, +x is the left arm's side, +y points toward the arm bases, the table top
is at TABLE_Z. The instrument frame has its origin at the nest centre on the table top, with the table's axes.
Every height constant below is measured up from the table top. Where each number comes from is in README.md.

Only the deck, housing, slot walls, carrier slab and corner guides collide. Every other part of the instrument is
drawn (contype 0, conaffinity 0, mass 0), so the look never changes what the arms and the plate can touch.

labbench's own seated_in_nest accepts a plate turned half a turn and a plate propped on a corner guide, so the
seating test here is stricter (see seated_strict).
"""

import mujoco
import numpy as np

import labbench.take as _take
from labbench import props
from labbench.sim import STEP_S, TABLE_Z, sub

## The plate: an SBS microplate, as labbench.props.microplate builds it.
PLATE_HALF = (0.0639, 0.04275)
PLATE_H = 0.0144
## Gap between the plate and the pocket walls on each side.
CLEAR = 0.002
POCKET = (PLATE_HALF[0] + CLEAR, PLATE_HALF[1] + CLEAR)
## Heights above the table: the deck top, the carrier slab on it, and the nest floor (the slab top).
DECK_TOP = 0.054
SLAB_T = 0.006
FLOOR = DECK_TOP + SLAB_T
## Corner locating guides: L shapes, each leg 4 mm thick, 12 mm long, 5 mm tall.
GUIDE_T, GUIDE_LEG, GUIDE_H = 0.004, 0.012, 0.005
## Bottom of the housing over the carrier slot: nest floor + plate + the manual's plate clearance height.
HOOD_BOTTOM = FLOOR + PLATE_H + 0.0165
## Overall size of the instrument (width, depth, height).
WIDTH, DEPTH, HEIGHT = 0.42, 0.32, 0.46
## Half size of the carrier slab, 10 mm wider than the pocket on each side.
SLAB = (POCKET[0] + 0.010, POCKET[1] + 0.010)
## Deck front edge (toward the arms) and housing front face, y in the instrument frame.
FRONT_Y = SLAB[1] + 0.015
FACE_Y = -0.125
## The slot the carrier would retract into, under the housing.
SLOT_HALF = SLAB[0] + 0.005
SLOT_BACK = FACE_Y - 0.12
BACK_Y = FRONT_Y - DEPTH
## The carrier's travel, as a keep-out box in the instrument frame: |x| limit, y range, z range above the table.
TRAVEL = {"x": SLAB[0] + 0.015, "y": (FACE_Y, FRONT_Y), "z": (DECK_TOP, FLOOR + 0.045)}
## Where the people's view looks from and what it looks at: from above the arm bases, a little in front of the
## overhead camera's pole, looking down across the bench, so the instrument's front, the nest, the mat, the cell
## bottle and both arms are all in frame and neither arm fills the foreground.
SHOW_POS = (0.00, 0.42, 0.80)  # world x, y; height above the table
SHOW_LOOK = (-0.14, -0.035, 0.12)  # offset from the nest centre; height above the table
SHOW_FOVY = 55.0  # vertical field of view, degrees

LIGHT = ".86 .87 .88 1"
DARK = ".25 .27 .30 1"
CARRIER = ".18 .19 .21 1"
GUIDE = ".45 .47 .5 1"
BLUE = ".1 .25 .7 1"
## Colours of the look, read off the manual's photos: a black base, a silver housing, black pump and head.
BASE = ".07 .07 .08 1"
SILVER = ".80 .81 .82 1"
SILVER_DK = ".72 .73 .75 1"
BLACK = ".08 .08 .09 1"
STEEL = ".72 .73 .75 1"
GRAY = ".50 .52 .55 1"
TUBE = ".93 .93 .90 .85"

## The cell bottle's line: where it runs. It leaves the side of the cap facing the instrument (between the right
## gripper's fingers, which close across y), drops to the bench at LINE_ANCHOR (offset from the bottle's spot, in the
## world), lies along the bench to the housing's right front corner, runs up that corner, along the top of the
## housing and down the face into the top of the peristaltic pump: tubing laid along surfaces, not a rod in the air.
## LINE_ROUTE and LINE_INLET are fixed points in the nest frame (m, heights above the table).
LINE_CAP = (0.020, 0.0, 0.091)  # on the bottle, from its underside centre
LINE_ANCHOR = (0.085, 0.0, 0.003)  # from the spot, on the bench
LINE_ROUTE = ((-0.2125, -0.135, 0.003), (-0.2125, -0.135, 0.465), (0.150, -0.135, 0.465), (0.150, -0.121, 0.461))
LINE_INLET = (0.150, -0.121, 0.262)  # inside the pump body, 8 mm below its top
LINE_WIDTH = 0.003
## The spot the bottle stands on: a green disc on the bench.
SPOT_R = 0.034


def box(parent, name, x0, x1, y0, y1, z0, z1, rgba=LIGHT, visual=False):
    """An axis-aligned box from its corner coordinates. A visual box neither collides nor weighs anything."""
    attrs = dict(type="box", size=f"{abs(x1 - x0) / 2} {abs(y1 - y0) / 2} {abs(z1 - z0) / 2}",
                 pos=f"{(x0 + x1) / 2} {(y0 + y1) / 2} {(z0 + z1) / 2}", rgba=rgba)
    if name:  # name=None would be written as the string "None" and clash
        attrs["name"] = name
    if visual:
        attrs.update(contype=0, conaffinity=0, mass=0)
    return sub(parent, "geom", **attrs)


def rod(parent, a, b, radius, rgba, kind="cylinder"):
    """A visual cylinder (or capsule) from point a to point b, in metres in the parent's frame."""
    return sub(parent, "geom", type=kind, fromto=" ".join(str(v) for v in (*a, *b)), size=radius,
               contype=0, conaffinity=0, mass=0, rgba=rgba)


def _mm_box(parent, x0, x1, y0, y1, z0, z1, rgba):
    """A visual box from corners given in millimetres (the look is drawn in mm to match the geometry table)."""
    return box(parent, None, x0 / 1000, x1 / 1000, y0 / 1000, y1 / 1000, z0 / 1000, z1 / 1000, rgba=rgba,
               visual=True)


def _mm_rod(parent, a, b, radius, rgba, kind="cylinder"):
    return rod(parent, [v / 1000 for v in a], [v / 1000 for v in b], radius / 1000, rgba, kind)


def draw_look(inst):
    """Draw the parts that make the instrument read as a washer-dispenser set up as a cell seeder. All visual.

    Nest frame, millimetres. Nothing is drawn over the nest (|x| < 76, |y| < 55, from 60 mm up), so the load
    position stays open from above, as on the real instrument. No brand text or logo. The sources for each part
    are in the geometry table of README.md; every part keeps at least 10 mm from the arms during the scripted
    expert's takes (tests/test_tending.py checks it).
    """
    b, t = _mm_box, _mm_rod
    b(inst, -210, 210, FRONT_Y * 1000, FRONT_Y * 1000 + 2, 40, 54, ".30 .34 .40 1")  # trim along the base front
    # Dispense head (the tip holder) over the slot mouth, so over the carrier's path into the slot: a black block
    # with a clear acrylic front, its 8 tips at 9 mm pitch along the front, each fed by a milky tube from the top.
    b(inst, -45, 45, -125, -95, 100, 150, BLACK)
    b(inst, -42, 42, -95, -87, 99, 142, ".82 .92 1 .28")
    b(inst, -42, 42, -95, -87, 142, 143.5, ".95 .97 1 .9")
    for k in range(8):
        x = -31.5 + 9 * k
        t(inst, (x, -91, 82), (x, -91, 99), 1.8, ".88 .89 .91 1")
        t(inst, (x, -91, 102), (x, -91, 140), 1.1, ".96 .96 .93 .9")  # the tube inside the clear block
    # The dispense arm the head hangs from, out of the pump's right end.
    b(inst, 45, 100, -125, -106, 150, 166, BLACK)
    # Peristaltic pump on the face above the wash manifold, on the left (+x) as in the manual's front photo: a black
    # motor body with a rounded pump cover at its left end and a yellow warning label; in front of it the pump head
    # (a roller cage turning about x) with the cassette's steel plate wrapped under and up its front, 8 milky tubes
    # over the rollers, and the black tube tensioner with its gold scale at the right end.
    b(inst, 104, 176, -125, -95, 200, 270, BLACK)
    t(inst, (176, -125, 235), (176, -97, 235), 33, ".12 .12 .13 1")
    b(inst, 126, 156, -95, -94.5, 256, 268, ".98 .82 .10 1")
    t(inst, (108, -75, 235), (110, -75, 235), 17, STEEL)
    t(inst, (172, -75, 235), (174, -75, 235), 17, STEEL)
    t(inst, (110, -75, 235), (172, -75, 235), 9, ".20 .20 .22 1")
    for k in range(6):
        a = np.pi * k / 3
        y, z = -75 + 13.5 * np.cos(a), 235 + 13.5 * np.sin(a)
        t(inst, (110, y, z), (172, y, z), 3.5, ".86 .87 .89 1")
    b(inst, 106, 176, -97, -55, 212, 215, STEEL)  # the cassette's centre holder under the rollers
    b(inst, 106, 176, -58, -55, 212, 233, STEEL)  # and its plate, wrapped up the front
    for k in range(8):
        x = 115 + 8 * k
        for p, q in (((x, -97, 250), (x, -83, 254)), ((x, -83, 254), (x, -67, 254)), ((x, -67, 254), (x, -57, 246))):
            t(inst, p, q, 2, ".95 .95 .92 1", "capsule")
    b(inst, 94, 104, -100, -52, 205, 262, ".10 .10 .11 1")
    b(inst, 96, 102, -52, -51.5, 212, 255, ".80 .66 .28 1")
    for z in range(216, 256, 8):
        b(inst, 96, 99, -51.5, -51.2, z, z + 1, ".15 .12 .05 1")
    # The tubes leave the tensioner and drop to the dispense head, as one bundle.
    t(inst, (99, -66, 207), (62, -96, 174), 4, TUBE, "capsule")
    t(inst, (62, -96, 174), (20, -104, 152), 4, TUBE, "capsule")
    # Keypad section at the upper right (-x): a raised step of the housing with a black bezel, a 2-line display and
    # 16 pale keys. Both stand only a few mm proud: the scene's main light grazes the face from above, so anything
    # deeper casts a long dark shadow down it (a 25 mm step did), and for the same reason the slope is not drawn.
    b(inst, -210, -75, -125, -119, 270, 460, SILVER_DK)
    b(inst, -198, -87, -119, -117, 300, 385, ".06 .06 .07 1")
    b(inst, -188, -97, -117, -116.5, 365, 379, ".62 .66 .58 1")
    for i in range(4):
        for j in range(4):
            x, z = -175 + 21 * i, 318 + 12 * j
            b(inst, x - 7, x + 7, -117, -116.5, z - 3.5, z + 3.5, ".78 .78 .74 1")
    # Wash manifold (2 bars, a hanger, 12 tubes and 4 thumbscrews) over its steel ultrasonic trough, left of the
    # carrier. The tubes run through both bars and stand above the top one, where the people's view sees them.
    b(inst, 100, 200, -105, -45, 54, 66, STEEL)
    b(inst, 104, 196, -101, -49, 66, 66.5, ".25 .27 .30 1")
    b(inst, 95, 205, -110, -40, 92, 106, GRAY)
    b(inst, 95, 205, -110, -40, 109, 123, GRAY)
    b(inst, 140, 160, -125, -110, 92, 140, GRAY)
    for k in range(12):
        x = 100.5 + 9 * k
        t(inst, (x, -60, 74), (x, -60, 138), 1.6, ".90 .91 .92 1")
    for x in (105, 195):
        for z in (99, 116):
            t(inst, (x, -40, z), (x, -34, z), 5, ".80 .80 .82 1")
    # The silver rail along the carrier's right (-x) edge.
    t(inst, (-82, -55, 58), (-82, 55, 58), 4, ".75 .76 .78 1")


def build_instrument(world, x, y):
    """Add the washer-dispenser with its nest centred at (x, y). One static body, no joints.
    @return The nest spec: x, y, yaw, pocket half size and the world height of the nest floor.
    """
    inst = sub(world, "body", name="dispenser", pos=f"{x} {y} {TABLE_Z}")
    w = WIDTH / 2
    box(inst, "dispenser_deck", -w, w, BACK_Y, FRONT_Y, 0, DECK_TOP, rgba=BASE)
    box(inst, "dispenser_housing", -w, w, BACK_Y, FACE_Y, HOOD_BOTTOM, HEIGHT, rgba=SILVER)
    box(inst, "dispenser_side_l", SLOT_HALF, w, BACK_Y, FACE_Y, DECK_TOP, HOOD_BOTTOM, rgba=SILVER)
    box(inst, "dispenser_side_r", -w, -SLOT_HALF, BACK_Y, FACE_Y, DECK_TOP, HOOD_BOTTOM, rgba=SILVER)
    box(inst, "dispenser_slot_back", -SLOT_HALF, SLOT_HALF, BACK_Y, SLOT_BACK, DECK_TOP, HOOD_BOTTOM, rgba=DARK)
    # A dark slot ceiling, so the opening reads as an opening.
    box(inst, None, -SLOT_HALF, SLOT_HALF, SLOT_BACK - 0.001, FACE_Y, HOOD_BOTTOM - 0.002, HOOD_BOTTOM, rgba=DARK,
        visual=True)
    draw_look(inst)

    # The carrier at its load position: a slab with an L guide at each corner. The middles of the long walls stay
    # open, so fingertips can come down beside the plate.
    carrier = sub(inst, "body", name="carrier", pos="0 0 0")
    box(carrier, "carrier_floor", -SLAB[0], SLAB[0], -SLAB[1], SLAB[1], DECK_TOP, FLOOR, rgba=CARRIER)
    hx, hy = POCKET
    for sx in (-1, 1):
        for sy in (-1, 1):
            box(carrier, None, sx * (hx - GUIDE_LEG), sx * (hx + GUIDE_T), sy * hy, sy * (hy + GUIDE_T),
                FLOOR, FLOOR + GUIDE_H, rgba=GUIDE)  # leg along the long side
            box(carrier, None, sx * hx, sx * (hx + GUIDE_T), sy * (hy - GUIDE_LEG), sy * (hy + GUIDE_T),
                FLOOR, FLOOR + GUIDE_H, rgba=GUIDE)  # leg along the short side
    # The spring clamp at the back-left (A1) corner. Seen only: it exerts no force.
    box(carrier, None, hx - 0.030, hx - 0.016, -hy - 0.006, -hy - 0.001, FLOOR, FLOOR + 0.008, rgba=".95 .55 .15 1",
        visual=True)
    return {"kind": "nest", "x": x, "y": y, "yaw": 0.0, "half": POCKET, "floor": TABLE_Z + FLOOR}


def a1_plate(world, name, x, y, yaw=0.0, z=TABLE_Z):
    """A 96-well microplate with its A1 corner and row A marked in blue on the top face.
    A1 is the plate's own (+x, -y) corner: at yaw 0 it sits at the left rear as seen from the arms.
    """
    spec = props.microplate(world, name, x, y, yaw=yaw, z=z)  # yaw and z by keyword: the 5th argument is rgba
    body = world.find(f".//body[@name='{name}']")
    hx, hy = PLATE_HALF
    top = PLATE_H + 0.0003
    sub(body, "geom", contype=0, conaffinity=0, mass=0, type="box", size=".012 .012 .0004",
        pos=f"{hx - 0.012} {-hy + 0.012} {top}", rgba=BLUE)
    sub(body, "geom", contype=0, conaffinity=0, mass=0, type="box", size=f"{hx - 0.004} .002 .0004",
        pos=f"0 {-hy + 0.003} {top}", rgba=BLUE)
    return spec


def cell_bottle(world, x, y, nest, name="bottle"):
    """labbench's 125 mL bottle on a green spot at (x, y), drawn as a clear media bottle of pink cell suspension
    with an orange cap, and its line to the pump.

    The physics is labbench.props.bottle unchanged (50 mm wide, 100 mm tall, 0.16 kg, freejoint `<name>_free`);
    only colours change, and the medium inside is a visual geom. The line is a spatial tendon from a site on the
    side of the cap, down to the bench and along the housing into the pump (see draw_line), so it follows the
    bottle wherever it is carried and adds no force.
    @return The props spec of the bottle.
    """
    sub(world, "geom", type="cylinder", contype=0, conaffinity=0, mass=0, size=f"{SPOT_R} .0003",
        pos=f"{x} {y} {TABLE_Z + 0.0003}", rgba=".30 .55 .45 1")
    spec = props.bottle(world, name, x, y)
    body = world.find(f".//body[@name='{name}']")
    body.find(f"geom[@name='{name}_wall']").set("rgba", ".86 .92 .96 .45")
    body.find(f"geom[@name='{name}_cap']").set("rgba", ".95 .50 .10 1")
    body.findall("geom")[2].set("rgba", ".96 .96 .94 1")  # the label band, labbench's 3rd geom
    sub(body, "geom", type="cylinder", contype=0, conaffinity=0, mass=0, size=".0235 .027", pos="0 0 .029",
        rgba=".88 .42 .48 1")
    draw_line(world, body, nest, name)
    return spec


def draw_line(world, body, nest, name="bottle"):
    """The tube bundle from the bottle cap to the pump, as a spatial tendon through sites: the cap, an anchor on
    the bench beside the bottle, then fixed points along the housing (see LINE_ROUTE).

    A tendon with no stiffness, damping, limit, friction loss or actuator only draws: it adds no force to the
    bottle (tests/test_tending.py checks this to the last bit). MJCF wants tendons at the model's top level, but a
    labbench build only sees the worldbody, so the tendon is staged there and moved up by the scene hook that
    install_scene_hook adds.
    """
    sub(body, "site", name=f"{name}_line_cap", pos=" ".join(str(v) for v in LINE_CAP), size=".002", rgba="0 0 0 0")
    spot = body.get("pos").split()
    sub(world, "site", name=f"{name}_line_anchor", size=".002", rgba="0 0 0 0",
        pos=f"{float(spot[0]) + LINE_ANCHOR[0]} {float(spot[1]) + LINE_ANCHOR[1]} {TABLE_Z + LINE_ANCHOR[2]}")
    inst = world.find(".//body[@name='dispenser']")
    points = [*LINE_ROUTE, LINE_INLET]
    for k, p in enumerate(points):
        sub(inst, "site", name=f"{name}_line_{k}", pos=" ".join(str(v) for v in p), size=".002", rgba="0 0 0 0")
    tendon = sub(world, "tendon")
    line = sub(tendon, "spatial", name=f"{name}_line", width=LINE_WIDTH, rgba=TUBE)
    sub(line, "site", site=f"{name}_line_cap")
    sub(line, "site", site=f"{name}_line_anchor")
    for k in range(len(points)):
        sub(line, "site", site=f"{name}_line_{k}")
    return line


def _lift_staged(build_scene):
    """Wrap a labbench scene builder so that <tendon> elements it staged in the worldbody move to the top level."""
    def build(root, world):
        build_scene(root, world)
        for el in world.findall("tendon"):
            world.remove(el)
            root.append(el)
    return build


def install_scene_hook():
    """Let tending's builds add a tendon. labbench.take.set_bench calls make_env from its own module namespace
    when it runs, so wrapping that name reaches every bench without editing labbench. A build that stages no
    tendon gets exactly the scene it got before. Idempotent; in memory only."""
    if getattr(_take.make_env, "tending_hook", False):
        return
    original = _take.make_env

    def make_env(build_scene, *args, **kwargs):
        return original(_lift_staged(build_scene), *args, **kwargs)

    make_env.tending_hook = True
    make_env.__doc__ = original.__doc__
    _take.make_env = make_env


def aim_show(bench):
    """Point the stock 'show' camera across the bench at the instrument, in memory.

    From its stock place the instrument's housing hides the nest. Moving the camera and its look-at body and
    setting its field of view changes only this simulation, never a labbench file. Does nothing on a bench built
    without the show camera.
    """
    m, d = bench.env.model, bench.env.data
    nest = bench.specs.get("nest")
    try:
        cam, look = m.camera("show").id, m.body("show_look").id
    except KeyError:
        return False
    if nest is None:
        return False
    m.cam_pos[cam] = (SHOW_POS[0], SHOW_POS[1], TABLE_Z + SHOW_POS[2])
    m.cam_fovy[cam] = SHOW_FOVY
    m.body_pos[look] = (nest["x"] + SHOW_LOOK[0], nest["y"] + SHOW_LOOK[1], TABLE_Z + SHOW_LOOK[2])
    mujoco.mj_forward(m, d)
    return True


# Scoring tests. Each takes a labbench World and returns True or False.


def nest_local(nest, point):
    """A world point in the nest frame: origin at the nest centre on the nest floor."""
    c, s = np.cos(nest["yaw"]), np.sin(nest["yaw"])
    d = np.asarray(point, float) - np.array([nest["x"], nest["y"], nest["floor"]])
    return np.array([c * d[0] + s * d[1], -s * d[0] + c * d[1], d[2]])


def corners(w, name):
    """World positions of the 4 underside corners of a plate."""
    p, r = w.pos(name), w.rot(name)
    hx, hy = PLATE_HALF
    return [p + r @ np.array([sx * hx, sy * hy, 0.0]) for sx in (-1, 1) for sy in (-1, 1)]


def seated_strict(name, nest):
    """The plate sits in the pocket: centre within the clearance, every underside corner within 1 mm of the nest
    floor, tilt at most 2 degrees, A1 at the back left within 3 degrees (a half turn fails), and let go."""
    def test(w):
        c = nest_local(nest, w.pos(name))
        if abs(c[0]) > CLEAR + 0.0005 or abs(c[1]) > CLEAR + 0.0005:
            return False
        if any(abs(nest_local(nest, k)[2]) > 0.001 for k in corners(w, name)):
            return False
        if w.tilt_deg(name) > 2.0:
            return False
        turn = (w.yaw_deg(name) - np.degrees(nest["yaw"]) + 180) % 360 - 180
        return abs(turn) <= 3.0 and w.released(name)
    return test


def in_travel(nest, point):
    """Whether a world point is inside the carrier's travel box."""
    c = nest_local(nest, point)
    z = point[2] - TABLE_Z
    return (abs(c[0]) <= TRAVEL["x"] and TRAVEL["y"][0] <= c[1] <= TRAVEL["y"][1]
            and TRAVEL["z"][0] <= z <= TRAVEL["z"][1])


def hand_points(w):
    """The 2 grasp points and the centre of every fingertip pad geom, as world points."""
    m, d = w.env.model, w.env.data
    if not hasattr(w, "_tending_pads"):  # the ids are fixed for a model, so look them up once
        w._tending_pads = [i for i in range(m.ngeom) if (m.geom(i).name or "").startswith(("left_tip_", "right_tip_"))]
    return [w.tcp("left"), w.tcp("right")] + [d.geom_xpos[i].copy() for i in w._tending_pads]


def hands_clear(nest):
    """Neither grasp point and no fingertip pad is inside the carrier's travel box."""
    return lambda w: not any(in_travel(nest, p) for p in hand_points(w))


def on_mat_flat(name, mat):
    """Every underside corner is on the mat and within 2 mm of the table, tilt at most 3 degrees, let go."""
    def test(w):
        for k in corners(w, name):
            if abs(k[0] - mat["x"]) > mat["half"][0] or abs(k[1] - mat["y"]) > mat["half"][1]:
                return False
            if abs(k[2] - TABLE_Z) > 0.002:
                return False
        return w.tilt_deg(name) <= 3.0 and w.released(name)
    return test


def carrier_empty(name, nest):
    """The plate origin is not on or over the carrier slab."""
    def test(w):
        c = nest_local(nest, w.pos(name))
        return not (abs(c[0]) < SLAB[0] + 0.01 and abs(c[1]) < SLAB[1] + 0.01 and c[2] > -0.02)
    return test


def low_z(w, name):
    """World height of a plate's lowest underside corner."""
    return min(k[2] for k in corners(w, name))


def lifted_flat(name, start_z, by=0.025, max_tilt=10.0):
    """The plate's lowest corner is `by` above where its underside started, and the plate is nearly level.
    Testing the lowest corner, not the centre, means tipping one end up does not count as a lift."""
    return lambda w: low_z(w, name) > start_z + by and w.tilt_deg(name) < max_tilt


def over_flat(name, x, y, half, top, clear=0.015, max_tilt=10.0):
    """The plate centre is within `half` of (x, y), its lowest corner is `clear` above `top`, and it is nearly
    level: carried over a place, not tipped or slid there."""
    def test(w):
        p = w.pos(name)
        return (abs(p[0] - x) < half[0] and abs(p[1] - y) < half[1] and low_z(w, name) > top + clear
                and w.tilt_deg(name) < max_tilt)
    return test


## A plate that falls further than this after the robot lets go counts as dropped.
DROP_H = 0.02
## Gravity, for the largest move a free plate can make in one control step.
G = 9.81


def no_drop(name, fall=DROP_H):
    """False for the rest of the take once the plate has fallen more than `fall` metres free of the robot.

    The fall is measured as a height, not read from a speed: `ref` is the lowest underside corner on the last
    control step the robot touched the plate (or the plate was at rest, or a script held it). When the plate next
    comes to rest untouched, ref minus its new lowest corner is the fall. A drop is final: touching or picking up
    the plate afterwards does not clear it, since the spill has already happened.

    Two things the scripted checks in labbench.oracle.play do are read as a hand, not as a fall:
    - a pin: the script puts the plate back at the same pose each step, so it reads at rest while its joint shows
      one step of free fall speed; the pose it was pinned at is the measured one plus that step's fall;
    - a teleport: the plate moved further in one step than gravity allows from its last speed, with neither
      grasp point within 0.12 m of it (so a robot that strikes the plate is not excused).

    It keeps state, so it must be called once on every control step; labbench's Tracker calls the success test on
    each, and prime() calls it once at the start.
    """
    state = {"ref": None, "last": None, "v": np.zeros(3), "dropped": False}

    def test(w):
        z, p = low_z(w, name), w.pos(name)
        v = w.env.data.joint(f"{name}_free").qvel[:3].copy()
        if state["ref"] is None or w.held(name):
            state["ref"] = z
        else:
            jump = 0.0 if state["last"] is None else float(np.linalg.norm(p - state["last"]))
            bound = float(np.linalg.norm(state["v"])) * STEP_S + 0.5 * G * STEP_S ** 2 + 0.005
            near = min(float(np.linalg.norm(w.tcp(s) - p)) for s in ("left", "right")) < 0.12
            if jump > bound and not near:  # put there by a script
                state["ref"] = z
            elif w.speed(name) < 0.03:
                if v[2] < -0.2:  # pinned by a script: still, yet falling for one step since it was put back
                    state["ref"] = z - v[2] * STEP_S / 2
                else:  # at rest on its own
                    if state["ref"] - z > fall:
                        state["dropped"] = True
                    state["ref"] = z
        state["last"], state["v"] = p, v
        return not state["dropped"]
    return test


# The cell bottle: the swirl meter and the home test. No liquid is simulated, so "swirled" is a judgement on how the
# bottle moved, not on the cells.

## Underside this far above its start, resting on nothing, counts as held (a hand and a script pin look the same).
SWIRL_LIFT = 0.01
## While held, tilt above this spoils the swirl; at any time, tilt above SPILL_DEG is a spill.
SWIRL_MAX_TILT = 20.0
SPILL_DEG = 30.0
## While held, the bottle must stay within this of where it was picked up, horizontally.
SWIRL_RADIUS = 0.12
## A swirl is at least this much horizontal travel and this many turns about a running centre, in one hold.
SWIRL_PATH = 0.60
SWIRL_TURNS = 3.0
## A control step "swirls" when, in an unspoiled hold, the bottle moves at least SWIRL_STEP horizontally and turns at
## least SWIRL_DA radians about the running centre, the same way as the hold's turns so far (0.04 rad a step is about
## 0.13 turns a second; the expert swirls at 0.8). A straight shake turns 0 and never swirls.
SWIRL_STEP = 0.001
SWIRL_DA = 0.04
## Time constant of the running centre the turns are counted about, and the least distance from it that counts.
CENTRE_TAU = 1.0
MIN_R = 0.004
## Home: within this of the spot, underside within HOME_Z of the table top, tilt under HOME_TILT, let go.
HOME_XY, HOME_Z, HOME_TILT = 0.02, 0.005, 5.0


def supported(w, name):
    """Whether the prop touches anything that is not a robot part: the table, the instrument, the plate. Read from the
    contacts as World.held reads them, so a prop pushed along a raised surface is not taken for a held one."""
    m, d = w.env.model, w.env.data
    body = m.body(name).id
    for i in range(d.ncon):
        c = d.contact[i]
        if c.dist > 0.001:
            continue
        a, b = c.geom1, c.geom2
        if m.geom_bodyid[b] == body:
            a, b = b, a
        if m.geom_bodyid[a] == body and m.geom_bodyid[b] != body and b not in w.robot_geoms:
            return True
    return False


def swirl_meter(name, z0):
    """A stateful reading of how the bottle has moved. Call it as meter(world); it returns its state dict.

    Each set_bench builds a new meter (through the task's scoring), so every take starts fresh. It is idempotent
    per simulated time, so stages and the success test can all call it on the same step without double counting.
    Keys of the state:
    - lifted: held right now: the underside more than SWIRL_LIFT above its start and the bottle touching nothing but
      the robot (so sliding it on the bench, or on the instrument's raised deck, is never a hold);
    - path, turns: horizontal travel (m) and signed turns about a running centre during the current hold;
    - spoiled: the current hold went above SWIRL_MAX_TILT or further than SWIRL_RADIUS from its pick point;
    - swirled: some hold reached SWIRL_PATH and SWIRL_TURNS unspoiled (latched for the take);
    - spilled: tilt went above SPILL_DEG at any time (latched for the take);
    - swirling: this step moved the bottle round its running centre (see SWIRL_STEP and SWIRL_DA);
    - best_path, best_turns, max_tilt_deg: for summaries.
    A step that moves the bottle further than its last speed and gravity allow (a scripted teleport) adds nothing.
    Turns are counted because path alone cannot tell a swirl from a straight shake.
    """
    st = {"t": None, "last": None, "v": 0.0, "up": False, "pick": None, "path": 0.0, "turns": 0.0, "c": None,
          "ang": None, "spoiled": False, "swirled": False, "spilled": False, "swirling": False, "lifted": False,
          "best_path": 0.0, "best_turns": 0.0, "max_tilt_deg": 0.0}

    def meter(w):
        if st["t"] == w.time:
            return st
        st["t"] = w.time
        p, tilt = w.pos(name), w.tilt_deg(name)
        st["max_tilt_deg"] = max(st["max_tilt_deg"], tilt)
        st["spilled"] = st["spilled"] or tilt > SPILL_DEG
        st["swirling"] = False
        st["lifted"] = bool(p[2] > z0 + SWIRL_LIFT) and not supported(w, name)
        if st["lifted"]:
            if not st["up"]:  # a new hold
                st.update(up=True, pick=p[:2].copy(), path=0.0, turns=0.0, c=p[:2].copy(), ang=None, spoiled=False)
            if tilt > SWIRL_MAX_TILT or np.linalg.norm(p[:2] - st["pick"]) > SWIRL_RADIUS:
                st["spoiled"] = True
            if st["last"] is not None and not st["spoiled"]:
                step = float(np.linalg.norm(p[:2] - st["last"][:2]))
                if step <= st["v"] * STEP_S + 0.5 * G * STEP_S ** 2 + 0.005:
                    st["path"] += step
                    st["c"] = st["c"] + (p[:2] - st["c"]) * STEP_S / CENTRE_TAU
                    d = p[:2] - st["c"]
                    if np.linalg.norm(d) > MIN_R:
                        a = float(np.arctan2(d[1], d[0]))
                        if st["ang"] is not None:
                            da = (a - st["ang"] + np.pi) % (2 * np.pi) - np.pi
                            if abs(da) < np.pi / 2:
                                st["turns"] += da / (2 * np.pi)
                                st["swirling"] = bool(step >= SWIRL_STEP and abs(da) >= SWIRL_DA
                                                      and da * st["turns"] > 0)
                        st["ang"] = a
                    else:
                        st["ang"] = None
                else:  # put there by a script
                    st["ang"] = None
            if not st["spoiled"] and st["path"] >= SWIRL_PATH and abs(st["turns"]) >= SWIRL_TURNS:
                st["swirled"] = True
            st["best_path"] = max(st["best_path"], st["path"])
            st["best_turns"] = max(st["best_turns"], abs(st["turns"]))
        else:
            st["up"] = False
        st["v"] = float(np.linalg.norm(w.env.data.joint(f"{name}_free").qvel[:2]))
        st["last"] = p.copy()
        return st

    return meter


def bottle_home(spot, name="bottle"):
    """The bottle stands upright on its spot: within HOME_XY of it, underside on the table, tilt under HOME_TILT,
    robot not touching it, at rest."""
    def test(w):
        p = w.pos(name)
        return (np.linalg.norm(p[:2] - np.asarray(spot, float)) < HOME_XY and abs(p[2] - TABLE_Z) < HOME_Z
                and w.tilt_deg(name) < HOME_TILT and w.released(name))
    return test


## The together rule needs at least this much plate travel in the window (the mat to the nest is about 0.17 m).
OVERLAP_MIN_PATH = 0.10


def overlap_meter(meter, plate_z0, seated, plate="plate"):
    """Whether the bottle kept swirling while the plate was on its way, for the two-arm chore. Call as over(world).

    The window opens when the plate's lowest corner first rises 1 cm above where it started and closes when the
    plate is seated. Every control step inside it counts, with no speed threshold:
    - steps, path: the window's steps, and the plate's travel over them (m);
    - steps_swirl, path_swirl: the same, over only the steps on which the swirl meter saw the bottle swirling.
    The rule (overlap_ok) asks for half of both. Weighting by the plate's own travel means the arms cannot take
    turns at any carry speed: a plate carried, however slowly, while the bottle rests adds travel with no swirl.
    Counting the steps as well covers the other case: a plate rushed to the nest while the bottle swirls, then left
    hanging there with the bottle resting until it is seated, has most of its travel swirled but not its time.
    Idempotent per simulated time, like the swirl meter.
    """
    st = {"t": None, "last": None, "open": False, "closed": False, "steps": 0, "steps_swirl": 0, "path": 0.0,
          "path_swirl": 0.0}

    def over(w):
        if st["t"] == w.time:
            return st
        st["t"] = w.time
        b, p = meter(w), w.pos(plate)
        if not st["closed"]:
            if not st["open"] and low_z(w, plate) > plate_z0 + 0.01:
                st["open"] = True
            if st["open"]:
                if seated(w):
                    st["closed"] = True
                else:
                    d = float(np.linalg.norm(p - st["last"])) if st["last"] is not None else 0.0
                    st["steps"] += 1
                    st["path"] += d
                    if b["swirling"]:
                        st["steps_swirl"] += 1
                        st["path_swirl"] += d
        st["last"] = p.copy()
        return st

    return over


def overlap_ok(st):
    """The window closed with the plate seated after at least OVERLAP_MIN_PATH of plate travel, and the bottle was
    swirling for at least half of the window's steps and over at least half of the plate's travel."""
    return (st["closed"] and st["path"] >= OVERLAP_MIN_PATH and st["path_swirl"] >= 0.5 * st["path"]
            and st["steps_swirl"] >= 0.5 * st["steps"])
