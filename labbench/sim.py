"""The simulated station: Dream's own two-arm YAM MuJoCo example, with the fruit swapped for lab labware.

The example ships inside the dreamlabs wheel (dream_examples/yam_mujoco). It is used as installed and never edited:
this module imports it, wraps its scene builder for one environment, then puts the original builder back.
"""

import pathlib
import sys
import xml.etree.ElementTree as ET

import dream

EXAMPLE = pathlib.Path(dream.__file__).resolve().parent.parent / "dream_examples" / "yam_mujoco"
if str(EXAMPLE) not in sys.path:
    sys.path.insert(0, str(EXAMPLE))

import dream_control  # noqa: E402  (the example's request and action helpers)
import yam_env  # noqa: E402  (the example's scene and physics)

## Height of the table top in the world frame, metres.
TABLE_Z = 0.76
## Control period of YamEnv.step, seconds (20 Hz).
STEP_S = 0.05
## The stock scene's objects, removed for every lab task.
STOCK_OBJECTS = ("apple", "banana", "orange", "water_bottle", "bowl", "plate")
## Each arm at rest: six joints at zero, gripper open.
HOME = yam_env.HOME

_STOCK_BUILD = yam_env.build_xml


def sub(parent, tag, **attrs):
    """Add an MJCF element; every attribute value is written with str()."""
    return ET.SubElement(parent, tag, **{k: str(v) for k, v in attrs.items()})


def make_env(build_scene, station_camera=True, show_camera=True):
    """Build a YamEnv whose table holds what build_scene adds.

    @param build_scene Called as build_scene(root, world) on the MJCF tree after the stock objects are removed.
    @param station_camera True keeps the overhead camera exactly at the calibrated YAM station pose (what the real
        station sees). False uses the example's lowered, tilted demo view.
    @param show_camera Adds a camera named "show" that looks across the bench at the arms. It is for people;
        the model never sees it.
    @return The environment, settled for a moment so nothing is mid-air.
    """
    yam_env.TOP_CAMERA_LOWER_M = 0.0 if station_camera else 0.15
    yam_env.TOP_CAMERA_TILT_UP_DEG = 0.0 if station_camera else 5.0

    def build_xml():
        root = ET.fromstring(_STOCK_BUILD())
        world = root.find("worldbody")
        for body in list(world.findall("body")):
            if body.get("name") in STOCK_OBJECTS:
                world.remove(body)
        build_scene(root, world)
        if show_camera:
            look = sub(world, "body", name="show_look", pos=f"0 0.08 {TABLE_Z + 0.17}")
            sub(look, "geom", type="sphere", size=".001", rgba="0 0 0 0", contype=0, conaffinity=0, mass=0)
            root.find("visual/global").set("offwidth", "1280")
            root.find("visual/global").set("offheight", "720")
            sub(world, "camera", name="show", mode="targetbody", target="show_look",
                pos=f"0.06 -0.92 {TABLE_Z + 0.66}", fovy="45")
        return ET.tostring(root, encoding="unicode")

    yam_env.build_xml = build_xml
    try:
        env = yam_env.YamEnv()
    finally:
        yam_env.build_xml = _STOCK_BUILD
    for _ in range(20):  # 1 s for the labware to settle on the table
        env.step(HOME, HOME)
    return env
