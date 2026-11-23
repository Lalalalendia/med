"""Exact / bounded research-only MILP for the Ahintek B offline graph problem.

This module does not run in the 2-second C++ submission. It produces certified
upper bounds and optimal witnesses on small / medium time-expanded graphs.
Requires optional scipy >= 1.10 (HiGHS MILP), not used by the core CI suite.

For a possible directed transmission e=(source, target, send hour), let z_e=1
iff the transmission is used. Each transmission contributes exactly one
activation, so maximize 1+sum(z_e).

At each vertex-hour the outbound quota cannot exceed k copies per activation.
An activation is created by one incoming transmission ending at that hour,
or by the unique initial activation. This enforces causality without a separate
activation variable. Occupancy constraints forbid intersecting unpacking
intervals on the same target. Instant completion-and-restart is permitted.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from time import perf_counter
from typing import Optional

from model import Problem, validate_output


class TooLarge(ValueError):
    pass


@dataclass
class MilpResult:
    activations: int | None
    witness: str | None
    upper_bound: int | None
    optimal: bool
    gap: int | None
    seconds: float
    variables: int
    status: str


def feasible_edges(g: Problem, max_variables: int) -> list[tuple[int, int, int]]:
    """The relaxed reachable DAG is a superset of feasible source events."""
    n, m = g.n, g.m
    seen = bytearray(n*m)
    head = [[g.p]] + [[] for _ in range(m-1)]
    seen[g.p] = 1
    edges = []
    for T in range(m):
        if not head[T]:
            continue
        phase = g.x+T
        for u in head[T]:
            for v in g.adj[u]:
                finish = T+g.t[v]
                if finish >= m or not g.eligible_start(v,phase):
                    continue
                edges.append((u,v,T))
                if len(edges)>max_variables:
                    raise TooLarge(f'MILP has >{max_variables} transmission variables')
                state = finish*n+v
                if not seen[state]:
                    seen[state] = 1
                    head[finish].append(v)
    return edges


def solve_milp(g: Problem, *, time_limit: float=10.0,
               max_variables: int=40_000, relative_gap: float=0.0) -> MilpResult:
    try:
        import numpy as np
        from scipy.optimize import Bounds, LinearConstraint, milp
        from scipy.sparse import coo_matrix
    except ImportError as exc:
        raise RuntimeError('Research MILP requires scipy (pip install scipy)') from exc
    started = perf_counter()
    edges = feasible_edges(g,max_variables)
    count = len(edges)
    if not count:
        return MilpResult(1,'1\n',1,True,0,perf_counter()-started,0,'Optimal: isolated initial activation')
    supply = {}
    busy = {}
    rows = []
    cols = []
    vals = []
    upper = []
    def get_row(pool,key,cap):
        row=pool.get(key)
        if row is None:
            row=len(upper)
            pool[key]=row
            upper.append(cap)
        return row
    for j,(u,v,T) in enumerate(edges):
        out = get_row(supply, (u,T), g.k if (u==g.p and T==0) else 0)
        rows.append(out);cols.append(j);vals.append(1)
        # Copies with arrival at (v,finish) create exactly one sender activation.
        arrival = get_row(supply, (v,T+g.t[v]), 0)
        rows.append(arrival);cols.append(j);vals.append(-g.k)
        for h in range(T,T+g.t[v]):
            occupation = get_row(busy,(v,h),1)
            rows.append(occupation);cols.append(j);vals.append(1)
    matrix=coo_matrix((np.array(vals,dtype=np.float64),(rows,cols)),
                      shape=(len(upper),count)).tocsr()
    c=-np.ones(count,dtype=np.float64)
    constraint=LinearConstraint(matrix,-np.inf,np.asarray(upper,dtype=np.float64))
    res=milp(c,integrality=np.ones(count,dtype=np.uint8),
             bounds=Bounds(0,1),constraints=constraint,
             options={'time_limit':time_limit,'mip_rel_gap':relative_gap,'presolve':True})
    if res.x is None:
        score, witness=None,None
    else:
        selected=[(u+1,v+1,g.x+T) for use,(u,v,T) in zip(res.x,edges) if use>0.5]
        selected.sort(key=lambda x:x[2])
        score=1+len(selected)
        witness=str(score)+'\n'+''.join('%d %d %d\n'%q for q in selected)
        validate_output(g,witness)  # independent of the optimization model
    # HiGHS gives a provable global dual bound even when a time limit is hit.
    dual=getattr(res,'mip_dual_bound',None)
    bound=int(math.floor(1-dual+1e-6)) if dual is not None and math.isfinite(dual) else None
    if res.status==0 and score is not None:
        bound=score
    gap=bound-score if bound is not None and score is not None else None
    return MilpResult(score,witness,bound,res.status==0,gap,
                      perf_counter()-started,count,str(res.message))
