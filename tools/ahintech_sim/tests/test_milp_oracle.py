"""Optional SciPy exact-model verification against the pure Python oracle."""
import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from model import Problem,validate_output
from oracle import solve_exact
from milp_oracle import solve_milp

try:
    import scipy
except ImportError:
    scipy=None

@unittest.skipIf(scipy is None,'SciPy research dependency not installed')
class MilpTests(unittest.TestCase):
    def make(self,n,m,k,a,b,t,edges,x=0,p=0):
        adj=[[] for _ in range(n)]
        for u,v in edges:
            adj[u].append(v)
            adj[v].append(u)
        q=Problem(n,p,k,x,m,a,b,t,adj)
        q.validate_definition()
        return q

    def test_tiny_exact_against_enumeration(self):
        import random
        rng=random.Random(12345)
        for rep in range(15):
            n=rng.randrange(2,6); m=rng.randrange(5,12)
            ed=[(u,v) for u in range(n) for v in range(u+1,n) if rng.random()<0.6]
            ed += [(0,1)]
            ed=list(set(ed))
            g=self.make(n,m,rng.randrange(1,n+1),[0]*n,[rng.randint(2,23) for _ in range(n)],
                        [rng.randint(1,2) for _ in range(n)],ed)
            exact,_=solve_exact(g,max_states=200000)
            mres=solve_milp(g,time_limit=3)
            self.assertTrue(mres.optimal,(rep,mres))
            self.assertEqual(exact,mres.activations,(rep,mres))
            self.assertEqual(exact,mres.upper_bound)
            validate_output(g,mres.witness)

    def test_busy_at_start_and_repeated_activations(self):
        g=self.make(2,14,2,[0,0],[23,23],[1,2],[(0,1)])
        a=solve_milp(g,time_limit=5)
        self.assertTrue(a.optimal)
        self.assertEqual(a.activations,solve_exact(g)[0])

    def test_disconnected(self):
        g=self.make(3,10,2,[0,0,0],[23,23,23],[1,1,1],[])
        result=solve_milp(g)
        self.assertEqual(result.activations,1)
        self.assertEqual(result.upper_bound,1)
