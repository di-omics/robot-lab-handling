"""Replay every recorded episode from its stored actions alone, and score it again with the bench's Tracker.

    python -m sim_demos.replay            (from the lab-handling-bench folder; writes sim_demos/replay_audit.json)

The dataset stores 10 actions a second, but the arms run at 20 Hz: only every second command that moved the robot
is in the dataset. This audit asks whether the stored half is enough to do the chore. For each episode it rebuilds
the same layout (same seed), feeds the simulator only what the dataset holds, and scores the result:

- interp: the stored actions, with the missing in-between command filled in as the midpoint of its 2 neighbours.
  This is the closest stand-in for run time, where the model's actions are resampled to 20 Hz.
- hold:   each stored action sent twice (held for 2 control steps).
- open:   as interp, but the left gripper is kept fully open. A control: it must fail, or the grasp was not
  what moved the plate.

It also reports how far the replayed joint states drift from the recorded ones. No rendering, no API call.
"""

import json
import sys
import time
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

from labbench.take import set_bench

from .record import EVERY

HERE = Path(__file__).resolve().parent
SESSION = HERE / "dataset" / "plate_to_tray_sim"
TASK = "plate_to_tray"


def episode_rows(index):
    table = pq.read_table(SESSION / "data" / "chunk-000" / f"episode_{index:06d}.parquet")
    return (np.array(table.column("observation.state").to_pylist(), dtype=np.float64),
            np.array(table.column("action").to_pylist(), dtype=np.float64))


def commands(actions, mode):
    """The 20 Hz command stream rebuilt from the stored 10 Hz actions."""
    out = []
    for k, action in enumerate(actions):
        out.append(action)
        nxt = actions[k + 1] if k + 1 < len(actions) else action
        out.append(action if mode == "hold" else (action + nxt) / 2)
    out = np.array(out)
    if mode == "open":
        out[:, 13] = 1.0  # left gripper command
    return out


def replay(seed, states, actions, mode):
    bench = set_bench(TASK, seed)
    env, world, tracker = bench.env, bench.world, bench.tracker
    worst_joint = worst_grip = 0.0
    try:
        for tick, command in enumerate(commands(actions, mode)):
            if tick % EVERY == 0:
                now = env.state()
                diff = np.abs(np.r_[now["right"], now["left"]] - states[tick // EVERY])
                worst_joint = max(worst_joint, float(np.delete(diff, [6, 13]).max()))
                worst_grip = max(worst_grip, float(diff[[6, 13]].max()))
            env.step(command[7:], command[:7])
            tracker.update()
        plate = (world.local("tray", world.pos("plate")) * 1000).round(1).tolist()
        return {"pass": tracker.success_at is not None, "success_at_s": tracker.success_at,
                "stages_reached": sum(t is not None for t in tracker.reached.values()),
                "max_joint_diff_rad": round(worst_joint, 6), "max_gripper_diff": round(worst_grip, 5),
                "plate_in_tray_mm": plate}
    finally:
        env.close()


def main():
    modes = sys.argv[1:] or ["interp", "hold", "open"]
    kept = [a for a in map(json.loads, (HERE / "attempts.jsonl").read_text().splitlines()) if a["kept"]]
    started = time.monotonic()
    rows = []
    for a in kept:
        states, actions = episode_rows(a["episode_index"])
        row = {"episode_index": a["episode_index"], "seed": a["seed"], "frames": len(actions),
               "recorded_success_at_s": a["success_at_s"]}
        for mode in modes:
            row[mode] = replay(a["seed"], states, actions, mode)
        rows.append(row)
        print(f"episode {row['episode_index']} seed {row['seed']}: " + ", ".join(
            f"{m} {'pass' if row[m]['pass'] else 'FAIL'} ({row[m]['stages_reached']}/3 stages)" for m in modes), flush=True)
    summary = {}
    for mode in modes:
        results = [r[mode] for r in rows]
        summary[mode] = {
            "passed": sum(r["pass"] for r in results), "of": len(results),
            "max_joint_diff_rad": max(r["max_joint_diff_rad"] for r in results),
            "max_gripper_diff": max(r["max_gripper_diff"] for r in results),
            "plate_lifted": sum(r["stages_reached"] >= 1 for r in results),
        }
    report = {"what": __doc__.split("\n\n")[2].replace("\n", " "), "task": TASK, "modes": modes,
              "summary": summary, "episodes": rows}
    (HERE / "replay_audit.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    print(f"{round(time.monotonic() - started)} s -> {HERE / 'replay_audit.json'}")
    ok = all(summary[m]["passed"] == summary[m]["of"] for m in modes if m != "open") and \
        ("open" not in summary or summary["open"]["passed"] == 0)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
