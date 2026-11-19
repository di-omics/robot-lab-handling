"""Take videos: what the model saw (overhead and both wrists) in one frame, with the clock and the score."""

import av
import numpy as np
from PIL import Image, ImageDraw, ImageFont

BAR = 26


def _font(size=13):
    for path in ("/System/Library/Fonts/Helvetica.ttc", "/System/Library/Fonts/HelveticaNeue.ttc"):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


FONT = _font()


class Mp4:
    """A small H.264 writer."""

    def __init__(self, path, width, height, fps):
        self.container = av.open(str(path), "w")
        self.stream = self.container.add_stream("libx264", rate=fps)
        self.stream.width, self.stream.height, self.stream.pix_fmt = width, height, "yuv420p"
        self.stream.options = {"crf": "23", "preset": "veryfast"}

    def add(self, rgb):
        frame = av.VideoFrame.from_ndarray(np.ascontiguousarray(rgb), format="rgb24")
        for packet in self.stream.encode(frame):
            self.container.mux(packet)

    def close(self):
        for packet in self.stream.encode():
            self.container.mux(packet)
        self.container.close()


def tile(images, line_left, line_right=""):
    """Overhead on top, left and right wrist below, a text bar above: 640 x 566."""
    canvas = Image.new("RGB", (640, BAR + 540), (250, 250, 248))
    canvas.paste(Image.fromarray(images["top"]), (0, BAR))
    canvas.paste(Image.fromarray(images["left"]).resize((320, 180)), (0, BAR + 360))
    canvas.paste(Image.fromarray(images["right"]).resize((320, 180)), (320, BAR + 360))
    d = ImageDraw.Draw(canvas)
    d.text((8, 6), line_left, fill=(40, 44, 50), font=FONT)
    if line_right:
        w = d.textlength(line_right, font=FONT)
        d.text((632 - w, 6), line_right, fill=(40, 44, 50), font=FONT)
    d.text((8, BAR + 364), "left wrist", fill=(255, 255, 255), font=FONT)
    d.text((328, BAR + 364), "right wrist", fill=(255, 255, 255), font=FONT)
    return np.asarray(canvas)


def speed_clip(src, dst, factor=4, headline="", size=None):
    """A faster copy of a take video with one headline line on top (for showing people, not for scoring).
    @param factor How many times faster than the take's own clock.
    @param size Optional (width, height) to scale the picture to.
    """
    with av.open(str(src)) as container:
        stream = container.streams.video[0]
        fps = float(stream.average_rate)
        frames = [f.to_ndarray(format="rgb24") for f in container.decode(video=0)]
    if not frames:
        return None
    keep = max(1, round(factor * fps / 20)) if fps < 20 else factor  # write at 20 fps when the source is slower
    out_fps = 20 if fps < 20 else round(fps)
    h, w = frames[0].shape[:2]
    if size:
        w, h = size
    bar = 44 if headline else 0
    font = _font(20)
    writer = Mp4(dst, w, h + bar, out_fps)
    for frame in frames[::keep]:
        picture = Image.fromarray(frame)
        if size:
            picture = picture.resize((w, h), Image.LANCZOS)
        canvas = Image.new("RGB", (w, h + bar), (250, 250, 248))
        canvas.paste(picture, (0, bar))
        if headline:
            ImageDraw.Draw(canvas).text((16, 11), headline, fill=(40, 44, 50), font=font)
        writer.add(np.asarray(canvas))
    writer.close()
    return dst
