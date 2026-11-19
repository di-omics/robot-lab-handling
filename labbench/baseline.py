"""A run: a set of tasks over a set of seeds, one take at a time, with a results table that is rewritten after
every take. Takes already in the run folder are kept, so a stopped run picks up where it left off.

One take at a time on purpose: the model serves a few sessions per account, and parallel sessions get refused.
"""

import json
from math import comb
from pathlib import Path
from statistics import median

from .take import PRICE_PER_CALL, code_id, contact_sheet, run_take
from .tasks import TASKS


def exact_range(k, n, level=0.95):
    """The exact (Clopper-Pearson) range for a true success rate, given k passes in n takes.
    @return (low, high) as fractions.
    """
    if n == 0:
        return 0.0, 1.0
    alpha = (1 - level) / 2

    def tail_ge(p):  # chance of k or more passes
        return sum(comb(n, i) * p**i * (1 - p) ** (n - i) for i in range(k, n + 1))

    def tail_le(p):  # chance of k or fewer passes
        return sum(comb(n, i) * p**i * (1 - p) ** (n - i) for i in range(0, k + 1))

    def solve(f, target, rising):
        lo, hi = 0.0, 1.0
        for _ in range(60):
            mid = (lo + hi) / 2
            if (f(mid) < target) == rising:
                lo = mid
            else:
                hi = mid
        return (lo + hi) / 2

    low = 0.0 if k == 0 else solve(tail_ge, alpha, True)
    high = 1.0 if k == n else solve(tail_le, alpha, False)
    return low, high


def load(out):
    """Every take summary in a run folder, oldest first."""
    return [json.loads(p.read_text()) for p in sorted(Path(out).glob("*/summary.json"))]


def table(summaries):
    """Per task and prompt wording: takes, passes with their exact range, mean stage progress, calls, cost."""
    groups = {}
    for s in summaries:
        if s.get("error"):
            continue
        groups.setdefault((s["task"], s.get("prompt_variant", "plain"), s.get("model")), []).append(s)
    order = list(TASKS)
    rows = []
    for (task, variant, model), takes in sorted(groups.items(), key=lambda kv: (order.index(kv[0][0]) if kv[0][0] in order else 99, kv[0][1])):
        wins = [t for t in takes if t["success"]]
        low, high = exact_range(len(wins), len(takes))
        rows.append({
            "task": task, "prompt_variant": variant, "model": model, "prompt": takes[0]["prompt"],
            "takes": len(takes), "passes": len(wins), "range_95": [round(low, 3), round(high, 3)],
            "mean_progress": round(sum(t["progress"] for t in takes) / len(takes), 3),
            "median_pass_s": median(t["success_at_s"] for t in wins) if wins else None,
            "calls": sum(t["calls"] for t in takes), "est_cost_usd": round(sum(t["est_cost_usd"] for t in takes), 3),
            "seeds": sorted(t["seed"] for t in takes),
        })
    return rows


def write_results(out):
    out = Path(out)
    summaries = load(out)
    rows = table(summaries)
    (out / "results.json").write_text(json.dumps({"rows": rows, "takes": summaries}, indent=2))
    good = [s for s in summaries if not s.get("error")]
    lines = []
    if good:
        days = sorted({s.get("started_at", "")[:10] for s in good if s.get("started_at")})
        models = sorted({s["model"] for s in good if s.get("model")})
        codes = sorted({s["versions"].get("code", "?") for s in good})
        libs = sorted({s["versions"]["dreamlabs"] for s in good})
        lines += [f"Simulation only. Model: {', '.join(models)}. Run date: {', '.join(days) or 'n/a'}. "
                  f"dreamlabs {', '.join(libs)}. Bench code {', '.join(codes)}.", ""]
    lines += ["| Task | Wording | Passes | True rate could be | Mean stage progress | Median time to pass | Calls | Est. cost |",
              "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        t = "n/a" if r["median_pass_s"] is None else f"{r['median_pass_s']:.0f} s"
        lines.append(f"| {r['task']} | {r['prompt_variant']} | {r['passes']} of {r['takes']} | "
                     f"{r['range_95'][0] * 100:.0f} to {r['range_95'][1] * 100:.0f}% | {r['mean_progress'] * 100:.0f}% | {t} | "
                     f"{r['calls']} | ${r['est_cost_usd']:.2f} |")
    lines += ["", "Passes are full successes. The range is the exact 95% range for that many passes in that many takes. "
              "Stage progress is partial credit and is a different measure: never read it as a success rate."]
    failed = [s for s in summaries if s.get("error")]
    if failed:
        lines += ["", f"{len(failed)} take(s) stopped on an error and are not counted: " + "; ".join(
            f"{s['task']} seed {s['seed']} ({s['error'][:80]})" for s in failed)]
    (out / "results.md").write_text("\n".join(lines) + "\n")
    return rows


def run_baseline(tasks, seeds, model, out, credentials, max_cost, variant="plain", seconds=None, show=False, say=print):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    for name in tasks:
        if name not in TASKS:
            raise SystemExit(f"unknown task {name}; known: {sorted(TASKS)}")
    have = {(s["task"], s.get("prompt_variant", "plain"), s["seed"]) for s in load(out) if not s.get("error")}
    spent = sum(s["est_cost_usd"] for s in load(out))
    price = PRICE_PER_CALL.get(model, 0.0)
    say(f"run: {len(tasks)} tasks x seeds {seeds}, wording {variant}, bench code {code_id()}")
    for seed in seeds:  # seed by seed, so a run stopped early still has every task covered evenly
        for name in tasks:
            if (name, variant, seed) in have:
                continue
            allowed = float(seconds or TASKS[name].seconds)
            worst = (allowed / 2.4 + 2) * price  # one call per 48 actions (2.4 s of simulated time)
            if spent + worst > max_cost:
                say(f"stopping before {name} seed {seed}: ${spent:.2f} spent, cap ${max_cost:.2f}")
                write_results(out)
                return
            summary = run_take(name, seed, model, "dream", seconds, out, credentials, show=show, say=say, variant=variant)
            spent += summary["est_cost_usd"]
            contact_sheet(summary["dir"])
            write_results(out)
    rows = write_results(out)
    say(f"run done: ${spent:.2f} estimated spend")
    say((out / "results.md").read_text())
    return rows
