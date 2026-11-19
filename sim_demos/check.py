"""Check a recorded dataset with Dream's own local dataset check, against sim_demos/embodiment.json.

    python -m sim_demos.check [dataset folder]       (from the lab-handling-bench folder)

dream.datasets.validate_dataset() runs on the local files only: nothing is sent and no API key is read. It is the
same check upload_dataset() runs before sending anything. The embodiment config is the one the YAM example in the
dreamlabs library uses for the model (dream_control.YAM_EMBODIMENT), so the dataset's state, action and camera keys
are exactly what the model reads at run time. The report is printed and written to sim_demos/validation_report.json.
"""

import dataclasses
import json
import sys
from pathlib import Path

from dream import datasets

HERE = Path(__file__).resolve().parent


def main():
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "dataset"
    config = json.loads((HERE / "embodiment.json").read_text())
    report = datasets.validate_dataset(path, config)
    result = {"dataset": str(path), "embodiment_config": config, **dataclasses.asdict(report)}
    text = json.dumps(result, indent=2)
    print(text)
    if len(sys.argv) <= 1:
        (HERE / "validation_report.json").write_text(text + "\n")
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
