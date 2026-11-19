"""Lab labware as MuJoCo bodies, built from simple shapes at real sizes.

Every movable prop has its body origin at the centre of its underside, so "put it on a surface at height z" is just
z. Each builder returns a small dict of the numbers the scoring needs (sizes, well centres, pocket sizes).
Sizes are metres, masses kilograms. x + is the left arm's side, y + points toward the arm bases.
"""

import math

from .sim import TABLE_Z, sub

## Plastic on plastic. The example's default (1.6) is tuned for grasping fruit and would make a tube stick to a rack wall.
PLASTIC = "0.4 0.01 0.001"
## How far above a surface a prop starts, so nothing begins in contact penetration.
DROP = 0.001


def yaw_quat(yaw):
    """Quaternion (w x y z) for a turn about the vertical axis."""
    return f"{math.cos(yaw / 2)} 0 0 {math.sin(yaw / 2)}"


def _visual(body, **attrs):
    """A geom that is seen but never touched or weighed."""
    return sub(body, "geom", contype=0, conaffinity=0, mass=0, **attrs)


def falcon_tube(world, name, x, y, cap_rgba=".15 .35 .8 1", liquid_rgba=".95 .75 .3 .9", z=TABLE_Z, capped=True):
    """A self-standing 50 mL tube: 30 mm wide, 115 mm tall, about 60 g with liquid.

    @param capped False leaves the cap off (a used tube): the same body, 103 mm tall.
    """
    radius, body_h, cap_h = 0.0148, 0.103, 0.012
    b = sub(world, "body", name=name, pos=f"{x} {y} {z + DROP}")
    sub(b, "freejoint", name=f"{name}_free")
    sub(b, "geom", name=f"{name}_wall", type="cylinder", size=f"{radius} {body_h / 2}", pos=f"0 0 {body_h / 2}",
        mass=".052", rgba=".86 .9 .94 .65", friction=PLASTIC)
    if capped:
        sub(b, "geom", name=f"{name}_cap", type="cylinder", size=f".017 {cap_h / 2}", pos=f"0 0 {body_h + cap_h / 2}",
            mass=".008", rgba=cap_rgba, friction=PLASTIC)
    _visual(b, type="cylinder", size=f"{radius - 0.002} .03", pos="0 0 .032", rgba=liquid_rgba)
    for mark in (0.03, 0.055, 0.08):
        _visual(b, type="cylinder", size=f"{radius + 0.0002} .0005", pos=f"0 0 {mark}", rgba=".2 .2 .2 .8")
    height = body_h + (cap_h if capped else 0.0)
    return {"name": name, "kind": "tube", "radius": radius, "height": height}


def tube_rack(world, name, x, y, nx=3, ny=2, yaw=0.0, rgba=".16 .42 .78 1", z=TABLE_Z, pitch=0.038, well=0.033):
    """A rack for 50 mL tubes: nx by ny square wells, 33 mm inside, 45 mm deep, about 220 g.

    @return Its spec, with "wells": each well centre (x, y) in the rack's own frame, and "floor": the height of
        the well floor above the rack's underside.
    """
    wall, base, depth = pitch - well, 0.004, 0.045
    length, width = nx * pitch + wall, ny * pitch + wall
    b = sub(world, "body", name=name, pos=f"{x} {y} {z + DROP}", quat=yaw_quat(yaw))
    sub(b, "freejoint", name=f"{name}_free")
    sub(b, "geom", name=f"{name}_base", type="box", size=f"{length / 2} {width / 2} {base / 2}", pos=f"0 0 {base / 2}",
        mass=".08", rgba=rgba, friction=PLASTIC)
    share = 0.14 / (nx + ny + 2)
    for i in range(nx + 1):
        sub(b, "geom", type="box", size=f"{wall / 2} {width / 2} {depth / 2}",
            pos=f"{(i - nx / 2) * pitch} 0 {base + depth / 2}", mass=share, rgba=rgba, friction=PLASTIC)
    for j in range(ny + 1):
        sub(b, "geom", type="box", size=f"{length / 2} {wall / 2} {depth / 2}",
            pos=f"0 {(j - ny / 2) * pitch} {base + depth / 2}", mass=share, rgba=rgba, friction=PLASTIC)
    wells = [((i - (nx - 1) / 2) * pitch, (j - (ny - 1) / 2) * pitch) for i in range(nx) for j in range(ny)]
    return {"name": name, "kind": "rack", "wells": wells, "floor": base, "well": well, "height": base + depth,
            "length": length, "width": width}


def bottle(world, name, x, y, z=TABLE_Z):
    """A white 125 mL wide-mouth reagent bottle with a blue screw cap: 50 mm wide, 100 mm tall, about 160 g."""
    radius, body_h, cap_h = 0.025, 0.082, 0.018
    b = sub(world, "body", name=name, pos=f"{x} {y} {z + DROP}")
    sub(b, "freejoint", name=f"{name}_free")
    sub(b, "geom", name=f"{name}_wall", type="cylinder", size=f"{radius} {body_h / 2}", pos=f"0 0 {body_h / 2}",
        mass=".14", rgba=".93 .94 .95 1")
    sub(b, "geom", name=f"{name}_cap", type="cylinder", size=f".019 {cap_h / 2}", pos=f"0 0 {body_h + cap_h / 2}",
        mass=".02", rgba=".15 .4 .8 1")
    _visual(b, type="cylinder", size=f"{radius + 0.0003} .016", pos="0 0 .042", rgba=".82 .9 .78 1")  # label
    return {"name": name, "kind": "bottle", "radius": radius, "height": body_h + cap_h}


def platform(world, name, x, y, half=(0.07, 0.055), height=0.06, rgba=".55 .57 .6 1"):
    """A fixed gray block that stands in for a shelf or an instrument stage."""
    sub(world, "geom", name=name, type="box", size=f"{half[0]} {half[1]} {height / 2}",
        pos=f"{x} {y} {TABLE_Z + height / 2}", rgba=rgba)
    _visual(world, type="box", size=f"{half[0] - 0.006} {half[1] - 0.006} .0006", pos=f"{x} {y} {TABLE_Z + height + 0.0004}",
            rgba=".66 .68 .71 1")  # a lighter top face, so it reads as a surface to put things on
    return {"name": name, "kind": "platform", "x": x, "y": y, "half": half, "top": TABLE_Z + height}


def mat(world, name, x, y, half=(0.05, 0.05), rgba=".2 .45 .8 1"):
    """A coloured square marked on the table: a target spot with no height."""
    _visual(world, name=name, type="box", size=f"{half[0]} {half[1]} .0006", pos=f"{x} {y} {TABLE_Z + 0.0006}",
            rgba=rgba)
    return {"name": name, "kind": "mat", "x": x, "y": y, "half": half, "top": TABLE_Z}


def deep_well_plate(world, name, x, y, yaw=0.0, z=TABLE_Z):
    """A 96 deep-well plate, SBS footprint 127.8 x 85.5 mm, 44 mm tall, about 150 g. The outer walls are real walls,
    so a jaw can take one of them."""
    hx, hy, h, t = 0.0639, 0.04275, 0.044, 0.002
    white = ".96 .96 .95 1"
    b = sub(world, "body", name=name, pos=f"{x} {y} {z + DROP}", quat=yaw_quat(yaw))
    sub(b, "freejoint", name=f"{name}_free")
    sub(b, "geom", name=f"{name}_floor", type="box", size=f"{hx} {hy} {t}", pos=f"0 0 {t}", mass=".05", rgba=white)
    for sx in (-1, 1):
        sub(b, "geom", type="box", size=f"{t} {hy} {h / 2}", pos=f"{sx * (hx - t)} 0 {h / 2}", mass=".025", rgba=white)
    for sy in (-1, 1):
        sub(b, "geom", type="box", size=f"{hx} {t} {h / 2}", pos=f"0 {sy * (hy - t)} {h / 2}", mass=".025", rgba=white)
    sub(b, "geom", type="box", size=f"{hx - t} {hy - t} .002", pos=f"0 0 {h - 0.0022}", mass=".02", rgba=".9 .9 .9 1")
    for r in range(8):
        for c in range(12):
            _visual(b, type="box", size=".0036 .0036 .0004", pos=f"{(c - 5.5) * 0.009} {(r - 3.5) * 0.009} {h - 0.0003}",
                    rgba=".55 .56 .58 1")
    return {"name": name, "kind": "plate", "half": (hx, hy), "height": h}


def plate_nest(world, name, x, y, yaw=0.0, clearance=0.003, rgba=".12 .13 .15 1"):
    """A fixed black tray with corner guides, like a plate reader drawer. The pocket is the SBS footprint plus
    clearance on every side."""
    hx, hy = 0.0639 + clearance, 0.04275 + clearance
    lip, floor, guide = 0.008, 0.004, 0.010
    b = sub(world, "body", name=name, pos=f"{x} {y} {TABLE_Z}", quat=yaw_quat(yaw))
    sub(b, "geom", name=f"{name}_floor", type="box", size=f"{hx + lip} {hy + lip} {floor / 2}", pos=f"0 0 {floor / 2}",
        rgba=rgba)
    for sx in (-1, 1):
        for sy in (-1, 1):  # an L at each corner
            sub(b, "geom", type="box", size=f"{lip / 2} .012 {guide / 2}",
                pos=f"{sx * (hx + lip / 2)} {sy * (hy - 0.012 + lip)} {floor + guide / 2}", rgba=".3 .32 .35 1")
            sub(b, "geom", type="box", size=f".012 {lip / 2} {guide / 2}",
                pos=f"{sx * (hx - 0.012 + lip)} {sy * (hy + lip / 2)} {floor + guide / 2}", rgba=".3 .32 .35 1")
    return {"name": name, "kind": "nest", "x": x, "y": y, "yaw": yaw, "half": (hx, hy), "floor": TABLE_Z + floor}


def open_tray(world, name, x, y, half=(0.06, 0.045), wall_h=0.02, rgba=".93 .93 .9 1", fixed=True, band=None):
    """A low open tray, 120 x 90 mm inside by default. band adds a coloured stripe on the rim, to tell trays apart."""
    t, floor = 0.003, 0.003
    parent = sub(world, "body", name=name, pos=f"{x} {y} {TABLE_Z + (0 if fixed else DROP)}")
    if not fixed:
        sub(parent, "freejoint", name=f"{name}_free")
    sub(parent, "geom", name=f"{name}_floor", type="box", size=f"{half[0] + t} {half[1] + t} {floor / 2}",
        pos=f"0 0 {floor / 2}", rgba=rgba, mass=".06")
    for sx in (-1, 1):
        sub(parent, "geom", type="box", size=f"{t / 2} {half[1] + t} {wall_h / 2}",
            pos=f"{sx * (half[0] + t / 2)} 0 {floor + wall_h / 2}", rgba=band or rgba, mass=".015")
    for sy in (-1, 1):
        sub(parent, "geom", type="box", size=f"{half[0] + t} {t / 2} {wall_h / 2}",
            pos=f"0 {sy * (half[1] + t / 2)} {floor + wall_h / 2}", rgba=band or rgba, mass=".015")
    return {"name": name, "kind": "tray", "x": x, "y": y, "half": half, "floor": TABLE_Z + floor,
            "rim": TABLE_Z + floor + wall_h}


def waste_bin(world, name, x, y, half=(0.07, 0.07), wall_h=0.09, rgba=".95 .78 .15 1"):
    """A fixed open bin, 140 x 140 mm inside and 90 mm deep, in waste yellow."""
    spec = open_tray(world, name, x, y, half=half, wall_h=wall_h, rgba=rgba, fixed=True)
    spec["kind"] = "bin"
    return spec


def tip_box(world, name, x, y, yaw=0.0, rgba=".2 .55 .5 1", z=TABLE_Z):
    """A closed pipette tip box, 122 x 80 x 55 mm, about 120 g, with the tip grid showing through the lid."""
    hx, hy, h = 0.061, 0.040, 0.055
    b = sub(world, "body", name=name, pos=f"{x} {y} {z + DROP}", quat=yaw_quat(yaw))
    sub(b, "freejoint", name=f"{name}_free")
    sub(b, "geom", name=f"{name}_shell", type="box", size=f"{hx} {hy} {h / 2}", pos=f"0 0 {h / 2}", mass=".12",
        rgba=rgba, friction=PLASTIC)
    _visual(b, type="box", size=f"{hx - 0.006} {hy - 0.006} .0005", pos=f"0 0 {h + 0.0003}", rgba=".88 .93 .92 1")
    for r in range(8):
        for c in range(12):
            _visual(b, type="cylinder", size=".0025 .0004", pos=f"{(c - 5.5) * 0.009} {(r - 3.5) * 0.009} {h + 0.0008}",
                    rgba=".95 .85 .3 1")
    return {"name": name, "kind": "tip_box", "half": (hx, hy), "height": h}


def carry_rack(world, name, x, y, yaw=0.0, rgba=".24 .6 .45 1", z=TABLE_Z):
    """A long tube rack with a handle tab at each end, too wide for one gripper: 220 x 90 x 50 mm, about 320 g.
    Each tab is a 6 mm plate standing above the end wall, for one hand each."""
    hx, hy, h = 0.11, 0.045, 0.05
    b = sub(world, "body", name=name, pos=f"{x} {y} {z + DROP}", quat=yaw_quat(yaw))
    sub(b, "freejoint", name=f"{name}_free")
    sub(b, "geom", name=f"{name}_block", type="box", size=f"{hx} {hy} {h / 2}", pos=f"0 0 {h / 2}", mass=".24",
        rgba=rgba)
    for sx in (-1, 1):
        sub(b, "geom", name=f"{name}_tab_{'l' if sx > 0 else 'r'}", type="box", size=".003 .03 .02",
            pos=f"{sx * (hx - 0.003)} 0 {h + 0.02}", mass=".02", rgba=".1 .3 .22 1")
    for i in range(5):
        for j in (-1, 1):
            px, py = (i - 2) * 0.038, j * 0.02
            _visual(b, type="cylinder", size=".0148 .0008", pos=f"{px} {py} {h + 0.0005}", rgba=".1 .3 .22 1")
            sub(b, "geom", type="cylinder", size=".008 .02", pos=f"{px} {py} {h + 0.02}", mass=".004",
                rgba=".9 .92 .95 .9")
    return {"name": name, "kind": "carry_rack", "half": (hx, hy), "height": h, "tab_x": hx - 0.003}


def microplate(world, name, x, y, yaw=0.0, rgba=".97 .97 .96 1", z=TABLE_Z):
    """A standard 96-well assay plate, SBS footprint 127.8 x 85.5 mm, 14.4 mm tall, about 45 g, with a rim skirt
    so plates sit squarely on each other."""
    hx, hy, h = 0.0639, 0.04275, 0.0144
    b = sub(world, "body", name=name, pos=f"{x} {y} {z + DROP}", quat=yaw_quat(yaw))
    sub(b, "freejoint", name=f"{name}_free")
    sub(b, "geom", name=f"{name}_body", type="box", size=f"{hx} {hy} {h / 2}", pos=f"0 0 {h / 2}", mass=".045",
        rgba=rgba, friction=PLASTIC)
    for r in range(8):
        for c in range(12):
            _visual(b, type="cylinder", size=".0033 .0003", pos=f"{(c - 5.5) * 0.009} {(r - 3.5) * 0.009} {h + 0.0002}",
                    rgba=".7 .72 .75 1")
    return {"name": name, "kind": "microplate", "half": (hx, hy), "height": h}


def plate_hotel(world, name, x, y, shelves=(0.02, 0.10, 0.18), rgba=".78 .8 .83 1"):
    """A fixed plate hotel: shelves between two side walls, open at the front (toward the arms), with a low stop at
    the back. A plate goes in short side first (portrait), so each shelf is 92 mm wide and 134 mm deep and a
    gripper can hold the plate by its near end. Only the top shelf can be reached from above; the lower ones need
    the plate slid in from the front.

    @param shelves Height of each shelf's top face above the table, lowest first.
    @return Its spec, with "levels": the world height of each shelf top, and the shelf footprint.
    """
    half_w, half_d, wall, plate_t = 0.046, 0.067, 0.004, 0.003
    top = max(shelves) + 0.03
    b = sub(world, "body", name=name, pos=f"{x} {y} {TABLE_Z}")
    for sx in (-1, 1):
        sub(b, "geom", type="box", size=f"{wall / 2} {half_d} {top / 2}", pos=f"{sx * (half_w + wall / 2)} 0 {top / 2}",
            rgba=rgba)
    for i, level in enumerate(shelves):
        sub(b, "geom", name=f"{name}_shelf_{i}", type="box", size=f"{half_w} {half_d} {plate_t / 2}",
            pos=f"0 0 {level - plate_t / 2}", rgba=".9 .91 .93 1")
        sub(b, "geom", type="box", size=f"{half_w} {wall / 2} .004", pos=f"0 {-half_d - wall / 2} {level + 0.004}",
            rgba=rgba)  # a low stop at the back so a plate cannot be pushed through
    return {"name": name, "kind": "hotel", "x": x, "y": y, "half": (half_w, half_d),
            "levels": [TABLE_Z + s for s in shelves]}


def eppendorf(world, name, x, y, yaw=0.0, lying=True, cap_rgba=".25 .55 .85 1", z=TABLE_Z):
    """A 1.5 mL microcentrifuge tube with its lid shut: 10.8 mm wide, 40 mm long, with a 13 mm cap rim.
    Heavier than the real 2.5 g (10 g) so the contact solver stays calm. Origin at the tip.

    @param lying True lays it on its side on the surface, pointing along yaw; False stands it on its tip
        (only stable inside a rack hole).
    """
    r, body, cone, cap_r, cap_h = 0.0054, 0.022, 0.015, 0.0066, 0.003
    if lying:
        quat = f"{math.cos(yaw / 2) * math.sqrt(0.5)} {-math.sin(yaw / 2) * math.sqrt(0.5)} " \
               f"{math.cos(yaw / 2) * math.sqrt(0.5)} {math.sin(yaw / 2) * math.sqrt(0.5)}"
        pos = f"{x} {y} {z + cap_r + DROP}"
    else:
        quat, pos = yaw_quat(yaw), f"{x} {y} {z + DROP}"
    b = sub(world, "body", name=name, pos=pos, quat=quat)
    sub(b, "freejoint", name=f"{name}_free")
    sub(b, "geom", name=f"{name}_tip", type="capsule", size=".0025", fromto=f"0 0 .0025 0 0 {cone}", mass=".002",
        rgba=".9 .93 .96 .8", friction=PLASTIC)
    sub(b, "geom", name=f"{name}_wall", type="cylinder", size=f"{r} {body / 2}", pos=f"0 0 {cone + body / 2}", mass=".006",
        rgba=".9 .93 .96 .8", friction=PLASTIC)
    sub(b, "geom", name=f"{name}_cap", type="cylinder", size=f"{cap_r} {cap_h / 2}", pos=f"0 0 {cone + body + cap_h / 2}",
        mass=".002", rgba=cap_rgba, friction=PLASTIC)
    return {"name": name, "kind": "eppendorf", "radius": r, "height": cone + body + cap_h, "cap_radius": cap_r,
            "under_cap": cone + body}


def micro_rack(world, name, x, y, nx=6, ny=4, yaw=0.0, rgba=".9 .5 .7 1", z=TABLE_Z, pitch=0.018, hole=0.0118):
    """A rack for 1.5 mL tubes: nx by ny square holes 11.8 mm across, 26 mm deep, about 90 g. A tube hangs in a
    hole by its cap rim."""
    wall, base, depth = pitch - hole, 0.003, 0.026
    length, width = nx * pitch + wall, ny * pitch + wall
    b = sub(world, "body", name=name, pos=f"{x} {y} {z + DROP}", quat=yaw_quat(yaw))
    sub(b, "freejoint", name=f"{name}_free")
    sub(b, "geom", name=f"{name}_base", type="box", size=f"{length / 2} {width / 2} {base / 2}", pos=f"0 0 {base / 2}",
        mass=".03", rgba=rgba, friction=PLASTIC)
    share = 0.06 / (nx + ny + 2)
    for i in range(nx + 1):
        sub(b, "geom", type="box", size=f"{wall / 2} {width / 2} {depth / 2}",
            pos=f"{(i - nx / 2) * pitch} 0 {base + depth / 2}", mass=share, rgba=rgba, friction=PLASTIC)
    for j in range(ny + 1):
        sub(b, "geom", type="box", size=f"{length / 2} {wall / 2} {depth / 2}",
            pos=f"0 {(j - ny / 2) * pitch} {base + depth / 2}", mass=share, rgba=rgba, friction=PLASTIC)
    wells = [((i - (nx - 1) / 2) * pitch, (j - (ny - 1) / 2) * pitch) for i in range(nx) for j in range(ny)]
    return {"name": name, "kind": "micro_rack", "wells": wells, "floor": base, "height": base + depth,
            "length": length, "width": width, "hole": hole}


def storage_box(world, name, x, y, half=(0.085, 0.065), wall_h=0.06, rgba=".72 .58 .4 1"):
    """A fixed open cardboard-coloured box, 170 x 130 mm inside and 60 mm deep."""
    spec = open_tray(world, name, x, y, half=half, wall_h=wall_h, rgba=rgba, fixed=True)
    spec["kind"] = "box"
    return spec
