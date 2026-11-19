"""Replay a recorded camera policy's accepted commands in a fresh, offline simulator."""
import argparse
import json
import subprocess
import sys
from pathlib import Path


def replay(source, destination):
    original = json.loads((source / "summary.json").read_text())
    if original["status"] != "complete":
        raise ValueError("Replay requires a completed source take")
    actions = [json.loads(line)["action"] for line in (source / "actions.jsonl").read_text().splitlines()]
    subprocess.run(
        [sys.executable, "-m", "camera_env", "--task", original["task"], "--seed", str(original["seed"]),
         "--actor", "offline-replay", "--out", str(destination)],
        input="".join(json.dumps(action) + "\n" for action in actions), text=True,
        stdout=subprocess.DEVNULL, check=True,
    )
    reproduced = json.loads((destination / "summary.json").read_text())
    fields = ("status", "bench_code", "adapter_sha256", "sim_s", "actions", "success", "success_at_s",
              "success_at_end", "stages", "stages_reached", "stages_total")
    differences = {k: [original[k], reproduced[k]] for k in fields if original[k] != reproduced[k]}
    return {"model": original["actor"], "seed": original["seed"], "matched": not differences,
            "fields_checked": list(fields), "differences": differences}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path, help="New directory for reproduced evidence")
    args = parser.parse_args()
    result = replay(args.source, args.destination)
    print(json.dumps(result))
    raise SystemExit(0 if result["matched"] else 1)
