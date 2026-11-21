"""C++ research regression: temporal deferral has measurable causal value.

The two builds differ only in whether the deliberate defer decision is enabled.
This synthetic case is a DEVELOPMENT fixture, not evidence of hidden-judge scores.
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
from temporal_separation import generate


class TemporalSeparationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory(prefix='ahin-temporal-')
        cls.binaries = []
        source = ROOT / 'solvers' / 'v51_time_separation.cpp'
        for name, extra in (
            ('enabled', []),
            ('disabled', ['-DAHINTEK_ABLATION_NO_TEMPORAL_DEFER']),
        ):
            exe = Path(cls.tmp.name) / name
            subprocess.run(['g++', '-std=c++23', '-O2', '-pipe', *extra,
                            str(source), '-o', str(exe)],
                           check=True, timeout=90)
            cls.binaries.append(exe)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def test_fixture_matches_deterministic_generator(self) -> None:
        expected = generate(22, 20261128).to_text().encode('ascii')
        fixture = (ROOT / 'tests' / 'cases' / 'temporal_dev_seed28_i22.in').read_bytes()
        self.assertEqual(expected, fixture)

    def test_ablation_proves_nontrivial_temporal_effect(self) -> None:
        raw = (ROOT / 'tests' / 'cases' / 'temporal_dev_seed28_i22.in').read_bytes()
        problem = Problem.parse(raw)
        scores = []
        for exe in self.binaries:
            run = subprocess.run([str(exe)], input=raw, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, timeout=2.5,
                                 check=True,
                                 env={**os.environ, 'AHINTEK_BUDGET_SEC':'0.45'})
            scores.append(validate_output(problem, run.stdout)['A'])
        self.assertGreaterEqual(scores[0], scores[1] + 1000,
                                f'Expected a temporal scheduling improvement: {scores}')


if __name__ == '__main__':
    unittest.main()
