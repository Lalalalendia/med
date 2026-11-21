"""Small exact reference solver for validating heuristics and the simulator.

Exponential; intentionally restricted to n<=6, m<=14 by default.
It enumerates feasible target sets and matching assignments for each active hour.
"""
from __future__ import annotations

from functools import lru_cache
from model import Problem


class TooComplex(RuntimeError):
    pass


def solve_exact(g: Problem, *, max_states: int = 150_000) -> tuple[int, list[tuple[int,int,int]]]:
    if g.n > 6 or g.m > 14:
        raise TooComplex('Oracle supports at most n=6, m=14')
    n, m = g.n, g.m
    choices = 0

    @lru_cache(None)
    def dp(busy: tuple[int,...], pending: tuple[tuple[int,int],...]) -> tuple[int, tuple]:
        nonlocal choices
        choices += 1
        if choices > max_states:
            raise TooComplex(f'Exact search exceeded {max_states} states')
        if not pending:
            return 0, ()
        moment = pending[0][0]
        if moment >= m:
            return 0, ()
        sources = [u for tt,u in pending if tt == moment]
        later = tuple((tt,u) for tt,u in pending if tt > moment)
        curr_abs = g.x + moment
        targets = [v for v in range(n) if busy[v] <= moment
                   and moment + g.t[v] < m and g.eligible_start(v,curr_abs)
                   and any(v in g.adj[u] for u in sources)]
        owners = [[idx for idx,u in enumerate(sources) if v in g.adj[u]] for v in targets]
        cap = [0] * len(sources)
        subsets: dict[int, tuple[tuple[int,int], ...]] = {}
        placement: list[tuple[int,int]] = []

        def enumerate_sets(i: int, mask: int) -> None:
            if i == len(targets):
                subsets.setdefault(mask,tuple(placement))
                return
            enumerate_sets(i+1,mask)
            v=targets[i]
            for who in owners[i]:
                if cap[who] >= g.k:
                    continue
                cap[who]+=1
                placement.append((sources[who],v))
                enumerate_sets(i+1,mask | (1<<v))
                placement.pop()
                cap[who]-=1

        enumerate_sets(0,0)
        best, best_witness = -1, ()
        for mask, assignments in subsets.items():
            new_busy = list(busy)
            futures = list(later)
            for v in range(n):
                if mask & (1<<v):
                    finish = moment + g.t[v]
                    new_busy[v] = finish
                    futures.append((finish,v))
            futures.sort()
            score, suffix = dp(tuple(new_busy), tuple(futures))
            score += mask.bit_count()
            if score > best:
                events = tuple((u+1,v+1,curr_abs) for u,v in assignments)
                best, best_witness = score, events + suffix
        return best, best_witness

    count, events = dp((0,)*n, ((0,g.p),))
    return 1+count, list(events)


def format_solution(answer: tuple[int,list[tuple[int,int,int]]]) -> str:
    count, events = answer
    return str(count)+'\n'+''.join(f'{u} {v} {s}\n' for u,v,s in events)
