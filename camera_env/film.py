"""Show the first paired layout on a common simulation clock, using recorded RGB."""
import argparse
import json
from contextlib import ExitStack
from pathlib import Path

import av
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from labbench.video import Mp4


class TakeVideo:
    def __init__(self, stack, path, skip_s):
        container = stack.enter_context(av.open(str(path)))
        self.frames = iter(container.decode(video=0))
        self.next_frame = next(self.frames)
        self.last = self.next_frame
        self.skip_s = skip_s

    def image(self, time_s):
        while self.next_frame is not None and float(self.next_frame.time) <= time_s + self.skip_s + 1e-7:
            self.last = self.next_frame
            self.next_frame = next(self.frames, None)
        return self.last.to_image().crop((0, 26, 640, 386)).resize((450, 254), Image.Resampling.LANCZOS)


def font(size):
    try:
        return ImageFont.truetype("Arial.ttf", size)
    except OSError:
        return ImageFont.load_default(size=size)


def render(run):
    root = run.parent.parent
    data = json.loads((run / "results.json").read_text())
    rows = [r for r in data["takes"] if r["seed"] == 100 and r["status"] == "complete"]
    fps, speed = 15, 6
    width, height = 20 + len(rows) * 454, 436
    fg, bg = "#eff3f4", "#17242a"
    title, label, small = font(28), font(22), font(16)
    dst = run / "plate-comparison-s100.mp4"
    with ExitStack() as stack:
        sources = []
        for row in rows:
            # The Dream video starts with 33 pre-roll steps; the scored clock follows.
            skip = 1.65 if row["policy"] == "Dream-1" else 0
            sources.append(TakeVideo(stack, (root / row["summary"]).parent / "take.mp4", skip))
        writer = Mp4(dst, width, height, fps)
        stack.callback(writer.close)
        for index in range(round(max(r["sim_s"] for r in rows) * fps / speed) + 1):
            t = index * speed / fps
            canvas = Image.new("RGB", (width, height), bg)
            d = ImageDraw.Draw(canvas)
            d.text((12, 10), "Put the plate on the black tray", font=title, fill=fg)
            d.text((12, 49), "YAM simulation   /   Layout 100   /   6× playback", font=small, fill="#b9d4d6")
            d.text((width-180, 22), f"Sim time   {t:05.1f} s", font=small, fill=fg)
            for i, (row, source) in enumerate(zip(rows, sources)):
                x = 12 + i*454
                d.text((x, 84), row["model"], font=label, fill=fg)
                canvas.paste(source.image(t), (x, 119))
                end = t >= row["sim_s"] - 1e-6
                passed = row["pass_at_s"] is not None and t >= row["pass_at_s"]
                stages = sum(v is not None and t >= v for v in row["stages"].values())
                info = "Passed" if passed else "Time limit" if end else "In progress"
                if end and row["sim_s"] < max(r["sim_s"] for r in rows)-0.5:
                    info += "  |  final view held"
                d.text((x, 386), f"{info}   ·   {stages}/3 stages", font=small, fill="#8ee7be" if passed else fg)
            writer.add(np.asarray(canvas))
    return dst


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    print(render(parser.parse_args().run.resolve()))
