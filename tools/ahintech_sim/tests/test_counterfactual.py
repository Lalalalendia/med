"""Reproducibility and validity of the counterfactual research workload."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from counterfactual import generate


class CounterfactualTests(unittest.TestCase):
    def test_deterministic_case(self) -> None:
        a=generate(5,20261125)
        b=generate(5,20261125)
        self.assertEqual(a.to_text(),b.to_text())
        self.assertEqual((a.n,a.m,a.k),(500,300,4))

    def test_varied_input_scales(self) -> None:
        for index in (0,6,15,16,31):
            with self.subTest(index=index):
                p=generate(index,20261125)
                p.validate_definition()
                self.assertLessEqual(p.n*p.m,1_000_000)
                self.assertTrue(p.adj[p.p])

    def test_out_of_range(self) -> None:
        for index in (-1,32):
            with self.assertRaises(ValueError):
                generate(index,20261125)


if __name__ == '__main__':
    unittest.main()
