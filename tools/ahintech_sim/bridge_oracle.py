"""Finite-horizon MILP to enter a prescribed 24h periodic orbit.

The horizon is finite, starts with one activation at x, and each transmission
in the forced steady-state suffix must coincide with the supplied stationary
periodic template. The prefix is freely optimized to connect initial state
to the template. This is an OFFLINE diagnostic, not a judge solution.
"""
from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Optional

from model import Problem, validate_output
from milp_oracle import feasible_edges
from periodic_oracle import StationaryResult

@dataclass
class BridgeResult:
    score: Optional[int]
    witness: Optional[str]
    optimal: bool
    status: str
    seconds: float
    variables: int
    forced_transmissions: int


def solve_bridge(g: Problem, orbit: StationaryResult, *, join_hour: int,
                 time_limit: float = 12.0, max_variables: int = 180000) -> BridgeResult:
    import numpy as np
    from scipy.optimize import milp, Bounds, LinearConstraint
    from scipy.sparse import coo_matrix
    started=perf_counter()
    edges=feasible_edges(g,max_variables)
    count=len(edges)
    target=set(orbit.assignments)
    lower_bounds=np.zeros(count,dtype=np.float64)
    upper_bounds=np.ones(count,dtype=np.float64)
    required=0
    for j,(u,v,T) in enumerate(edges):
        if T < join_hour:
            continue
        if (u,v,(g.x+T)%24) in target:
            lower_bounds[j]=1
            required+=1
        else:
            upper_bounds[j]=0
    # Check whether any orbit edge was pruned as unreachable by the relaxed
    # time-expanded construction. If yes it is impossible to join at this B.
    edge_set=set(edges)
    required_expected=0
    for T in range(join_hour,g.m):
        s=(g.x+T)%24
        for u,v,phase in orbit.assignments:
            if s==phase and T+g.t[v]<g.m:
                required_expected+=1
                if (u,v,T) not in edge_set:
                    return BridgeResult(None,None,False,'mandatory periodic edge not causally reachable',perf_counter()-started,count,required_expected)
    assert required_expected==required
    supplies={}; busy={}; rows=[];cols=[];vals=[];upp=[]
    def row(index,key,cap):
        if key not in index:
            index[key]=len(upp);upp.append(cap)
        return index[key]
    for j,(u,v,T) in enumerate(edges):
        i=row(supplies,(u,T),g.k if u==g.p and T==0 else 0)
        rows.append(i);cols.append(j);vals.append(1)
        arrival=row(supplies,(v,T+g.t[v]),0)
        rows.append(arrival);cols.append(j);vals.append(-g.k)
        for t in range(T,T+g.t[v]):
            i=row(busy,(v,t),1)
            rows.append(i);cols.append(j);vals.append(1)
    mat=coo_matrix((np.array(vals,float),(rows,cols)),shape=(len(upp),count)).tocsr()
    out=milp(-np.ones(count),integrality=np.ones(count,dtype=np.uint8),
             bounds=Bounds(lower_bounds,upper_bounds),
             constraints=LinearConstraint(mat,-np.inf,np.array(upp,float)),
             options={'time_limit':time_limit,'mip_rel_gap':0.0})
    solution=None
    if out.x is not None:
        chosen=[(u+1,v+1,g.x+T) for take,(u,v,T) in zip(out.x,edges) if take>0.5]
        chosen.sort(key=lambda x:x[2])
        solution=f'{1+len(chosen)}\n'+''.join(f'{u} {v} {s}\n' for u,v,s in chosen)
        validate_output(g,solution)
    return BridgeResult(1+len(chosen) if out.x is not None else None,solution,
                        out.status==0,str(out.message),perf_counter()-started,count,required)
