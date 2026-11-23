"""V52 group-planning regression against MILP-certified small instances.

Source files are generated from a documented deterministic seed, not hidden
competition cases. SciPy is optional; output validation is mandatory.
"""
from __future__ import annotations
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from model import Problem,validate_output

class JointBeamTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='ahintek-v52-beam-')
        cls.binary=Path(cls.temp.name)/'solver'
        subprocess.run(['g++','-std=c++23','-O2','-pipe','-o',str(cls.binary),
                        str(ROOT/'solvers'/'v52_joint_beam.cpp')],check=True,timeout=70)
        cls.record=json.loads((ROOT/'tests'/'cases'/'v52_certified.json').read_text())

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_milp_certified_joint_cases(self):
        for name,meta in self.record.items():
            with self.subTest(case=name):
                raw=(ROOT/'tests'/'cases'/(name+'.in')).read_bytes()
                self.assertEqual(hashlib.sha256(raw).hexdigest(),meta['sha256'])
                problem=Problem.parse(raw)
                completed=subprocess.run([str(self.binary)],input=raw,
                          stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                          timeout=2.5,check=True)
                score=validate_output(problem,completed.stdout)['A']
                self.assertEqual(score,meta['optimal_score'])

    def test_independent_teacher_when_available(self):
        try:
            import scipy
        except ImportError:
            self.skipTest('SciPy optional in core CI')
        from milp_oracle import solve_milp
        for name,meta in self.record.items():
            with self.subTest(case=name):
                raw=(ROOT/'tests'/'cases'/(name+'.in')).read_bytes()
                problem=Problem.parse(raw)
                exact=solve_milp(problem,time_limit=10,max_variables=16000)
                self.assertTrue(exact.optimal,(name,exact.status))
                self.assertEqual(exact.activations,meta['optimal_score'])
                validate_output(problem,exact.witness)

if __name__=='__main__':unittest.main()
