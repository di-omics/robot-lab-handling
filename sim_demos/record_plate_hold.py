"""Record local LeRobot v2.1 training demonstrations for a left-arm YAM plate lift and hold.

Run from the bench root with the Dream simulator environment. The task uses the
acquisition prefix of the sibling plate-transfer script. All motion passes through
the simulator's ordinary joint-target interface. Only Dream's offline checker is used.
"""
import argparse
from concurrent.futures import ProcessPoolExecutor
from contextlib import ExitStack
import dataclasses
import hashlib
import importlib.metadata
import importlib.util
import itertools
import json
from pathlib import Path
import shutil
import tempfile

import av
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from dream.datasets import validate_dataset
from labbench.sim import dream_control
from labbench.take import set_bench

FPS = 10
CAMERAS = {"overhead": "top", "wrist_l": "left", "wrist_r": "right"}
BODY = dream_control.YAM_EMBODIMENT
TASK = "Pick up the deep-well plate with the left gripper and hold it steady above the bench."
DIMS = [f"{side}_joint{i}" if i < 7 else f"{side}_gripper" for side in ("right", "left") for i in range(1, 8)]
DATA = "data/chunk-{episode_chunk:03d}/episode_{episode_index:06d}.parquet"
VIDEO = "videos/chunk-{episode_chunk:03d}/{video_key}/episode_{episode_index:06d}.mp4"
KEYS = BODY["video"]


def dump(path, data):
    path.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n")


def lines(path, rows):
    path.write_text("".join(json.dumps(row, allow_nan=False) + "\n" for row in rows))


def load_expert(path):
    spec = importlib.util.spec_from_file_location("pinned_plate_expert", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.PlateToTray


def bilateral_contact(env):
    m, d = env.model, env.data
    plate = m.body("plate").id
    tips = {m.body("left_tip_left").id, m.body("left_tip_right").id}
    touching = set()
    for contact in d.contact[:d.ncon]:
        if contact.dist > 0:
            continue
        pair = {int(m.geom_bodyid[contact.geom1]), int(m.geom_bodyid[contact.geom2])}
        if plate in pair:
            touching.update(pair & tips)
    return touching == tips


def metrics(rows):
    # The final 1.5 continuous seconds, including the final simulated observation.
    return {
        "bilateral_contact_every_step": all(x[0] for x in rows),
        "minimum_lift_mm": float(min(x[1] for x in rows)) * 1000,
        "maximum_tilt_deg": float(max(x[2] for x in rows)),
        "maximum_drift_mm": float(max(np.linalg.norm(x[3] - rows[0][3]) for x in rows)) * 1000,
    }


def successful(m):
    return (m["bilateral_contact_every_step"] and m["minimum_lift_mm"] >= 30
            and m["maximum_tilt_deg"] <= 5 and m["maximum_drift_mm"] <= 3)


def stats(a):
    return {k: getattr(a, k)(axis=0).tolist() for k in ("min", "max", "mean", "std")} | {"count": [len(a)]}


class CameraWriter:
    def __init__(self, manager, path):
        self.file = manager.enter_context(av.open(str(path), "w"))
        self.stream = self.file.add_stream("libx264", rate=FPS)
        self.stream.width, self.stream.height, self.stream.pix_fmt = 640, 360, "yuv420p"
        self.stream.options = {"crf": "22", "preset": "ultrafast", "threads": "1"}

    def frame(self, rgb):
        for packet in self.stream.encode(av.VideoFrame.from_ndarray(rgb, format="rgb24")):
            self.file.mux(packet)

    def finish(self):
        for packet in self.stream.encode():
            self.file.mux(packet)


def rollout(seed, snapshot, destination=None):
    bench = set_bench("plate_to_tray", seed)
    env, world = bench.env, bench.world
    z0 = world.pos("plate")[2]
    clips, states, actions, checks = {}, [], [], []
    camera_pixels = {name: [] for name in CAMERAS}
    expert = load_expert(snapshot)(bench)
    trajectory = expert.actions()
    last_command, settle_steps = None, None
    if destination is not None:
        destination.mkdir()
    try:
        with ExitStack() as manager:
            if destination:
                clips = {name: CameraWriter(manager, destination / f"{name}.mp4") for name in CAMERAS}
            for tick in range(400):
                if settle_steps is None:
                    proposed = next(trajectory)
                    if expert.phase == "carry":
                        settle_steps = 0
                    elif tick % 2 == 0:
                        # The selected target is held for both 20 Hz ticks, exactly matching 10 Hz actions.
                        last_command = tuple(a.copy() for a in proposed)
                if tick % 2 == 0 and destination:
                    obs = env.state()
                    states.append(np.r_[obs["right"], obs["left"]])
                    actions.append(np.r_[last_command[1], last_command[0]])
                    frames = env.images()
                    for name, camera in CAMERAS.items():
                        image = frames[camera]
                        clips[name].frame(image)
                        camera_pixels[name].append(image[::16, ::16].reshape(-1, 3))
                env.step(*last_command)
                if settle_steps is not None:
                    settle_steps += 1
                    p = world.pos("plate")
                    checks.append((bilateral_contact(env), p[2] - z0, world.tilt_deg("plate"), p))
                    if settle_steps >= 40:
                        break
            else:
                raise RuntimeError("acquisition did not reach hold")
            for clip in clips.values():
                clip.finish()
    finally:
        env.close()
    verdict = metrics(checks[-30:])
    report = {"seed": seed, "metrics": verdict, "pass": successful(verdict), "layout": bench.layout}
    if destination:
        state = np.asarray(states, np.float32)
        action = np.asarray(actions, np.float32)
        np.savez(destination / "vectors.npz", state=state, action=action)
        all_stats = {"observation.state": stats(state), "action": stats(action)}
        for name, samples in camera_pixels.items():
            v = np.concatenate(samples).astype(np.float32) / 255
            s = stats(v)
            all_stats[KEYS[name]] = {k: np.asarray(x).reshape(3, 1, 1).tolist() if k != "count" else [len(state)]
                                     for k, x in s.items()}
        dump(destination / "stats.json", all_stats)
        report["frames"] = len(state)
    return report


def work(args):
    seed, snapshot, stage = args
    try:
        return rollout(seed, snapshot, stage / str(seed) if stage else None)
    except Exception as exc:
        return {"seed": seed, "pass": False, "error": f"{type(exc).__name__}: {exc}"}


def write_dataset(stage, selected):
    base = stage / "plate-hold"
    meta = base / "meta"
    meta.mkdir(parents=True)
    episodes, summaries, offset = [], [], 0
    for idx, result in enumerate(selected):
        root = stage / str(result["seed"])
        table_path = base / DATA.format(episode_chunk=idx // 1000, episode_index=idx)
        table_path.parent.mkdir(parents=True, exist_ok=True)
        with np.load(root / "vectors.npz") as source:
            state, action = source["state"], source["action"]
        n = len(state)
        arrays = {"observation.state": pa.array(state.tolist(), pa.list_(pa.float32(), 14)),
                  "action": pa.array(action.tolist(), pa.list_(pa.float32(), 14)),
                  "timestamp": np.arange(n, dtype=np.float32) / FPS,
                  "frame_index": np.arange(n, dtype=np.int64), "episode_index": np.full(n, idx, np.int64),
                  "index": np.arange(offset, offset + n, dtype=np.int64), "task_index": np.zeros(n, dtype=np.int64)}
        pq.write_table(pa.table(arrays), table_path)
        episode_stats = json.loads((root / "stats.json").read_text())
        for col in ("timestamp", "frame_index", "episode_index", "index", "task_index"):
            episode_stats[col] = stats(np.asarray(arrays[col]).reshape(-1, 1))
        for name in CAMERAS:
            target = base / VIDEO.format(episode_chunk=idx // 1000, episode_index=idx, video_key=KEYS[name])
            target.parent.mkdir(parents=True, exist_ok=True)
            (root / f"{name}.mp4").rename(target)
        summaries.append({"episode_index": idx, "stats": episode_stats})
        episodes.append({"episode_index": idx, "tasks": [TASK], "length": n})
        offset += n
    features = {k: {"dtype": "float32", "shape": [14], "names": DIMS} for k in ("observation.state", "action")}
    for k in ("timestamp", "frame_index", "episode_index", "index", "task_index"):
        features[k] = {"dtype": "float32" if k == "timestamp" else "int64", "shape": [1], "names": None}
    for k in KEYS.values():
        features[k] = {"dtype": "video", "shape": [360, 640, 3], "names": ["height", "width", "channels"],
                       "info": {"video.fps": FPS, "video.codec": "h264", "video.pix_fmt": "yuv420p",
                                "video.is_depth_map": False, "video.height": 360, "video.width": 640,
                                "video.channels": 3, "has_audio": False}}
    dump(meta / "info.json", {"codebase_version": "v2.1", "robot_type": "yam", "fps": FPS, "chunks_size": 1000,
         "total_chunks": (len(selected)+999)//1000, "total_episodes": len(selected), "total_frames": offset,
         "total_tasks": 1, "total_videos": 3 * len(selected), "splits": {"train": f"0:{len(selected)}"},
         "data_path": DATA, "video_path": VIDEO, "features": features})
    lines(meta / "episodes.jsonl", episodes)
    lines(meta / "tasks.jsonl", [{"task_index": 0, "task": TASK}])
    lines(meta / "episodes_stats.jsonl", summaries)
    return base


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("output", type=Path)
    p.add_argument("--count", type=int, default=50)
    p.add_argument("--start-seed", type=int, default=20000)
    p.add_argument("--workers", type=int, default=2)
    args = p.parse_args()
    out = args.output.resolve()
    if args.start_seed < 1000 or args.count < 1 or args.workers < 1:
        p.error("Use positive counts and training seeds >= 1000.")
    out.mkdir(parents=True, exist_ok=False)
    snapshot = out / "acquisition_source.py"
    shutil.copyfile(Path(__file__).with_name("expert.py"), snapshot)
    dump(out / "yam-embodiment.json", BODY)
    fingerprint = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in (snapshot, Path(__file__), Path("labbench/tasks.py"), Path("labbench/props.py"), Path("labbench/sim.py"))}
    dump(out / "provenance.json", {"source_sha256": fingerprint,
         "package_versions": {pkg: importlib.metadata.version(pkg) for pkg in ("dreamlabs", "dreamlabs-client", "mujoco", "av", "pyarrow")},
         "start_seed": args.start_seed, "training_only": True, "sim_hz": 20, "action_hz": FPS})
    kept, attempts = [], []
    with tempfile.TemporaryDirectory(dir=out, prefix=".staging-") as temp, ProcessPoolExecutor(args.workers) as pool:
        stage = Path(temp)
        seeds = itertools.count(args.start_seed)
        while len(kept) < args.count and len(attempts) < args.count * 4:
            batch = [next(seeds) for _ in range(min(args.workers, args.count - len(kept)))]
            for result in pool.map(work, [(s, snapshot, stage) for s in batch]):
                attempts.append(result)
                if result["pass"]:
                    result["episode_index"] = len(kept)
                    kept.append(result)
                with (out / "attempts.jsonl").open("a") as f:
                    f.write(json.dumps(result) + "\n")
                print(f"seed {result['seed']} kept {len(kept)}/{args.count} {result.get('error', '')}", flush=True)
        if len(kept) < args.count:
            raise RuntimeError("demonstration target not reached, see attempts.jsonl")
        dataset = write_dataset(stage, kept)
        report = validate_dataset(dataset, BODY)
        dump(out / "dream-local-validation.json", dataclasses.asdict(report))
        if not report.ok:
            raise RuntimeError(report.error)
        dataset.rename(out / dataset.name)
        print(report, flush=True)


if __name__ == "__main__":
    main()
