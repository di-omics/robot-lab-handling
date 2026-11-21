"""Run takes of the tending chores through labbench's own take code, and record every command sent to the arms.

Each take is labbench.take.run_take, unchanged. While it runs, every env.step(left, right) of the bench is kept in
memory, from the moment the bench is built (the camera priming steps included). After the take this script writes
into the take folder:

  actions.f64le  float64 little-endian, 1 row of 14 numbers per step (left 7, then right 7)
  trace.json     step counts, column names, sha256 of the actions and of summary.json, and the code versions

so anyone can replay the take and score it again (scripts/tending_replay.py).

A take runs in <out>/unfinished/ and moves up into <out> only once its summary is stamped and its trace is
written. Only takes in <out> count as completed. A take that stopped on a service or network error has no score:
it stays in the folder and the pair is tried again, up to --attempts in all. A take left in unfinished/ (killed
from outside, or run_take raised) also counts as 1 attempt, and as the worst case of a take in the spend. A take
stopped by hand (Ctrl-C, a closed terminal, SIGTERM) counts in the spend but not as an attempt. Pairs that already
have a completed take are skipped, so a stopped run picks up where it left off. 1 take at a time, in this
process only, with a lock on <out>/.lock.

The cost cap is an estimate: labbench counts only the model calls that returned actions, and a call it retried
inside a take is not counted. Keep --max-cost below the account credit (for example 1.20 for 1.50).

Usage (from the repo root):
  python scripts/tending_run.py --out runs/NAME --seeds 100,101,102 --max-cost 1.50
  python scripts/tending_run.py --out /tmp/dry --seeds 0 --policy hold --seconds 4     (no model call)
Exit code 1 when the run stopped early (cost cap, a take with more calls than 48-action chunks need, an error that
run_take raised, a stop by hand).
"""

import argparse
import fcntl
import hashlib
import json
import math
import signal
import sys
import tempfile
import time
from contextlib import contextmanager
from importlib import metadata
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import tending  # noqa: E402  (first: it adds the chores to labbench's task table)
import labbench  # noqa: E402
import labbench.take as lt  # noqa: E402
import mujoco  # noqa: E402
import numpy as np  # noqa: E402
from labbench.baseline import load, write_results  # noqa: E402
from labbench.sim import STEP_S, dream_control as dc  # noqa: E402

COLUMNS = [f"left{i}" for i in range(7)] + [f"right{i}" for i in range(7)]
PRICE = lt.PRICE_PER_CALL[lt.DEFAULT_MODEL]  # dollars per model call
## run_take fills the model's 9-frame camera windows before its first call: a frame is kept every
## dc.FRAME_EVERY_STEPS steps, starting at step 0, so 33 steps. The stage clock (tracker.t0) starts after them.
PRIMING_STEPS = (dc.FRAMES - 1) * dc.FRAME_EVERY_STEPS + 1
CHUNK_S = 48 * STEP_S  # the model returns at most 48 actions (2.4 s) per call
## Calls a take may need beyond 1 per chunk: 2 to spare, plus the retries DreamPolicy.act makes inside 1 call
## (3 session restarts, 5 timeouts, 4 service errors), which labbench does not count.
SPARE_CALLS = 2 + 3 + 5 + 4
UNFINISHED = "unfinished"
HAND_STOPS = {signal.SIGINT, signal.SIGHUP, signal.SIGTERM}


def versions():
    return {"labbench": labbench.__version__, "code": lt.CODE_ID, "dreamlabs": metadata.version("dreamlabs"),
            "mujoco": mujoco.__version__, "tending": tending.TENDING_ID}


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def clean(text):
    """Text without this machine's home folder or repo root in it."""
    return str(text).replace(str(REPO), ".").replace(str(Path.home()), "~")


def worst_cost(task_seconds):
    """Dollars for a take that uses its whole time limit with full 48-action chunks, plus SPARE_CALLS."""
    return (task_seconds / CHUNK_S + SPARE_CALLS) * PRICE


def next_take_allowed(spent, task_seconds, max_cost):
    """True when what is spent plus the worst case of the next take stays within max_cost (None: no cap)."""
    return max_cost is None or spent + worst_cost(task_seconds) <= max_cost


def calls_look_normal(calls, sim_s):
    """False when a take made more calls than full 48-action chunks need (short chunks multiply the cost)."""
    return calls <= math.ceil(sim_s / CHUNK_S) + 2


def pair_takes(summaries, task, seed):
    return [s for s in summaries
            if s["task"] == task and s["seed"] == seed and s.get("prompt_variant", "plain") == "plain"]


def by_hand(take):
    return str(take.get("error") or "").startswith("KeyboardInterrupt")


def next_pair(summaries, tasks, seeds, attempts):
    """The pair to run next, seed by seed and task by task, or None when every pair is done or given up.
    A pair is done once it has a take with no error, and given up after `attempts` takes with an error.
    Takes stopped by hand do not count as attempts.
    @return (next pair or None, list of given up pairs)
    """
    given_up, todo = [], None
    for seed in seeds:
        for task in tasks:
            takes = pair_takes(summaries, task, seed)
            if any(not s.get("error") for s in takes):
                continue
            if len([s for s in takes if not by_hand(s)]) >= attempts:
                given_up.append((task, seed))
            elif todo is None:
                todo = (task, seed)
    return todo, given_up


def unfinished(out):
    """1 record per take folder left in <out>/unfinished/, with an error so it never counts as completed.
    Its cost is what its summary says, or the worst case of the task when it has no summary.
    """
    records = []
    for folder in sorted(Path(out).glob(f"{UNFINISHED}/*/*")):
        _, _, task, variant, seed, *tag = folder.name.split("-")
        path = folder / "summary.json"
        summary = json.loads(path.read_text()) if path.is_file() else {}
        worst = 0.0 if tag == ["hold"] else worst_cost(lt.TASKS[task].seconds)
        records.append({"task": task, "seed": int(seed[1:]), "prompt_variant": variant,
                        "error": summary.get("error") or "unfinished: no stamped summary and trace",
                        "est_cost_usd": summary.get("est_cost_usd", worst), "dir": f"{UNFINISHED}/{folder.name}"})
    return records


def all_takes(out):
    """The completed and errored takes in <out>, then the unfinished ones."""
    return load(out) + unfinished(out)


def spent_usd(out):
    return round(sum(s.get("est_cost_usd", 0.0) for s in all_takes(out)), 4)


@contextmanager
def recording():
    """While open, every bench labbench.take builds records its env.step(left, right) calls into `rows`."""
    rows, original = [], lt.set_bench

    def set_bench(*args, **kwargs):
        bench = original(*args, **kwargs)
        step = bench.env.step
        rows.clear()

        def recorded_step(left, right):
            rows.append(np.concatenate([np.asarray(left, dtype="<f8"), np.asarray(right, dtype="<f8")]))
            return step(left, right)

        bench.env.step = recorded_step
        return bench

    lt.set_bench = set_bench
    try:
        yield rows
    finally:
        lt.set_bench = original


def public_dir(take_dir):
    """The take folder relative to the repo root; for a folder outside the repo, '<out name>/<take name>'."""
    take_dir = Path(take_dir).resolve()
    if take_dir.is_relative_to(REPO):
        return str(take_dir.relative_to(REPO))
    return f"{take_dir.parent.name}/{take_dir.name}"


def write_trace(take_dir, rows, summary_name):
    """actions.f64le and trace.json in take_dir. summary_name is None when the take left no summary."""
    take_dir = Path(take_dir)
    data = np.array(rows, dtype="<f8").reshape(-1, 14)
    (take_dir / "actions.f64le").write_bytes(data.tobytes())
    trace = {"steps": len(data), "priming_steps": min(PRIMING_STEPS, len(data)), "step_s": STEP_S, "dtype": "<f8",
             "columns": COLUMNS, "actions_sha256": sha256(take_dir / "actions.f64le"), "summary": summary_name,
             "summary_sha256": sha256(take_dir / summary_name) if summary_name else None, "versions": versions()}
    (take_dir / "trace.json").write_text(json.dumps(trace, indent=2))
    return trace


def one_take(task, seed, out, policy, seconds=None, say=print):
    """Run, record and stamp 1 take in its own folder under <out>/unfinished/, then move it into <out>.
    @return Its final summary. Raises what run_take raises, after recording; the take then stays unfinished.
    """
    (Path(out) / UNFINISHED).mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f"{task}-s{seed}-", dir=Path(out) / UNFINISHED))
    with recording() as rows:
        try:
            lt.run_take(task, seed=seed, policy=policy, seconds=seconds, variant="plain", out_root=staging,
                        show=False, say=lambda line: say(clean(line)))
        except BaseException:
            made = [p for p in staging.iterdir() if p.is_dir()]
            if made:
                write_trace(made[0], rows, None)
            else:
                staging.rmdir()
            raise
    signal.pthread_sigmask(signal.SIG_BLOCK, HAND_STOPS)  # a stop by hand waits until the take is in place
    try:
        take_dir = next(p for p in staging.iterdir() if p.is_dir())
        final = Path(out) / take_dir.name
        path = take_dir / "summary.json"
        summary = json.loads(path.read_text())
        summary["dir"] = public_dir(final)
        if summary.get("error"):
            summary["error"] = clean(summary["error"])
        path.write_text(json.dumps(summary, indent=2))
        summary = tending.stamp(take_dir)
        write_trace(take_dir, rows, "summary.json")
        take_dir.rename(final)
        staging.rmdir()
        if not any(staging.parent.iterdir()):
            staging.parent.rmdir()
    finally:
        signal.pthread_sigmask(signal.SIG_UNBLOCK, HAND_STOPS)
    return summary


def finish(out, tasks, seeds, attempts, stopped, say):
    """Write results.json and results.md, add the tending ID and the unfinished takes, print the summary line."""
    rows = write_results(out)
    extra = [f"Tending code {tending.TENDING_ID}."]
    left = unfinished(out)
    if left:
        extra.append(f"{len(left)} take(s) did not finish and are not counted: " + "; ".join(
            f"{x['task']} seed {x['seed']} ({x['dir']})" for x in left))
    with open(Path(out) / "results.md", "a") as f:
        f.write("\n" + "\n\n".join(extra) + "\n")
    summaries = all_takes(out)
    done = [(t, s) for s in seeds for t in tasks if any(not x.get("error") for x in pair_takes(summaries, t, s))]
    passes = sum(1 for t, s in done if any(x["success"] for x in pair_takes(summaries, t, s) if not x.get("error")))
    errored = sum(1 for x in summaries if x.get("error"))
    _, given_up = next_pair(summaries, tasks, seeds, attempts)
    say(f"pairs done {len(done)} of {len(tasks) * len(seeds)}, passes {passes}, attempts stopped {errored}, "
        f"given up {len(given_up)}, spend ${spent_usd(out):.4f}" + (f" ({stopped})" if stopped else ""))
    return rows


def run(out, tasks, seeds, policy="dream", max_cost=None, seconds=None, attempts=3, say=print):
    """Every task on every seed, 1 completed take per pair at most. @return Why the run stopped early, or None."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    for task in tasks:
        if task not in tending.NAMES:
            raise SystemExit(f"unknown tending task {task}; known: {', '.join(tending.NAMES)}")
    with lock(out / ".lock"):
        other = {s.get("policy") for s in load(out)} - {policy}
        if other:
            raise SystemExit(f"{out} already holds takes of policy {', '.join(map(str, other))}; use a new folder")
        say(f"run: {', '.join(tasks)} x seeds {seeds}, policy {policy}, labbench {lt.CODE_ID}, "
            f"tending {tending.TENDING_ID}")
        stopped = None
        while stopped is None:
            pair, _ = next_pair(all_takes(out), tasks, seeds, attempts)
            if pair is None:
                break
            task, seed = pair
            allowed = float(seconds or lt.TASKS[task].seconds)
            spent = spent_usd(out)
            if not next_take_allowed(spent, allowed, max_cost):
                stopped = f"stopping before {task} seed {seed}: ${spent:.4f} spent, worst case of the next take " \
                          f"${worst_cost(allowed):.4f}, cap ${max_cost:.2f}"
                say(stopped)
                break
            time.sleep(1 - time.time() % 1)  # take folders are named by the second: never reuse one
            try:
                summary = one_take(task, seed, out, policy, seconds, say)
            except KeyboardInterrupt:
                stopped = "stopped: interrupted by hand"
                say(stopped)
                break
            except BaseException as error:
                stopped = clean(f"stopped: run_take raised {type(error).__name__}: {error}")
                say(stopped)
                break
            say(f"  {task} seed {seed}: success={summary['success']} error={summary['error']}  "
                f"spent so far ${spent_usd(out):.4f}")
            if by_hand(summary):
                stopped = "stopped: interrupted by hand"
            elif not calls_look_normal(summary["calls"], summary["sim_s"]):
                stopped = f"stopped: {summary['calls']} calls for {summary['sim_s']} s, more than 48-action " \
                          f"chunks need; check the model's chunk size before going on"
            if stopped:
                say(stopped)
        finish(out, tasks, seeds, attempts, stopped, say)
    return stopped


@contextmanager
def lock(path):
    """An exclusive, non-blocking lock on `path` while open (None: no lock)."""
    if path is None:
        yield
        return
    with open(path, "a") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit(f"another process holds the lock {path}; not starting")
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def say_safely(line):
    try:
        print(line, flush=True)
    except OSError:  # the terminal is gone: keep going so the take is still recorded
        pass


def stop_by_hand(signum, frame):
    raise KeyboardInterrupt


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", required=True, help="run folder; takes already in it are kept")
    p.add_argument("--seeds", required=True, help="comma list, for example 100,101,102")
    p.add_argument("--tasks", default=",".join(tending.NAMES), help="comma list (default: the 4 tending chores)")
    p.add_argument("--policy", choices=("dream", "hold"), default="dream", help="hold = arms stay home, no model call")
    p.add_argument("--max-cost", type=float, help="USD cap on the estimated spend (required with --policy dream)")
    p.add_argument("--seconds", type=float, help="simulated seconds per take (only with --policy hold)")
    p.add_argument("--attempts", type=int, default=3, help="most takes per task and seed (default 3)")
    p.add_argument("--lock", help="a second file to lock for the whole run (<out>/.lock is always locked)")
    a = p.parse_args()
    if a.policy == "dream" and a.max_cost is None:
        p.error("--max-cost is required with --policy dream")
    if a.seconds is not None and a.policy != "hold":
        p.error("--seconds is only allowed with --policy hold")
    if a.attempts < 1:
        p.error("--attempts must be 1 or more")
    seeds = [int(s) for s in a.seeds.split(",") if s.strip()]
    tasks = [t.strip() for t in a.tasks.split(",") if t.strip()]
    for signum in (signal.SIGHUP, signal.SIGTERM):  # run_take then records the take as stopped by hand
        signal.signal(signum, stop_by_hand)
    with lock(a.lock):
        stopped = run(a.out, tasks, seeds, a.policy, a.max_cost, a.seconds, a.attempts, say_safely)
    sys.exit(1 if stopped else 0)


if __name__ == "__main__":
    main()
