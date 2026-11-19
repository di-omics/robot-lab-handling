"""A contact sheet and a short mp4 of one recorded episode, from the dataset's own videos (what the model will see).

    python -m sim_demos.media [episode index]       (from the lab-handling-bench folder)

Writes sim_demos/media/demo_episode_<n>.mp4 (the 3 cameras tiled, played at 2x) and
sim_demos/media/contact_sheet_episode_<n>.jpg (8 evenly spaced moments).
"""

import json
import sys
from pathlib import Path

import av
import numpy as np
from PIL import Image, ImageDraw

from labbench.video import FONT, Mp4

HERE = Path(__file__).resolve().parent
SESSION = HERE / "dataset" / "plate_to_tray_sim"
KEYS = ("overhead", "wrist_l", "wrist_r")
BAR = 24


def frames(key, episode):
    path = SESSION / "videos" / "chunk-000" / f"observation.images.{key}" / f"episode_{episode:06d}.mp4"
    with av.open(str(path)) as container:
        return [f.to_ndarray(format="rgb24") for f in container.decode(video=0)]


def tile(overhead, wrist_l, wrist_r, top_line, clock):
    """Overhead at 2x on top, the left and right wrist below at 1x: 640 x 552 with a text bar."""
    canvas = Image.new("RGB", (640, BAR + 352 + 176), (250, 250, 248))
    canvas.paste(Image.fromarray(overhead).resize((640, 352), Image.BILINEAR), (0, BAR))
    canvas.paste(Image.fromarray(wrist_l), (0, BAR + 352))
    canvas.paste(Image.fromarray(wrist_r), (320, BAR + 352))
    d = ImageDraw.Draw(canvas)
    d.text((8, 5), top_line, fill=(40, 44, 50), font=FONT)
    w = d.textlength(clock, font=FONT)
    d.text((632 - w, 5), clock, fill=(40, 44, 50), font=FONT)
    d.text((8, BAR + 356), "left wrist", fill=(255, 255, 255), font=FONT)
    d.text((328, BAR + 356), "right wrist", fill=(255, 255, 255), font=FONT)
    return np.asarray(canvas)


def main():
    episode = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    info = json.loads((SESSION / "meta" / "info.json").read_text())
    task = json.loads((SESSION / "meta" / "tasks.jsonl").read_text().splitlines()[0])["task"]
    fps = info["fps"]
    videos = {key: frames(key, episode) for key in KEYS}
    n = min(len(v) for v in videos.values())
    line = f"{task}   [scripted demo, episode {episode}]"
    tiles = [tile(*(videos[k][i] for k in KEYS), line, f"{i / fps:4.1f} s") for i in range(n)]
    out = HERE / "media"
    out.mkdir(exist_ok=True)
    mp4 = out / f"demo_episode_{episode:03d}.mp4"
    writer = Mp4(mp4, 640, BAR + 352 + 176, fps * 2)  # 2x speed
    for t in tiles:
        writer.add(t)
    writer.close()
    picks = [tiles[round(i * (n - 1) / 7)] for i in range(8)]
    h, w = picks[0].shape[:2]
    sheet = Image.new("RGB", (4 * w // 2, 2 * h // 2), "white")
    for i, t in enumerate(picks):
        sheet.paste(Image.fromarray(t).resize((w // 2, h // 2), Image.LANCZOS), ((i % 4) * w // 2, (i // 4) * h // 2))
    jpg = out / f"contact_sheet_episode_{episode:03d}.jpg"
    sheet.save(jpg, quality=88)
    print(mp4, jpg)


if __name__ == "__main__":
    main()
