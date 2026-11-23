"""Standalone V46 causal window replacement regression.

The fixture is deterministic and synthetic, NOT from the official judge.
The independent checker validates all event times, capacities and occupancy.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from model import Problem, validate_output


class V46SpliceWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory(prefix='ahintek-v46-splice-')
        cls.binary = Path(cls._tmp.name) / 'v46'
        source = ROOT / 'solvers' / 'v46_window_splice.cpp'
        subprocess.run(['g++', '-std=c++23', '-O2', '-pipe', '-o', str(cls.binary), str(source)],
                       check=True, timeout=70)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def test_valid_period_repair_and_score(self) -> None:
        path = ROOT / 'tests' / 'cases' / 'v46_splice_community_n32_m360.in'
        raw = path.read_bytes()
        problem = Problem.parse(raw)
        p = subprocess.run([str(self.binary)], input=raw, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, timeout=2.8, check=True,
                           env={**os.environ, 'AHINTEK_BUDGET_SEC': '2', 'AHINTEK_TRACE': '1'})
        a = validate_output(problem, p.stdout)['A']
        self.assertGreaterEqual(a, 990, 'V46 returned a weak schedule on its deterministic regression')
        self.assertIn('[SPLICE]', p.stderr.decode(), 'Splice search did not execute')

    def test_low_budget_preserves_validity(self) -> None:
        path = ROOT / 'tests' / 'cases' / 'v46_splice_community_n32_m360.in'
        raw = path.read_bytes()
        p = subprocess.run([str(self.binary)], input=raw, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, timeout=1.5, check=True,
                           env={**os.environ, 'AHINTEK_BUDGET_SEC': '0.25'})
        self.assertGreaterEqual(validate_output(Problem.parse(raw), p.stdout)['A'], 1)


if __name__ == '__main__':
    unittest.main()
