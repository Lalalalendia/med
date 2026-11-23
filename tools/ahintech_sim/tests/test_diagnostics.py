"""Properties of the optimistic time-expanded state bound."""
import os
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from model import Problem
from diagnostics import time_expanded_upper_bound
from oracle import solve_exact, TooComplex


class BoundTests(unittest.TestCase):
    def test_alternating_two_nodes(self):
        p=Problem(2,0,1,0,7,[0,0],[23,23],[1,1],[[1],[0]])
        p.validate_definition()
        bound=time_expanded_upper_bound(p)
        self.assertEqual(bound.upper_bound, 7)
        self.assertEqual(bound.reachable_devices, 2)
        self.assertEqual(bound.last_activation_hour, 6)

    def test_disconnected_and_unusable_devices(self):
        p=Problem(4,0,2,0,15,[0,0,0,0],[23,1,23,23],[1,3,1,1],[[1],[0,2],[1],[]])
        p.validate_definition()
        bound=time_expanded_upper_bound(p)
        self.assertEqual(bound.upper_bound, 1)
        self.assertEqual(bound.reachable_devices, 1)

    def test_budget_abort_never_returns_false_upper_bound(self):
        p=Problem(3,0,2,0,10,[0]*3,[23]*3,[1]*3,[[1,2],[0,2],[0,1]])
        self.assertIsNone(time_expanded_upper_bound(p,max_edge_checks=1))

    def test_no_underestimates_exact_optimum(self):
        tested=0
        for seed in range(40):
            rng=random.Random(seed)
            n=3+seed%3
            m=5+seed%7
            k=1+seed%3
            adj=[[] for _ in range(n)]
            for u in range(n):
                for v in range(u+1,n):
                    if rng.random()<.55:
                        adj[u].append(v)
                        adj[v].append(u)
            a=[rng.randrange(24) for _ in range(n)]
            b=[rng.randrange(5,24) for _ in range(n)]
            t=[rng.randrange(1,5) for _ in range(n)]
            a[0]=0
            p=Problem(n,0,k,0,m,a,b,t,adj)
            p.validate_definition()
            ub=time_expanded_upper_bound(p)
            try:
                exact=solve_exact(p,max_states=30000)[0]
            except TooComplex:
                continue
            self.assertGreaterEqual(ub.upper_bound,exact)
            tested+=1
        self.assertGreaterEqual(tested,30)


if __name__=='__main__':
    unittest.main()
