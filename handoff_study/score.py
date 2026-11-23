"""Read, check and score the 3 sheets of the reader handoff study, and render the report.

Every metric here is a pure function over lists of row dicts as the sheets give them: every value is text, and a
blank cell is "". The definitions:

- A usable read is a done trial whose first read was valid, with 0 interventions: a valid result on the first try.
- Valid with help is done and valid with 1 or more interventions. It is not usable.
- A reader-confirmed failure is a done bench trial that is not a usable read.
- Every rate is k of n with the exact (Clopper-Pearson) 95% range. No p-values.

Bench and simulation results are never pooled: they sit in separate tables.
"""

import csv
import io
import json
import re
import textwrap
from collections import Counter
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from math import comb
from pathlib import Path

from . import design as d
from . import study_id

FILES = {"trials": "trials.csv", "verdicts": "verdicts.csv", "setup": "setup_time.csv"}

TOKEN = re.compile(r"[a-z][a-z0-9_]*")
SOURCE_NAME = re.compile(r"[a-z0-9][a-z0-9_.-]*")
WHOLE = re.compile(r"[0-9]+")
AMOUNT = re.compile(r"[0-9]+(\.[0-9]+)?")
NUMBER = re.compile(r"-?[0-9]+(\.[0-9]+)?([eE][-+]?[0-9]+)?")
DAY = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
OPERATOR = re.compile(r"[a-z]{1,6}[0-9]{1,3}")

## trials.csv cells with a fixed vocabulary, and cells with a fixed form.
CHOICES = {"status": d.STATUSES, "first_read": d.FIRST_READS, "read_fault": d.READ_FAULTS,
           "placement_pass": d.PASS_VALUES, "seated_pass": d.PASS_VALUES}
FORMS = {"date": (DAY, "a date written YYYY-MM-DD"),
         "operator": (OPERATOR, "a short code of 1 to 6 lower-case letters, then 1 to 3 digits, such as op1"),
         "interventions": (WHOLE, "a whole number, 0 or more"),
         "hands_on_s": (AMOUNT, "a number of seconds, 0 or more"),
         "first_failed_stage": (TOKEN, "a lower-case token such as over_tray")}

## Result cells by kind of row: reader cells belong to bench rows, simulator cells to simulated rows.
COMMON_CELLS = ("date", "operator", "reason", "notes")
READER_CELLS = ("first_read", "read_fault", "interventions", "hands_on_s")
SIM_CELLS = ("placement_pass", "seated_pass")

CAVEATS = (
    "Every range is the exact (Clopper-Pearson) 95% range, two-sided. It treats trials as independent.",
    "The 2 placements of a camera pair share a layout and a day, so they are not independent.",
    "Original and relit pictures show the same placements: 2 looks at 1 placement, not 2 placements.",
    "The sizes are those of a feasibility pilot: 48 placements, 120 simulated attempts, 24 robot attempts, "
    "12 manual handoffs.",
)


## ---------- reading ----------

def shown(value):
    """Return a cell as it can be printed: itself when ASCII, else with its other characters escaped."""
    return value if value.isascii() else ascii(value)[1:-1]


def read_csv(path):
    """Return (header, rows, problems) for 1 sheet.

    rows are dicts of text, padded with "" where a row is short. header is None when the file is missing or is not
    UTF-8 text. A leading byte order mark (a spreadsheet's "CSV UTF-8") is dropped. A blank row (no cells, or only
    empty cells) and a row whose cell count differs from the header's are problems. Row numbers are those a
    spreadsheet shows: the header is row 1.
    """
    path = Path(path)
    try:
        text = path.read_bytes().decode("utf-8-sig")
    except FileNotFoundError:
        return None, [], [f"{path.name}: no such file"]
    except UnicodeDecodeError:
        return None, [], [f"{path.name}: not UTF-8 text"]
    lines = list(csv.reader(io.StringIO(text, newline="")))
    if not lines:
        return [], [], []
    header, rows, problems = lines[0], [], []
    for number, cells in enumerate(lines[1:], start=2):
        if not any(cell.strip() for cell in cells):
            problems.append(f"{path.name} row {number}: blank row (delete it)")
        elif len(cells) != len(header):
            problems.append(f"{path.name} row {number}: {len(cells)} cells, the header has {len(header)}")
        rows.append(dict(zip(header, cells + [""] * (len(header) - len(cells)))))
    return header, rows, problems


def load(folder):
    """Return (sheets, problems) for the 3 sheets in a folder.

    sheets maps trials, verdicts and setup to their rows. problems lists every problem by file and row; score only
    when it is empty.
    """
    folder = Path(folder)
    read = {key: read_csv(folder / name) for key, name in FILES.items()}
    problems = [p for _, _, found in read.values() for p in found]
    (trial_header, trials, _), (verdict_header, verdicts, _), (setup_header, setup, _) = read.values()
    if trial_header is not None:
        problems += trial_problems(trial_header, trials)
    if verdict_header is not None:
        problems += verdict_problems(verdict_header, verdicts, trials)
    if setup_header is not None:
        problems += setup_problems(setup_header, setup)
    return {"trials": trials, "verdicts": verdicts, "setup": setup}, problems


## ---------- checking ----------

def header_problems(name, header, expected):
    """Return the problems of a header row: empty file, missing, unknown or repeated columns."""
    if not header:
        return [f"{name}: the file is empty (it needs the header row)"]
    problems = [f"{name}: missing column {column}" for column in expected if column not in header]
    problems += [f"{name}: unknown column '{shown(column)}'" for column in header if column not in expected]
    problems += [f"{name}: column {column} is repeated" for column in expected if header.count(column) > 1]
    return problems


def choices(options):
    """Return the options as text: 'a, b or c'."""
    return ", ".join(options[:-1]) + " or " + options[-1]


def is_blank(row):
    """Return True for a row with no cell that holds more than spaces (read_csv reports it as a blank row)."""
    return not any(value.strip() for value in row.values())


def text_problems(row):
    """Return a problem for every cell of a row that holds non-ASCII text."""
    return [f"{column} holds non-ASCII text" for column, value in row.items() if not value.isascii()]


def is_date(value):
    """Return True when value is a real date written YYYY-MM-DD."""
    if not DAY.fullmatch(value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def design_problems(header, rows):
    """Return every difference between the design columns of a trial sheet and design.py, naming the row.

    Covers missing design columns, a duplicate trial_id, a trial_id not in the design, a design cell that differs,
    and a trial of the design that the sheet lacks. Row positions are not compared: the order column is the run order.
    """
    missing = [f"trials.csv: missing column {column}" for column in d.DESIGN_COLUMNS if column not in header]
    if missing:
        return missing
    planned = {row["trial_id"]: row for row in d.trials()}
    problems, seen = [], {}
    for number, row in enumerate(rows, start=2):
        if is_blank(row):
            continue
        trial_id = row["trial_id"]
        where = f"trials.csv row {number} ({shown(trial_id)})"
        if trial_id in seen:
            problems.append(f"{where}: duplicate trial_id, first on row {seen[trial_id]}")
            continue
        seen[trial_id] = number
        if trial_id not in planned:
            problems.append(f"{where}: trial_id is not in the design")
            continue
        for column in d.DESIGN_COLUMNS[1:]:
            if row[column] != planned[trial_id][column]:
                problems.append(f"{where}: {column} is '{shown(row[column])}', the design says "
                                f"'{planned[trial_id][column]}'")
    problems += [f"trials.csv: trial {trial_id} of the design is missing" for trial_id in planned
                 if trial_id not in seen]
    return problems


def allowed_cells(status, physical):
    """Return the result cells, status aside, that a row of this status may fill (a planned row: none)."""
    if status == "planned":
        return set()
    cells = set(COMMON_CELLS)
    if status == "done":
        cells |= {"first_failed_stage"} | set(READER_CELLS if physical else SIM_CELLS)
    if status == "interrupted" and physical:
        cells |= {"interventions", "hands_on_s"}
    return cells


def required_cells(row, physical):
    """Return the result cells a row must fill for its status."""
    status = row["status"]
    need = {"done": ["date", "operator"], "unverified": ["date", "operator", "reason"],
            "interrupted": ["date", "operator", "reason"], "excluded": ["reason"]}.get(status, [])
    if status == "done":
        need += ["first_read", "interventions", "hands_on_s"] if physical else ["placement_pass"]
        if row["first_read"] == "invalid":
            need.append("read_fault")
    if status == "interrupted" and physical:
        need += ["interventions", "hands_on_s"]
    return need


def misplaced(column, status, physical):
    """Return the message for a result cell filled where its row may not fill it."""
    if status == "planned":
        return f"{column} is filled on a planned row (a planned row has only its status)"
    if column in READER_CELLS and not physical:
        return f"{column} on a simulation row (there is no reader in simulation)"
    if column in SIM_CELLS and physical:
        return f"{column} on a physical row (it is for simulated rows only)"
    return f"{column} is not used on a row with status {status}"


def trial_row_problems(row):
    """Return the problems of 1 trials.csv row: vocabulary, forms, and the cells its status needs or forbids."""
    problems = text_problems(row)
    for column, options in CHOICES.items():
        if row[column] and row[column] not in options:
            problems.append(f"{column} '{shown(row[column])}' must be {choices(options)}")
    for column, (form, what) in FORMS.items():
        if row[column] and not form.fullmatch(row[column]):
            problems.append(f"{column} '{shown(row[column])}' is not {what}")
    if DAY.fullmatch(row["date"]) and not is_date(row["date"]):
        problems.append(f"date '{row['date']}' is not a real date")
    status = row["status"]
    if not status:
        problems.append(f"status is blank (it must be {choices(d.STATUSES)})")
    if status not in d.STATUSES:
        return problems
    if status == "unverified" and row["experiment"] != "camera":
        problems.append("status unverified is for the camera study only")
    physical = row["experiment"] in d.PHYSICAL
    allowed = allowed_cells(status, physical)
    problems += [misplaced(column, status, physical) for column in d.RESULT_COLUMNS[1:]
                 if row[column] and column not in allowed]
    problems += [f"status {status} needs {column}" for column in required_cells(row, physical)
                 if not row[column].strip()]
    if row["read_fault"] and row["first_read"] == "valid":
        problems.append("read_fault is only for an invalid first_read")
    return problems + outcome_problems(row, physical)


def outcome_problems(row, physical):
    """Return the problems of a done row whose outcome cells contradict each other.

    seated_pass is the stricter check, so seated_pass 1 needs placement_pass 1. first_failed_stage stays blank when
    nothing failed: on a usable read, and on a simulated row with placement_pass 1 and no seated_pass 0.
    """
    if row["status"] != "done":
        return []
    problems = []
    if not physical and row["seated_pass"] == "1" and row["placement_pass"] == "0":
        problems.append("seated_pass 1 needs placement_pass 1 (seated_pass is the stricter check)")
    if row["first_failed_stage"]:
        if physical and WHOLE.fullmatch(row["interventions"]) and is_usable(row):
            problems.append("first_failed_stage is filled on a usable read (blank when nothing failed)")
        if not physical and row["placement_pass"] == "1" and row["seated_pass"] != "0":
            problems.append("first_failed_stage is filled on a row that passed (blank when nothing failed)")
    return problems


def trial_problems(header, rows):
    """Return every problem of trials.csv: header, design columns, then each row, naming the row."""
    problems = header_problems("trials.csv", header, d.TRIAL_COLUMNS)
    if problems:
        return problems
    problems = design_problems(header, rows)
    for number, row in enumerate(rows, start=2):
        if not is_blank(row):
            where = f"trials.csv row {number} ({shown(row['trial_id'])})"
            problems += [f"{where}: {message}" for message in trial_row_problems(row)]
    return problems


def verdict_problems(header, rows, trials):
    """Return every problem of verdicts.csv, given the trial rows, naming the row.

    A verdict must name a known bench trial that was photographed (not planned, not excluded); source, capture and
    verdict must be in the vocabulary; score is blank or a number; model_id is required; and each
    (trial_id, source, capture) appears once.
    """
    problems = header_problems("verdicts.csv", header, d.VERDICT_COLUMNS)
    if problems:
        return problems
    trial = {row.get("trial_id"): row for row in trials}
    seen = {}
    for number, row in enumerate(rows, start=2):
        if is_blank(row):
            continue
        key = (row["trial_id"], row["source"], row["capture"])
        where = f"verdicts.csv row {number} ({', '.join(shown(part) for part in key)})"
        found = text_problems(row)
        status = trial.get(row["trial_id"], {}).get("status")
        if row["trial_id"] not in trial:
            found.append("verdict for an unknown trial")
        elif trial[row["trial_id"]].get("experiment") not in d.PHYSICAL:
            found.append("verdict on a simulation row (there is no reader to check it against)")
        elif status in ("planned", "excluded"):
            found.append(f"verdict on a trial with status {status} (it was never photographed)")
        if not SOURCE_NAME.fullmatch(row["source"]):
            found.append(f"source '{shown(row['source'])}' is not a lower-case name such as marker_rule")
        if row["capture"] not in d.CAPTURES:
            found.append(f"capture '{shown(row['capture'])}' must be {choices(d.CAPTURES)}")
        if row["verdict"] not in d.VERDICTS:
            found.append(f"verdict '{shown(row['verdict'])}' must be {choices(d.VERDICTS)}")
        if row["score"] and not NUMBER.fullmatch(row["score"]):
            found.append(f"score '{shown(row['score'])}' is not a number")
        if not row["model_id"].strip():
            found.append("model_id is blank (name the exact model or rule version)")
        if key in seen:
            found.append(f"duplicate (trial_id, source, capture), first on row {seen[key]}")
        seen.setdefault(key, number)
        problems += [f"{where}: {message}" for message in found]
    return problems


def setup_problems(header, rows):
    """Return every problem of setup_time.csv, naming the row: date, activity, minutes and arm."""
    problems = header_problems("setup_time.csv", header, d.SETUP_COLUMNS)
    if problems:
        return problems
    for number, row in enumerate(rows, start=2):
        if is_blank(row):
            continue
        found = text_problems(row)
        if not is_date(row["date"]):
            found.append(f"date '{shown(row['date'])}' is not a real date written YYYY-MM-DD")
        if row["activity"] not in d.ACTIVITIES:
            found.append(f"activity '{shown(row['activity'])}' must be {choices(d.ACTIVITIES)}")
        if not AMOUNT.fullmatch(row["minutes"]):
            found.append(f"minutes '{shown(row['minutes'])}' is not a number of minutes, 0 or more")
        if row["arm"] and row["arm"] not in d.ARM_NAMES:
            found.append(f"arm '{shown(row['arm'])}' must be blank or {choices(d.ARM_NAMES)}")
        problems += [f"setup_time.csv row {number}: {message}" for message in found]
    return problems


def holds_results(key, rows):
    """Return the row number of the first row that holds a result, or None.

    trials: a status other than planned, or any filled result cell. verdicts and setup: any filled row.
    """
    for number, row in enumerate(rows, start=2):
        if key != "trials":
            filled = not is_blank(row)
        else:
            filled = row.get("status", "") not in ("", "planned") or any(
                value for column, value in row.items() if column not in d.DESIGN_COLUMNS + ("status",))
        if filled:
            return number
    return None


## ---------- metrics ----------

def exact_range(k, n, level=0.95):
    """Return the exact (Clopper-Pearson) range (low, high) for a true rate as fractions, or None when n is 0.

    The same calculation as labbench.baseline.exact_range: the binomial tails solved by bisection.
    """
    if n == 0:
        return None
    alpha = (1 - level) / 2

    def tail_ge(p):  # chance of k or more
        return sum(comb(n, i) * p**i * (1 - p) ** (n - i) for i in range(k, n + 1))

    def tail_le(p):  # chance of k or fewer
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


def count(k, n):
    """Return {"k", "n", "range_95"}: k of n with its exact 95% range as fractions to 3 places (None when n is 0)."""
    found = exact_range(k, n)
    return {"k": k, "n": n, "range_95": None if found is None else [round(found[0], 3), round(found[1], 3)]}


def whole(value):
    """Return a cell as a whole number, or None when it is blank."""
    return int(value) if value else None


def is_usable(row):
    """Return True for a usable read: done, first read valid, 0 interventions."""
    return row["status"] == "done" and row["first_read"] == "valid" and whole(row["interventions"]) == 0


def is_failure(row):
    """Return True for a reader-confirmed failure: a done bench trial that is not a usable read."""
    return row["status"] == "done" and not is_usable(row)


def tally(values):
    """Return {value: count} over the non-blank values, most common first, then by name."""
    found = Counter(value for value in values if value)
    return dict(sorted(found.items(), key=lambda item: (-item[1], item[0])))


def stage_tally(failed):
    """Return the tally of first_failed_stage over failed rows; a failure with a blank stage counts as 'not recorded'.

    An empty tally means nothing failed.
    """
    return tally(row["first_failed_stage"] or "not recorded" for row in failed)


def tenth(value):
    """Return a Decimal rounded half up to 0.1, as a float: 42.25 -> 42.3, as a person adding up by hand expects."""
    return float(value.quantize(Decimal("0.1"), ROUND_HALF_UP))


def arm_rows(trials, experiment, arm):
    """Return the rows of 1 arm of 1 experiment."""
    return [row for row in trials if row["experiment"] == experiment and row["arm"] == arm]


def status_row(rows):
    """Return assigned and the count of each status for a group of rows."""
    found = Counter(row["status"] for row in rows)
    return {"assigned": len(rows), **{status: found[status] for status in d.STATUSES}}


def status_table(trials):
    """Return status_row for every arm of the design, with its experiment, arm and where it runs."""
    return [{"experiment": experiment, "arm": arm, "where": d.WHERE[experiment],
             **status_row(arm_rows(trials, experiment, arm))} for experiment, arm in d.ARMS]


def reader_row(rows):
    """Return the reader outcome of a group of bench rows.

    done; usable reads k of done with the exact range; valid with help; invalid; the tally of read_fault over the
    done rows; and the tally of first_failed_stage over the reader-confirmed failures.
    """
    done = [row for row in rows if row["status"] == "done"]
    return {"done": len(done),
            "usable": count(sum(map(is_usable, done)), len(done)),
            "valid_with_help": sum(row["first_read"] == "valid" and (whole(row["interventions"]) or 0) > 0
                                   for row in done),
            "invalid": sum(row["first_read"] == "invalid" for row in done),
            "read_faults": tally(row["read_fault"] for row in done),
            "first_failed_stages": stage_tally(row for row in done if not is_usable(row))}


def reader_table(trials):
    """Return reader_row for every bench arm, with its experiment and arm."""
    return [{"experiment": experiment, "arm": arm, **reader_row(arm_rows(trials, experiment, arm))}
            for experiment, arm in d.ARMS if experiment in d.PHYSICAL]


def simulation_row(rows):
    """Return the simulated outcome of a group of rows.

    done; placement_pass k of done; seated_pass k of the done rows that have a value; each with the exact range;
    and the tally of first_failed_stage over the failed rows (placement_pass 0 or seated_pass 0).
    """
    done = [row for row in rows if row["status"] == "done"]
    seated = [row for row in done if row["seated_pass"]]
    return {"done": len(done),
            "placement_pass": count(sum(row["placement_pass"] == "1" for row in done), len(done)),
            "seated_pass": count(sum(row["seated_pass"] == "1" for row in seated), len(seated)),
            "first_failed_stages": stage_tally(row for row in done
                                               if "0" in (row["placement_pass"], row["seated_pass"]))}


def simulation_table(trials):
    """Return simulation_row for every simulated arm, with its experiment and arm."""
    return [{"experiment": experiment, "arm": arm, **simulation_row(arm_rows(trials, experiment, arm))}
            for experiment, arm in d.ARMS if experiment not in d.PHYSICAL]


def is_right(row, verdict):
    """Return True when a verdict agrees with the reader: release on a usable read, hold on a failure.

    none is never right.
    """
    return (verdict == "release" and is_usable(row)) or (verdict == "hold" and is_failure(row))


def pairs_right(rows, verdicts):
    """Return pairs both right of pairs complete over camera rows, as a count.

    A pair is the 2 placements of a camera layout. It is complete when both are done and have a verdict, and right
    when both verdicts are right.
    """
    pairs = {}
    for row in rows:
        pairs.setdefault(row["pair"], []).append(row)
    complete = [pair for pair in pairs.values()
                if all(row["status"] == "done" and row["trial_id"] in verdicts for row in pair)]
    return count(sum(all(is_right(row, verdicts[row["trial_id"]]) for row in pair) for pair in complete),
                 len(complete))


def camera_row(rows, verdicts):
    """Return the camera outcome for 1 source and 1 capture over the rows of 1 experiment (or of 1 day of it).

    verdicts maps trial_id to that source's verdict on that capture. Over done rows that have a verdict: failures F,
    false releases r of F, usable reads G, good reads blocked b of G, releases, holds, no decision, and decision
    coverage (releases + holds) of those with a verdict. Then: done rows with no verdict (missing); pairs both right
    of pairs complete, for the camera study only (None elsewhere: a hardware start holds 2 models and a manual
    handoff, not a matched pair of placements); verdicts on unverified and on interrupted trials, which are counted
    apart and in nothing else.
    """
    done = [row for row in rows if row["status"] == "done"]
    with_verdict = [row for row in done if row["trial_id"] in verdicts]
    failures = [row for row in with_verdict if is_failure(row)]
    usable = [row for row in with_verdict if is_usable(row)]
    said = Counter(verdicts[row["trial_id"]] for row in with_verdict)
    camera = bool(rows) and all(row["experiment"] == "camera" for row in rows)
    apart = Counter(row["status"] for row in rows if row["trial_id"] in verdicts)
    return {"with_verdict": len(with_verdict),
            "failures": len(failures),
            "false_releases": count(sum(verdicts[row["trial_id"]] == "release" for row in failures), len(failures)),
            "usable_reads": len(usable),
            "good_reads_blocked": count(sum(verdicts[row["trial_id"]] == "hold" for row in usable), len(usable)),
            "releases": said["release"], "holds": said["hold"], "no_decision": said["none"],
            "decision_coverage": count(said["release"] + said["hold"], len(with_verdict)),
            "missing": len(done) - len(with_verdict),
            "pairs_right": pairs_right(rows, verdicts) if camera else None,
            "on_unverified": apart["unverified"],
            "on_interrupted": apart["interrupted"]}


def source_kind(source):
    """Return the kind of a verdict source: rule, probe or zero_shot when registered in design.SOURCES, else other."""
    return d.SOURCES[source][0] if source in d.SOURCES else "other"


def verdict_groups(trials, verdicts):
    """Return {(experiment, source, capture): {trial_id: verdict}} over verdicts on known trials, in report order.

    Order: experiment, kind, registered sources first and others by name, then original before relit.
    """
    experiment = {row["trial_id"]: row["experiment"] for row in trials}
    groups = {}
    for row in verdicts:
        if row["trial_id"] in experiment:
            key = (experiment[row["trial_id"]], row["source"], row["capture"])
            groups.setdefault(key, {})[row["trial_id"]] = row["verdict"]
    sources = list(d.SOURCES)

    def order(key):
        exp, source, capture = key
        return (d.EXPERIMENTS.index(exp), d.KINDS.index(source_kind(source)),
                sources.index(source) if source in sources else len(sources), source, d.CAPTURES.index(capture))

    return {key: groups[key] for key in sorted(groups, key=order)}


def camera_table(trials, verdicts):
    """Return camera_row for every experiment, source and capture that has a verdict, with the source's kind."""
    return [{"experiment": exp, "kind": source_kind(source), "source": source, "capture": capture,
             **camera_row([row for row in trials if row["experiment"] == exp], said)}
            for (exp, source, capture), said in verdict_groups(trials, verdicts).items()]


def camera_day_table(trials, verdicts):
    """Return, for every source, capture and day that has a verdict, false releases r of F and good reads blocked
    b of G on that day. Only rows with a day (the camera study) are split by day."""
    out = []
    for (exp, source, capture), said in verdict_groups(trials, verdicts).items():
        days = sorted({row["day"] for row in trials if row["experiment"] == exp and row["day"]}, key=int)
        for day in days:
            found = camera_row([row for row in trials if row["experiment"] == exp and row["day"] == day], said)
            if found["with_verdict"]:
                out.append({"experiment": exp, "kind": source_kind(source), "source": source, "capture": capture,
                            "day": int(day), "failures": found["failures"],
                            "false_releases": found["false_releases"], "usable_reads": found["usable_reads"],
                            "good_reads_blocked": found["good_reads_blocked"]})
    return out


def same_verdict_table(trials, verdicts):
    """Return, for every experiment and source with verdicts on both captures, how often the 2 pictures of 1
    placement got the same verdict: k of the done trials that have a verdict on both, with the exact range."""
    groups = verdict_groups(trials, verdicts)
    done = {row["trial_id"] for row in trials if row["status"] == "done"}
    out = []
    for (exp, source, capture), original in groups.items():
        relit = groups.get((exp, source, "relit"))
        if capture == "original" and relit:
            both = [trial_id for trial_id in original if trial_id in relit and trial_id in done]
            out.append({"experiment": exp, "kind": source_kind(source), "source": source,
                        "same_verdict": count(sum(original[t] == relit[t] for t in both), len(both))})
    return out


def time_row(rows):
    """Return the operator time of a group of bench rows, over its done and interrupted attempts with hands_on_s.

    attempts with time; hands-on seconds and minutes in total; interventions in total; attempts with 1 or more
    interventions; usable reads; and minutes per usable read, which is None (never a division by 0) with 0 usable
    reads. Seconds are added exactly and rounded half up to 0.1 only at the end.
    """
    timed = [row for row in rows if row["status"] in ("done", "interrupted") and row["hands_on_s"]]
    seconds = sum((Decimal(row["hands_on_s"]) for row in timed), Decimal(0))
    helps = [whole(row["interventions"]) or 0 for row in timed]
    usable = sum(map(is_usable, timed))
    return {"attempts_with_time": len(timed),
            "hands_on_s": tenth(seconds),
            "hands_on_min": tenth(seconds / 60),
            "interventions": sum(helps),
            "attempts_with_interventions": sum(help > 0 for help in helps),
            "usable_reads": usable,
            "min_per_usable_read": tenth(seconds / 60 / usable) if usable else None}


def time_table(trials):
    """Return time_row for every bench arm where any hands_on_s is filled, with its experiment and arm."""
    out = []
    for experiment, arm in d.ARMS:
        rows = arm_rows(trials, experiment, arm)
        if experiment in d.PHYSICAL and any(row["hands_on_s"] for row in rows):
            out.append({"experiment": experiment, "arm": arm, **time_row(rows)})
    return out


def setup_table(setup):
    """Return entries and minutes (added exactly, rounded half up to 0.1) for every activity and arm that has an entry.

    Order: activity in vocabulary order, then arm, a blank arm (shown as "all") first and then the design's arms.
    Teaching and calibration time stay apart from the per-read time.
    """
    out = []
    for activity in d.ACTIVITIES:
        for arm in ("",) + d.ARM_NAMES:
            rows = [row for row in setup if row["activity"] == activity and row["arm"] == arm]
            if rows:
                out.append({"activity": activity, "arm": arm or "all", "entries": len(rows),
                            "minutes": tenth(sum((Decimal(row["minutes"]) for row in rows), Decimal(0)))})
    return out


def passed(row, outcome):
    """Return True or False for a done row on an outcome (placement_pass, seated_pass or usable), or None when the
    row is missing, not done, or has no value for that outcome."""
    if row is None or row["status"] != "done":
        return None
    if outcome == "usable":
        return is_usable(row)
    return None if not row[outcome] else row[outcome] == "1"


def paired_row(trials, experiment, outcome):
    """Return dream1_demos_50 against dream1_demos_0 on the same pair of 1 experiment, for 1 outcome.

    pairs; both pass; only 50; only 0; neither; incomplete (either row not done, or without a value).
    """
    rows = {(row["pair"], row["arm"]): row for row in trials if row["experiment"] == experiment}
    pairs = sorted({pair for pair, arm in rows if arm in ("dream1_demos_0", "dream1_demos_50")})
    names = {(True, True): "both_pass", (True, False): "only_50", (False, True): "only_0", (False, False): "neither"}
    found = Counter()
    for pair in pairs:
        key = tuple(passed(rows.get((pair, arm)), outcome) for arm in ("dream1_demos_50", "dream1_demos_0"))
        found["incomplete" if None in key else names[key]] += 1
    return {"experiment": experiment, "outcome": outcome, "pairs": len(pairs),
            **{name: found[name] for name in ("both_pass", "only_50", "only_0", "neither", "incomplete")}}


def paired_table(trials):
    """Return paired_row for simulation (placement_pass, then seated_pass) and the bench (usable)."""
    return [paired_row(trials, "teaching_sim", "placement_pass"), paired_row(trials, "teaching_sim", "seated_pass"),
            paired_row(trials, "hardware", "usable")]


def not_done(trials):
    """Return trial_id, status and reason of every unverified, interrupted or excluded trial, in sheet order."""
    return [{"trial_id": row["trial_id"], "status": row["status"], "reason": " ".join(row["reason"].split())}
            for row in trials if row["status"] in ("unverified", "interrupted", "excluded")]


def score(trials, verdicts, setup):
    """Return the whole report as a dict: what results.json holds and what render() prints.

    Call it on sheets that load() found no problem in.
    """
    done = [row for row in trials if row["status"] == "done"]
    return {"study": "Can the reader use the plate?",
            "scorer_id": study_id(),
            "design_id": d.design_id(),
            "trials_assigned": len(trials),
            "trials_done": len(done),
            "done_on_bench": sum(row["experiment"] in d.PHYSICAL for row in done),
            "done_in_simulation": sum(row["experiment"] not in d.PHYSICAL for row in done),
            "verdict_rows": len(verdicts),
            "setup_entries": len(setup),
            "status": status_table(trials),
            "reader": reader_table(trials),
            "simulation": simulation_table(trials),
            "camera": camera_table(trials, verdicts),
            "camera_by_day": camera_day_table(trials, verdicts),
            "camera_same_verdict": same_verdict_table(trials, verdicts),
            "operator_time": time_table(trials),
            "setup_time": setup_table(setup),
            "paired": paired_table(trials),
            "not_done": not_done(trials),
            "caveats": list(CAVEATS)}


## ---------- rendering ----------

def as_json(data):
    """Return the report dict as JSON text (ASCII, 2-space indent, LF line end)."""
    return json.dumps(data, indent=2) + "\n"


def range_text(found):
    """Return a count's exact range as 'a to b%', computed afresh from k and n, or 'n/a' when n is 0."""
    exact = exact_range(found["k"], found["n"])
    return "n/a" if exact is None else f"{exact[0] * 100:.0f} to {exact[1] * 100:.0f}%"


def of(found):
    """Return a count as 'k of n'."""
    return f"{found['k']} of {found['n']}"


def recorded(found):
    """Return a count as 'k of n', or 'not recorded' when n is 0 (for seated_pass, which may stay blank)."""
    return of(found) if found["n"] else "not recorded"


def tally_text(found):
    """Return a tally as 'name 2, other 1', or 'none'."""
    return ", ".join(f"{name} {n}" for name, n in found.items()) or "none"


def table(header, rows):
    """Return a Markdown table as a list of lines."""
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    return lines + ["| " + " | ".join(str(cell) for cell in row) + " |" for row in rows]


def started(found):
    """Return True when a status row has any trial that is not planned."""
    return found["assigned"] != found["planned"]


def head_lines(data):
    """Return the report's title, provenance line and ids."""
    done = f"Done: {data['trials_done']}."
    if data["trials_done"]:
        done = (f"Done: {data['trials_done']} ({data['done_on_bench']} on the bench, "
                f"{data['done_in_simulation']} in simulation).")
    return ["# Results: can the reader use the plate?", "",
            "Written by `python -m handoff_study score --write` from trials.csv, verdicts.csv and setup_time.csv in",
            "this folder. Do not edit it by hand. Bench and simulation results sit in separate tables and are never",
            "pooled.", "",
            f"Scorer `{data['scorer_id']}`. Design `{data['design_id']}`. Trials assigned: {data['trials_assigned']}. "
            + done, ""]


def empty_lines(data):
    """Return the short report for a sheet where every trial is still planned."""
    lines = [f"**0 trials have been run.** All {data['trials_assigned']} rows of trials.csv are planned. Camera "
             f"verdicts: {data['verdict_rows']}.", f"Setup time entries: {data['setup_entries']}. There is nothing "
             "to score yet.", ""]
    lines += table(["Experiment", "Arm", "Where", "Trials assigned"],
                   [[row["experiment"], row["arm"], row["where"], row["assigned"]] for row in data["status"]])
    return lines + [""] + (setup_lines(data) if data["setup_time"] else [])


def status_lines(data):
    """Return the table of trials by status, every arm."""
    lines = ["## Trials by status", ""]
    lines += table(["Experiment", "Arm", "Where", "Assigned", "Planned", "Done", "Unverified", "Interrupted",
                    "Excluded"],
                   [[row["experiment"], row["arm"], row["where"], row["assigned"]] + [row[s] for s in d.STATUSES]
                    for row in data["status"]])
    return lines + [""]


def reader_lines(data):
    """Return question 1: the reader on the bench, then the simulator's rules in simulation."""
    begun = {(row["experiment"], row["arm"]) for row in data["status"] if started(row)}
    lines = ["## 1. Does the reader give a valid result on the first try?", "",
             "A usable read is a done trial whose first read was valid, with 0 interventions. Valid with help is valid",
             "with 1 or more interventions; it is not usable. Usable reads are counted out of done trials.", "",
             "'True rate could be' is the exact (Clopper-Pearson) 95% range for that k of n, here and in every table",
             "below. The first failed stage is tallied over the failures; 'not recorded' is a failure with no stage.",
             "",
             "### On the bench", ""]
    rows = [row for row in data["reader"] if (row["experiment"], row["arm"]) in begun]
    if rows:
        lines += table(["Experiment", "Arm", "Usable reads", "True rate could be", "Valid with help", "Invalid",
                        "Read faults", "First failed stage"],
                       [[row["experiment"], row["arm"], of(row["usable"]), range_text(row["usable"]),
                         row["valid_with_help"], row["invalid"], tally_text(row["read_faults"]),
                         tally_text(row["first_failed_stages"])] for row in rows])
    else:
        lines.append("No bench trial has been run yet.")
    lines += ["", "### In simulation", "",
              "There is no reader in simulation. placement_pass is the repo's frozen plate_to_tray pass rule.",
              "seated_pass is a stricter seating check, not in this repo yet for plate_to_tray; it is counted over",
              "the rows that have it. A failure here is placement_pass 0 or seated_pass 0.", ""]
    rows = [row for row in data["simulation"] if (row["experiment"], row["arm"]) in begun]
    if rows:
        lines += table(["Arm", "Placement pass", "True rate could be", "Seated pass", "True rate could be",
                        "First failed stage"],
                       [[row["arm"], of(row["placement_pass"]), range_text(row["placement_pass"]),
                         recorded(row["seated_pass"]), range_text(row["seated_pass"]),
                         tally_text(row["first_failed_stages"])] for row in rows])
    else:
        lines.append("No simulated trial has been run yet.")
    return lines + [""]


def camera_lines(data):
    """Return question 2: 1 table per experiment and kind of source, then the camera study per day."""
    lines = ["## 2. Can a camera tell before the reader runs?", ""]
    if not data["camera"]:
        return lines + ["No camera verdicts yet.", ""]
    lines += ["Counted over done trials that have a verdict from that source on that capture. A failure is a done",
              "trial that is not a usable read. A false release is `release` on a failure; a good read blocked is",
              "`hold` on a usable read; `none` is no decision. Decision coverage is releases and holds out of the",
              "trials with a verdict. Missing counts done trials of the experiment with no verdict from that source",
              "on that capture (on hardware, the manual handoffs too). The rates leave missing trials out: 2 sources",
              "are sure to be compared on the same trials when both have 0 missing. Pairs both right is for the",
              "camera study only: a pair is the 2 placements of a layout, complete when both are done and have a",
              "verdict, right when both verdicts are right (n/a on hardware). Verdicts on unverified placements are",
              "counted apart and in nothing else. `original` and `relit` are separate rows, never pooled; the same",
              "verdict on both pictures of 1 placement is counted in its own table.", "",
              "Kinds: rule, a fixed rule; probe, a linear probe on frozen image features, fitted in simulation;",
              "zero_shot, a vision-language model used with no fitting; other, any other source.", ""]
    groups = {}
    for row in data["camera"]:
        groups.setdefault((row["experiment"], row["kind"]), []).append(row)
    for (experiment, kind), rows in groups.items():
        lines += [f"### Experiment {experiment}, sources of kind {kind}", ""]
        lines += table(["Source", "Capture", "With a verdict", "False releases", "True rate could be",
                        "Good reads blocked", "True rate could be", "Release, hold, none", "Decision coverage",
                        "Missing", "Pairs both right", "On unverified"],
                       [[row["source"], row["capture"], row["with_verdict"], of(row["false_releases"]),
                         range_text(row["false_releases"]), of(row["good_reads_blocked"]),
                         range_text(row["good_reads_blocked"]),
                         f"{row['releases']}, {row['holds']}, {row['no_decision']}", of(row["decision_coverage"]),
                         row["missing"], "n/a" if row["pairs_right"] is None else of(row["pairs_right"]),
                         row["on_unverified"]] for row in rows])
        lines.append("")
        interrupted = sum(row["on_interrupted"] for row in rows)
        if interrupted:
            lines += [f"Verdicts on interrupted trials, not scored: {interrupted}.", ""]
        same = [row for row in data["camera_same_verdict"] if (row["experiment"], row["kind"]) == (experiment, kind)]
        if same:
            lines += ["Same verdict on the original and the relit picture, over done placements with a verdict on "
                      "both:", ""]
            lines += table(["Source", "Same verdict", "True rate could be"],
                           [[row["source"], of(row["same_verdict"]), range_text(row["same_verdict"])]
                            for row in same])
            lines.append("")
        days = [row for row in data["camera_by_day"] if (row["experiment"], row["kind"]) == (experiment, kind)]
        if days:
            lines += ["Per day:", ""]
            lines += table(["Source", "Capture", "Day", "False releases", "True rate could be", "Good reads blocked",
                            "True rate could be"],
                           [[row["source"], row["capture"], row["day"], of(row["false_releases"]),
                             range_text(row["false_releases"]), of(row["good_reads_blocked"]),
                             range_text(row["good_reads_blocked"])] for row in days])
            lines.append("")
    return lines


def setup_lines(data):
    """Return the setup time table, or a line saying there is none."""
    lines = ["### Setup time, apart from the per-read time", ""]
    if not data["setup_time"]:
        return lines + ["No setup time recorded yet.", ""]
    lines += table(["Activity", "Arm", "Entries", "Minutes"],
                   [[row["activity"], row["arm"], row["entries"], f"{row['minutes']:.1f}"]
                    for row in data["setup_time"]])
    return lines + [""]


def time_lines(data):
    """Return question 3: hands-on minutes per usable read, then setup time."""
    lines = ["## 3. How much hands-on time does a usable read cost?", ""]
    if data["operator_time"]:
        lines += ["Over the done and interrupted attempts, with the reset before each and any rescue. Minutes per",
                  "usable read divide all those minutes by the usable reads.", ""]
        lines += table(["Experiment", "Arm", "Attempts with time", "Hands-on minutes", "Interventions",
                        "Attempts with 1 or more", "Usable reads", "Minutes per usable read"],
                       [[row["experiment"], row["arm"], row["attempts_with_time"], f"{row['hands_on_min']:.1f}",
                         row["interventions"], row["attempts_with_interventions"], row["usable_reads"],
                         f"{row['hands_on_min']:.1f} min, 0 usable reads" if row["min_per_usable_read"] is None
                         else f"{row['min_per_usable_read']:.1f}"] for row in data["operator_time"]])
    else:
        lines.append("No hands-on time recorded yet.")
    return lines + [""] + setup_lines(data)


def paired_lines(data):
    """Return the paired table, dream1_demos_50 against dream1_demos_0 on the same pair, simulation then bench."""
    begun = {(row["experiment"], row["arm"]) for row in data["status"] if started(row)}
    lines = ["## 4. 50 demonstrations against 0 on the same layout or start", ""]
    for experiment, title in (("teaching_sim", "In simulation"), ("hardware", "On the bench")):
        lines += [f"### {title}", ""]
        rows = [row for row in data["paired"] if row["experiment"] == experiment]
        if any((experiment, arm) in begun for arm in ("dream1_demos_0", "dream1_demos_50")):
            lines += table(["Outcome", "Pairs", "Both pass", "Only 50", "Only 0", "Neither", "Incomplete"],
                           [[row["outcome"], row["pairs"], row["both_pass"], row["only_50"], row["only_0"],
                             row["neither"], row["incomplete"]] for row in rows])
        else:
            lines.append("No pair has been run yet.")
        lines.append("")
    return lines


def not_done_lines(data):
    """Return the list of unverified, interrupted and excluded trials with their reasons, when there are any."""
    if not data["not_done"]:
        return []
    lines = ["## Trials not done, with their reasons", ""]
    lines += [f"- `{row['trial_id']}` {row['status']}: {row['reason']}" for row in data["not_done"]]
    return lines + [""]


def caveat_lines(data):
    """Return the caveats, printed under every report."""
    lines = ["## Caveats", ""]
    for caveat in data["caveats"]:
        lines += textwrap.wrap(caveat, 105, initial_indent="- ", subsequent_indent="  ")
    return lines


def render(data):
    """Return the report as Markdown text, from the dict score() returns."""
    lines = head_lines(data)
    if not any(started(row) for row in data["status"]):
        lines += empty_lines(data)
    else:
        lines += (status_lines(data) + reader_lines(data) + camera_lines(data) + time_lines(data)
                  + paired_lines(data) + not_done_lines(data))
    return "\n".join(lines + caveat_lines(data)) + "\n"
