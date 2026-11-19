"""Build the paired plate-placement report from the original terminal records."""
import argparse
import hashlib
import json
from pathlib import Path

from labbench.baseline import exact_range

SEEDS = (100, 101, 102)
POLICIES = ("Codex", "Fable", "Dream-1")
BENCH = "92c256eb309b"


def read(path):
    return json.loads(path.read_text())


def paired_rows(out, dream):
    rows = []
    adapter_hashes = set()
    interruptions = {(r["policy"], r["seed"]): r for r in read(out / "interruptions.json")} if (out / "interruptions.json").exists() else {}
    for seed in SEEDS:
        for name in POLICIES:
            partial = interruptions.get((name, seed))
            if partial:
                if partial["bench_code"] != BENCH or partial["success"] is not None:
                    raise ValueError("Invalid interrupted-take declaration")
                adapter_hashes.add(partial["adapter_sha256"])
                rows.append(partial)
                continue
            if name == "Dream-1":
                attempts = sorted(dream.glob(f"*-plate_to_tray-plain-s{seed}-*/summary.json"))
                finished = [p for p in attempts if not read(p).get("error")]
                if not finished and attempts:
                    take = read(attempts[-1])
                    if take["versions"]["code"] != BENCH or take["seconds_allowed"] != 150:
                        raise ValueError("Dream interrupted record uses a different protocol")
                    rows.append({"policy": name, "model": take["model"], "seed": seed, "status": "interrupted",
                                 "sim_s": take["sim_s"], "success": None, "error_attempts": [p.parent.name for p in attempts],
                                 "calls": take["calls"], "reason": "Dream service or infrastructure error. No completed take available."})
                    continue
                if len(finished) != 1:
                    raise ValueError(f"Expected one complete Dream take for {seed}, found {len(finished)}")
                path = finished[0]
                take = read(path)
                bench = take["versions"]["code"]
                model = take["model"]
                errors = [p.parent.name for p in attempts if read(p).get("error")]
                effort = {"calls": take["calls"], "estimated_usd": take["est_cost_usd"]}
            else:
                path = out / f"{name.lower()}-s{seed}" / "summary.json"
                take = read(path)
                if take["status"] != "complete":
                    raise ValueError(f"Incomplete take at {path}")
                trace = (path.parent / "actions.jsonl").read_text().splitlines()
                if len(trace) != take["actions"]:
                    raise ValueError(f"Action count differs from summary at {path}")
                bench = take["bench_code"]
                model = take["actor"]
                adapter_hashes.add(take["adapter_sha256"])
                errors = []
                effort = {"commands": take["actions"]}
            if (take["task"], take["seed"], take["seconds_allowed"], bench) != ("plate_to_tray", seed, 150, BENCH):
                raise ValueError(f"Protocol mismatch at {path}")
            rows.append({
                "policy": name, "model": model, "seed": seed, "status": "complete", "success": take["success"],
                "stages": take["stages"], "sim_s": take["sim_s"], "pass_at_s": take["success_at_s"],
                "wall_s": take["wall_s"], **effort, "error_attempts": errors,
                "summary": str(path.relative_to(out.parent.parent)),
                "summary_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            })
    if len(adapter_hashes) != 1:
        raise ValueError("The language-model policies used different adapters")
    return rows, adapter_hashes.pop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("out", type=Path, help="Paired run directory")
    parser.add_argument("dream", type=Path, help="Frozen Dream run directory")
    args = parser.parse_args()
    out = args.out.resolve()
    rows, adapter = paired_rows(out, args.dream.resolve())
    totals = {}
    for name in POLICIES:
        selected = [r for r in rows if r["policy"] == name and r["status"] == "complete"]
        k = sum(r["success"] for r in selected)
        n = len(selected)
        totals[name] = {"passes": k if n else None, "takes": n, "interrupted": len(SEEDS) - n, "exact_95": list(exact_range(k, n)) if n else None}
    (out / "results.json").write_text(json.dumps({
        "task": "plate_to_tray", "bench_code": BENCH, "adapter_sha256": adapter, "totals": totals, "takes": rows
    }, indent=2) + "\n")
    lines = [
        "# Plate placement in simulation", "",
        "Put the plate on the black tray. Three layouts were assigned to each policy under the frozen 150-second limit. A pass requires stable, hands-off placement. The stage timestamps show partial progress.", "",
        "| Policy | Passes | Exact 95% interval | Controller |",
        "| --- | ---: | --- | --- |",
    ]
    for name, stats in totals.items():
        if not stats["takes"]:
            lines.append(f"| {name} | Unscored ({stats['interrupted']} interrupted) | · | Camera-guided Cartesian commands |")
            continue
        low, high = stats["exact_95"]
        controller = "48 joint actions per call" if name == "Dream-1" else "Camera-guided Cartesian commands"
        lines.append(f"| {name} | {stats['passes']}/{stats['takes']} | {low:.1%} to {high:.1%} | {controller} |")
    lines += ["", "| Layout | Policy | Pass | Lifted at | Over tray at | In tray at | Passed at | Simulated duration | Commands or calls |", "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for r in rows:
        if r["status"] != "complete":
            count = f"{r['commands']} commands" if "commands" in r else f"{r['calls']} calls"
            lines.append(f"| {r['seed']} | {r['policy']} | Interrupted | · | · | · | · | {r['sim_s']:.1f} s | {count} |")
            continue
        def seconds(value):
            return f"{value:.1f} s" if value is not None else "·"
        stages = [seconds(r["stages"][s]) for s in ("plate_lifted", "plate_over_tray", "plate_in_tray")]
        count = f"{r['calls']} calls" if r["policy"] == "Dream-1" else f"{r['commands']} commands"
        lines.append("| " + " | ".join([str(r["seed"]), r["policy"], "Yes" if r["success"] else "No", *stages, seconds(r["pass_at_s"]), seconds(r["sim_s"]), count]) + " |")
    lines += ["", "Dream received nine RGB frames per camera, joint angles and gripper state per call. Codex and Fable received current RGB views, robot proprioception and a calibrated pixel-to-plane inverse-kinematics controller. Each language model started with a fresh context on each seed. The three layouts estimate this one task imprecisely. The controller difference limits conclusions about the underlying models.", ""]
    for r in rows:
        if r.get("error_attempts") and r["status"] == "complete":
            lines.append(f"Dream layout {r['seed']} had {len(r['error_attempts'])} interrupted attempt before the recorded completion. The frozen protocol permits one same-layout infrastructure retry.")
    if any(r["policy"] == "Fable" and r["status"] == "interrupted" for r in rows):
        lines += ["", "Claude Fable 5.2 was stopped by the operator before terminal scoring on all three layouts. Its partial traces are archived. There is no Fable success rate or ranking from this pilot."]
    lines += ["", "[Paired protocol](PROTOCOL.md) · [Actor instructions](ACTOR.md) · [Terminal records and source digests](results.json)", ""]
    (out / "RESULTS.md").write_text("\n".join(lines))


if __name__ == "__main__":
    main()
