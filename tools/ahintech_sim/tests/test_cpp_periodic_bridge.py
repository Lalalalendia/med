"""Offline regression: the standalone C++23 solver constructs a causal closed day.

The workload is generated deterministically; it is not an official judge test.
"""
from __future__ import annotations

from collections import Counter
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from counterfactual import generate
from model import Problem,validate_output


def boundary_state(g: Problem, events: list[tuple[int,int,int]], B: int) -> tuple[int,...]:
    state=[0]*g.n
    if B==0:
        state[g.p]=-1
    for _,receiver,s in events:
        v=receiver-1
        send=s-g.x
        finish=send+g.t[v]
        if send < B <= finish:
            state[v]=-1 if finish==B else finish-B
    return tuple(state)


class StandaloneCyclicPlannerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp=tempfile.TemporaryDirectory(prefix='ahintek-periodic-cpp-')
        cls.binary=Path(cls._tmp.name)/'v38'
        source=ROOT/'solvers'/'v38_periodic_bridge.cpp'
        subprocess.run(['g++','-std=c++23','-O2','-pipe','-o',str(cls.binary),str(source)],
                       check=True,timeout=65)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def test_periodic_closure_and_real_causal_schedule(self) -> None:
        base=generate(1,20261125)
        problem=Problem(base.n,base.p,base.k,base.x,144,
                        base.a,base.b,base.t,base.adj)
        process=subprocess.run([str(self.binary)],input=problem.to_text().encode('ascii'),
                               stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                               timeout=2.6,check=True)
        score=validate_output(problem,process.stdout)['A']
        # The research test guards a nontrivial, *validated* use of the new
        # causal period planner, not a hidden-score prediction.
        self.assertGreaterEqual(score,1140)
        lines=process.stdout.decode('ascii').splitlines()
        events=[tuple(map(int,line.split())) for line in lines[1:]]
        found=False
        for B in (24,48,72):
            if B+48>=problem.m:
                continue
            earlier=Counter((u,v,s-problem.x-B) for u,v,s in events
                            if B<=s-problem.x<B+24)
            later=Counter((u,v,s-problem.x-B-24) for u,v,s in events
                          if B+24<=s-problem.x<B+48)
            if earlier and earlier==later and \
                    boundary_state(problem,events,B)==boundary_state(problem,events,B+24):
                found=True
                break
        self.assertTrue(found,'No identical 24-hour causal cycle in validated output')


if __name__=='__main__':
    unittest.main()
