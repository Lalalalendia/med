"""Relaxed time-expanded reachability for contest problem B.

Every real activation must appear in this relaxed DAG, which ignores
receiver occupancy and sender quotas. Therefore the number of individually
reachable (device, hour) activation states is a rigorous (often loose)
upper bound on the maximum possible score. No network operations occur.
"""
from __future__ import annotations

from array import array
from dataclasses import dataclass
from model import Problem


@dataclass(frozen=True)
class ReachabilityBound:
    upper_bound: int
    reachable_devices: int
    last_activation_hour: int
    directed_edge_checks: int


def time_expanded_upper_bound(g: Problem, *, max_edge_checks: int = 1_500_000
                              ) -> ReachabilityBound | None:
    """Return rigorous score upper bound, or None when computation is capped.

    T is relative to x. A possible activation at (u,T) can create a possible
    activation at (v,T+t[v]) only if v's complete unpacking fits into the
    same uninterrupted work interval and finishes within the process horizon.
    """
    n, m = g.n, g.m
    cells = n * m  # <= 1e6 from input conditions
    reached = bytearray(cells)
    touched_devices = bytearray(n)
    head = array('i', [-1]) * m
    successor = array('i', [-1]) * cells
    reached[g.p] = 1
    touched_devices[g.p] = 1
    head[0] = g.p
    states = devices = 1
    last_hour = edge_checks = 0
    for hour in range(m):
        state = head[hour]
        if state < 0:
            continue
        last_hour = hour
        absolute = g.x + hour
        while state >= 0:
            u = state % n
            row = g.adj[u]
            edge_checks += len(row)
            if edge_checks > max_edge_checks:
                return None
            for v in row:
                finish = hour + g.t[v]
                if finish >= m or not g.eligible_start(v, absolute):
                    continue
                destination = finish * n + v
                if reached[destination]:
                    continue
                reached[destination] = 1
                states += 1
                successor[destination] = head[finish]
                head[finish] = destination
                if not touched_devices[v]:
                    touched_devices[v] = 1
                    devices += 1
            state = successor[state]
    return ReachabilityBound(states, devices, last_hour, edge_checks)
