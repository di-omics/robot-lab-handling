"""One take: set the bench, let a policy drive both arms, score what happened, save the video and the log.

The simulator only advances while actions run; it waits while the model thinks, so a slow network never costs
the robot time. A take ends when the allowed simulated time is used up, or 1 s after the task has succeeded.
"""

import hashlib
import json
import os
import re
import time
from collections import deque
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path

import mujoco
import numpy as np
from PIL import Image

from . import __version__
from .score import Tracker, World
from .sim import HOME, STEP_S, dream_control as dc, make_env
from .tasks import TASKS
from .video import Mp4, tile

DEFAULT_CREDENTIALS = "~/.dreamlabs/credentials"
DEFAULT_MODEL = "dreamlabs/dream-1-beta"
GATEWAY = "https://api.dreamlabs.ai"
## Dollars per model call, from the platform's Billing page on 18 Nov 2026. Used only for the cost estimate.
PRICE_PER_CALL = {"dreamlabs/dream-1-beta": 0.0014, "dreamlabs/dream-1-beta-flash": 0.0009}
## Render a video frame every this many control steps (2 = 10 frames a second of simulated time).
VIDEO_EVERY = 2


def _fingerprint():
    digest = hashlib.sha256()
    for path in sorted(Path(__file__).resolve().parent.glob("*.py")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()[:12]


## A short fingerprint of the bench's own source as loaded by this process, so every result names the exact
## code that scored it (later edits on disk do not change what a running job reports).
CODE_ID = _fingerprint()


def code_id():
    return CODE_ID


def read_key(credentials=DEFAULT_CREDENTIALS):
    """The API key from one credentials file, and nothing else.

    A key or key file named in the environment would otherwise win silently, and bill whatever account it
    belongs to. This bench only ever uses the one file it is pointed at.
    """
    path = Path(credentials).expanduser()
    env_file = os.environ.get("DREAM_CREDENTIALS")
    if os.environ.get("DREAM_API_KEY") or (env_file and Path(env_file).expanduser() != path):
        raise SystemExit(
            "DREAM_API_KEY or DREAM_CREDENTIALS is set in the environment and would override the key file. "
            "Unset it, or pass --credentials with the file you mean."
        )
    key = None
    for line in path.read_text().splitlines():
        name, sep, value = line.removeprefix("export ").partition("=")
        if sep and name.strip() == "DREAM_API_KEY":
            key = value.strip().strip("\"'")
    if not key:
        raise SystemExit(f"No DREAM_API_KEY in {path}")
    os.environ["DREAM_CREDENTIALS"] = str(path)  # the client reads its addresses from the same file
    return key


class HoldPolicy:
    """No model: both arms stay at home. For checking the bench, the scoring and the video without a call."""

    def __init__(self):
        self.calls = 0

    def prime(self, windows, steps):
        pass

    def tick(self, windows, steps):
        pass

    def act(self):
        self.calls += 1
        rows = np.tile(HOME, (48, 1))
        return {"q_l_chunk": rows, "q_r_chunk": rows.copy()}, 0.0

    def close(self):
        pass


class DreamPolicy:
    """A Dream model over the API, spoken to exactly as the library's own YAM example does."""

    MAX_WAIT_S = 900.0  # give up on a model that has not started after 15 minutes

    def __init__(self, env, model, prompt, key, say=print):
        self.env, self.model, self.prompt, self.key, self.say = env, model, prompt, key, say
        self.poses = model in dc.POSE_MODELS
        self.calls = 0
        self.client = dc.open_policy(dc.policy_config(model, GATEWAY, self.poses), key)

    def prime(self, windows, steps):
        """Hand the client the whole 9-frame window (a new session)."""
        dc.feed(self.client, self.env, windows, self.prompt, self.model, steps, every=0, station=self.poses)
        self._windows, self._steps = windows, steps

    def tick(self, windows, steps):
        """Hand the client the newest frame and the state now."""
        dc.feed(self.client, self.env, windows, self.prompt, self.model, steps, station=self.poses)
        self._windows, self._steps = windows, steps

    def act(self):
        """Ask for the next chunk; wait and ask again while the model starts or the network hiccups.
        @return (reply, seconds the call took).
        """
        waited, errors, restarts, drops = 0.0, 0, 0, 0
        while True:
            started = time.monotonic()
            try:
                reply = self.client.get_action()
                self.calls += 1
                return reply, time.monotonic() - started
            except Exception as error:  # the client's error classes, told apart by name and fields
                kind = type(error).__name__
                if kind == "DreamSessionExpired" and restarts < 3:
                    restarts += 1
                    self.say("  the model restarted the episode; asking again")
                    continue
                if not self.poses and dc.needs_poses(error):
                    self.say("  this model reads hand poses; reopening with the station keys")
                    self.client.close()
                    self.poses = True
                    self.client = dc.open_policy(dc.policy_config(self.model, GATEWAY, True), self.key)
                    self.prime(self._windows, self._steps)
                    continue
                if kind in ("DreamTimeout", "DreamProtocolError") and drops < 5:
                    drops += 1
                    self.say(f"  {kind}: asking again in 1 s")
                    time.sleep(1.0)
                    continue
                if getattr(error, "retryable", False):
                    reason = getattr(error, "reason", "")
                    errors = errors + 1 if reason == "error" else 0
                    wait = float(getattr(error, "retry_after_s", None) or 1.0)
                    waited += wait
                    if errors > 3 or waited > self.MAX_WAIT_S:
                        raise
                    self.say(f"  waiting ({reason}), asking again in {wait:.0f} s")
                    time.sleep(wait)
                    continue
                raise

    def close(self):
        try:
            self.client.close()
        except Exception:
            pass


@dataclass
class Bench:
    """One seeded bench, ready for a take."""

    task: object
    env: object
    world: World
    tracker: Tracker
    layout: dict
    specs: dict


def set_bench(task_name, seed, show=False):
    """Build one seeded bench for a task."""
    task = TASKS[task_name]
    layout = task.layout(np.random.default_rng(seed))
    specs = {}
    env = make_env(lambda root, world: specs.update(task.build(world, layout)), show_camera=show)
    world = World(env)
    start_z = {name: float(world.pos(name)[2]) for name in task.movable}
    stages, success, *rest = task.scoring(specs, start_z)
    tracker = Tracker(world, stages, success, task.movable, requires=rest[0] if rest else ())
    tracker.prime()
    return Bench(task, env, world, tracker, layout, specs)


def save_stills(task_name, seed, out_dir):
    """Save what each camera sees at the start of a take, plus the view across the bench. No model call."""
    bench = set_bench(task_name, seed, show=True)
    env = bench.env
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for name, rgb in env.images().items():
        Image.fromarray(rgb).save(out / f"{task_name}-s{seed}-{name}.png")
    renderer = mujoco.Renderer(env.model, height=720, width=1280)
    renderer.update_scene(env.data, camera="show")
    Image.fromarray(renderer.render()).save(out / f"{task_name}-s{seed}-show.png")
    renderer.close()
    env.close()
    return out


def run_take(task_name, seed=0, model=DEFAULT_MODEL, policy="dream", seconds=None, out_root="takes",
             credentials=DEFAULT_CREDENTIALS, actions=48, show=False, say=print, variant="plain"):
    """Run and score one take.
    @param policy "dream" calls the model; "hold" keeps the arms at home and makes no call.
    @param seconds Simulated seconds allowed; default is the task card's.
    @return The summary dict, also written to <take dir>/summary.json.
    """
    bench = set_bench(task_name, seed, show=show)
    task, env, world, tracker, layout = bench.task, bench.env, bench.world, bench.tracker, bench.layout
    budget = float(seconds or task.seconds)
    prompt = task.wording(variant)
    tag = model.rsplit("/", 1)[-1] if policy == "dream" else policy
    tag = re.sub(r"[^A-Za-z0-9.-]+", "-", tag)
    out = Path(out_root) / f"{time.strftime('%Y%m%d-%H%M%S')}-{task_name}-{variant}-s{seed}-{tag}"
    out.mkdir(parents=True)
    video = Mp4(out / "take.mp4", 640, 566, round(1 / (STEP_S * VIDEO_EVERY)))
    show_renderer = mujoco.Renderer(env.model, height=720, width=1280) if show else None
    show_video = Mp4(out / "show.mp4", 1280, 720, round(1 / (STEP_S * VIDEO_EVERY))) if show else None
    windows = {name: deque(maxlen=dc.FRAMES) for name in dc.VIDEO_ROLES}
    replies, error, driver = [], None, None
    steps = 0
    wall0 = time.monotonic()
    started_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    t0 = None

    def advance(left, right):
        nonlocal steps
        env.step(left, right)
        tracker.update()
        if steps % VIDEO_EVERY == 0:
            kept = steps % dc.FRAME_EVERY_STEPS == 0
            images = dc.capture(env, windows, keep=kept)
            if kept and driver is not None and all(len(w) == dc.FRAMES for w in windows.values()):
                driver.tick(windows, steps)
            clock = 0.0 if t0 is None else world.time - t0
            done = sum(t is not None for t in tracker.reached.values())
            status = f"{clock:5.1f} s   {done}/{len(tracker.stages)} steps" + ("   DONE" if tracker.success_at is not None else "")
            video.add(tile(images, f"{prompt}   [{tag}]", status))
            if show_renderer is not None:
                show_renderer.update_scene(env.data, camera="show")
                show_video.add(show_renderer.render())
        steps += 1

    try:
        while any(len(w) < dc.FRAMES for w in windows.values()):  # fill the 9-frame windows before the first call
            state = env.state()
            advance(state["left"], state["right"])
        key = read_key(credentials) if policy == "dream" else None
        driver = DreamPolicy(env, model, prompt, key, say) if policy == "dream" else HoldPolicy()
        driver.prime(windows, steps)
        t0 = world.time
        tracker.t0 = t0
        say(f"take: {task_name} [{variant}] seed {seed}, {tag}, {budget:.0f} s allowed -> {out}")
        while world.time - t0 < budget:
            reply, rtt = driver.act()
            left, right = dc.validate_chunk(env, reply, actions, verbose=False)
            replies.append({
                "i": len(replies), "sim_s": round(world.time - t0, 2), "rtt_s": round(rtt, 3),
                "grip_l": [round(float(left[:, 6].min()), 3), round(float(left[:, 6].max()), 3)],
                "grip_r": [round(float(right[:, 6].min()), 3), round(float(right[:, 6].max()), 3)],
                "tcp_l": world.tcp("left").round(4).tolist(), "tcp_r": world.tcp("right").round(4).tolist(),
            })
            stop = False
            for l, r in zip(left, right):
                advance(l, r)
                if world.time - t0 >= budget:
                    stop = True
                    break
                if tracker.success_at is not None and (world.time - t0) - tracker.success_at >= 1.0:
                    stop = True
                    break
            if stop:
                break
    except (Exception, KeyboardInterrupt) as e:  # keep the video and the log of a take that stopped early
        error = f"{type(e).__name__}: {e}"
        say(f"  stopped: {error}")
    finally:
        if driver is not None:
            driver.close()
        video.close()
        if show_video is not None:
            show_video.close()
            show_renderer.close()

    calls = driver.calls if driver is not None else 0
    summary = {
        "task": task_name, "title": task.title, "prompt": prompt, "prompt_variant": variant, "seed": seed,
        "model": model if policy == "dream" else None, "policy": policy,
        "seconds_allowed": budget, "sim_s": round(world.time - (t0 if t0 is not None else world.time), 2),
        "calls": calls,
        "est_cost_usd": round(calls * PRICE_PER_CALL.get(model, 0.0), 4) if policy == "dream" else 0.0,
        **tracker.summary(),
        "objects": {n: {"pos": world.pos(n).round(4).tolist(), "tilt_deg": round(world.tilt_deg(n), 1)} for n in task.movable},
        "layout": {k: [round(float(v), 4) for v in vals] for k, vals in layout.items()},
        "error": error, "wall_s": round(time.monotonic() - wall0, 1), "dir": str(out), "started_at": started_at,
        "median_call_s": round(float(np.median([r["rtt_s"] for r in replies])), 3) if replies else None,
        "versions": {"labbench": __version__, "code": code_id(), "dreamlabs": metadata.version("dreamlabs"),
                     "mujoco": mujoco.__version__},
    }
    with open(out / "replies.jsonl", "w") as f:
        for r in replies:
            f.write(json.dumps(r) + "\n")
    (out / "summary.json").write_text(json.dumps(summary, indent=2))
    env.close()
    say(f"  result: success={summary['success']}  steps {summary['stages_reached']}/{summary['stages_total']}  "
        f"calls {calls}  sim {summary['sim_s']} s  wall {summary['wall_s']} s")
    return summary


def contact_sheet(take_dir, n=8, cols=4, name="take.mp4"):
    """Evenly spaced frames of a take video in one picture: <take dir>/sheet.jpg."""
    import av

    take_dir = Path(take_dir)
    with av.open(str(take_dir / name)) as container:
        frames = [f.to_ndarray(format="rgb24") for f in container.decode(video=0)]
    if not frames:
        return None
    picks = [frames[round(i * (len(frames) - 1) / max(n - 1, 1))] for i in range(n)]
    h, w = picks[0].shape[:2]
    rows = (n + cols - 1) // cols
    sheet = Image.new("RGB", (cols * w, rows * h), "white")
    for i, frame in enumerate(picks):
        sheet.paste(Image.fromarray(frame), ((i % cols) * w, (i // cols) * h))
    path = take_dir / "sheet.jpg"
    sheet.save(path, quality=85)
    return path
