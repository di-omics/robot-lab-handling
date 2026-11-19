"""Audit the exported plate-hold demonstrations, replay five and render episode zero.

Run as python -m sim_demos.check_plate_hold <run-directory> after generation.
"""
import argparse
import json
from contextlib import ExitStack
from pathlib import Path

import av
import numpy as np
import pyarrow.parquet as pq
from PIL import Image, ImageDraw, ImageFont

from labbench.take import set_bench
from .record_plate_hold import CAMERAS, DATA, FPS, KEYS, VIDEO, bilateral_contact, dump, metrics, successful


def replay(seed, states, actions, open_gripper):
    bench = set_bench("plate_to_tray", seed)
    w, env = bench.world, bench.env
    z0 = w.pos("plate")[2]
    checks, max_joint_error, max_opening_error = [], 0.0, 0.0
    try:
        for state, action in zip(states, actions, strict=True):
            obs = env.state()
            error = np.abs(np.r_[obs["right"], obs["left"]] - state).reshape(2, 7)
            max_joint_error = max(max_joint_error, float(error[:, :6].max()))
            max_opening_error = max(max_opening_error, float(error[:, 6].max()))
            right, left = action[:7].copy(), action[7:].copy()
            if open_gripper:
                left[6] = 1
            for _ in range(2):
                env.step(left, right)
                p = w.pos("plate")
                checks.append((bilateral_contact(env), p[2] - z0, w.tilt_deg("plate"), p))
    finally:
        env.close()
    score = metrics(checks[-30:])
    return {"pass": successful(score), "metrics": score, "max_joint_error_rad": max_joint_error,
            "max_normalized_grip_error": max_opening_error,
            "within_numeric_tolerance": max(max_joint_error, max_opening_error) <= 1e-4}


def font(size):
    for path in ("/System/Library/Fonts/Supplemental/Arial.ttf", "/Library/Fonts/Arial.ttf"):
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def preview(paths, count, out):
    labels = ["Overhead", "Left wrist", "Right wrist"]
    sheet = Image.new("RGB", (960, 4 * 212), "#101317")
    with ExitStack() as stack:
        inputs = [stack.enter_context(av.open(str(path))) for path in paths]
        clips = [c.decode(video=0) for c in inputs]
        output = stack.enter_context(av.open(str(out / "plate-hold-preview.mp4"), "w"))
        stream = output.add_stream("libx264", rate=FPS)
        stream.width, stream.height, stream.pix_fmt = 960, 212, "yuv420p"
        stream.options = {"crf": "19", "preset": "fast"}
        picks = [0, 43, 65, count-1]
        frames_seen = 0
        for frame_id, group in enumerate(zip(*clips, strict=True)):
            strip = Image.new("RGB", (960, 212), "#101317")
            text = ImageDraw.Draw(strip)
            for col, (cam, frame) in enumerate(zip(labels, group)):
                strip.paste(frame.to_image().resize((320, 180), Image.Resampling.LANCZOS), (320 * col, 0))
                text.text((320*col + 8, 186), f"{cam}   {frame_id / FPS:.1f} s", font=font(16), fill="#eff2f4")
            for packet in stream.encode(av.VideoFrame.from_image(strip)):
                output.mux(packet)
            if frame_id in picks:
                sheet.paste(strip, (0, picks.index(frame_id)*212))
            frames_seen += 1
        for packet in stream.encode():
            output.mux(packet)
    if frames_seen != count:
        raise ValueError("preview source decoding did not match episode length")
    sheet.save(out / "plate-hold-sheet.jpg", quality=94)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    run = parser.parse_args().run
    dataset = run / "plate-hold"
    total = 0
    checks = []
    attempts = [json.loads(line) for line in (run / "attempts.jsonl").read_text().splitlines()]
    for attempt in (a for a in attempts if a["pass"]):
        idx, n = attempt["episode_index"], attempt["frames"]
        fields = {"episode_chunk": idx // 1000, "episode_index": idx}
        table = pq.read_table(dataset / DATA.format(**fields))
        if list(range(total, total + n)) != table["index"].to_pylist():
            raise ValueError("row indices are not globally contiguous")
        if list(range(n)) != table["frame_index"].to_pylist() or set(table["episode_index"].to_pylist()) != {idx}:
            raise ValueError("episode-local row IDs are inconsistent")
        if idx < 5:
            states = np.array(table["observation.state"].to_pylist(), float)
            actions = np.array(table["action"].to_pylist(), float)
            on = replay(attempt["seed"], states, actions, False)
            off = replay(attempt["seed"], states, actions, True)
            if not on["pass"] or off["pass"]:
                raise ValueError(f"replay/control failed on episode {idx}: {on}, {off}")
            checks.append({"episode_index": idx, "seed": attempt["seed"], "replay": on, "locked_open": off})
        if idx == 0 and not ((run / "plate-hold-sheet.jpg").is_file() and (run / "plate-hold-preview.mp4").is_file()):
            paths = [dataset / VIDEO.format(**fields, video_key=KEYS[name]) for name in CAMERAS]
            preview(paths, n, run)
        total += n
    dump(run / "replay-audit.json", {"all_rows_checked": total, "paired_replays": checks,
         "positive": sum(x["replay"]["pass"] for x in checks),
         "within_numeric_tolerance": sum(x["replay"]["within_numeric_tolerance"] for x in checks),
         "numeric_tolerance": {"joint_radians": 1e-4, "normalized_grip": 1e-4},
         "open_gripper_control_positive": sum(x["locked_open"]["pass"] for x in checks)})


if __name__ == "__main__":
    main()
