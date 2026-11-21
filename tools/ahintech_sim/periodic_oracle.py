"""Research-only stationary 24-hour integer program for fictional contest task B.

It determines the best internally consistent schedule REPEATED EVERY 24 HOURS
with no restriction that the periodic orbit can be reached from the initial
activation. It is therefore NOT an upper bound on arbitrary finite-horizon
strategies. It is a target steady-state throughput and a constructive
periodic orbit, not a contest submission. Requires SciPy.
"""
from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Optional

from model import Problem


@dataclass
class StationaryResult:
    rate: Optional[int]
    bound: Optional[int]
    optimal: bool
    seconds: float
    assignments: list[tuple[int, int, int]]
    status: str
    variables: int


def solve_stationary(g: Problem, *, time_limit: float = 6., max_variables: int = 120000,
                     relative_gap: float = 0.) -> StationaryResult:
    import numpy as np
    from scipy.optimize import Bounds, LinearConstraint, milp
    from scipy.sparse import coo_matrix
    import math

    began = perf_counter()
    n = g.n
    if n > 3000:
        raise ValueError('periodic MILP restricted to n<=3000')
    # y_(v,h) is the binary fact that the copy completes at hour h modulo 24.
    y_count = 24*n
    idx_y = lambda v,h: v*24+h
    # z_(u,v,s) sends at hour s, completes at (s+t[v]) modulo 24.
    edges = []
    for u in range(n):
        for v in g.adj[u]:
            for hour in range(24):
                if g.eligible_start(v, hour):
                    edges.append((u,v,hour))
                    if len(edges) + y_count > max_variables:
                        raise ValueError('too many stationary MILP variables')
    nvars = y_count + len(edges)
    if not edges:
        return StationaryResult(0,0,True,perf_counter()-began,[],'no eligible edges',nvars)

    r=[]; c=[]; val=[]
    lower=np.full(72*n,-np.inf)
    upper=np.zeros(72*n)
    # 0..24*n: every activation must have exactly one incoming transmission.
    lower[:24*n]=0
    # 24*n..48*n: out quota, <=0.
    # 48*n..72*n: at most one unfinished copy at each device-hour.
    upper[48*n:72*n]=1
    for v in range(n):
        for h in range(24):
            at=idx_y(v,h)
            r.append(at); c.append(at); val.append(1)
            # outgoing <=k*y
            r.append(y_count+at);c.append(at);val.append(-g.k)
    for j,(u,v,s) in enumerate(edges):
        var=y_count+j
        dest=(s+g.t[v])%24
        # in activation constraint -z
        r.append(idx_y(v,dest));c.append(var);val.append(-1)
        # out <=k*y
        r.append(y_count+idx_y(u,s));c.append(var);val.append(1)
        # interval occupies s, s+1, ..., s+t-1 (cyclic).
        for dt in range(g.t[v]):
            r.append(48*n+idx_y(v,(s+dt)%24));c.append(var);val.append(1)
    mat=coo_matrix((np.array(val,dtype=np.float64),(r,c)),shape=(72*n,nvars)).tocsr()
    obj=np.zeros(nvars)
    obj[:y_count]=-1
    res=milp(obj,integrality=np.ones(nvars,dtype=np.uint8),
             bounds=Bounds(0,1),constraints=LinearConstraint(mat,lower,upper),
             options={'time_limit':time_limit,'mip_rel_gap':relative_gap,'presolve':True})
    assignments=[]
    if res.x is not None:
        assignments=[(u,v,s) for j,(u,v,s) in enumerate(edges) if res.x[y_count+j]>0.5]
        # Check the proof obligations independently, including across midnight.
        incoming={(v,h):0 for v in range(n) for h in range(24)}
        out={(v,h):0 for v in range(n) for h in range(24)}
        busy={(v,h):0 for v in range(n) for h in range(24)}
        for u,v,s in assignments:
            incoming[(v,(s+g.t[v])%24)]+=1
            out[(u,s)]+=1
            for delta in range(g.t[v]):busy[(v,(s+delta)%24)]+=1
        assert max(incoming.values())<=1 and max(busy.values())<=1
        assert all(out[(u,h)]<=g.k*incoming[(u,h)] for u in range(n) for h in range(24))
        assert all(g.eligible_start(v,s) for _,v,s in assignments)
    bound=(-res.mip_dual_bound if getattr(res,'mip_dual_bound',None) is not None and
           math.isfinite(res.mip_dual_bound) else None)
    bound=int(math.floor(bound+1e-6)) if bound is not None else None
    rate=len(assignments) if res.x is not None else None
    if res.status==0 and rate is not None:bound=rate
    return StationaryResult(rate,bound,res.status==0,perf_counter()-began,assignments,
                            str(res.message),nvars)
