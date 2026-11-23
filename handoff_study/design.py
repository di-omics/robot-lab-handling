"""The planned design of the reader handoff study, as data and pure functions.

3 experiments, 204 trials:

    experiment    arm                                     units                              rows
    camera        hand_nominal, hand_challenge            3 days x 8 layouts x 2 placements    48
    teaching_sim  dream1_demos_0, _5, _20, _50            4 models x 30 layouts               120
    hardware      dream1_demos_0, dream1_demos_50         2 models x 12 starts                 24
    hardware      manual                                  1 timed manual handoff per start     12

Nothing here uses Python's random module. Where an order is drawn, the items are ranked by the hex of
sha256("handoff-study-1|<purpose>|<item>") and the options are dealt in that rank order, so the sheet is the same
on every Python and every platform.
"""

import csv
import hashlib
import io

## The tag every drawn order starts from. Changing it changes the design id.
SEED_TAG = "handoff-study-1"

## trials.csv: design columns are written by `sheet` and never edited by hand; result columns are filled at the bench.
DESIGN_COLUMNS = ("trial_id", "experiment", "arm", "day", "layout", "pair", "order", "challenge")
RESULT_COLUMNS = ("status", "date", "operator", "first_read", "read_fault", "interventions", "hands_on_s",
                  "placement_pass", "seated_pass", "first_failed_stage", "reason", "notes")
TRIAL_COLUMNS = DESIGN_COLUMNS + RESULT_COLUMNS
VERDICT_COLUMNS = ("trial_id", "source", "capture", "verdict", "score", "model_id", "notes")
SETUP_COLUMNS = ("date", "activity", "minutes", "arm", "notes")

## Each experiment and where it runs. Bench and simulation results are never pooled.
EXPERIMENTS = ("camera", "teaching_sim", "hardware")
WHERE = {"camera": "bench", "teaching_sim": "simulation", "hardware": "bench"}
PHYSICAL = ("camera", "hardware")
ARMS = (("camera", "hand_nominal"), ("camera", "hand_challenge"),
        ("teaching_sim", "dream1_demos_0"), ("teaching_sim", "dream1_demos_5"),
        ("teaching_sim", "dream1_demos_20"), ("teaching_sim", "dream1_demos_50"),
        ("hardware", "dream1_demos_0"), ("hardware", "dream1_demos_50"), ("hardware", "manual"))
ARM_NAMES = tuple(dict.fromkeys(arm for _, arm in ARMS))

## Experiment 1: manual placements, a nominal and a challenge placement at each layout.
DAYS = (1, 2, 3)
LAYOUTS_PER_DAY = 8
FAMILIES = ("orientation", "seating")
FIRSTS = ("nominal", "challenge")
COMBINATIONS = tuple((family, first) for family in FAMILIES for first in FIRSTS)

## Experiment 2: the dose sets of sim_demos/PROPOSAL.md on its 30 unseen layouts.
DOSES = (0, 5, 20, 50)
SEEDS = tuple(range(42000, 42030))

## Experiment 3: 12 fresh starts on real arms, a fresh set (not the camera study's layouts).
STARTS = tuple(f"S{n:02d}" for n in range(1, 13))
HARDWARE_DOSES = (0, 50)

## Result vocabulary. Anything else is a validation error.
STATUSES = ("planned", "done", "unverified", "interrupted", "excluded")
FIRST_READS = ("valid", "invalid")
READ_FAULTS = ("no_load", "alarm", "out_of_limits", "reversed", "other")
PASS_VALUES = ("1", "0")
CAPTURES = ("original", "relit")
VERDICTS = ("release", "hold", "none")
ACTIVITIES = ("teaching", "calibration", "other")

## The 4 planned verdict sources: name -> (kind, what it is). Any other source name is reported as kind "other".
SOURCES = {
    "marker_rule": ("rule", "a fixed marker-and-geometry rule on the top view"),
    "probe_siglip2_crops": ("probe", "the linear probe on frozen SigLIP 2 features, top-view crops, fitted in "
                                     "simulation (robot-lab-judge row frozen/siglip2-lfm2.5-vl-450m/fine-logreg)"),
    "lfm3_top": ("zero_shot", "LFM3-VL-2B zero-shot, thinking on, top view only"),
    "lfm3_3view": ("zero_shot", "LFM3-VL-2B zero-shot, thinking on, top view and both wrist views"),
}
KINDS = ("rule", "probe", "zero_shot", "other")


def rank(purpose, items):
    """Return the items sorted by the hex of sha256("handoff-study-1|<purpose>|<item>")."""
    return sorted(items, key=lambda item: hashlib.sha256(f"{SEED_TAG}|{purpose}|{item}".encode()).hexdigest())


def deal(purpose, items, options):
    """Return {item: option}, the options dealt in turn to the items in rank order.

    With 8 items and 4 options each option goes to exactly 2 items; with 12 and 2, to exactly 6.
    """
    return {item: options[n % len(options)] for n, item in enumerate(rank(purpose, items))}


def planned_row(**design):
    """Return a full trials.csv row: the given design cells as text, status planned, every other cell blank."""
    row = dict.fromkeys(TRIAL_COLUMNS, "")
    row.update({column: str(value) for column, value in design.items()})
    row["status"] = "planned"
    return row


def camera_trials():
    """Return the 48 camera rows in run order.

    Each day runs its 8 layouts in number order, 2 placements each, order 1 to 16. The 4 combinations of challenge
    family and which placement goes first are dealt to the day's layouts, so each day has 2 layouts of each.
    """
    rows = []
    for day in DAYS:
        layouts = [f"D{day}-L{n}" for n in range(1, LAYOUTS_PER_DAY + 1)]
        combination = deal("camera", layouts, COMBINATIONS)
        order = 0
        for layout in layouts:
            family, first = combination[layout]
            for placement in (("N", "C") if first == "nominal" else ("C", "N")):
                order += 1
                rows.append(planned_row(
                    trial_id=f"C-{layout}-{placement}", experiment="camera",
                    arm="hand_nominal" if placement == "N" else "hand_challenge", day=day, layout=layout,
                    pair=layout, order=order, challenge="none" if placement == "N" else family))
    return rows


def teaching_trials():
    """Return the 120 simulated rows, sorted by seed and then by number of demonstrations, order 1 to 120.

    The simulator resets exactly, so the order carries no meaning here.
    """
    rows = []
    for seed in SEEDS:
        for demos in DOSES:
            rows.append(planned_row(
                trial_id=f"T-{demos:03d}-{seed}", experiment="teaching_sim", arm=f"dream1_demos_{demos}",
                layout=seed, pair=seed, order=len(rows) + 1, challenge="none"))
    return rows


def hardware_trials():
    """Return the 24 robot rows: starts in number order, 2 attempts each, order 1 to 24.

    Which model goes first at a start is dealt, so exactly 6 starts run dream1_demos_0 first.
    """
    first = deal("hardware", STARTS, HARDWARE_DOSES)
    rows = []
    for start in STARTS:
        for demos in (HARDWARE_DOSES if first[start] == HARDWARE_DOSES[0] else HARDWARE_DOSES[::-1]):
            rows.append(planned_row(
                trial_id=f"H-{demos:03d}-{start}", experiment="hardware", arm=f"dream1_demos_{demos}",
                layout=start, pair=start, order=len(rows) + 1, challenge="none"))
    return rows


def manual_trials():
    """Return the 12 timed manual handoffs, 1 per start, order 1 to 12 in start order."""
    return [planned_row(trial_id=f"M-{start}", experiment="hardware", arm="manual", layout=start, pair=start,
                        order=n, challenge="none")
            for n, start in enumerate(STARTS, start=1)]


def trials():
    """Return all 204 planned rows in sheet order: camera, teaching_sim, hardware robot attempts, manual."""
    return camera_trials() + teaching_trials() + hardware_trials() + manual_trials()


def csv_text(columns, rows):
    """Return the CSV text of the rows (dicts) under a header row, with LF line ends."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(columns)
    writer.writerows([row[column] for column in columns] for row in rows)
    return out.getvalue()


def design_id(rows=None):
    """Return the design id: first 12 hex of the sha256 over the design columns of the planned sheet as CSV."""
    text = csv_text(DESIGN_COLUMNS, trials() if rows is None else rows)
    return hashlib.sha256(text.encode()).hexdigest()[:12]
