"""Command line: python -m tending <stills|take|expert> ...   (run from the project folder)

  stills   save what the 3 model cameras see at the start of a chore, plus the view across the bench (no model call)
  take     run and score one take through labbench's own run_take, then stamp it with TENDING_ID
  expert   play the scripted expert, write summary.json and a 1280 x 720 show.mp4
"""

import argparse
import json
from contextlib import contextmanager
from pathlib import Path

import mujoco
from PIL import Image

import labbench.take as lt

from . import NAMES, stamp
from .dispenser import aim_show


@contextmanager
def show_aimed():
    """While open, every labbench bench of a tending chore gets the show camera aimed at the nest.

    run_take looks up set_bench in labbench.take's namespace when it runs, so swapping that name for a wrapper
    reaches it without editing labbench. The original is put back on the way out.
    """
    original = lt.set_bench

    def set_bench(*args, **kwargs):
        bench = original(*args, **kwargs)
        aim_show(bench)
        return bench

    lt.set_bench = set_bench
    try:
        yield
    finally:
        lt.set_bench = original


def save_stills(task_name, seed, out_dir):
    """DIR/<task>-s<seed>-{top,left,right}.png as the model sees them, and <task>-s<seed>-show.png at 1280 x 720."""
    bench = lt.set_bench(task_name, seed, show=True)
    aim_show(bench)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    try:
        for name, rgb in bench.env.images().items():
            paths.append(out / f"{task_name}-s{seed}-{name}.png")
            Image.fromarray(rgb).save(paths[-1])
        renderer = mujoco.Renderer(bench.env.model, height=720, width=1280)
        renderer.update_scene(bench.env.data, camera="show")
        paths.append(out / f"{task_name}-s{seed}-show.png")
        Image.fromarray(renderer.render()).save(paths[-1])
        renderer.close()
    finally:
        bench.env.close()
    return paths


def take(task_name, seed=0, policy="hold", seconds=None, variant="plain", out_root="takes", show=False,
         model=lt.DEFAULT_MODEL, credentials=lt.DEFAULT_CREDENTIALS, say=print):
    """One labbench take of a tending chore, stamped with TENDING_ID. policy "hold" makes no model call."""
    with show_aimed():
        summary = lt.run_take(task_name, seed=seed, model=model, policy=policy, seconds=seconds, out_root=out_root,
                              credentials=credentials, show=show, say=say, variant=variant)
    return stamp(summary["dir"])


def main():
    parser = argparse.ArgumentParser(prog="tending", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)

    p = commands.add_parser("stills")
    p.add_argument("--task", choices=NAMES, required=True)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--out", default="stills")

    p = commands.add_parser("take")
    p.add_argument("--task", choices=NAMES, required=True)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--policy", choices=("hold", "dream"), default="hold", help="hold = arms stay home, no model call")
    p.add_argument("--seconds", type=float, help="simulated seconds allowed (default: the task card's)")
    p.add_argument("--variant", default="plain", help="which wording of the prompt (plain, terse, precise, wrong_object)")
    p.add_argument("--out", default="takes")
    p.add_argument("--show", action="store_true", help="also record show.mp4, the view across the bench")
    p.add_argument("--model", default=lt.DEFAULT_MODEL)
    p.add_argument("--credentials", default=lt.DEFAULT_CREDENTIALS)

    p = commands.add_parser("expert")
    p.add_argument("--task", choices=NAMES, required=True)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--out", default="takes")
    p.add_argument("--no-video", action="store_true", help="skip show.mp4")

    args = parser.parse_args()
    if args.command == "stills":
        for path in save_stills(args.task, args.seed, args.out):
            print(path)
    elif args.command == "take":
        summary = take(args.task, args.seed, args.policy, args.seconds, args.variant, args.out, args.show,
                       args.model, args.credentials)
        print(json.dumps({k: summary[k] for k in ("success", "stages", "progress", "dir", "versions")}, indent=2))
    elif args.command == "expert":
        from .expert import play_expert

        summary = play_expert(args.task, args.seed, args.out, video=not args.no_video)
        print(json.dumps({k: summary[k] for k in ("success", "success_at_s", "stages", "error", "dir")}, indent=2))


if __name__ == "__main__":
    main()
