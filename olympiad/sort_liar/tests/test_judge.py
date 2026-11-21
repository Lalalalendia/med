import asyncio
import stat
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from judge import Liar, RecordedLiar, answer_diagnostics, build_permutation, case_seed, render_markdown, run_case


class JudgeTests(unittest.TestCase):
    def test_permutations_are_valid_and_reproducible(self):
        for n in (2, 3, 9, 100):
            for shape in ("random", "sorted", "reversed", "nearly_sorted", "zigzag", "blocks"):
                p = build_permutation(n, shape, 42)
                self.assertEqual(sorted(p), list(range(1, n + 1)))
                self.assertEqual(p, build_permutation(n, shape, 42))

    def test_case_seeds_are_deterministic(self):
        self.assertEqual(case_seed(2, 1000, 30, 11000, "uniform", 3),
                         case_seed(2, 1000, 30, 11000, "uniform", 3))
        self.assertNotEqual(case_seed(2, 1000, 30, 11000, "uniform", 3),
                            case_seed(2, 1000, 30, 11000, "uniform", 4))

    def test_all_strategies_respect_lie_budget(self):
        p = build_permutation(20, "random", 42)
        for strategy in ("honest", "uniform", "first", "last", "spaced", "midburst",
                         "first_neighbor", "middle_neighbor", "repeat_pair", "repeat_all",
                         "element", "late_element", "late"):
            j = Liar(strategy, p, 7, 100, 42)
            for i in range(100):
                x, y = (1, 2) if i % 2 else (2, 1)
                said, truth, lied = j.respond(x, y)
                self.assertEqual(said != truth, lied)
            self.assertLessEqual(j.lies, 7)

    def test_interactive_protocol_and_score(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "solver.py"
            path.write_text("#!/usr/bin/env python3\n"
                            "import sys\n"
                            "n,k,q=map(int,input().split())\n"
                            "print('? 1 2',flush=True)\n"
                            "reply=input()\n"
                            "print('! '+' '.join(map(str,range(1,n+1))),flush=True)\n")
            path.chmod(path.stat().st_mode | stat.S_IXUSR)
            result, detail = asyncio.run(run_case(
                "sample", str(path), suite="smoke", n=3, k=1, q=11,
                strategy="first", shape="sorted", trial=0, seed=42, memory_mb=512, cpu_limit=4,
            ))
            self.assertTrue(result.correct, detail["stderr"])
            self.assertEqual(result.queries, 1)
            self.assertEqual(result.lies, 1)
            self.assertAlmostEqual(result.score, 1.5 + 0.5 * 10 / 11)
            self.assertEqual(detail["trace"][0]["reply"], "NO")

    def test_rejects_invalid_query(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.py"
            path.write_text("#!/usr/bin/env python3\n"
                            "n,k,q=map(int,input().split())\n"
                            "print('? 1 1',flush=True)\n"
                            "print('! 1 2',flush=True)\n")
            path.chmod(path.stat().st_mode | stat.S_IXUSR)
            result, _ = asyncio.run(run_case(
                "bad", str(path), suite="smoke", n=2, k=0, q=10,
                strategy="honest", shape="sorted", trial=0, seed=42, memory_mb=512, cpu_limit=4,
            ))
            self.assertFalse(result.correct)
            self.assertEqual(result.score, 0)
            self.assertEqual(result.reason, "invalid_query_indices")

    def test_rejects_query_budget_violation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.py"
            path.write_text("#!/usr/bin/env python3\n"
                            "n,k,q=map(int,input().split())\n"
                            "print('? 1 2',flush=True)\n"
                            "input()\n"
                            "print('? 1 2',flush=True)\n")
            path.chmod(path.stat().st_mode | stat.S_IXUSR)
            result, _ = asyncio.run(run_case(
                "bad", str(path), suite="smoke", n=2, k=0, q=1,
                strategy="honest", shape="sorted", trial=0, seed=42, memory_mb=512, cpu_limit=4,
            ))
            self.assertFalse(result.correct)
            self.assertEqual(result.reason, "query_limit_exceeded")


    def test_diagnostics_identify_adjacent_swap(self):
        d = answer_diagnostics([1, 2, 3, 4], [1, 3, 2, 4], [])
        self.assertEqual(d['wrong_positions'], 2)
        self.assertEqual(d['kendall_inversions'], 1)
        self.assertEqual(d['inverted_true_neighbor_pairs'], 1)
        self.assertEqual(d['inverted_neighbor_examples'][0]['true_ranks'], [2, 3])
        self.assertEqual(d['inverted_neighbor_examples'][0]['comparisons'], 0)

    def test_exact_replay_and_query_divergence(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'solver.py'
            p.write_text('#!/usr/bin/env python3\n'
                         'n,k,q=map(int,input().split())\n'
                         "print('? 1 2',flush=True)\n"
                         'input()\n'
                         "print('! 1 2',flush=True)\n")
            p.chmod(p.stat().st_mode | stat.S_IXUSR)
            kwargs = dict(
                suite='smoke', n=2, k=1, q=5, strategy='first',
                shape='sorted', trial=0, seed=45, memory_mb=512, cpu_limit=4,
            )
            first, detail = asyncio.run(run_case('fixed', str(p), **kwargs))
            self.assertTrue(first.correct)
            same, again = asyncio.run(run_case(
                'fixed', str(p), replay_trace=detail['trace'], **kwargs,
            ))
            self.assertEqual(same.reason, first.reason)
            self.assertEqual(same.queries, first.queries)
            self.assertEqual(same.lies, first.lies)
            self.assertEqual(detail['trace'], again['trace'])
            p.write_text('#!/usr/bin/env python3\n'
                         'n,k,q=map(int,input().split())\n'
                         "print('? 2 1',flush=True)\n"
                         'input()\n'
                         "print('! 1 2',flush=True)\n")
            bad, issue = asyncio.run(run_case(
                'fixed', str(p), replay_trace=detail['trace'], **kwargs,
            ))
            self.assertEqual(bad.reason, 'replay_query_diverged')
            self.assertIn('expected 1 2', issue['replay_divergence'])

    def test_replay_rejects_tampered_lie_budget(self):
        recorded = [dict(t=1, x=1, y=2, truth='YES', reply='NO', lie=True)]
        with self.assertRaises(ValueError):
            RecordedLiar([1, 2], 0, 5, recorded)

    def test_paired_score_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'solver.py'
            p.write_text('#!/usr/bin/env python3\n'
                         'n,k,q=map(int,input().split())\n'
                         "print('! 1 2',flush=True)\n")
            p.chmod(p.stat().st_mode | stat.S_IXUSR)
            args = dict(suite='smoke', n=2, k=0, q=5, strategy='honest',
                        shape='sorted', trial=0, seed=42, memory_mb=512, cpu_limit=4)
            base, _ = asyncio.run(run_case('adaptive_v5', str(p), **args))
            competitor, _ = asyncio.run(run_case('greedy_v7', str(p), **args))
            md = render_markdown([base, competitor], [], baseline='adaptive_v5')
            self.assertIn('Paired comparison', md)
            self.assertIn('| greedy_v7 | 1 | +0.000 |', md)

    def test_wrong_permutation_scores_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "wrong.py"
            path.write_text("#!/usr/bin/env python3\n"
                            "n,k,q=map(int,input().split())\n"
                            "print('! 2 1',flush=True)\n")
            path.chmod(path.stat().st_mode | stat.S_IXUSR)
            result, _ = asyncio.run(run_case(
                "wrong", str(path), suite="smoke", n=2, k=0, q=1,
                strategy="honest", shape="sorted", trial=0, seed=42,
                memory_mb=512, cpu_limit=4,
            ))
            self.assertEqual(result.reason, "wrong_permutation")
            self.assertEqual(result.score, 0)


if __name__ == "__main__":
    unittest.main()
