"""Checks for handoff_study: the planned design, the 3 sheets, the scorer and the command line. Standard library
only: no simulator, no model, no network. Every made-up result row lives in this file or in a temp folder.

Run: python -m unittest -v tests.test_handoff_study   (from the project folder; a few seconds)
"""

import contextlib
import csv
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from handoff_study import design as d  # noqa: E402
from handoff_study import score as s  # noqa: E402
from handoff_study import study_id  # noqa: E402
from handoff_study.__main__ import main, planned_files  # noqa: E402

PACKAGE = REPO / "handoff_study"
SHEETS = ("trials.csv", "verdicts.csv", "setup_time.csv")


def run(*argv):
    """Run the command line in this process. @return (exit code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main([str(arg) for arg in argv])
    return code, out.getvalue(), err.getvalue()


def bench(read, interventions=0, seconds=60, fault="", stage=""):
    """A done bench row's result cells."""
    return {"status": "done", "date": "2026-12-01", "operator": "op1", "first_read": read, "read_fault": fault,
            "interventions": str(interventions), "hands_on_s": str(seconds), "first_failed_stage": stage}


def sim(placement, seated="", stage=""):
    """A done simulated row's result cells."""
    return {"status": "done", "date": "2026-12-01", "operator": "op1", "placement_pass": placement,
            "seated_pass": seated, "first_failed_stage": stage}


def stopped(status, reason, **cells):
    """An unverified, interrupted or excluded row's result cells."""
    found = {"status": status, "reason": reason}
    if status != "excluded":
        found.update(date="2026-12-01", operator="op1")
    found.update(cells)
    return found


def said(trial_id, verdict, source="marker_rule", capture="original"):
    """A verdicts.csv row."""
    return {"trial_id": trial_id, "source": source, "capture": capture, "verdict": verdict, "score": "",
            "model_id": "rule-0.1", "notes": ""}


## A small made-up sheet. The expected answers in the tests below are worked out by hand from it.
FILLED = {
    # camera, day 1 and day 2
    "C-D1-L1-N": bench("valid", 0, 120),                        # usable
    "C-D1-L1-C": bench("invalid", 0, 150, "reversed"),          # failure
    "C-D1-L2-N": bench("valid", 1, 300),                        # valid with help, so a failure
    "C-D1-L2-C": stopped("unverified", "reference read missing"),
    "C-D1-L3-N": bench("valid", 0, 60),                         # usable
    "C-D1-L3-C": stopped("interrupted", "reader out of service", interventions="2", hands_on_s="90"),
    "C-D2-L1-N": bench("invalid", 0, 120, "no_load", "load"),   # failure
    "C-D2-L1-C": bench("valid", 0, 120),                        # usable
    # hardware
    "H-000-S01": bench("invalid", 1, 240, "no_load"),
    "H-000-S02": stopped("interrupted", "power cut", interventions="0", hands_on_s="60"),
    "H-050-S01": bench("valid", 0, 180),
    "H-050-S02": bench("valid", 1, 240),
    "M-S01": bench("valid", 0, 120),
    # teaching in simulation
    "T-000-42000": sim("0", stage="over_tray"), "T-050-42000": sim("1", "1"),
    "T-000-42001": sim("1", "0"), "T-050-42001": sim("1", "1"),
    "T-000-42002": sim("0", stage="over_tray"), "T-050-42002": sim("0", stage="seated"),
    "T-050-42003": stopped("excluded", "layout file damaged"),
    "T-000-42004": stopped("interrupted", "simulator crash"),
    "T-000-42005": sim("1"), "T-050-42005": sim("0", stage="lifted"),
    "T-005-42000": sim("1"),
}
VERDICTS = [
    said("C-D1-L1-N", "release"), said("C-D1-L1-C", "release"), said("C-D1-L2-N", "hold"),
    said("C-D1-L2-C", "hold"), said("C-D1-L3-N", "hold"), said("C-D1-L3-C", "none"),
    said("C-D2-L1-N", "hold"), said("C-D2-L1-C", "release"),
    said("C-D1-L1-N", "none", "lfm3_top", "relit"), said("C-D1-L1-C", "hold", "lfm3_top", "relit"),
    said("C-D2-L1-N", "release", "lfm3_top", "relit"),
    said("C-D1-L1-N", "release", "my_rule_v2"),
]
SETUP = [
    {"date": "2026-12-01", "activity": "calibration", "minutes": "30", "arm": "", "notes": ""},
    {"date": "2026-12-01", "activity": "calibration", "minutes": "15.5", "arm": "", "notes": ""},
    {"date": "2026-12-02", "activity": "teaching", "minutes": "45", "arm": "dream1_demos_50", "notes": ""},
]


def trials(filled=FILLED):
    """The planned rows with the given result cells filled in."""
    rows = d.trials()
    for row in rows:
        row.update(filled.get(row["trial_id"], {}))
    return rows


def only(rows, **keys):
    """The single row whose cells match keys."""
    [found] = [row for row in rows if all(row[k] == v for k, v in keys.items())]
    return found


def count(k, n):
    """A count as the scorer gives it."""
    return s.count(k, n)


class Design(unittest.TestCase):
    def test_counts(self):
        rows = d.trials()
        found = Counter((row["experiment"], row["arm"]) for row in rows)
        self.assertEqual(sum(n for (e, _), n in found.items() if e == "camera"), 48)
        self.assertEqual(sum(n for (e, _), n in found.items() if e == "teaching_sim"), 120)
        self.assertEqual(found[("hardware", "dream1_demos_0")] + found[("hardware", "dream1_demos_50")], 24)
        self.assertEqual(found[("hardware", "manual")], 12)
        self.assertEqual(len(rows), 204)
        self.assertEqual(set(found), set(d.ARMS))
        self.assertEqual(len({row["trial_id"] for row in rows}), 204)
        self.assertTrue(all(row["status"] == "planned" for row in rows))
        self.assertTrue(all(not row[c] for row in rows for c in d.RESULT_COLUMNS[1:]))

    def test_camera_days_are_balanced(self):
        rows = [row for row in d.trials() if row["experiment"] == "camera"]
        for day in ("1", "2", "3"):
            today = [row for row in rows if row["day"] == day]
            self.assertEqual([row["order"] for row in today], [str(n) for n in range(1, 17)])
            self.assertEqual([row["layout"] for row in today][::2], [f"D{day}-L{n}" for n in range(1, 9)])
            combos = Counter()
            for layout in {row["layout"] for row in today}:
                first, second = sorted((r for r in today if r["layout"] == layout), key=lambda r: int(r["order"]))
                self.assertEqual({first["arm"], second["arm"]}, {"hand_nominal", "hand_challenge"})
                challenge = first if first["arm"] == "hand_challenge" else second
                self.assertEqual((first["pair"], second["pair"]), (layout, layout))
                combos[(challenge["challenge"], "challenge" if first is challenge else "nominal")] += 1
            self.assertEqual(combos, Counter({combo: 2 for combo in d.COMBINATIONS}))
        self.assertEqual({row["challenge"] for row in rows if row["arm"] == "hand_nominal"}, {"none"})
        self.assertEqual(only(rows, trial_id="C-D1-L3-N")["layout"], "D1-L3")

    def test_hardware_order_is_split_6_and_6(self):
        rows = d.hardware_trials()
        self.assertEqual([row["order"] for row in rows], [str(n) for n in range(1, 25)])
        self.assertEqual([row["layout"] for row in rows][::2], list(d.STARTS))
        firsts = Counter(row["arm"] for row in rows[::2])
        self.assertEqual(firsts, Counter({"dream1_demos_0": 6, "dream1_demos_50": 6}))
        manual = d.manual_trials()
        self.assertEqual([(row["trial_id"], row["order"]) for row in manual],
                         [(f"M-S{n:02d}", str(n)) for n in range(1, 13)])
        self.assertEqual(only(rows, trial_id="H-050-S01")["pair"], "S01")
        self.assertTrue(all(row["day"] == "" and row["challenge"] == "none" for row in rows + manual))

    def test_teaching_order_and_ids(self):
        rows = d.teaching_trials()
        self.assertEqual([row["order"] for row in rows], [str(n) for n in range(1, 121)])
        self.assertEqual([row["trial_id"] for row in rows[:5]],
                         ["T-000-42000", "T-005-42000", "T-020-42000", "T-050-42000", "T-000-42001"])
        self.assertEqual(sorted({row["layout"] for row in rows}), [str(n) for n in range(42000, 42030)])
        self.assertTrue(all(row["pair"] == row["layout"] and row["day"] == "" for row in rows))

    def test_draw_uses_sha256_not_random(self):
        items = ["S01", "S02", "S03"]
        key = [hashlib.sha256(f"handoff-study-1|hardware|{item}".encode()).hexdigest() for item in items]
        self.assertEqual(d.rank("hardware", items), [item for _, item in sorted(zip(key, items))])
        self.assertNotIn("import random", (PACKAGE / "design.py").read_text())

    def test_ids(self):
        digest = hashlib.sha256()
        for path in sorted(PACKAGE.glob("*.py")):
            digest.update(path.name.encode())
            digest.update(path.read_bytes())
        self.assertEqual(study_id(), digest.hexdigest()[:12])
        with open(PACKAGE / "trials.csv", newline="") as f:
            rows = list(csv.reader(f))
        text = "".join(",".join(row[:8]) + "\n" for row in rows)
        self.assertEqual(d.design_id(), hashlib.sha256(text.encode()).hexdigest()[:12])


class Sheets(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_sheet_is_the_same_when_built_twice(self):
        self.assertEqual(run("sheet", "--dir", self.tmp / "a")[0], 0)
        self.assertEqual(run("sheet", "--dir", self.tmp / "b")[0], 0)
        for name in SHEETS:
            self.assertEqual((self.tmp / "a" / name).read_bytes(), (self.tmp / "b" / name).read_bytes())
        self.assertEqual(planned_files(), planned_files())

    def test_committed_sheets_match_the_design(self):
        ## Byte for byte while a sheet holds no result. Once the bench fills it, only its design columns are checked,
        ## so a filled sheet, whatever its line ends, does not fail this test.
        for key, name in s.FILES.items():
            if s.holds_results(key, s.read_csv(PACKAGE / name)[1]) is None:
                self.assertEqual((PACKAGE / name).read_bytes(), planned_files()[name].encode(), name)
        code, out, _ = run("sheet", "--check")
        self.assertEqual(code, 0, out)
        self.assertIn("204 trials", out)

    def test_check_finds_a_changed_design_cell(self):
        run("sheet", "--dir", self.tmp)
        path = self.tmp / "trials.csv"
        path.write_text(path.read_text().replace("C-D1-L3-N,camera,hand_nominal,1,", "C-D1-L3-N,camera,manual,1,"))
        code, out, _ = run("sheet", "--check", "--dir", self.tmp)
        self.assertEqual(code, 1)
        self.assertIn("(C-D1-L3-N): arm is 'manual', the design says 'hand_nominal'", out)
        self.assertEqual(run("sheet", "--check", "--dir", self.tmp / "nothing")[0], 1)

    def test_sheet_refuses_to_overwrite_results(self):
        run("sheet", "--dir", self.tmp)
        self.assertEqual(run("sheet", "--dir", self.tmp)[0], 0)  # all planned: rewriting is fine
        path = self.tmp / "trials.csv"
        rows = trials({"C-D1-L1-N": {"notes": "x"}})
        path.write_text(d.csv_text(d.TRIAL_COLUMNS, rows))
        before = path.read_bytes()
        code, out, _ = run("sheet", "--dir", self.tmp)
        self.assertEqual(code, 1)
        self.assertIn("trials.csv holds results", out)
        self.assertEqual(path.read_bytes(), before)
        run("sheet", "--dir", self.tmp / "v")
        (self.tmp / "v" / "verdicts.csv").write_text(d.csv_text(d.VERDICT_COLUMNS, [said("C-D1-L1-N", "hold")]))
        code, out, _ = run("sheet", "--dir", self.tmp / "v")
        self.assertEqual(code, 1)
        self.assertIn("verdicts.csv holds results", out)
        run("sheet", "--dir", self.tmp / "t")
        (self.tmp / "t" / "setup_time.csv").write_text(d.csv_text(d.SETUP_COLUMNS, SETUP[:1]))
        code, out, _ = run("sheet", "--dir", self.tmp / "t")
        self.assertEqual(code, 1)
        self.assertIn("setup_time.csv holds results (row 2)", out)


class Range(unittest.TestCase):
    def test_check_values(self):
        values = [(0, 3, "0", "71"), (0, 5, "0", "52"), (5, 5, "48", "100"), (10, 20, "27", "73"),
                  (20, 20, "83", "100"), (10, 192, "3", "9"), (65, 192, "27", "41"), (25, 192, "9", "19")]
        for k, n, low, high in values:
            with self.subTest(k=k, n=n):
                found = s.exact_range(k, n)
                self.assertEqual((f"{found[0] * 100:.0f}", f"{found[1] * 100:.0f}"), (low, high))
                self.assertEqual(s.range_text({"k": k, "n": n}), f"{low} to {high}%")

    def test_json_ranges(self):
        ## Written by hand (they agree with scipy's beta quantiles to 3 places).
        self.assertEqual(s.count(1, 3), {"k": 1, "n": 3, "range_95": [0.008, 0.906]})
        self.assertEqual(s.count(10, 192)["range_95"], [0.025, 0.094])
        self.assertEqual(s.count(0, 3)["range_95"], [0.0, 0.708])
        self.assertEqual(s.count(1, 2)["range_95"], [0.013, 0.987])

    def test_edges(self):
        self.assertIsNone(s.exact_range(0, 0))
        self.assertEqual(s.range_text({"k": 0, "n": 0}), "n/a")
        self.assertEqual(s.count(0, 0), {"k": 0, "n": 0, "range_95": None})
        low, high = s.exact_range(3, 10)
        mirror = s.exact_range(7, 10)
        self.assertAlmostEqual(low, 1 - mirror[1], places=12)
        self.assertAlmostEqual(high, 1 - mirror[0], places=12)


class Metrics(unittest.TestCase):
    rows = trials()

    def test_sheet_is_valid(self):
        self.assertEqual(s.trial_problems(list(d.TRIAL_COLUMNS), self.rows), [])
        self.assertEqual(s.verdict_problems(list(d.VERDICT_COLUMNS), VERDICTS, self.rows), [])
        self.assertEqual(s.setup_problems(list(d.SETUP_COLUMNS), SETUP), [])

    def test_reader(self):
        table = {row["arm"]: row for row in s.reader_table(self.rows) if row["experiment"] == "camera"}
        self.assertEqual(table["hand_nominal"], {
            "experiment": "camera", "arm": "hand_nominal", "done": 4, "usable": count(2, 4), "valid_with_help": 1,
            "invalid": 1, "read_faults": {"no_load": 1}, "first_failed_stages": {"load": 1, "not recorded": 1}})
        self.assertEqual(table["hand_challenge"], {
            "experiment": "camera", "arm": "hand_challenge", "done": 2, "usable": count(1, 2), "valid_with_help": 0,
            "invalid": 1, "read_faults": {"reversed": 1}, "first_failed_stages": {"not recorded": 1}})
        status = only(s.status_table(self.rows), experiment="camera", arm="hand_challenge")
        self.assertEqual(status, {"experiment": "camera", "arm": "hand_challenge", "where": "bench", "assigned": 24,
                                  "planned": 20, "done": 2, "unverified": 1, "interrupted": 1, "excluded": 0})
        hardware = only(s.reader_table(self.rows), experiment="hardware", arm="dream1_demos_50")
        self.assertEqual((hardware["usable"], hardware["valid_with_help"]), (count(1, 2), 1))
        self.assertEqual(only(s.reader_table(self.rows), experiment="hardware", arm="dream1_demos_0"), {
            "experiment": "hardware", "arm": "dream1_demos_0", "done": 1, "usable": count(0, 1), "valid_with_help": 0,
            "invalid": 1, "read_faults": {"no_load": 1}, "first_failed_stages": {"not recorded": 1}})
        self.assertEqual(only(s.reader_table(self.rows), experiment="hardware", arm="manual"), {
            "experiment": "hardware", "arm": "manual", "done": 1, "usable": count(1, 1), "valid_with_help": 0,
            "invalid": 0, "read_faults": {}, "first_failed_stages": {}})
        self.assertEqual(only(s.status_table(self.rows), experiment="hardware", arm="dream1_demos_0"),
                         {"experiment": "hardware", "arm": "dream1_demos_0", "where": "bench", "assigned": 12,
                          "planned": 10, "done": 1, "unverified": 0, "interrupted": 1, "excluded": 0})
        self.assertEqual(only(s.status_table(self.rows), experiment="teaching_sim", arm="dream1_demos_50"),
                         {"experiment": "teaching_sim", "arm": "dream1_demos_50", "where": "simulation",
                          "assigned": 30, "planned": 25, "done": 4, "unverified": 0, "interrupted": 0, "excluded": 1})

    def test_usable_and_failure(self):
        by = {row["trial_id"]: row for row in self.rows}
        self.assertEqual([s.is_usable(by[t]) for t in ("C-D1-L1-N", "C-D1-L2-N", "C-D1-L1-C", "C-D1-L2-C")],
                         [True, False, False, False])
        self.assertEqual([s.is_failure(by[t]) for t in ("C-D1-L1-N", "C-D1-L2-N", "C-D1-L1-C", "C-D1-L3-C")],
                         [False, True, True, False])  # an interrupted trial is not a failure

    def test_simulation(self):
        table = {row["arm"]: row for row in s.simulation_table(self.rows)}
        self.assertEqual(table["dream1_demos_0"], {
            "experiment": "teaching_sim", "arm": "dream1_demos_0", "done": 4, "placement_pass": count(2, 4),
            "seated_pass": count(0, 1), "first_failed_stages": {"over_tray": 2, "not recorded": 1}})
        self.assertEqual(table["dream1_demos_50"], {
            "experiment": "teaching_sim", "arm": "dream1_demos_50", "done": 4, "placement_pass": count(2, 4),
            "seated_pass": count(2, 2), "first_failed_stages": {"lifted": 1, "seated": 1}})
        self.assertEqual(table["dream1_demos_5"]["seated_pass"], {"k": 0, "n": 0, "range_95": None})
        self.assertEqual(table["dream1_demos_20"]["done"], 0)

    def test_camera(self):
        table = s.camera_table(self.rows, VERDICTS)
        self.assertEqual([(r["kind"], r["source"], r["capture"]) for r in table],
                         [("rule", "marker_rule", "original"), ("zero_shot", "lfm3_top", "relit"),
                          ("other", "my_rule_v2", "original")])
        self.assertEqual(table[0], {
            "experiment": "camera", "kind": "rule", "source": "marker_rule", "capture": "original",
            "with_verdict": 6, "failures": 3, "false_releases": count(1, 3), "usable_reads": 3,
            "good_reads_blocked": count(1, 3), "releases": 3, "holds": 3, "no_decision": 0,
            "decision_coverage": count(6, 6), "missing": 0, "pairs_right": count(1, 2), "on_unverified": 1,
            "on_interrupted": 1})
        self.assertEqual(table[1], {
            "experiment": "camera", "kind": "zero_shot", "source": "lfm3_top", "capture": "relit",
            "with_verdict": 3, "failures": 2, "false_releases": count(1, 2), "usable_reads": 1,
            "good_reads_blocked": count(0, 1), "releases": 1, "holds": 1, "no_decision": 1,
            "decision_coverage": count(2, 3), "missing": 3, "pairs_right": count(0, 1), "on_unverified": 0,
            "on_interrupted": 0})

    def test_camera_on_hardware(self):
        ## H-000-S01 failed (hold: right), H-050-S01 usable (release: right), H-050-S02 valid with help, so a failure
        ## (release: a false release). M-S01 is done with no verdict: missing. A hardware start is not a pair: n/a.
        extra = [said("H-000-S01", "hold"), said("H-050-S01", "release"), said("H-050-S02", "release")]
        [row] = [r for r in s.camera_table(self.rows, VERDICTS + extra) if r["experiment"] == "hardware"]
        self.assertEqual(row, {
            "experiment": "hardware", "kind": "rule", "source": "marker_rule", "capture": "original",
            "with_verdict": 3, "failures": 2, "false_releases": count(1, 2), "usable_reads": 1,
            "good_reads_blocked": count(0, 1), "releases": 2, "holds": 1, "no_decision": 0,
            "decision_coverage": count(3, 3), "missing": 1, "pairs_right": None, "on_unverified": 0,
            "on_interrupted": 0})
        text = s.render(s.score(self.rows, VERDICTS + extra, []))
        self.assertIn("| marker_rule | original | 3 | 1 of 2 | 1 to 99% | 0 of 1 | 0 to 98% | 2, 1, 0 | 3 of 3 | 1 | "
                      "n/a | 0 |", text)
        self.assertEqual([r for r in s.camera_day_table(self.rows, VERDICTS + extra) if r["experiment"] == "hardware"],
                         [])

    def test_same_verdict_on_original_and_relit(self):
        ## lfm3_top relit: C-D1-L1-N none, C-D1-L1-C hold, C-D2-L1-N release. Original: C-D1-L1-N none (same),
        ## C-D1-L1-C release (not the same). C-D1-L2-C has hold on the original and release on the relit picture,
        ## but it is unverified, so not done: it is left out, or the count would be 1 of 3. 1 of 2.
        extra = [said("C-D1-L1-N", "none", "lfm3_top"), said("C-D1-L1-C", "release", "lfm3_top"),
                 said("C-D1-L2-C", "hold", "lfm3_top"), said("C-D1-L2-C", "release", "lfm3_top", "relit")]
        self.assertEqual(s.same_verdict_table(self.rows, VERDICTS + extra),
                         [{"experiment": "camera", "kind": "zero_shot", "source": "lfm3_top",
                           "same_verdict": count(1, 2)}])
        self.assertEqual(s.same_verdict_table(self.rows, VERDICTS), [])
        text = s.render(s.score(self.rows, VERDICTS + extra, []))
        self.assertIn("| lfm3_top | 1 of 2 | 1 to 99% |", text)

    def test_original_and_relit_are_not_pooled(self):
        both = VERDICTS + [said("C-D1-L1-N", "release", "lfm3_top", "original")]
        table = [r for r in s.camera_table(self.rows, both) if r["source"] == "lfm3_top"]
        self.assertEqual([(r["capture"], r["with_verdict"]) for r in table], [("original", 1), ("relit", 3)])

    def test_camera_per_day(self):
        days = [(r["source"], r["capture"], r["day"], r["failures"], r["false_releases"]["k"], r["usable_reads"],
                 r["good_reads_blocked"]["k"]) for r in s.camera_day_table(self.rows, VERDICTS)]
        self.assertEqual(days, [("marker_rule", "original", 1, 2, 1, 2, 1), ("marker_rule", "original", 2, 1, 0, 1, 0),
                                ("lfm3_top", "relit", 1, 1, 0, 1, 0), ("lfm3_top", "relit", 2, 1, 1, 0, 0),
                                ("my_rule_v2", "original", 1, 0, 0, 1, 0)])

    def test_operator_time(self):
        table = {(r["experiment"], r["arm"]): r for r in s.time_table(self.rows)}
        self.assertEqual(sorted(table), [("camera", "hand_challenge"), ("camera", "hand_nominal"),
                                         ("hardware", "dream1_demos_0"), ("hardware", "dream1_demos_50"),
                                         ("hardware", "manual")])
        self.assertEqual(table[("camera", "hand_nominal")], {
            "experiment": "camera", "arm": "hand_nominal", "attempts_with_time": 4, "hands_on_s": 600.0,
            "hands_on_min": 10.0, "interventions": 1, "attempts_with_interventions": 1, "usable_reads": 2,
            "min_per_usable_read": 5.0})
        ## The interrupted attempt counts its time and its 2 interventions; the unverified placement is not an attempt.
        self.assertEqual(table[("camera", "hand_challenge")], {
            "experiment": "camera", "arm": "hand_challenge", "attempts_with_time": 3, "hands_on_s": 360.0,
            "hands_on_min": 6.0, "interventions": 2, "attempts_with_interventions": 1, "usable_reads": 1,
            "min_per_usable_read": 6.0})
        ## 0 usable reads: the minutes are reported, and there is no division.
        self.assertEqual(table[("hardware", "dream1_demos_0")], {
            "experiment": "hardware", "arm": "dream1_demos_0", "attempts_with_time": 2, "hands_on_s": 300.0,
            "hands_on_min": 5.0, "interventions": 1, "attempts_with_interventions": 1, "usable_reads": 0,
            "min_per_usable_read": None})
        self.assertEqual(table[("hardware", "dream1_demos_50")]["min_per_usable_read"], 7.0)
        self.assertEqual(table[("hardware", "manual")]["min_per_usable_read"], 2.0)
        self.assertEqual(s.time_table(d.trials()), [])

    def test_setup_time(self):
        self.assertEqual(s.setup_table(SETUP), [
            {"activity": "teaching", "arm": "dream1_demos_50", "entries": 1, "minutes": 45.0},
            {"activity": "calibration", "arm": "all", "entries": 2, "minutes": 45.5}])
        self.assertEqual(s.setup_table([]), [])
        ## Halves round up, as a person adding up by hand would: 30 + 12.25 = 42.25 -> 42.3, and 5.55 -> 5.6.
        rows = [dict(SETUP[0], minutes="30"), dict(SETUP[0], minutes="12.25"),
                dict(SETUP[0], activity="other", minutes="5.55")]
        self.assertEqual([row["minutes"] for row in s.setup_table(rows)], [42.3, 5.6])
        self.assertEqual(s.time_row([dict(only(self.rows, trial_id="M-S01"), hands_on_s="33")])["hands_on_min"], 0.6)

    def test_paired(self):
        placement, seated, usable = s.paired_table(self.rows)
        self.assertEqual(placement, {"experiment": "teaching_sim", "outcome": "placement_pass", "pairs": 30,
                                     "both_pass": 1, "only_50": 1, "only_0": 1, "neither": 1, "incomplete": 26})
        self.assertEqual(seated, {"experiment": "teaching_sim", "outcome": "seated_pass", "pairs": 30,
                                  "both_pass": 0, "only_50": 1, "only_0": 0, "neither": 0, "incomplete": 29})
        self.assertEqual(usable, {"experiment": "hardware", "outcome": "usable", "pairs": 12,
                                  "both_pass": 0, "only_50": 1, "only_0": 0, "neither": 0, "incomplete": 11})

    def test_report(self):
        data = s.score(self.rows, VERDICTS, SETUP)
        self.assertEqual((data["trials_assigned"], data["trials_done"], data["done_on_bench"]), (204, 19, 10))
        self.assertEqual([row["trial_id"] for row in data["not_done"]],
                         ["C-D1-L2-C", "C-D1-L3-C", "T-050-42003", "T-000-42004", "H-000-S02"])
        text = s.render(data)
        self.assertTrue(text.isascii())
        for part in ("| camera | hand_nominal | 2 of 4 | 7 to 93% | 1 | 1 | no_load 1 | load 1, not recorded 1 |",
                     "| marker_rule | original | 6 | 1 of 3 | 1 to 91% | 1 of 3 | 1 to 91% | 3, 3, 0 | 6 of 6 | 0 | "
                     "1 of 2 | 1 |",
                     "| hardware | dream1_demos_0 | 2 | 5.0 | 1 | 1 | 0 | 5.0 min, 0 usable reads |",
                     "| placement_pass | 30 | 1 | 1 | 1 | 1 | 26 |",
                     "| calibration | all | 2 | 45.5 |",
                     "| dream1_demos_5 | 1 of 1 | 3 to 100% | not recorded | n/a | none |",
                     "### Experiment camera, sources of kind zero_shot",
                     "- `C-D1-L2-C` unverified: reference read missing",
                     "Verdicts on interrupted trials, not scored: 1.",
                     "It treats trials as independent.",
                     "95% range for that k of n"):
            self.assertIn(part, text)
        self.assertNotIn("0 trials have been run", text)

    def test_empty_report(self):
        text = s.render(s.score(d.trials(), [], []))
        self.assertIn("**0 trials have been run.**", text)
        self.assertIn("Trials assigned: 204. Done: 0.", text)
        self.assertNotIn("True rate could be", text)
        self.assertIn("The 2 placements of a camera pair share a layout and a day", text)
        self.assertLess(len(text.splitlines()), 40)


class Validation(unittest.TestCase):
    def trial_problems(self, filled, header=d.TRIAL_COLUMNS, rows=None):
        return s.trial_problems(list(header), trials(filled) if rows is None else rows)

    def assertFlags(self, problems, *parts):
        for part in parts:
            self.assertTrue(any(part in p for p in problems), f"{part!r} not in {problems}")

    def test_columns(self):
        self.assertFlags(self.trial_problems({}, d.TRIAL_COLUMNS[:-1]), "trials.csv: missing column notes")
        rows = [dict(row, extra="") for row in trials({})]
        self.assertFlags(self.trial_problems({}, d.TRIAL_COLUMNS + ("extra",), rows), "unknown column 'extra'")
        self.assertFlags(self.trial_problems({}, d.TRIAL_COLUMNS + ("notes",)), "trials.csv: column notes is repeated")
        self.assertFlags(s.verdict_problems(["trial_id"], [], []), "verdicts.csv: missing column source")
        self.assertFlags(s.setup_problems([], []), "setup_time.csv: the file is empty")

    def test_duplicate_trial_id(self):
        rows = trials({})
        rows.append(dict(rows[0]))
        self.assertFlags(self.trial_problems({}, rows=rows), f"row 206 ({rows[0]['trial_id']}): duplicate trial_id, "
                                                             "first on row 2")

    def test_design_columns(self):
        rows = trials({})
        only(rows, trial_id="C-D1-L3-N")["order"] = "16"
        only(rows, trial_id="T-000-42000")["trial_id"] = "T-000-49999"
        del rows[-1]
        self.assertFlags(self.trial_problems({}, rows=rows), "(C-D1-L3-N): order is '16', the design says '5'",
                         "(T-000-49999): trial_id is not in the design",
                         "trial T-000-42000 of the design is missing", "trial M-S12 of the design is missing")

    def test_vocabulary(self):
        cases = {"status": ("finished", "status 'finished' must be planned, done, unverified, interrupted or excluded"),
                 "first_read": ("ok", "first_read 'ok' must be valid or invalid"),
                 "read_fault": ("jam", "read_fault 'jam' must be no_load, alarm"),
                 "interventions": ("1.5", "interventions '1.5' is not a whole number"),
                 "hands_on_s": ("-5", "hands_on_s '-5' is not a number of seconds"),
                 "date": ("01/12/2026", "date '01/12/2026' is not a date written YYYY-MM-DD"),
                 "operator": ("tech", "operator 'tech' is not a short code of 1 to 6 lower-case letters, then 1 to 3"),
                 "first_failed_stage": ("Over tray", "first_failed_stage 'Over tray' is not a lower-case token")}
        for column, (value, part) in cases.items():
            with self.subTest(column=column):
                cells = dict(bench("invalid", 0, 60, "alarm"), **{column: value})
                self.assertFlags(self.trial_problems({"C-D1-L1-N": cells}), f"(C-D1-L1-N): {part}")
        self.assertFlags(self.trial_problems({"C-D1-L1-N": dict(bench("valid"), date="2026-02-30")}),
                         "date '2026-02-30' is not a real date")
        self.assertFlags(self.trial_problems({"T-000-42000": sim("yes")}),
                         "(T-000-42000): placement_pass 'yes' must be 1 or 0")
        self.assertFlags(self.trial_problems({"C-D1-L1-N": {"status": ""}}), "status is blank")

    def test_result_on_a_planned_row(self):
        self.assertFlags(self.trial_problems({"C-D1-L1-N": {"notes": "moved"}}),
                         "(C-D1-L1-N): notes is filled on a planned row")

    def test_required_cells(self):
        cases = {"C-D1-L1-N": (dict(bench("valid"), first_read=""), "status done needs first_read"),
                 "C-D1-L1-C": (bench("invalid"), "status done needs read_fault"),
                 "C-D1-L2-N": (dict(bench("valid"), hands_on_s=""), "status done needs hands_on_s"),
                 "C-D1-L2-C": (stopped("unverified", ""), "status unverified needs reason"),
                 "H-000-S01": (stopped("interrupted", "power cut"), "status interrupted needs hands_on_s"),
                 "T-000-42000": (sim(""), "status done needs placement_pass"),
                 "T-000-42001": (stopped("excluded", ""), "status excluded needs reason"),
                 "M-S01": (dict(bench("valid"), operator=""), "status done needs operator"),
                 "T-020-42000": (stopped("excluded", "  "), "status excluded needs reason"),
                 "H-050-S03": (dict(bench("valid"), hands_on_s=" "), "status done needs hands_on_s")}
        for trial_id, (cells, part) in cases.items():
            with self.subTest(trial_id=trial_id):
                self.assertFlags(self.trial_problems({trial_id: cells}), f"({trial_id}): {part}")

    def test_cells_in_the_wrong_kind_of_row(self):
        self.assertFlags(self.trial_problems({"T-000-42000": dict(sim("1"), first_read="valid")}),
                         "(T-000-42000): first_read on a simulation row")
        self.assertFlags(self.trial_problems({"C-D1-L1-N": dict(bench("valid"), placement_pass="1")}),
                         "(C-D1-L1-N): placement_pass on a physical row")
        self.assertFlags(self.trial_problems({"H-000-S01": stopped("unverified", "no reference")}),
                         "(H-000-S01): status unverified is for the camera study only")
        self.assertFlags(self.trial_problems({"C-D1-L1-N": dict(bench("valid"), read_fault="alarm")}),
                         "(C-D1-L1-N): read_fault is only for an invalid first_read")
        self.assertFlags(self.trial_problems({"C-D1-L2-C": stopped("unverified", "x", first_read="valid")}),
                         "(C-D1-L2-C): first_read is not used on a row with status unverified")

    def test_outcomes_that_contradict_each_other(self):
        self.assertFlags(self.trial_problems({"T-000-42000": sim("0", "1", "over_tray")}),
                         "(T-000-42000): seated_pass 1 needs placement_pass 1")
        self.assertFlags(self.trial_problems({"C-D1-L1-N": bench("valid", 0, 60, stage="load")}),
                         "(C-D1-L1-N): first_failed_stage is filled on a usable read")
        self.assertFlags(self.trial_problems({"T-000-42000": sim("1", "", "lifted")}),
                         "(T-000-42000): first_failed_stage is filled on a row that passed")
        ## A stage is allowed on any failure: valid with help, or placement passed and seating failed.
        self.assertEqual(self.trial_problems({"C-D1-L1-N": bench("valid", 1, 60, stage="reseat"),
                                              "T-000-42000": sim("1", "0", "seated")}), [])

    def test_non_ascii_text(self):
        self.assertFlags(self.trial_problems({"C-D1-L1-N": dict(bench("valid"), notes="caf" + chr(0xE9))}),
                         "(C-D1-L1-N): notes holds non-ASCII text")
        rows = trials()
        self.assertFlags(s.verdict_problems(list(d.VERDICT_COLUMNS), [dict(VERDICTS[0], notes=chr(0x2192))], rows),
                         "verdicts.csv row 2 (C-D1-L1-N, marker_rule, original): notes holds non-ASCII text")
        self.assertFlags(s.setup_problems(list(d.SETUP_COLUMNS), [dict(SETUP[0], notes="5 " + chr(0xD7) + " 2")]),
                         "setup_time.csv row 2: notes holds non-ASCII text")

    def test_verdicts(self):
        rows = trials()
        cases = [(said("C-D9-L1-N", "hold"), "(C-D9-L1-N, marker_rule, original): verdict for an unknown trial"),
                 (said("C-D3-L1-N", "hold"), "verdict on a trial with status planned"),
                 (said("T-050-42003", "hold"), "verdict on a simulation row"),
                 (said("C-D1-L1-N", "pass", "lfm3_3view"), "verdict 'pass' must be release, hold or none"),
                 (said("C-D1-L1-N", "hold", "lfm3_3view", "dim"), "capture 'dim' must be original or relit"),
                 (said("C-D1-L1-N", "hold", "Marker Rule"), "source 'Marker Rule' is not a lower-case name"),
                 (dict(said("C-D1-L1-N", "hold", "x1"), score="high"), "score 'high' is not a number"),
                 (dict(said("C-D1-L1-N", "hold", "x2"), model_id=""), "model_id is blank")]
        for row, part in cases:
            with self.subTest(part=part):
                self.assertFlags(s.verdict_problems(list(d.VERDICT_COLUMNS), [row], rows), part)
        repeated = [said("C-D1-L1-N", "hold"), said("C-D1-L1-N", "release")]
        self.assertFlags(s.verdict_problems(list(d.VERDICT_COLUMNS), repeated, rows),
                         "verdicts.csv row 3 (C-D1-L1-N, marker_rule, original): duplicate (trial_id, source, "
                         "capture), first on row 2")
        self.assertEqual(s.verdict_problems(list(d.VERDICT_COLUMNS), [dict(VERDICTS[0], score="-0.25")], rows), [])
        excluded = trials(dict(FILLED, **{"C-D3-L1-N": stopped("excluded", "plate cracked before the run")}))
        self.assertFlags(s.verdict_problems(list(d.VERDICT_COLUMNS), [said("C-D3-L1-N", "hold")], excluded),
                         "(C-D3-L1-N, marker_rule, original): verdict on a trial with status excluded")
        self.assertFlags(s.verdict_problems(list(d.VERDICT_COLUMNS), [dict(VERDICTS[0], model_id="  ")], rows),
                         "model_id is blank")

    def test_setup(self):
        cases = [(dict(SETUP[0], activity="training"), "activity 'training' must be teaching, calibration or other"),
                 (dict(SETUP[0], minutes="lots"), "minutes 'lots' is not a number of minutes"),
                 (dict(SETUP[0], date=""), "date '' is not a real date"),
                 (dict(SETUP[0], arm="robot"), "arm 'robot' must be blank or hand_nominal, hand_challenge, "
                                               "dream1_demos_0, dream1_demos_5, dream1_demos_20, dream1_demos_50 or "
                                               "manual")]
        for row, part in cases:
            with self.subTest(part=part):
                self.assertFlags(s.setup_problems(list(d.SETUP_COLUMNS), [row]), f"setup_time.csv row 2: {part}")

    def test_read_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "verdicts.csv"
            path.write_text("trial_id,source,capture,verdict,score,model_id,notes\n"
                            "C-D1-L1-N,marker_rule,original,hold,,r1,,extra\n\n")
            header, rows, problems = s.read_csv(path)
            self.assertEqual(len(rows), 2)
            self.assertFlags(problems, "verdicts.csv row 2: 8 cells, the header has 7", "verdicts.csv row 3: blank row")
            ## A spreadsheet's "CSV UTF-8" starts with a byte order mark: it is dropped. A row of commas (or of
            ## spaces) is a blank row, so it is reported and never counted.
            path.write_bytes(b"\xef\xbb\xbftrial_id,source,capture,verdict,score,model_id,notes\n,,,,,,\n , ,,,,,\n")
            header, rows, problems = s.read_csv(path)
            self.assertEqual(header, list(d.VERDICT_COLUMNS))
            self.assertEqual(problems, ["verdicts.csv row 2: blank row (delete it)",
                                        "verdicts.csv row 3: blank row (delete it)"])
            path.write_bytes(b"\xff\xfe")
            self.assertEqual(s.read_csv(path), (None, [], ["verdicts.csv: not UTF-8 text"]))
            self.assertEqual(s.read_csv(Path(tmp) / "none.csv")[2], ["none.csv: no such file"])


class Scorer(unittest.TestCase):
    def setUp(self):
        ## The planned sheets, not the committed ones, so these tests still pass once the bench fills the sheet.
        self.tmp = Path(tempfile.mkdtemp())
        for name, text in planned_files().items():
            (self.tmp / name).write_text(text)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_committed_results_are_fresh(self):
        for name in SHEETS:
            shutil.copy(PACKAGE / name, self.tmp / name)
        sheets, problems = s.load(PACKAGE)
        self.assertEqual(problems, [])
        data = s.score(sheets["trials"], sheets["verdicts"], sheets["setup"])
        self.assertEqual((PACKAGE / "results.md").read_text(), s.render(data))
        self.assertEqual((PACKAGE / "results.json").read_text(), s.as_json(data))
        code, out, err = run("score", "--write", "--dir", self.tmp)
        self.assertEqual((code, err), (0, "wrote results.md and results.json\n"))
        for name in ("results.md", "results.json"):
            self.assertEqual((self.tmp / name).read_bytes(), (PACKAGE / name).read_bytes())
        self.assertEqual(out, (PACKAGE / "results.md").read_text())

    def test_exit_codes(self):
        code, out, _ = run("score", "--dir", self.tmp)
        self.assertEqual(code, 0)
        self.assertIn("**0 trials have been run.**", out)
        code, out, _ = run("score", "--json", "--dir", self.tmp)
        self.assertEqual((code, json.loads(out)["trials_done"]), (0, 0))
        (self.tmp / "trials.csv").write_text(d.csv_text(d.TRIAL_COLUMNS, trials({"C-D1-L1-N": {"status": "ok"}})))
        (self.tmp / "verdicts.csv").write_text(d.csv_text(d.VERDICT_COLUMNS, [said("C-D9-L9-N", "hold")]))
        code, out, err = run("score", "--write", "--dir", self.tmp)
        self.assertEqual((code, out), (1, ""))
        self.assertIn("trials.csv row 3 (C-D1-L1-N): status 'ok' must be planned", err)
        self.assertIn("verdicts.csv row 2 (C-D9-L9-N, marker_rule, original): verdict for an unknown trial", err)
        self.assertIn("2 problem(s): nothing scored", err)
        self.assertFalse((self.tmp / "results.md").exists())
        planned = planned_files()
        (self.tmp / "trials.csv").write_text(planned["trials.csv"] + "," * (len(d.TRIAL_COLUMNS) - 1) + "\n")
        (self.tmp / "verdicts.csv").write_text(planned["verdicts.csv"])
        code, out, err = run("score", "--dir", self.tmp)
        self.assertEqual((code, out), (1, ""))
        self.assertIn("trials.csv row 206: blank row (delete it)", err)
        (self.tmp / "trials.csv").write_bytes(b"\xef\xbb\xbf" + planned["trials.csv"].encode())
        self.assertEqual(run("score", "--dir", self.tmp)[0], 0)
        self.assertEqual(run("sheet", "--check", "--dir", self.tmp)[0], 0)
        (self.tmp / "setup_time.csv").unlink()
        code, _, err = run("score", "--dir", self.tmp)
        self.assertEqual(code, 1)
        self.assertIn("setup_time.csv: no such file", err)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as stop:
            main(["count"])
        self.assertEqual(stop.exception.code, 2)

    def test_run_as_a_module(self):
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        done = subprocess.run([sys.executable, "-m", "handoff_study", "score"], cwd=REPO, env=env,
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout, (PACKAGE / "results.md").read_text())
        (self.tmp / "trials.csv").write_text("trial_id\n")
        done = subprocess.run([sys.executable, "-m", "handoff_study", "score", "--dir", str(self.tmp)], cwd=REPO,
                              env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 1)
        self.assertIn("trials.csv: missing column experiment", done.stderr)


class Text(unittest.TestCase):
    def test_files_are_ascii(self):
        paths = [p for p in PACKAGE.rglob("*") if p.is_file() and "__pycache__" not in p.parts]
        paths.append(Path(__file__))
        self.assertGreaterEqual(len(paths), 10)
        for path in paths:
            with self.subTest(path=path.name):
                self.assertTrue(path.read_bytes().isascii())


if __name__ == "__main__":
    unittest.main()
