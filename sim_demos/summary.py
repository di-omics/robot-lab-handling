"""The numbers quoted in NOTES.md and PROPOSAL.md, computed from the files (attempts.jsonl and the dataset).

    python -m sim_demos.summary          (from the lab-handling-bench folder; writes sim_demos/summary.json)
"""

import json
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

from labbench.take import set_bench

from .expert import ArmIK
from .record import FPS

HERE = Path(__file__).resolve().parent
SESSION = HERE / "dataset" / "plate_to_tray_sim"


def main():
    attempts = [json.loads(line) for line in (HERE / "attempts.jsonl").read_text().splitlines()]
    kept = [a for a in attempts if a["kept"]]
    episodes = [json.loads(line) for line in (SESSION / "meta" / "episodes.jsonl").read_text().splitlines()]
    seconds = np.array([e["length"] for e in episodes]) / FPS
    files = [p for p in SESSION.rglob("*") if p.is_file() and not p.name.startswith(".")]
    out = {
        "attempts": len(attempts), "kept": len(kept), "dropped": len(attempts) - len(kept),
        "seeds": [attempts[0]["seed"], attempts[-1]["seed"]],
        "frames": int(sum(e["length"] for e in episodes)), "fps": FPS,
        "robot_minutes": round(float(seconds.sum()) / 60, 2),
        "episode_s": {"min": float(seconds.min()), "median": float(np.median(seconds)), "max": float(seconds.max())},
        "success_at_s": {"min": min(a["success_at_s"] for a in kept), "max": max(a["success_at_s"] for a in kept)},
        "files": len(files), "bytes": int(sum(p.stat().st_size for p in files)),
        "record_wall_min": round(sum(a["wall_s"] for a in attempts) / 60, 1),
    }
    # Where things ended and how much the expert had to correct, over the kept episodes (mm).
    end = np.abs(np.array([a["plate_in_tray_mm"] for a in kept]))
    hand = np.abs(np.array([a["expert_log"][0]["plate_in_hand_mm"] for a in kept]))
    trim = np.abs(np.array([a["expert_log"][1]["carry_trim_mm"] for a in kept]))
    out["plate_off_tray_centre_mm_max"] = end[:, :2].max(0).tolist()
    out["plate_off_hand_centre_mm_max"] = hand[:, :2].max(0).tolist()
    out["carry_trim_mm_max"] = trim[:, :2].max(0).tolist()
    out["expert_speed_factor"] = [min(a["expert"]["speed"] for a in kept), max(a["expert"]["speed"] for a in kept)]
    if "layout" in kept[0]:
        plate = np.array([a["layout"]["plate"] for a in kept])
        tray = np.array([a["layout"]["tray"] for a in kept])
        out["layout_spread"] = {
            "plate_x_mm": [round(plate[:, 0].min() * 1000, 1), round(plate[:, 0].max() * 1000, 1)],
            "plate_y_mm": [round(plate[:, 1].min() * 1000, 1), round(plate[:, 1].max() * 1000, 1)],
            "plate_yaw_deg": [round(float(np.degrees(plate[:, 2].min())), 1), round(float(np.degrees(plate[:, 2].max())), 1)],
            "tray_x_mm": [round(tray[:, 0].min() * 1000, 1), round(tray[:, 0].max() * 1000, 1)],
            "tray_y_mm": [round(tray[:, 1].min() * 1000, 1), round(tray[:, 1].max() * 1000, 1)],
        }
    # Speeds of the commanded motion, from the stored actions: joints (rad/s) and the left grasp point (m/s).
    bench = set_bench("plate_to_tray", attempts[0]["seed"])
    ik = ArmIK(bench.env, "left")
    joint_peak, hand_peak, grip_states = np.zeros(6), [], []
    for e in episodes:
        table = pq.read_table(SESSION / "data" / "chunk-000" / f"episode_{e['episode_index']:06d}.parquet")
        action = np.array(table.column("action").to_pylist())
        state = np.array(table.column("observation.state").to_pylist())
        joint_peak = np.maximum(joint_peak, np.abs(np.diff(action[:, 7:13], axis=0)).max(0) * FPS)
        path = np.array([ik.fk(q)[0] for q in action[:, 7:13]])
        hand_peak.append(float(np.linalg.norm(np.diff(path, axis=0), axis=1).max() * FPS))
        held = state[action[:, 13] < 0.61, 13]
        grip_states.append(float(np.median(held)))
        assert np.abs(action[:, :6]).max() == 0 and (action[:, 6] == 1).all(), "the right arm should stay at home"
    bench.env.close()
    out["peak_joint_speed_rad_s"] = joint_peak.round(2).tolist()
    out["peak_hand_speed_m_s"] = {"median": round(float(np.median(hand_peak)), 3), "max": round(float(np.max(hand_peak)), 3)}
    out["gripper_opening_while_holding"] = {"min": round(min(grip_states), 3), "max": round(max(grip_states), 3)}
    audit = HERE / "replay_audit.json"
    if audit.exists():
        out["replay"] = json.loads(audit.read_text())["summary"]
    (HERE / "summary.json").write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
