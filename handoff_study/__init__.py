"""The reader handoff study: can the reader use the plate?

A plan for the first check on a real bench. Nothing in it has been run. This package holds the planned design
(design.py), the scorer (score.py), the command line (__main__.py) and the 3 sheets the bench fills in:
trials.csv, verdicts.csv and setup_time.csv. The plan itself is README.md in this folder.

Standard library only: no simulator, no model, no network. study_id() names the exact scorer code, and every
report prints it.
"""

import hashlib
from pathlib import Path


def study_id():
    """Return the scorer id: sha256 over the name and bytes of each handoff_study/*.py, first 12 hex digits.

    The same recipe as tending/__init__.py uses for TENDING_ID (and labbench.take for CODE_ID).
    """
    digest = hashlib.sha256()
    for path in sorted(Path(__file__).resolve().parent.glob("*.py")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()[:12]
