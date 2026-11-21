"""Research-only tests: periodic capacity is not the same as reachability."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from model import Problem, validate_output
try:
    import scipy
except ImportError:
    scipy = None

@unittest.skipIf(scipy is None, 'SciPy is only installed for research runs')
class PeriodicResearchTests(unittest.TestCase):
    def test_start_compatibility_and_infeasible_isolation(self):
        from periodic_oracle import solve_stationary
        from bridge_oracle import solve_bridge
        g=Problem(4,0,1,1,72,[1,12,1,12],[23]*4,[1]*4,
                  [[1],[0,2],[1,3],[2]])
        g.validate_definition()
        orbit=solve_stationary(g,time_limit=3)
        self.assertTrue(orbit.optimal)
        self.assertEqual(orbit.rate,48)
        # Every standalone activation can emit only ONE copy (k=1), so no
        # 24h template containing two concurrent chains can be reached.
        bridge=solve_bridge(g,orbit,join_hour=24,time_limit=3)
        self.assertIsNone(bridge.score)

    def test_positive_bridge_30_devices(self):
        from periodic_oracle import solve_stationary
        from bridge_oracle import solve_bridge
        from counterfactual import generate
        original=generate(1,20261125)
        g=Problem(original.n,original.p,original.k,original.x,96,
                  original.a,original.b,original.t,original.adj)
        orbit=solve_stationary(g,time_limit=4)
        self.assertTrue(orbit.optimal)
        self.assertEqual(orbit.rate,205)
        bridge=solve_bridge(g,orbit,join_hour=48,time_limit=4)
        self.assertIsNotNone(bridge.score)
        self.assertGreaterEqual(bridge.score,785)
        self.assertEqual(validate_output(g,bridge.witness)['A'],bridge.score)

    def test_no_edges_periodic_zero(self):
        from periodic_oracle import solve_stationary
        g=Problem(2,0,2,0,72,[0,0],[23,23],[1,1],[[],[]])
        g.validate_definition()
        orbit=solve_stationary(g)
        self.assertEqual(orbit.rate,0)
        self.assertTrue(orbit.optimal)

if __name__=='__main__': unittest.main()
