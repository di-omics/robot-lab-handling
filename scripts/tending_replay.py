"""Replay recorded takes offline and check that they give the recorded result.

For every actions.f64le under the given folders, this script reads trace.json beside it (if there is one) and the
recorded result beside it: summary.json (the layout scripts/tending_run.py writes) or recorded.json (a slimmer
layout with task, seed, stages, success, success_at_s, objects, steps, priming_steps, actions_sha256). It then
builds the same bench, feeds the recorded rows to env.step in order with the stage tracker updated after every step
as a live take does (its clock starts after the priming steps), and compares every stage time, success,
success_at_s, and each object's final position (within 1e-4 m) and tilt (within 0.1 degree) with the record.

It also checks that the record was made by the bench code and tending code running now. It writes replay.json
beside the actions, with a "motion" block that says how far each object moved after the priming steps (it
plays no part in the checks), and prints 1 line per take. A take whose record has an error has no score: it is
replayed for its recorded steps and reported as "stopped, no score": its sha256s, row count and code fingerprints
are checked, but not its result. A summary.json with no actions beside it is a problem, unless it is in an
unfinished/ folder (a take that never finished).
Exit code 1 if any completed take disagrees, any sha256 or code version is wrong, a summary has no actions, or a
folder has nothing to replay. No model, no network, no credentials: only labbench.take.set_bench, env.step, the
stage tracker and the bench's own pose readings are used.

Usage (from the repo root):
  python scripts/tending_replay.py runs/NAME [more folders]
"""

import hashlib
import json
import sys
from importlib import metadata
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import tending  # noqa: E402  (first: it adds the chores to labbench's task table)
import labbench  # noqa: E402
import labbench.take as lt  # noqa: E402
import mujoco  # noqa: E402
import numpy as np  # noqa: E402
from tending.dispenser import low_z  # noqa: E402

POS_TOL_M = 1e-4
TILT_TOL_DEG = 0.1


def versions():
    return {"labbench": labbench.__version__, "code": lt.CODE_ID, "dreamlabs": metadata.version("dreamlabs"),
            "mujoco": mujoco.__version__, "tending": tending.TENDING_ID}


def read_record(folder, trace):
    """The recorded result beside the actions: summary.json, recorded.json, or the summary trace.json names."""
    for name in ("summary.json", "recorded.json", (trace or {}).get("summary")):
        if name and (folder / name).is_file():
            return folder / name
    return None


def motion_meter(world, names):
    """How each object moved, measured from its pose when the meter starts. @return (update, motion): call
    update() after every step. Per object: largest horizontal move, largest rise of its origin (the centre of its
    underside), largest tilt, and the steps the robot touched it. For the plate also the largest rise of its lowest
    underside corner, overall and while tilted under 10 degrees (the tilt the lift stage allows)."""
    start = {n: world.pos(n) for n in names}
    motion = {n: {"moved_max_xy_m": 0.0, "rose_max_m": 0.0, "tilt_max_deg": 0.0, "touched_steps": 0} for n in names}
    if "plate" in motion:
        motion["plate"].update(low_corner_rose_max_m=0.0, low_corner_rose_max_m_under_10_deg=0.0)

    def update():
        for n, m in motion.items():
            p, tilt = world.pos(n), world.tilt_deg(n)
            m["moved_max_xy_m"] = max(m["moved_max_xy_m"], float(np.linalg.norm(p[:2] - start[n][:2])))
            m["rose_max_m"] = max(m["rose_max_m"], float(p[2] - start[n][2]))
            m["tilt_max_deg"] = max(m["tilt_max_deg"], tilt)
            m["touched_steps"] += int(world.held(n))
            if n == "plate":
                rise = float(low_z(world, n) - start[n][2])
                m["low_corner_rose_max_m"] = max(m["low_corner_rose_max_m"], rise)
                if tilt < 10.0:
                    m["low_corner_rose_max_m_under_10_deg"] = max(m["low_corner_rose_max_m_under_10_deg"], rise)

    return update, motion


def replay_rows(task, seed, rows, priming_steps):
    """Build the bench and play the rows as a live take does.
    @return (the bench after the last row, the motion of each object after the priming steps)."""
    bench = lt.set_bench(task, seed, show=False)
    env, world, tracker = bench.env, bench.world, bench.tracker
    meter = None
    if priming_steps == 0:
        tracker.t0 = world.time
        meter = motion_meter(world, bench.task.movable)
    for i, row in enumerate(rows):
        env.step(row[:7], row[7:])
        tracker.update()
        if meter:
            meter[0]()
        if i + 1 == priming_steps:  # run_take starts the stage clock here
            tracker.t0 = world.time
            meter = motion_meter(world, bench.task.movable)
    motion = meter[1] if meter else {}
    return bench, {n: {k: round(v, 1 if k.endswith("deg") else 4) if isinstance(v, float) else v
                       for k, v in m.items()} for n, m in motion.items()}


def compare(record, result):
    """@return A list of what differs between a recorded result and a replayed one (empty when they agree)."""
    bad = []
    for name, t in record["stages"].items():
        if result["stages"].get(name, "missing") != t:
            bad.append(f"stage {name}: recorded {t}, replay {result['stages'].get(name, 'missing')}")
    for key in ("success", "success_at_s"):
        if record[key] != result[key]:
            bad.append(f"{key}: recorded {record[key]}, replay {result[key]}")
    for name, obj in record["objects"].items():
        got = result["objects"][name]
        off = float(np.max(np.abs(np.array(got["pos"]) - np.array(obj["pos"]))))
        if off > POS_TOL_M + 1e-9:
            bad.append(f"{name} position off by {off:.5f} m")
        if abs(got["tilt_deg"] - obj["tilt_deg"]) > TILT_TOL_DEG + 1e-9:
            bad.append(f"{name} tilt: recorded {obj['tilt_deg']}, replay {got['tilt_deg']:.2f}")
    return bad


def replay_take(actions_path):
    """Replay 1 take and write replay.json beside it. @return (status, problems, replay dict)."""
    folder = actions_path.parent
    trace = json.loads((folder / "trace.json").read_text()) if (folder / "trace.json").is_file() else None
    record_path = read_record(folder, trace)
    record = json.loads(record_path.read_text()) if record_path else None
    meta = trace or record or {}
    problems = []

    sha = hashlib.sha256(actions_path.read_bytes()).hexdigest()
    if sha != meta.get("actions_sha256"):
        problems.append(f"actions sha256 {sha[:12]} is not the recorded {str(meta.get('actions_sha256'))[:12]}")
    if trace and record_path and trace.get("summary_sha256"):
        if hashlib.sha256(record_path.read_bytes()).hexdigest() != trace["summary_sha256"]:
            problems.append("summary sha256 is not the recorded one")
    now = versions()
    for source in (trace or {}, record or {}):
        for key in ("code", "tending"):
            if key in source.get("versions", {}) and source["versions"][key] != now[key]:
                problems.append(f"recorded {key} {source['versions'][key]}, running {now[key]}")
    if record is None:  # run_take raised before it wrote a summary: nothing to score
        return "no recorded result, not replayed", problems, None

    rows = np.frombuffer(actions_path.read_bytes(), dtype="<f8").reshape(-1, 14)
    if "steps" in meta and meta["steps"] != len(rows):
        problems.append(f"{len(rows)} rows, recorded steps {meta['steps']}")
    bench, motion = replay_rows(record["task"], record["seed"], rows, int(meta.get("priming_steps", 0)))
    world, tracker = bench.world, bench.tracker
    result = {
        "task": record["task"], "seed": record["seed"], **tracker.summary(),
        "objects": {n: {"pos": world.pos(n).round(4).tolist(), "tilt_deg": round(world.tilt_deg(n), 1)}
                    for n in bench.task.movable},
        "motion": motion, "qpos": bench.env.data.qpos.copy().tolist(),
        "steps": len(rows), "actions_sha256": sha, "versions": now,
    }
    bench.env.close()
    if record.get("error"):
        status = "stopped, no score"
    else:
        problems += compare(record, result)
        status = "agrees" if not problems else "DISAGREES"
    if status == "stopped, no score" and problems:
        status = "stopped, no score, CHECK FAILED"
    result.update(status=status, problems=problems)
    keep = ("task", "seed", "stages", "success", "success_at_s", "objects", "motion", "steps", "actions_sha256",
            "versions", "status", "problems")
    (folder / "replay.json").write_text(json.dumps({k: result[k] for k in keep}, indent=2))
    return status, problems, result


def main(folders):
    failed = False
    for folder in map(Path, folders):
        found = sorted(folder.rglob("actions.f64le"))
        for actions_path in found:
            status, problems, _ = replay_take(actions_path)
            failed |= bool(problems)
            print(f"{actions_path.parent}: {status}" + (f" ({'; '.join(problems)})" if problems else ""))
        for summary_path in sorted(folder.rglob("summary.json")):
            if (summary_path.parent / "actions.f64le").is_file():
                continue
            if summary_path.resolve().parents[2].name == "unfinished":  # <out>/unfinished/<staging>/<take>
                print(f"{summary_path.parent}: unfinished take, not replayed")
                continue
            failed = True
            print(f"{summary_path.parent}: PROBLEM (summary.json with no actions.f64le beside it)")
        if not found:
            failed = True
            print(f"{folder}: PROBLEM (nothing to replay{'' if folder.is_dir() else ', no such folder'})")
    return 1 if failed else 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    sys.exit(main(sys.argv[1:]))
