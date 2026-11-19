"""Trajectory grader for two-handed desealing of a stationary, dry 96-well plate.

Run from the lab-handling-bench directory:
    python -m sim_demos.seal_benchmark --controls
    python -m sim_demos.seal_benchmark --trace path/to/oracle-telemetry.jsonl

The independent observer must record one JSON object per frame, including:
  t_s: monotonic elapsed time, seconds. Log from settled, fully sealed reset through timeout.
  plate_xyz_mm, plate_qwxyz: measured plate position and unit quaternion in a fixed station frame.
  attached: eight booleans, ordered from pull tab to far edge. True means any bond remains
      in that transverse strip. Measure the bond state independently of the commanded peel.
  clear_wells: number of wells (0..96) whose entire aperture is uncovered. Use a separate
      geometry or vision check: detached film can still cover wells.
  brace_contact, tab_grasp: observed load-bearing left-hand contact with the plate and actual
      opposing right-finger contacts on the intact pull tab. Jaw commands/proximity are insufficient.
  film_intact, operator_intervention: observed sheet integrity and any human intervention.

These are provisional benchmark limits. The first release needs 150 ms of established bimanual
contact. The verified terminal state must persist for 500 ms. Record at 20 Hz or faster
(maximum accepted sampling gap 75 ms). Existing transfer-only trajectories lack seal telemetry.
The controls below are generated observer signals, not physics runs or policy demonstrations.
"""
import argparse
import json
import math
from pathlib import Path

ZONES = 8
WELLS = 96
MAX_DRIFT_MM = 5.0
MAX_ROTATION_DEG = 5.0
MAX_SAMPLE_GAP_S = 0.075
CONTACT_LEAD_S = 0.15
END_DWELL_S = 0.5
VERSION = "dry-plate-peel-v1"


def finite_number(value):
    return type(value) in (int, float) and math.isfinite(value)


def validate(frame):
    if not isinstance(frame, dict) or not finite_number(frame.get("t_s")):
        raise ValueError("missing or invalid t_s")
    for field, length in (("plate_xyz_mm", 3), ("plate_qwxyz", 4)):
        vector = frame.get(field)
        if not isinstance(vector, list) or len(vector) != length or not all(map(finite_number, vector)):
            raise ValueError(f"missing or invalid {field}")
    if abs(math.hypot(*frame["plate_qwxyz"]) - 1) > 1e-3:
        raise ValueError("plate_qwxyz must be a unit quaternion")
    attached = frame.get("attached")
    if not isinstance(attached, list) or len(attached) != ZONES or any(type(v) is not bool for v in attached):
        raise ValueError("expected eight boolean attachment witnesses")
    wells = frame.get("clear_wells")
    if type(wells) is not int or not 0 <= wells <= WELLS:
        raise ValueError("invalid clear_wells count")
    for field in ("brace_contact", "tab_grasp", "film_intact", "operator_intervention"):
        if type(frame.get(field)) is not bool:
            raise ValueError(f"missing or invalid {field}")


def rotation_from_reset(q, reset):
    # The two opposite quaternion signs represent the same pose.
    cos_half = abs(sum(a * b for a, b in zip(q, reset))) / (math.hypot(*q) * math.hypot(*reset))
    return math.degrees(2 * math.acos(min(1.0, cos_half)))


def grade(frames):
    stages = {"contacts_established": None, "partial_peel": None,
              "fully_detached": None, "all_wells_clear_at_end": None}
    violations = {}
    reset = previous = None
    contact_since = clear_since = None
    peel_started = peel_done = False
    max_drift = max_rotation = 0.0
    peak_clear = samples = 0
    try:
        for frame in frames:
            validate(frame)
            t = frame["t_s"]
            attached = frame["attached"]
            if reset is None:
                if not all(attached) or frame["clear_wells"] or not frame["film_intact"]:
                    raise ValueError("invalid reset: require a fully covered, intact and attached seal")
                reset = frame
            if previous and not 0 < t - previous["t_s"] <= MAX_SAMPLE_GAP_S + 1e-9:
                raise ValueError("nonmonotonic timestamp or missing observation interval")
            samples += 1
            elapsed = round(t - reset["t_s"], 6)
            drift = math.dist(frame["plate_xyz_mm"], reset["plate_xyz_mm"])
            rotation = rotation_from_reset(frame["plate_qwxyz"], reset["plate_qwxyz"])
            max_drift = max(max_drift, drift)
            max_rotation = max(max_rotation, rotation)
            if drift > MAX_DRIFT_MM + 1e-8 or rotation > MAX_ROTATION_DEG + 1e-8:
                violations.setdefault("plate_moved", elapsed)
            if not frame["film_intact"]:
                violations.setdefault("torn_film", elapsed)
            if frame["operator_intervention"]:
                violations.setdefault("operator_intervened", elapsed)
            if previous and any(was is False and now is True for was, now in zip(previous["attached"], attached)):
                violations.setdefault("released_zone_reattached", elapsed)
            released = attached.count(False)
            if attached != [False] * released + [True] * (ZONES - released):
                violations.setdefault("release_out_of_order", elapsed)

            contacts = frame["brace_contact"] and frame["tab_grasp"]
            if contacts and contact_since is None:
                contact_since = t
            if not contacts:
                contact_since = None
            ready = contact_since is not None and t - contact_since + 1e-9 >= CONTACT_LEAD_S
            if ready and stages["contacts_established"] is None:
                stages["contacts_established"] = elapsed
            if released and not peel_started:
                if not ready:
                    violations.setdefault("release_before_bimanual_contact", elapsed)
                peel_started = True
            if peel_started and not peel_done and not contacts:
                violations.setdefault("contact_lost_during_peel", elapsed)
            if 0 < released < ZONES and stages["partial_peel"] is None:
                stages["partial_peel"] = elapsed
            if released == ZONES and not peel_done:
                peel_done = True
                stages["fully_detached"] = elapsed
                if stages["partial_peel"] is None:
                    violations.setdefault("no_progressive_peel_witness", elapsed)

            peak_clear = max(peak_clear, frame["clear_wells"])
            if released == ZONES and frame["clear_wells"] == WELLS:
                if clear_since is None:
                    clear_since = t
            else:
                clear_since = None
            previous = frame

        if samples < 2:
            raise ValueError("a trajectory requires at least two observations")
    except (ValueError, TypeError) as error:
        return {"version": VERSION, "status": "unscorable", "reason": str(error), "observations_read": samples}

    dwell = 0.0 if clear_since is None else previous["t_s"] - clear_since
    if clear_since is not None and dwell + 1e-9 >= END_DWELL_S:
        stages["all_wells_clear_at_end"] = round(clear_since - reset["t_s"] + END_DWELL_S, 6)
    passed = all(value is not None for value in stages.values()) and not violations
    return {"version": VERSION, "status": "pass" if passed else "fail",
            "reached_at_s": stages, "violations_at_s": violations, "observations": samples,
            "peak_clear_wells": peak_clear, "final_clear_wells": previous["clear_wells"],
            "terminal_clear_dwell_s": round(dwell, 6), "max_plate_drift_mm": round(max_drift, 4),
            "max_plate_rotation_deg": round(max_rotation, 4)}


def synthetic_trace(case):
    """Deterministic 20 Hz signals for verifying the grader. No policy or hardware is involved."""
    for i in range(48):
        released = min(ZONES, max(0, (i - 8) // 2))
        if case == "paused_clean_peel":
            active_steps = min(i, 16) + max(0, i - 24)
            released = min(ZONES, max(0, (active_steps - 8) // 2))
        if case == "no_motion":
            released = 0
        if case == "partial_peel":
            released = min(4, released)
        if case == "end_frame_only":
            released = 8 if i >= 24 else 0
        attached = [False] * released + [True] * (ZONES - released)
        if case == "wrong_edge" and 0 < released < ZONES:
            attached.reverse()
        frame = {"t_s": i / 20, "plate_xyz_mm": [0.0, 0.0, 0.0], "plate_qwxyz": [1.0, 0.0, 0.0, 0.0],
                 "attached": attached, "clear_wells": released * (WELLS // ZONES),
                 "brace_contact": 2 <= i <= 26, "tab_grasp": 3 <= i <= 27,
                 "film_intact": True, "operator_intervention": False}
        if case == "paused_clean_peel":
            frame["brace_contact"] = i >= 3
            frame["tab_grasp"] = i >= 4
            frame["plate_xyz_mm"] = [32.0 + 2.0 * math.sin(i / 10), -8.0, 760.0]
            frame["plate_qwxyz"] = [-1.0, 0.0, 0.0, 0.0] if i % 2 else [1.0, 0.0, 0.0, 0.0]
            if i >= 36:
                frame["brace_contact"] = frame["tab_grasp"] = False
        if case == "late_grasp":
            frame["tab_grasp"] = i >= 10
        if case == "tilt_returns" and 14 <= i <= 16:
            half_angle = math.radians(7) / 2
            frame["plate_qwxyz"] = [math.cos(half_angle), math.sin(half_angle), 0.0, 0.0]
        if case == "no_brace":
            frame["brace_contact"] = False
        if case == "lost_pinch" and i == 15:
            frame["tab_grasp"] = False
        if case == "plate_returns" and 15 <= i < 17:
            frame["plate_xyz_mm"][0] = 9.0
        if case == "torn_film" and i >= 25:
            frame["film_intact"] = False
        if case == "film_drapes_back" and i >= 41:
            frame["clear_wells"] = 80
        if case == "intervened" and i == 14:
            frame["operator_intervention"] = True
        if case == "short_final_dwell" and i > 26:
            break
        if case == "observer_dropout" and i == 17:
            continue
        if case == "missing_bond_channel" and i == 8:
            del frame["attached"]
        yield frame


EXPECTED = {
    "clean_peel": "pass", "paused_clean_peel": "pass", "no_motion": "fail",
    "partial_peel": "fail", "late_grasp": "fail", "tilt_returns": "fail", "end_frame_only": "fail", "wrong_edge": "fail",
    "no_brace": "fail", "lost_pinch": "fail", "plate_returns": "fail", "torn_film": "fail",
    "film_drapes_back": "fail", "intervened": "fail", "short_final_dwell": "fail",
    "observer_dropout": "unscorable", "missing_bond_channel": "unscorable",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--trace", type=Path, help="grade JSON Lines oracle telemetry")
    mode.add_argument("--controls", action="store_true", help="self-test the grader")
    args = parser.parse_args()
    if args.controls:
        actual = {name: grade(synthetic_trace(name))["status"] for name in EXPECTED}
        print(json.dumps({"scope": "synthetic grader controls", "results": actual}, indent=2))
        return 0 if actual == EXPECTED else 1
    with args.trace.open() as trace:
        result = grade(json.loads(line) for line in trace)
    print(json.dumps(result, indent=2))
    return {"pass": 0, "fail": 1, "unscorable": 2}[result["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
