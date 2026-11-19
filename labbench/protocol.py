"""The written protocol: what is scored, on which layouts, how many takes, and each task's pass rule.

It is written to a file and frozen before the first scored take, so the rules cannot drift toward the results.
The tables come straight from the task cards, so the text and the code cannot disagree about a prompt or a limit.
"""

import time
from pathlib import Path

import numpy as np

from .take import DEFAULT_MODEL, code_id
from .tasks import TASKS


def stage_names(task):
    """A task's stages, in order, read from its scoring (no simulator needed)."""
    layout = task.layout(np.random.default_rng(0))

    class _Null:  # the scoring only stores the specs it is given, so empty stand-ins are enough to list the stages
        def __getitem__(self, key):
            return {"wells": [(0, 0)] * 24, "floor": 0.0, "height": 0.0, "half": (0.0, 0.0), "x": 0.0, "y": 0.0, "top": 0.0,
                    "rim": 0.0, "yaw": 0.0, "levels": [0.0, 0.0, 0.0], "length": 0.0, "width": 0.0, "radius": 0.0}

    stages, *_ = task.scoring(_Null(), {name: 0.0 for name in task.movable})
    return [s.name for s in stages]


def task_table(with_stages=False):
    head = "| # | Task | The robot is told | Passes when | Time limit |"
    rule = "|---|---|---|---|---|"
    if with_stages:
        head, rule = head + " Stages (partial credit) |", rule + "---|"
    lines = [head, rule]
    for i, task in enumerate(TASKS.values(), 1):
        row = f"| {i} | `{task.name}` | {task.prompt} | {task.rule} | {task.seconds:.0f} s |"
        if with_stages:
            row += " " + ", ".join(stage_names(task)) + " |"
        lines.append(row)
    return "\n".join(lines)


def write_protocol(path, seeds, batches, model=DEFAULT_MODEL):
    seeds = list(seeds)
    text = f"""# Protocol: zero-shot baseline

Frozen {time.strftime('%Y-%m-%d %H:%M %Z')}, before any scored take. Bench code `{code_id()}`.
If the code or this file changes after that, the results say so by carrying a different code id.

## What is scored

- **Model:** `{model}` through its API, joint control, 48 actions per call. Zero-shot: no fine-tuning and no
  examples of these tasks.
- **Inputs:** 3 cameras (the last 9 frames of each, 0.2 s apart), the joint angles and gripper openings, and
  one sentence.
- **Wording:** the plain wording on each task card. Other wordings are a separate experiment.
- **Takes:** {len(seeds)} per task, on the layouts of seeds {seeds[0]} to {seeds[-1]}. They run in {len(batches)} batches fixed here
  ({'; then '.join('seeds ' + ', '.join(str(s) for s in b) for b in batches)}), split for budget only. No take is added or dropped after
  results are seen.
- **Errors:** a take that stops on a software or network error is rerun once on the same seed, and the error
  is reported next to the results.
- **Human assists:** none. Nothing is reset, moved or nudged during a take.
- **Time:** the simulator advances only while actions run. A take ends at the task's time limit, or 1 s after
  the pass rule has held for 1.5 s.

## Development layouts, kept apart

Seeds 0 to 4 were used for practice before this file was frozen (`tubes_to_rack` only, both wordings). The time
limit of that task was raised from 120 s to 240 s after the first practice take. No scored take uses those
seeds.

## Reporting

- Passes as k of n with the exact 95% range for the true rate. With 5 takes that range is wide (0 of 5 still
  allows up to 52%), so 5 takes sort a task into fails, sometimes works or works, and no finer.
- Stage progress (partial credit) in its own column, never mixed with the pass count.
- Per take: date, model ID, library version, bench code id, calls, estimated cost, median call time.

## Tasks and pass rules

The rule that counts is the code in `labbench/tasks.py` and `labbench/score.py`. This table says the same in
words. A stage counts once its test has held for 0.5 s.

{task_table(with_stages=True)}
"""
    Path(path).write_text(text)
    return path
