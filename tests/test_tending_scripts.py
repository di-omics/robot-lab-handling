"""Checks for scripts/tending_run.py and scripts/tending_replay.py. No model, no network, no credentials.

Run: python -m unittest -v tests.test_tending_scripts   (from the project folder; about 1 minute)
"""

import fcntl
import json
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import tending  # noqa: E402,F401
import labbench.take as lt  # noqa: E402
import tending_replay as replay  # noqa: E402
import tending_run as run  # noqa: E402
from labbench.sim import HOME, STEP_S  # noqa: E402
from tending.expert import BottleSwirler  # noqa: E402


class WigglePolicy:
    """No model: smooth joint wiggles on both arms and the grippers closing and opening."""

    rows = 48

    def __init__(self):
        self.calls, self.t = 0, 0.0

    def prime(self, windows, steps):
        pass

    def tick(self, windows, steps):
        pass

    def act(self):
        self.calls += 1
        t = self.t + STEP_S * np.arange(1, self.rows + 1)
        self.t = t[-1]
        wave = np.sin(2 * np.pi * 0.4 * t)[:, None]
        left = np.tile(HOME, (self.rows, 1))
        right = left.copy()
        left[:, :6] += 0.3 * wave * np.array([1.0, 1.0, 1.0, 0.5, 0.5, 0.5])
        right[:, :6] -= 0.3 * wave * np.array([1.0, 1.0, 1.0, 0.5, 0.5, 0.5])
        left[:, 6] = right[:, 6] = 0.65 + 0.35 * np.cos(2 * np.pi * 0.5 * t)
        return {"q_l_chunk": left, "q_r_chunk": right}, 0.0

    def close(self):
        pass


class ShortChunkPolicy(WigglePolicy):
    """No model: 10 actions per call, so a take needs about 5 times the calls."""

    rows = 10


class SwirlPolicy(WigglePolicy):
    """No model: the scripted expert's right arm picks up the cell bottle, so a stage is reached."""

    bench = None

    def act(self):
        self.calls += 1
        if self.calls == 1:
            self.moves = BottleSwirler(SwirlPolicy.bench).swirl(min_turns=6)
        right = np.array([next(self.moves) for _ in range(48)])
        return {"q_l_chunk": np.tile(HOME, (48, 1)), "q_r_chunk": right}, 0.0


class FailingPolicy(WigglePolicy):
    """No model: moves for 1 chunk, then fails as a lost connection would (run_take records the error).
    Its message names a file in the home folder and the repo, as a missing key file would."""

    def act(self):
        if self.calls == 1:
            raise RuntimeError(f"connection lost in this test, see {Path.home() / 'key.txt'} and {REPO / 'x'}")
        return super().act()


class RaisingPolicy:
    """No model: stops run_take with an exception it does not catch."""

    def __init__(self):
        raise SystemExit("stopped by this test")


def quiet(*args):
    pass


def no_network(*args, **kwargs):
    raise AssertionError("a test tried to open a network connection")


def no_key(*args, **kwargs):
    raise AssertionError("a test tried to read a credentials file")


def take_dirs(out):
    return sorted(p for p in Path(out).iterdir() if p.is_dir() and p.name != run.UNFINISHED)


class Scripts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.saved = (socket.socket.connect, lt.read_key, lt.DreamPolicy, lt.HoldPolicy, lt.set_bench)
        socket.socket.connect, lt.read_key, lt.DreamPolicy = no_network, no_key, no_key
        for name in ("hold", "wiggle", "swirl"):
            (cls.tmp / name).mkdir()
        ## 1 hold take (3 s) and 2 takes where the arms really move (6 s and 9 s), recorded by the run script.
        cls.hold = run.one_take("dispenser_plate_in", 0, cls.tmp / "hold", "hold", seconds=3, say=quiet)
        lt.HoldPolicy = WigglePolicy
        cls.wiggle = run.one_take("plate_in_with_swirl", 0, cls.tmp / "wiggle", "hold", seconds=6, say=quiet)
        lt.HoldPolicy = SwirlPolicy
        original = lt.set_bench

        def keep_scene(*args, **kwargs):
            SwirlPolicy.bench = original(*args, **kwargs)
            return SwirlPolicy.bench

        lt.set_bench = keep_scene
        cls.swirl = run.one_take("cell_bottle_swirl", 0, cls.tmp / "swirl", "hold", seconds=9, say=quiet)
        cls.swirl_qpos = SwirlPolicy.bench.env.data.qpos.copy()
        lt.HoldPolicy, lt.set_bench = cls.saved[3], cls.saved[4]

    @classmethod
    def tearDownClass(cls):
        socket.socket.connect, lt.read_key, lt.DreamPolicy, lt.HoldPolicy, lt.set_bench = cls.saved
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def take_dir(self, summary):
        return self.tmp / summary["dir"]

    def test_1_hold_take_replays(self):
        folder = self.take_dir(self.hold)
        trace = json.loads((folder / "trace.json").read_text())
        self.assertEqual(trace["priming_steps"], 33)
        self.assertEqual(trace["steps"] - trace["priming_steps"], round(self.hold["sim_s"] / STEP_S))
        self.assertEqual(trace["summary_sha256"], run.sha256(folder / "summary.json"))
        self.assertEqual(self.hold["versions"]["tending"], tending.TENDING_ID)
        self.assertFalse(Path(self.hold["dir"]).is_absolute())
        self.assertFalse((self.tmp / "hold" / run.UNFINISHED).exists())  # the take moved up into the run folder
        self.assertEqual(replay.main([folder]), 0)
        self.assertEqual(json.loads((folder / "replay.json").read_text())["status"], "agrees")

    def test_2_moving_takes_replay(self):
        for summary in (self.wiggle, self.swirl):
            folder = self.take_dir(summary)
            rows = np.fromfile(folder / "actions.f64le", dtype="<f8").reshape(-1, 14)
            self.assertGreater(np.ptp(rows[:, :6], axis=0).max() + np.ptp(rows[:, 7:13], axis=0).max(), 0.3)
            status, problems, result = replay.replay_take(folder / "actions.f64le")
            self.assertEqual((status, problems), ("agrees", []))
            self.assertEqual(result["stages"], summary["stages"])
        self.assertIsNotNone(self.swirl["stages"]["bottle_lifted"])  # a stage really was reached
        _, _, result = replay.replay_take(self.take_dir(self.swirl) / "actions.f64le")
        np.testing.assert_allclose(result["qpos"], self.swirl_qpos, atol=1e-9)  # the very same final poses

    def test_3_flipped_column_disagrees(self):
        folder = self.tmp / "flipped"
        shutil.copytree(self.take_dir(self.swirl), folder)
        rows = np.fromfile(folder / "actions.f64le", dtype="<f8").reshape(-1, 14)
        rows[:, 7] = -rows[:, 7]  # right arm base joint
        (folder / "actions.f64le").write_bytes(rows.astype("<f8").tobytes())
        self.assertEqual(replay.main([folder]), 1)  # the sha256 no longer matches
        trace = json.loads((folder / "trace.json").read_text())
        trace["actions_sha256"] = run.sha256(folder / "actions.f64le")
        (folder / "trace.json").write_text(json.dumps(trace))
        status, problems, _ = replay.replay_take(folder / "actions.f64le")
        self.assertEqual(status, "DISAGREES")  # with a matching sha256, the physics alone catches it
        self.assertTrue(problems)

    def test_4_cost_guard(self):
        self.assertTrue(run.next_take_allowed(0.0, 150, 1.50))
        self.assertTrue(run.next_take_allowed(0.0, 150, None))
        self.assertFalse(run.next_take_allowed(1.45, 150, 1.50))
        self.assertAlmostEqual(run.worst_cost(150), (150 / 2.4 + 2 + 12) * 0.0014)  # 12 retries to spare
        self.assertTrue(run.calls_look_normal(63, 150.0))  # what the recorded model takes made
        self.assertFalse(run.calls_look_normal(300, 150.0))
        out = self.tmp / "capped"
        lines = []
        stopped = run.run(out, ["cell_bottle_swirl"], [0], policy="hold", max_cost=0.001, seconds=3,
                          say=lines.append)
        self.assertEqual(take_dirs(out), [])  # stopped before any take
        self.assertTrue(stopped.startswith("stopping before cell_bottle_swirl seed 0"))
        self.assertIn(stopped, lines)
        ## A take with short chunks makes more calls than the cap assumes: the run stops after it.
        out = self.tmp / "short"
        try:
            lt.HoldPolicy = ShortChunkPolicy
            stopped = run.run(out, ["dispenser_plate_in", "cell_bottle_swirl"], [0], policy="hold", seconds=6,
                              say=quiet)
        finally:
            lt.HoldPolicy = self.saved[3]
        self.assertIn("more than 48-action chunks need", stopped)
        self.assertEqual(len(take_dirs(out)), 1)

    def test_5_rerun_rule(self):
        def take(task, seed, error=None):
            return {"task": task, "seed": seed, "prompt_variant": "plain", "error": error}

        tasks, seeds = ["a", "b"], [100, 101]
        self.assertEqual(run.next_pair([], tasks, seeds, 3), (("a", 100), []))
        have = [take("a", 100), take("b", 100, "DreamTimeout: x")]
        self.assertEqual(run.next_pair(have, tasks, seeds, 3), (("b", 100), []))
        have += [take("b", 100, "DreamTimeout: x"), take("b", 100, "DreamTimeout: x")]
        self.assertEqual(run.next_pair(have, tasks, seeds, 3), (("a", 101), [("b", 100)]))
        self.assertEqual(run.next_pair(have, tasks, seeds, 4), (("b", 100), []))
        have += [take("a", 101), take("b", 101, "x"), take("b", 101)]
        self.assertEqual(run.next_pair(have, tasks, seeds, 3), (None, [("b", 100)]))
        ## Stops by hand are not attempts.
        hand = [take("a", 100, "KeyboardInterrupt: ")] * 3
        self.assertEqual(run.next_pair(hand, ["a"], [100], 1), (("a", 100), []))

    def test_6_second_run_skips(self):
        out = self.tmp / "hold"
        before = sorted(p.name for p in out.iterdir())
        lines = []
        self.assertIsNone(run.run(out, ["dispenser_plate_in"], [0], policy="hold", seconds=3, say=lines.append))
        after = sorted(p.name for p in out.iterdir())
        self.assertEqual(sorted(set(after) - set(before)), [".lock", "results.json", "results.md"])
        self.assertFalse(any(line.startswith("take:") for line in lines))
        self.assertIn("pairs done 1 of 1", lines[-1])
        self.assertIn(f"Tending code {tending.TENDING_ID}.", (out / "results.md").read_text())
        ## While another holder has the folder's lock, a run does not start.
        with open(out / ".lock", "a") as f:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(SystemExit) as stop:
                run.run(out, ["dispenser_plate_in"], [0], policy="hold", seconds=3, say=quiet)
            self.assertIn("another process holds the lock", str(stop.exception))

    def test_7_errors_are_kept_and_tried_again(self):
        out = self.tmp / "errors"
        lines = []
        try:
            lt.HoldPolicy = FailingPolicy
            run.run(out, ["dispenser_plate_in"], [0], policy="hold", seconds=3, attempts=2, say=lines.append)
            lt.HoldPolicy = RaisingPolicy
            run.run(out, ["cell_bottle_swirl"], [0], policy="hold", seconds=3, say=lines.append)
        finally:
            lt.HoldPolicy = self.saved[3]
        takes = take_dirs(out)
        self.assertEqual(len(takes), 2)  # 2 errored attempts kept
        errors = [json.loads((p / "summary.json").read_text())["error"] for p in takes]
        self.assertTrue(all(e.startswith("RuntimeError: connection lost") for e in errors))
        self.assertTrue(all(str(Path.home()) not in e and str(REPO) not in e for e in errors))
        self.assertIn("~/key.txt and ./x", errors[0])
        raised = list((out / run.UNFINISHED).glob("*/*"))  # the take that raised stays unfinished
        self.assertEqual(len(raised), 1)
        self.assertFalse((raised[0] / "summary.json").exists())
        self.assertIsNone(json.loads((raised[0] / "trace.json").read_text())["summary"])
        self.assertEqual(run.next_pair(run.all_takes(out), ["cell_bottle_swirl"], [0], 1)[1],
                         [("cell_bottle_swirl", 0)])  # and counts as 1 attempt
        first_end = next(x for x in lines if x.startswith("pairs done"))
        self.assertIn("given up 1", first_end)
        self.assertIn("stopped: run_take raised SystemExit: stopped by this test", lines)
        results = (out / "results.md").read_text()
        self.assertIn("2 take(s) stopped on an error", results)
        self.assertIn("1 take(s) did not finish", results)
        self.assertNotIn(str(Path.home()), results)
        self.assertEqual(replay.main([out]), 0)
        self.assertEqual(json.loads((takes[0] / "replay.json").read_text())["status"], "stopped, no score")

    def test_8_unfinished_takes_count(self):
        out = self.tmp / "killed"
        ## A take killed before run_take wrote anything: 1 attempt, at the worst cost of the task.
        (out / run.UNFINISHED / "x" / "20261121-000000-cell_bottle_swirl-plain-s0-dream-1-beta").mkdir(parents=True)
        self.assertAlmostEqual(run.spent_usd(out), round(run.worst_cost(lt.TASKS["cell_bottle_swirl"].seconds), 4))
        self.assertEqual(run.next_pair(run.all_takes(out), ["cell_bottle_swirl"], [0], 1)[1],
                         [("cell_bottle_swirl", 0)])
        ## A take interrupted after run_take returned, before the stamp: not completed; the rerun takes the pair.
        out = self.tmp / "postcrash"
        real_stamp = tending.stamp

        def interrupted_stamp(take_dir):
            raise KeyboardInterrupt

        try:
            tending.stamp = interrupted_stamp
            stopped = run.run(out, ["cell_bottle_swirl"], [0], policy="hold", seconds=3, say=quiet)
        finally:
            tending.stamp = real_stamp
        self.assertEqual(stopped, "stopped: interrupted by hand")
        self.assertEqual(take_dirs(out), [])
        self.assertEqual(len(list((out / run.UNFINISHED).glob("*/*/summary.json"))), 1)
        self.assertIsNone(run.run(out, ["cell_bottle_swirl"], [0], policy="hold", seconds=3, say=quiet))
        [done] = take_dirs(out)
        summary = json.loads((done / "summary.json").read_text())
        self.assertEqual((summary["error"], summary["dir"]), (None, f"postcrash/{done.name}"))
        self.assertEqual(summary["versions"]["tending"], tending.TENDING_ID)
        self.assertEqual(replay.main([out]), 0)  # the unfinished summary is listed, not failed

    def test_9_replay_reports_missing_and_mismatched(self):
        empty = self.tmp / "noactions"
        shutil.copytree(self.take_dir(self.hold), empty / "take")
        (empty / "take" / "actions.f64le").unlink()
        (empty / "take" / "trace.json").unlink()
        self.assertEqual(replay.main([empty]), 1)
        self.assertEqual(replay.main([self.tmp / "no such folder"]), 1)
        other = self.tmp / "othercode"
        shutil.copytree(self.take_dir(self.hold), other)
        trace = json.loads((other / "trace.json").read_text())
        trace["versions"]["tending"] = "000000000000"
        (other / "trace.json").write_text(json.dumps(trace))
        status, problems, _ = replay.replay_take(other / "actions.f64le")
        self.assertEqual(status, "DISAGREES")
        self.assertTrue(any("recorded tending 000000000000" in p for p in problems))

    def test_10_hangup_is_recorded_as_a_stop_by_hand(self):
        out = self.tmp / "hangup"
        cmd = [sys.executable, str(REPO / "scripts" / "tending_run.py"), "--out", str(out), "--seeds", "0",
               "--tasks", "cell_bottle_swirl", "--policy", "hold", "--seconds", "60"]
        proc = subprocess.Popen(cmd, cwd=REPO, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        deadline = time.monotonic() + 40
        while not list(out.glob("unfinished/*/*/take.mp4")) and time.monotonic() < deadline:
            time.sleep(0.2)
        time.sleep(2)
        proc.send_signal(signal.SIGHUP)
        log, _ = proc.communicate(timeout=60)
        self.assertEqual(proc.returncode, 1, log)
        self.assertIn("stopped: interrupted by hand", log)
        [take] = take_dirs(out)
        summary = json.loads((take / "summary.json").read_text())
        self.assertTrue(summary["error"].startswith("KeyboardInterrupt"))
        self.assertTrue((take / "trace.json").is_file())
        self.assertEqual(run.next_pair(run.all_takes(out), ["cell_bottle_swirl"], [0], 1),
                         (("cell_bottle_swirl", 0), []))  # not an attempt
        self.assertEqual(replay.main([out]), 0)

    def test_11_motion_block(self):
        folder = self.take_dir(self.swirl)
        self.assertEqual(replay.main([folder]), 0)
        first = (folder / "replay.json").read_bytes()
        motion = json.loads(first)["motion"]
        keys = {"moved_max_xy_m", "rose_max_m", "tilt_max_deg", "touched_steps"}
        self.assertEqual(set(motion), {"bottle", "plate"})
        self.assertEqual(set(motion["bottle"]), keys)
        self.assertEqual(set(motion["plate"]), keys | {"low_corner_rose_max_m", "low_corner_rose_max_m_under_10_deg"})
        self.assertGreater(motion["bottle"]["rose_max_m"], 0.01)  # the swirl policy lifted the bottle
        self.assertGreater(motion["bottle"]["touched_steps"], 0)
        self.assertEqual(motion["plate"]["touched_steps"], 0)
        self.assertEqual(replay.main([folder]), 0)
        self.assertEqual((folder / "replay.json").read_bytes(), first)  # a second replay writes the same file


if __name__ == "__main__":
    unittest.main()
