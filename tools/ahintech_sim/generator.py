"""Reproducible offline test-case generator. No external dependencies."""
from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path

from model import Problem

FAMILIES = ('path', 'ring', 'star', 'hubs', 'random', 'dense', 'communities', 'disconnected', 'phase_trap')
SCHEDULES = ('wide', 'narrow', 'mixed', 'staggered', 'night')


def graph_edges(n: int, family: str, rng: random.Random, *, stress: bool = False) -> set[tuple[int, int]]:
    edges: set[tuple[int, int]] = set()

    def add(u: int, v: int) -> None:
        if u != v:
            if u > v:
                u, v = v, u
            edges.add((u, v))

    reach = max(2, n // 5) if family == 'disconnected' else n
    if family == 'star':
        for i in range(1, reach):
            add(0, i)
    elif family in ('path', 'ring', 'phase_trap'):
        for i in range(1, reach):
            add(i-1, i)
        if family == 'ring' and reach > 2:
            add(0, reach-1)
    elif family in ('communities', 'disconnected'):
        block = max(2, reach // 4)
        for i in range(1, reach):
            if i % block:
                add(i-1, i)
            else:
                add(0, i)
        if family == 'communities':
            for i in range(block, reach, block):
                add(i-1, i)
    else:
        for i in range(1, reach):
            add(i-1, i)

    if family == 'disconnected':
        for i in range(reach+1, n):
            add(i-1, i)

    if family in ('path', 'ring', 'star', 'phase_trap'):
        return edges
    if family == 'hubs':
        hubs = max(2, min(16, int(n**0.5)))
        for i in range(hubs, reach):
            add(i, rng.randrange(hubs))
        target = min(500_000, len(edges)+3*reach)
    elif family == 'dense':
        target = min(500_000, n*(n-1)//2, (n*(n-1)//2 if stress else 20*n))
    elif family == 'communities':
        target = min(500_000, n*6)
    else:
        target = min(500_000, len(edges) + (5 if stress else 3)*reach)
    cap = min(target, reach*(reach-1)//2 + (n-reach)*(n-reach-1)//2)
    attempts = 0
    while len(edges) < cap and attempts < 12*cap + 100:
        attempts += 1
        if family == 'communities':
            block = max(2, n // 4)
            base = rng.randrange((n + block - 1)//block)*block
            if base >= n:
                continue
            u = rng.randrange(base, min(n,base+block))
            v = rng.randrange(base, min(n,base+block))
        elif family == 'disconnected':
            if rng.random() < 0.5:
                u = rng.randrange(reach)
                v = rng.randrange(reach)
            else:
                u = rng.randrange(reach, n)
                v = rng.randrange(reach, n)
        else:
            u, v = rng.randrange(reach), rng.randrange(reach)
        add(u, v)
    return edges


def generate(n: int, m: int, family: str, schedule: str, k: int, x: int, seed: int,
             *, stress: bool = False) -> Problem:
    if n*m > 1_000_000:
        raise ValueError('n*m exceeds task limit')
    rng = random.Random(seed)
    edges = graph_edges(n, family, rng, stress=stress)
    adj: list[list[int]] = [[] for _ in range(n)]
    for u, v in sorted(edges):
        adj[u].append(v)
        adj[v].append(u)
    a, b, t = [], [], []
    for i in range(n):
        if schedule == 'wide':
            bb = rng.randrange(16, 24)
        elif schedule == 'narrow':
            bb = rng.randrange(2, 9)
        elif schedule == 'staggered':
            bb = rng.randrange(8, 19)
        elif schedule == 'night':
            bb = rng.randrange(9, 19)
        else:
            bb = rng.randrange(3, 24)
        aa = (i * 7 + seed) % 24 if schedule == 'staggered' else rng.randrange(24)
        if schedule == 'night':
            aa = rng.choice([17,18,19,20,21,22,23,0,1])
        tt = rng.randint(1, min(bb, 14))
        if family == 'phase_trap' or (schedule == 'narrow' and rng.random() < 0.2):
            tt = bb
        # Intentionally infeasible recipients test the legal-phase guard.
        if rng.random() < 0.025:
            tt = min(23, bb+1)
        a.append(aa)
        b.append(bb)
        t.append(tt)
    p = 0
    a[p] = x  # guarantee the initial device is switched on
    # Most generated instances must have a nontrivial first generation.
    # Otherwise many different algorithms would all score A=1 and provide
    # no signal about scheduling quality. Keep phase_trap as an adversarial
    # exception; it is allowed to be impossible.
    if adj[p] and family != 'phase_trap' and m >= 3:
        first = adj[p][0]
        a[first] = x
        b[first] = max(b[first], 4)
        t[first] = min(t[first], 2)
    g = Problem(n=n, p=p, k=min(k,n), x=x, m=m, a=a, b=b, t=t, adj=adj)
    g.validate_definition()
    return g


def matrix(suite: str) -> list[tuple[int, int, str, str, int]]:
    if suite == 'smoke':
        sizes = [(2, 10), (3, 14), (4, 24), (6, 48), (8, 60),
                 (12, 96), (20, 120), (24, 144), (40, 96)]
    elif suite == 'standard':
        sizes = [(3, 20), (5, 48), (8, 120), (12, 240), (20, 500),
                 (40, 600), (80, 600), (120, 500), (200, 500),
                 (500, 400), (1000, 500), (2000, 400)]
    elif suite == 'stress':
        sizes = [(1000, 1000), (5000, 200), (10000, 100),
                 (20000, 50), (100000, 10), (1000, 1000)]
    elif suite == 'paired':
        sizes = [(12, 160), (20, 360), (20, 360), (12, 360),
                 (20, 160), (20, 360), (12, 360), (20, 360)]
    elif suite == 'research':
        sizes = [(6, 18), (8, 36), (9, 60), (10, 48),
                 (11, 60), (12, 72), (16, 80), (20, 120)]
    else:
        raise ValueError('suite must be smoke, standard, stress, paired or research')
    result = []
    for i, (n, m) in enumerate(sizes):
        fam = FAMILIES[i % len(FAMILIES)]
        if suite == 'stress' and i == len(sizes)-1:
            fam = 'dense'
        k = [1,2,3,4,8,12,20][i % 7]
        result.append((n, m, fam, SCHEDULES[i % len(SCHEDULES)], min(k,n)))
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--suite', choices=['smoke','standard','stress','paired','research'], default='smoke')
    ap.add_argument('--seed', type=int, default=20261121)
    ap.add_argument('--out', type=Path, default=Path('cases'))
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    manifest = []
    for i, (n,m,family,schedule,k) in enumerate(matrix(args.suite)):
        seed = args.seed + i * 1000003
        x = random.Random(seed ^ 0xABCD).randrange(24)
        prob = generate(n,m,family,schedule,k,x,seed,stress=args.suite=='stress')
        data = prob.to_text()
        name = f'{i:02d}_{family}_n{n}_m{m}_k{k}'
        path = args.out / (name+'.in')
        path.write_text(data,encoding='ascii')
        manifest.append({'name': name, 'file':path.name, 'n':n, 'm':m, 'k':k, 'x':x,
                         'family':family, 'schedule':schedule, 'edges':sum(map(len,prob.adj))//2,
                         'seed':seed, 'sha256':hashlib.sha256(data.encode('ascii')).hexdigest(),
                         'pair':i if args.suite=='paired' else None, 'variant':'base'})
        if args.suite=='paired':
            pad=150
            rng=random.Random(seed^0xC0FFEE)
            extra_a=[rng.randrange(24) for _ in range(pad)]
            extra_b=[rng.randrange(1,24) for _ in range(pad)]
            extra_t=[rng.randrange(1,24) for _ in range(pad)]
            augmented=Problem(n+pad,prob.p,prob.k,prob.x,prob.m,
                              prob.a+extra_a,prob.b+extra_b,prob.t+extra_t,
                              prob.adj+[[] for _ in range(pad)])
            augmented.validate_definition()
            augmented_data=augmented.to_text()
            padded_name=name+'_padded'
            padded_path=args.out/(padded_name+'.in')
            padded_path.write_text(augmented_data,encoding='ascii')
            manifest.append({'name':padded_name,'file':padded_path.name,'n':n+pad,
                             'm':m,'k':k,'x':x,'family':family,'schedule':schedule,
                             'edges':sum(map(len,prob.adj))//2,'seed':seed,
                             'sha256':hashlib.sha256(augmented_data.encode('ascii')).hexdigest(),
                             'pair':i,'variant':'padded'})
    # Certified small regression inputs are explicitly developmental, not
    # an independent hold-out set and never official hidden judge cases.
    if args.suite in ('smoke','research'):
        fixtures=Path(__file__).parent/'tests'/'cases'
        for source in sorted(fixtures.glob('dev_gap_*.in')):
            name='99_'+source.stem
            data=source.read_bytes()
            problem=Problem.parse(data)
            (args.out/(name+'.in')).write_bytes(data)
            manifest.append({'name':name,'file':name+'.in','n':problem.n,
                             'm':problem.m,'k':problem.k,'x':problem.x,
                             'family':'certified-dev-fixture','schedule':'known',
                             'edges':sum(map(len,problem.adj))//2,
                             'seed':None,'sha256':hashlib.sha256(data).hexdigest(),
                             'pair':None,'variant':'development-regression'})
    (args.out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    print(f'Generated {len(manifest)} reproducible {args.suite} cases in {args.out}')


if __name__ == '__main__':
    main()
