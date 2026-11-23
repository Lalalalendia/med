import os
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from model import Problem, InvalidInput, InvalidSolution, validate_output
from generator import generate, matrix
from oracle import solve_exact, format_solution


def tiny(n=2,m=5,k=1,x=0, a=None,b=None,t=None,adj=None,p=0):
    if a is None:a=[0]*n
    if b is None:b=[23]*n
    if t is None:t=[1]*n
    if adj is None:adj=[[1],[0]]
    g=Problem(n,p,k,x,m,a,b,t,adj)
    g.validate_definition()
    return g


class ModelTests(unittest.TestCase):
    def test_roundtrip(self):
        g=tiny()
        h=Problem.parse(g.to_text())
        self.assertEqual(g.to_text(),h.to_text())

    def test_repeated_infections_are_counted(self):
        g=tiny()
        sol='5\n1 2 0\n2 1 1\n1 2 2\n2 1 3\n'
        self.assertEqual(validate_output(g,sol)['A'],5)

    def test_unordered_lines_are_allowed(self):
        sol='5\n2 1 3\n2 1 1\n1 2 2\n1 2 0\n'
        self.assertEqual(validate_output(tiny(),sol)['A'],5)

    def test_starting_node_is_available_exactly_at_activation(self):
        g=tiny(n=2,m=4,k=1,x=23,a=[23,22],b=[1,3],t=[1,2])
        # 23: node 2 starts, completes at 25 (hour 1), fine.
        self.assertEqual(validate_output(g,'2\n1 2 23\n')['A'],2)

    def test_cannot_reinfect_on_busy_node(self):
        with self.assertRaisesRegex(InvalidSolution,'occupied'):
            validate_output(tiny(k=2), '3\n1 2 0\n1 2 0\n')

    def test_sender_must_activate_at_exact_hour(self):
        with self.assertRaisesRegex(InvalidSolution,'did not activate'):
            validate_output(tiny(), '2\n1 2 1\n')

    def test_quota_enforced(self):
        g=tiny(n=3,m=8,k=1,adj=[[1,2],[0],[0]])
        with self.assertRaisesRegex(InvalidSolution,'more than k'):
            validate_output(g,'3\n1 2 0\n1 3 0\n')

    def test_completion_at_horizon_is_disallowed(self):
        with self.assertRaisesRegex(InvalidSolution,'outside horizon'):
            validate_output(tiny(m=1),'2\n1 2 0\n')

    def test_crossing_shutdown_is_disallowed(self):
        g=tiny(n=2,m=8,k=1,x=0,a=[0,0],b=[23,1],t=[1,2])
        with self.assertRaisesRegex(InvalidSolution,'off before completion'):
            validate_output(g,'2\n1 2 0\n')

    def test_missing_link_disallowed(self):
        g=tiny(n=3,m=4,adj=[[1],[0],[]])
        with self.assertRaisesRegex(InvalidSolution,'no edge'):
            validate_output(g,'2\n1 3 0\n')

    def test_invalid_graph_rejected(self):
        with self.assertRaises(InvalidInput):
            tiny(n=2,adj=[[1],[]])

    def test_generator_matrix_legal(self):
        for suite in ('smoke','standard','stress'):
            for i,(n,m,f,s,k) in enumerate(matrix(suite)):
                self.assertLessEqual(n*m, 1_000_000)
                g=generate(n,m,f,s,k,5,12345+i,stress=(suite=='stress'))
                self.assertEqual(g.n,n)
                self.assertLessEqual(sum(map(len,g.adj)),1_000_000)
                self.assertTrue(g.is_on(g.p,g.x))

    def test_exact_oracle_matches_chain(self):
        ans=solve_exact(tiny(n=2,m=5,k=1))
        self.assertEqual(ans[0],5)
        validate_output(tiny(n=2,m=5,k=1),format_solution(ans))

    def test_exact_oracle_outlasts_obvious_greedy(self):
        g=tiny(n=3,m=9,k=2,adj=[[1,2],[0,2],[0,1]],a=[0,0,0],b=[23,23,23],t=[1,2,1])
        ans=solve_exact(g)
        self.assertGreater(ans[0],1)
        self.assertEqual(validate_output(g,format_solution(ans))['A'],ans[0])


if __name__=='__main__':
    unittest.main()
