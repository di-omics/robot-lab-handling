"""Checks that need no model and no network: every task's bench is stable, its oracle scores as success, and
none of its traps do. Run: python -m unittest -v tests.test_tasks   (from the project folder)"""

import unittest

from labbench.oracle import at_rest_problems, play
from labbench.take import set_bench
from labbench.tasks import TASKS

SEEDS = (0, 1, 2)


class TaskChecks(unittest.TestCase):
    def test_bench_is_still_at_rest(self):
        for name in TASKS:
            for seed in SEEDS:
                with self.subTest(task=name, seed=seed):
                    bench = set_bench(name, seed)
                    try:
                        self.assertEqual(at_rest_problems(bench), [])
                    finally:
                        bench.env.close()

    def test_oracle_scores_success(self):
        for name, task in TASKS.items():
            self.assertIsNotNone(task.oracle, f"{name} has no oracle")
            for seed in SEEDS:
                with self.subTest(task=name, seed=seed):
                    bench = set_bench(name, seed)
                    try:
                        self.assertEqual(play(bench, task.oracle(bench.specs)), [])
                        self.assertTrue(bench.tracker.summary()["success"])
                        self.assertEqual(bench.tracker.summary()["progress"], 1.0)
                    finally:
                        bench.env.close()

    def test_traps_do_not_score_success(self):
        for name, task in TASKS.items():
            self.assertIsNotNone(task.traps, f"{name} has no traps")
            for trap, steps in task.traps(set_bench_specs(name)).items():
                for seed in SEEDS[:2]:
                    with self.subTest(task=name, trap=trap, seed=seed):
                        bench = set_bench(name, seed)
                        try:
                            steps_here = task.traps(bench.specs)[trap]
                            self.assertEqual(play(bench, steps_here), [])
                            self.assertFalse(bench.tracker.summary()["success"])
                        finally:
                            bench.env.close()


def set_bench_specs(name):
    bench = set_bench(name, 0)
    try:
        return bench.specs
    finally:
        bench.env.close()


if __name__ == "__main__":
    unittest.main()
