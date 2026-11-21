"""Independent verification of MILP-certified optimization witnesses."""
from pathlib import Path
import json
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from model import Problem,validate_output

ROOT=Path(__file__).resolve().parent/'cases'

class CertifiedWitnessTests(unittest.TestCase):
    def test_static_witnesses(self):
        records=json.loads((ROOT/'certified_optima.json').read_text())
        self.assertGreaterEqual(len(records),3)
        for name,info in records.items():
            with self.subTest(name=name):
                g=Problem.parse((ROOT/(name+'.in')).read_bytes())
                witness=(ROOT/(name+'.opt.out')).read_bytes()
                self.assertEqual(validate_output(g,witness)['A'],info['optimum'])
                self.assertEqual(g.n,info['n'])
                self.assertEqual(g.m,info['m'])
