"""Cut smaller training sets from the recorded dataset: the first N episodes, each as its own LeRobot v2.1 dataset.

    python -m sim_demos.subset 5 20          (from the lab-handling-bench folder)

For the dose question (how many demonstrations does the chore need), every fine-tune trains on the first N episodes
of the same recording, so a larger set always contains the smaller ones. Writes
sim_demos/dataset_doses/first_005/plate_to_tray_sim and so on, runs Dream's local dataset check on each (nothing is
sent, no key is read), and writes sim_demos/dose_sets.json.
"""

import json
import shutil
import sys
from pathlib import Path

from dream import datasets

from .record import CAMERAS, FPS

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "dataset" / "plate_to_tray_sim"


def cut(n):
    out = HERE / "dataset_doses" / f"first_{n:03d}" / SOURCE.name
    if out.parent.exists():
        shutil.rmtree(out.parent)
    (out / "meta").mkdir(parents=True)
    episodes = [json.loads(line) for line in (SOURCE / "meta" / "episodes.jsonl").read_text().splitlines()][:n]
    stats = (SOURCE / "meta" / "episodes_stats.jsonl").read_text().splitlines()[:n]
    if len(episodes) < n:
        raise SystemExit(f"the dataset holds {len(episodes)} episodes, fewer than {n}")
    for e in episodes:
        name = f"episode_{e['episode_index']:06d}"
        for rel in [f"data/chunk-000/{name}.parquet", *(f"videos/chunk-000/{key}/{name}.mp4" for key in CAMERAS.values())]:
            (out / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(SOURCE / rel, out / rel)
    frames = sum(e["length"] for e in episodes)
    info = json.loads((SOURCE / "meta" / "info.json").read_text())
    info.update(total_episodes=n, total_frames=frames, total_videos=n * len(CAMERAS), splits={"train": f"0:{n}"})
    (out / "meta" / "info.json").write_text(json.dumps(info, indent=4))
    (out / "meta" / "episodes.jsonl").write_text("".join(json.dumps(e) + "\n" for e in episodes))
    (out / "meta" / "episodes_stats.jsonl").write_text("".join(line + "\n" for line in stats))
    shutil.copy2(SOURCE / "meta" / "tasks.jsonl", out / "meta" / "tasks.jsonl")
    report = datasets.validate_dataset(out.parent, json.loads((HERE / "embodiment.json").read_text()))
    return {"episodes": n, "frames": frames, "robot_minutes": round(frames / FPS / 60, 2), "bytes": report.bytes,
            "files": report.files, "validate_ok": report.ok, "validate_error": report.error,
            "validate_notes": report.notes, "folder": str(out.parent.relative_to(HERE.parent))}


def main():
    sizes = [int(v) for v in sys.argv[1:]] or [5, 20]
    full = datasets.validate_dataset(HERE / "dataset", json.loads((HERE / "embodiment.json").read_text()))
    rows = [cut(n) for n in sizes]
    rows.append({"episodes": full.episodes, "frames": full.frames, "robot_minutes": round(full.frames / FPS / 60, 2),
                 "bytes": full.bytes, "files": full.files, "validate_ok": full.ok, "validate_error": full.error,
                 "validate_notes": full.notes, "folder": "sim_demos/dataset"})
    (HERE / "dose_sets.json").write_text(json.dumps(rows, indent=2) + "\n")
    print(json.dumps(rows, indent=2))
    return 0 if all(r["validate_ok"] for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
