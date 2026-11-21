# Runs

Take records, one folder per run. The videos are too large for git and are not here.

| Folder | Kind | What it is |
|---|---|---|
| `2026-11-18-zero-shot/` | Scored | Dream-1, zero-shot, the first 15 tasks on layouts 100 to 102, under the frozen [PROTOCOL.md](../PROTOCOL.md). `results.md` is the table. There are 61 take folders for 45 task-layout pairs, because attempts that stopped on an error are kept next to their retries. A stopped take has an `error` in its `summary.json` and is not counted. |
| `2026-11-18-tubes-to-rack/` | Practice | Dream-1 on `tubes_to_rack`, practice layouts 0 to 4, with 2 wordings. Not part of any scored table. |
| `2026-11-18-camera-comparison/` | Pilot | Plate placement on layouts 100 to 102 through the camera environment: Codex, Fable (stopped before scoring) and the Dream-1 takes from the scored run, under its own [PROTOCOL.md](2026-11-18-camera-comparison/PROTOCOL.md). `RESULTS.md` is the table. |
| `2026-11-19-tending-first-look/` | Practice | Dream-1 on the 4 instrument tending tasks, practice layout 0, 1 completed take per task, with the recorded commands so each take can be replayed. Not part of any scored table. |
| `2026-11-21-tending-zero-shot/` | Scored | Dream-1, zero-shot, the 4 instrument tending tasks on layouts 100 to 102, under its own [PROTOCOL.md](2026-11-21-tending-zero-shot/PROTOCOL.md). `results.md` is the table and `README.md` says what happened: 12 takes, each completed on its first attempt, with the recorded commands. |

Each take folder holds a `summary.json` (in the first-look folder, a `recorded.json`): the task, the layout
seed, the stages reached, pass or not, and the versions it ran with. A folder with an `actions.f64le` can be
replayed and scored again with `python scripts/tending_replay.py <folder>`.
[DEVIATIONS.md](../DEVIATIONS.md) lists everything that departed from a protocol.
