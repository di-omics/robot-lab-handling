"""Instrument tending: a simulated washer-dispenser set up as a cell seeder, with its plate carrier at the load
position and a cell bottle beside it, and 4 chores (2 plate chores, a bottle swirl, and a two-arm chore that does
both at once).

Importing this package adds the chores to labbench.tasks.TASKS (in memory only, no labbench file changes), so
labbench.take.set_bench("dispenser_plate_in", seed) and run_take work afterwards. labbench's own fingerprint,
CODE_ID, is unchanged by this. This package has its own, TENDING_ID, and every result for these chores carries it
in summary["versions"]["tending"] (stamp() adds it to a labbench take).
"""

import hashlib
import json
from pathlib import Path

from labbench.tasks import TASKS


def _fingerprint():
    """The same recipe as labbench.take's: sha256 over the name and bytes of each tending/*.py, first 12 hex."""
    digest = hashlib.sha256()
    for path in sorted(Path(__file__).resolve().parent.glob("*.py")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()[:12]


## A short fingerprint of this package's source as loaded by this process.
TENDING_ID = _fingerprint()


def register():
    """Add the chores to labbench's shared task table, and the scene hook that lets their builds add the bottle's
    line (see dispenser.install_scene_hook). Refuses to replace a different task of the same name."""
    from .chores import CHORES
    from .dispenser import install_scene_hook

    install_scene_hook()

    for task in CHORES:
        if TASKS.get(task.name) not in (None, task):
            raise RuntimeError(f"{task.name} already names another task")
        TASKS[task.name] = task
    return [task.name for task in CHORES]


NAMES = tuple(register())


def stamp(take_dir):
    """Add TENDING_ID to a take's summary.json (labbench writes it without one). @return The updated summary."""
    path = Path(take_dir) / "summary.json"
    summary = json.loads(path.read_text())
    summary.setdefault("versions", {})["tending"] = TENDING_ID
    path.write_text(json.dumps(summary, indent=2))
    return summary
