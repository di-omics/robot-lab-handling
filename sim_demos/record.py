"""Record scripted demonstrations as one LeRobot v2.1 dataset, keeping only episodes the bench scores as a success.

    python -m sim_demos.record --keep 50          (from the lab-handling-bench folder)

Each attempt builds the bench for one layout seed (1000 and up only: seeds 0 to 4 are practice layouts and 100 to 104
are the scored ones), lets the expert drive both arms through env.step, and scores the result with the bench's own
Tracker. A success is written as one episode; anything else is dropped and logged in attempts.jsonl.

What is recorded, chosen to match what the model is fed at run time (dream_examples/yam_mujoco/dream_control.py):
- 3 cameras: the overhead station camera and both wrists, rendered by env.images() (640 x 360) and resized to
  320 x 176 with the same bilinear filter the run-time client uses, under the keys of the YAM embodiment
  (observation.images.overhead, observation.images.wrist_l, observation.images.wrist_r).
- observation.state: 14 values, right arm then left arm, each 6 joint angles (rad) and the measured gripper opening
  (0 closed to 1 open), as env.state() reports them.
- action: 14 values in the same order: the joint targets and gripper command sent to env.step.
- Rate: 10 rows a second. The arms run at 20 Hz, but Dream's dataset check takes only 30, 15, 10 or 5 fps
  (shared.datasets.content_checks.USABLE_FPS). 10 fps is every second control step taken as it is: each row is the
  state and images at that step and the command sent at that step, nothing interpolated or made up. The commands of
  the steps in between are not stored. python -m sim_demos.replay checks that the stored half is enough: it replays
  every episode from its stored actions alone and scores it again.
"""

import argparse
import hashlib
import json
import shutil
import sys
import time
from fractions import Fraction
from importlib import metadata
from pathlib import Path

import av
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from PIL import Image

from labbench.sim import STEP_S
from labbench.take import code_id, set_bench
from labbench.tasks import TASKS

from .expert import ExpertFailed, PlateToTray

FPS = 10
EVERY = round(1 / (FPS * STEP_S))  # control steps per recorded row: 2
FRAME_SIZE = (320, 176)  # what the model sees at run time (dream_control.FRAME_SIZE)
CAMERAS = {"top": "observation.images.overhead", "left": "observation.images.wrist_l",
           "right": "observation.images.wrist_r"}  # env camera -> dataset video key (dream_control.VIDEO_ROLES)
JOINT_NAMES = [f"{side}_{part}" for side in ("right", "left")
               for part in (*(f"joint_{i}" for i in range(1, 7)), "gripper")]
EXPERTS = {"plate_to_tray": PlateToTray}
FIRST_ALLOWED_SEED = 1000
## Simulated seconds an attempt may take before it counts as a failure (the expert needs about 20).
ATTEMPT_LIMIT_S = 45.0
## Simulated seconds kept after the bench has scored the success, with the arm back at home.
TAIL_S = 1.0
CHUNKS_SIZE = 1000
HERE = Path(__file__).resolve().parent


def expert_rng(seed):
    """The random stream that varies the expert's speed and heights for one layout seed."""
    return np.random.default_rng([seed, 1])


def split(command):
    """A stored 14-value action as the (left, right) pair env.step takes."""
    command = np.asarray(command, dtype=np.float64)
    return command[7:], command[:7]


class VideoWriter:
    """One H.264 mp4 at a constant 10 fps: one frame per row, no B-frames, a keyframe every 2 frames (LeRobot's
    choice, so a training loader can seek to any frame cheaply)."""

    def __init__(self, path, size):
        self.container = av.open(str(path), "w")
        self.stream = self.container.add_stream("libx264", rate=FPS)
        self.stream.width, self.stream.height = size
        self.stream.pix_fmt = "yuv420p"
        self.stream.time_base = Fraction(1, FPS)
        self.stream.codec_context.gop_size = 2
        self.stream.codec_context.max_b_frames = 0
        self.stream.options = {"crf": "23", "preset": "medium"}
        self.count = 0

    def add(self, rgb):
        frame = av.VideoFrame.from_ndarray(np.ascontiguousarray(rgb), format="rgb24")
        frame.pts = self.count
        frame.time_base = Fraction(1, FPS)
        for packet in self.stream.encode(frame):
            self.container.mux(packet)
        self.count += 1

    def close(self):
        for packet in self.stream.encode():
            self.container.mux(packet)
        self.container.close()


def vector_stats(rows):
    rows = np.asarray(rows, dtype=np.float64)
    if rows.ndim == 1:
        rows = rows[:, None]
    return {"min": rows.min(0).tolist(), "max": rows.max(0).tolist(), "mean": rows.mean(0).tolist(),
            "std": rows.std(0).tolist(), "count": [int(len(rows))]}


def image_stats(frames):
    """Per-channel stats over sampled frames, scaled to 0..1, shaped (3, 1, 1) as LeRobot v2.1 writes them."""
    x = np.stack(frames).astype(np.float64) / 255.0  # (n, h, w, 3)
    per = lambda f: [[[float(v)]] for v in f]
    return {"min": per(x.min((0, 1, 2))), "max": per(x.max((0, 1, 2))), "mean": per(x.mean((0, 1, 2))),
            "std": per(x.std((0, 1, 2))), "count": [int(len(frames))]}


def attempt(task_name, seed, episode_index, first_index, tmp, size=FRAME_SIZE, video=True):
    """Play the expert once on one layout, writing the episode's videos into `tmp`.
    @param video False skips rendering and encoding (a fast check of the expert alone).
    @return (summary dict, table of rows or None when the attempt failed, stats dict)."""
    bench = set_bench(task_name, seed)
    env, world, tracker = bench.env, bench.world, bench.tracker
    expert = EXPERTS[task_name](bench, rng=expert_rng(seed))
    writers = {key: VideoWriter(tmp / f"{key}.mp4", size) for key in CAMERAS.values()} if video else {}
    samples = {key: [] for key in CAMERAS.values()}
    states, actions = [], []
    tick, error, end_at = 0, None, None
    wall0 = time.monotonic()
    try:
        # The expert sends a target on every 50 ms control step. Every second step becomes one stored row: what the
        # robot saw just before the step, and the target sent on that step.
        for left, right in expert.actions():
            if tick % EVERY == 0:
                state = env.state()
                states.append(np.r_[state["right"], state["left"]])
                actions.append(np.r_[right, left])
                if video:
                    for cam, rgb in env.images().items():
                        small = np.asarray(Image.fromarray(rgb).resize(size, Image.BILINEAR))
                        writers[CAMERAS[cam]].add(small)
                        if len(states) % 5 == 1:
                            samples[CAMERAS[cam]].append(small)
            env.step(left, right)
            tracker.update()
            tick += 1
            elapsed = world.time - tracker.t0
            if end_at is None and tracker.success_at is not None and expert.phase == "rest":
                end_at = elapsed + TAIL_S
            if end_at is not None and elapsed >= end_at and tick % EVERY == 0:
                break
            if elapsed > ATTEMPT_LIMIT_S:
                break
    except ExpertFailed as e:
        error = str(e)
    finally:
        for writer in writers.values():
            writer.close()
    kept = tracker.success_at is not None and end_at is not None and error is None
    summary = {
        "seed": seed, "kept": bool(kept), "episode_index": episode_index if kept else None,
        "frames": len(states), "sim_s": round(world.time - tracker.t0, 2),
        "success_at_s": tracker.success_at, "stages": tracker.reached, "error": error,
        "plate_in_tray_mm": (world.local("tray", world.pos("plate")) * 1000).round(1).tolist()
        if task_name == "plate_to_tray" else None,
        "layout": {k: [round(float(v), 5) for v in vals] for k, vals in bench.layout.items()},
        "expert": expert.settings, "expert_log": expert.log, "wall_s": round(time.monotonic() - wall0, 1),
    }
    env.close()
    if not kept:
        return summary, None, None
    n = len(states)
    states = np.asarray(states, dtype=np.float32)
    actions = np.asarray(actions, dtype=np.float32)
    frame_index = np.arange(n, dtype=np.int64)
    timestamps = (frame_index / FPS).astype(np.float32)
    table = pa.table({
        "observation.state": pa.array(states.tolist(), type=pa.list_(pa.float32(), states.shape[1])),
        "action": pa.array(actions.tolist(), type=pa.list_(pa.float32(), actions.shape[1])),
        "timestamp": pa.array(timestamps, type=pa.float32()),
        "frame_index": pa.array(frame_index, type=pa.int64()),
        "episode_index": pa.array(np.full(n, episode_index, dtype=np.int64), type=pa.int64()),
        "index": pa.array(first_index + frame_index, type=pa.int64()),
        "task_index": pa.array(np.zeros(n, dtype=np.int64), type=pa.int64()),
    })
    stats = {
        "observation.state": vector_stats(states), "action": vector_stats(actions),
        "timestamp": vector_stats(timestamps), "frame_index": vector_stats(frame_index),
        "episode_index": vector_stats(np.full(n, episode_index)), "index": vector_stats(first_index + frame_index),
        "task_index": vector_stats(np.zeros(n)),
        **({key: image_stats(frames) for key, frames in samples.items()} if video else {}),
    }
    return summary, table, stats


def info_json(episodes, frames, size=FRAME_SIZE):
    vector = lambda: {"dtype": "float32", "shape": [len(JOINT_NAMES)], "names": JOINT_NAMES}
    scalar = lambda dtype: {"dtype": dtype, "shape": [1], "names": None}
    w, h = size
    video = {
        "dtype": "video", "shape": [h, w, 3], "names": ["height", "width", "channels"],
        "info": {"video.height": h, "video.width": w, "video.codec": "h264", "video.pix_fmt": "yuv420p",
                 "video.is_depth_map": False, "video.fps": FPS, "video.channels": 3, "has_audio": False},
    }
    return {
        "codebase_version": "v2.1",
        "robot_type": "yam_bimanual_mujoco_sim",
        "total_episodes": episodes,
        "total_frames": frames,
        "total_tasks": 1,
        "total_videos": episodes * len(CAMERAS),
        "total_chunks": max(1, (episodes + CHUNKS_SIZE - 1) // CHUNKS_SIZE),
        "chunks_size": CHUNKS_SIZE,
        "fps": FPS,
        "splits": {"train": f"0:{episodes}"},
        "data_path": "data/chunk-{episode_chunk:03d}/episode_{episode_index:06d}.parquet",
        "video_path": "videos/chunk-{episode_chunk:03d}/{video_key}/episode_{episode_index:06d}.mp4",
        "features": {
            **{key: video for key in CAMERAS.values()},
            "observation.state": vector(),
            "action": vector(),
            "timestamp": scalar("float32"),
            "frame_index": scalar("int64"),
            "episode_index": scalar("int64"),
            "index": scalar("int64"),
            "task_index": scalar("int64"),
        },
    }


def provenance(args, first_seed, last_seed):
    """What made this dataset: source hashes, the bench's code id, library versions and the settings."""
    sha = lambda name: hashlib.sha256((HERE / name).read_bytes()).hexdigest()
    return {
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "task": args.task, "layout_seeds": [first_seed, last_seed], "training_only": True,
        "sim_control_hz": round(1 / STEP_S), "dataset_fps": FPS, "frame_size": list(args.size),
        "source_sha256": {name: sha(name) for name in ("expert.py", "record.py")},
        "labbench_code_id": code_id(),
        "package_versions": {name: metadata.version(name) for name in ("dreamlabs", "mujoco", "av", "pyarrow", "numpy")},
        "python": sys.version.split()[0],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--task", default="plate_to_tray", choices=sorted(EXPERTS))
    parser.add_argument("--first-seed", type=int, default=FIRST_ALLOWED_SEED)
    parser.add_argument("--keep", type=int, default=50, help="successful episodes to keep")
    parser.add_argument("--max-attempts", type=int, default=100)
    parser.add_argument("--out", default="sim_demos/dataset/plate_to_tray_sim", help="the session folder to write")
    parser.add_argument("--log", default="sim_demos/attempts.jsonl", help="one line per attempt, kept or not")
    parser.add_argument("--size", default="320x176", help="video frame size, WIDTHxHEIGHT (320x176 is what the model "
                        "is sent at run time; 640x360 is the full camera crop)")
    parser.add_argument("--no-video", action="store_true", help="check the expert only: no rendering, nothing written")
    args = parser.parse_args()
    if args.first_seed < FIRST_ALLOWED_SEED:
        parser.error(f"layout seeds start at {FIRST_ALLOWED_SEED}: 0 to 4 are practice and 100 to 104 are scored")
    args.size = tuple(int(v) for v in args.size.split("x"))

    task = TASKS[args.task]
    prompt = task.wording("plain")
    out = Path(args.out)
    tmp = out.parent / f".{out.name}-tmp"
    log = None
    if not args.no_video:
        if out.exists():
            shutil.rmtree(out)
        (out / "meta").mkdir(parents=True)
        log_path = Path(args.log)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log = log_path.open("w")
    episodes, all_stats, total_frames, attempts = [], [], 0, 0
    seed = args.first_seed
    started = time.monotonic()
    while len(episodes) < args.keep and attempts < args.max_attempts:
        attempts += 1
        if not args.no_video:
            if tmp.exists():
                shutil.rmtree(tmp)
            tmp.mkdir(parents=True)
        index = len(episodes)
        summary, table, stats = attempt(args.task, seed, index, total_frames, tmp, args.size, not args.no_video)
        if log:
            log.write(json.dumps(summary) + "\n")
            log.flush()
        if table is not None:
            if not args.no_video:
                chunk = index // CHUNKS_SIZE
                data = out / "data" / f"chunk-{chunk:03d}" / f"episode_{index:06d}.parquet"
                data.parent.mkdir(parents=True, exist_ok=True)
                pq.write_table(table, data)
                for key in CAMERAS.values():
                    video = out / "videos" / f"chunk-{chunk:03d}" / key / f"episode_{index:06d}.mp4"
                    video.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(tmp / f"{key}.mp4", video)
            episodes.append({"episode_index": index, "tasks": [prompt], "length": table.num_rows})
            all_stats.append({"episode_index": index, "stats": stats})
            total_frames += table.num_rows
        print(f"attempt {attempts}: seed {seed} {'KEPT as episode ' + str(index) if table is not None else 'dropped'} "
              f"({summary['frames']} frames, success at {summary['success_at_s']} s, plate in tray "
              f"{summary['plate_in_tray_mm']} mm, wall {summary['wall_s']} s"
              f"{', ' + summary['error'] if summary['error'] else ''})", flush=True)
        seed += 1
    print(f"kept {len(episodes)} of {attempts} attempts (seeds {args.first_seed} to {seed - 1}), {total_frames} frames, "
          f"{round(time.monotonic() - started)} s" + ("" if args.no_video else f" -> {out}"))
    if args.no_video:
        return
    if tmp.exists():
        shutil.rmtree(tmp)
    log.close()
    (out / "meta" / "info.json").write_text(json.dumps(info_json(len(episodes), total_frames, args.size), indent=4))
    (out / "meta" / "tasks.jsonl").write_text(json.dumps({"task_index": 0, "task": prompt}) + "\n")
    (out / "meta" / "episodes.jsonl").write_text("".join(json.dumps(e) + "\n" for e in episodes))
    (out / "meta" / "episodes_stats.jsonl").write_text("".join(json.dumps(s) + "\n" for s in all_stats))
    (HERE / "provenance.json").write_text(json.dumps(provenance(args, args.first_seed, seed - 1), indent=2) + "\n")


if __name__ == "__main__":
    main()
