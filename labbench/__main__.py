"""Command line: python -m labbench <stills|take|sheet|baseline|protocol> ...

  stills    save what the cameras see at the start of a task (no model call)
  take      run and score one take
  sheet     make a contact sheet from a take's video
  baseline  run a set of tasks over a set of seeds, one take at a time, and write the results table
"""

import argparse
import json
from pathlib import Path

from .take import DEFAULT_CREDENTIALS, DEFAULT_MODEL, contact_sheet, run_take, save_stills
from .tasks import TASKS


def main():
    parser = argparse.ArgumentParser(prog="labbench", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)

    p = commands.add_parser("stills")
    p.add_argument("--task", choices=sorted(TASKS), required=True)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--out", default="stills")

    p = commands.add_parser("take")
    p.add_argument("--task", choices=sorted(TASKS), required=True)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--policy", choices=("dream", "hold"), default="dream", help="hold = arms stay home, no model call")
    p.add_argument("--seconds", type=float, help="simulated seconds allowed (default: the task card's)")
    p.add_argument("--out", default="takes")
    p.add_argument("--credentials", default=DEFAULT_CREDENTIALS)
    p.add_argument("--show", action="store_true", help="also record show.mp4, the view across the bench")
    p.add_argument("--variant", default="plain", help="which wording of the prompt (plain, or a name from the task card)")

    p = commands.add_parser("sheet")
    p.add_argument("take_dir")
    p.add_argument("--frames", type=int, default=8)

    p = commands.add_parser("baseline")
    p.add_argument("--tasks", default=",".join(sorted(TASKS)))
    p.add_argument("--seeds", default="0,1,2,3,4")
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--out", required=True, help="run folder; takes already in it are kept, so a stopped run can resume")
    p.add_argument("--credentials", default=DEFAULT_CREDENTIALS)
    p.add_argument("--max-cost", type=float, default=5.0, help="stop before the estimated spend passes this many dollars")
    p.add_argument("--variant", default="plain")
    p.add_argument("--seconds", type=float)
    p.add_argument("--show", action="store_true")

    p = commands.add_parser("protocol", help="write the frozen protocol file")
    p.add_argument("--seeds", default="100,101,102,103,104")
    p.add_argument("--batches", default="100,101,102;103,104", help="seed batches, separated by ;")
    p.add_argument("--out", default="PROTOCOL.md")

    args = parser.parse_args()
    if args.command == "stills":
        print("stills in", save_stills(args.task, args.seed, args.out))
    elif args.command == "take":
        summary = run_take(args.task, args.seed, args.model, args.policy, args.seconds, args.out, args.credentials,
                           show=args.show, variant=args.variant)
        print("sheet:", contact_sheet(summary["dir"]))
    elif args.command == "sheet":
        print(contact_sheet(args.take_dir, n=args.frames))
    elif args.command == "protocol":
        from .protocol import write_protocol

        batches = [[int(v) for v in b.split(",")] for b in args.batches.split(";")]
        print(write_protocol(args.out, [int(v) for v in args.seeds.split(",")], batches))
    elif args.command == "baseline":
        from .baseline import run_baseline

        run_baseline(args.tasks.split(","), [int(s) for s in args.seeds.split(",")], args.model, Path(args.out),
                     args.credentials, args.max_cost, variant=args.variant, seconds=args.seconds, show=args.show)


if __name__ == "__main__":
    main()
