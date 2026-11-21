"""V53 medium-size multi-hour joint-subset beam, independently validated.

Fixtures are synthetic and intentionally reveal a difference against V52;
they are NOT hidden contest tests or certified global optima.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
from model import Problem, validate_output


class MediumSubsetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory(prefix='ahintek-v53-')
        cls.binary = Path(cls._tmp.name) / 'solver'
        subprocess.run([
            'g++', '-std=c++23', '-O2', '-pipe',
            '-o', str(cls.binary), str(ROOT/'solvers'/'v53_medium_subsets.cpp')
        ], check=True, timeout=70)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_medium_joint_beam_regressions(self):
        fixtures = [
            ('v53_seed20270116_01_n15_m48.in', 78, 75,
             'edad8115564e4e3668c0f26a19ffc33e5d6199893613ce7586e2c6934108be4b'),
            ('v53_seed20270116_12_n14_m48.in', 96, 93,
             '21bf548effc8ff5a79e0b34dd571c35235e07757d7600611d1a5663aa4aa16fb'),
        ]
        for filename, expected_min, previous, sha in fixtures:
            with self.subTest(fixture=filename):
                source = (HERE/'cases'/filename).read_bytes()
                self.assertEqual(hashlib.sha256(source).hexdigest(), sha)
                problem = Problem.parse(source)
                env = dict(os.environ, AHINTEK_BUDGET_SEC='0.70')
                run = subprocess.run([str(self.binary)], input=source,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     timeout=2.8, check=True, env=env)
                result = validate_output(problem, run.stdout)
                self.assertGreaterEqual(result['A'], expected_min)
                self.assertGreater(result['A'], previous)


if __name__ == '__main__':
    unittest.main()
