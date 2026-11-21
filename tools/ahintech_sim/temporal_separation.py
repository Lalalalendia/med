"""Deterministic numerical benchmarks for deferring candidate activations.

Offline synthetic graph tests only. No network operations or real propagation.
The official hidden input distribution is unknown; these are not judge scores.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path

from model import Problem

SIZES = [(20, 900, 2), (30, 650, 4), (40, 900, 4), (60, 600, 2),
         (80, 800, 2), (100, 650, 4), (150, 700, 8), (200, 550, 4),
         (250, 700, 8), (500, 500, 4), (800, 850, 8), (1000, 650, 2),
         (1500, 550, 4), (60, 900, 8), (40, 1000, 4), (100, 900, 2)]


def generate(index: int, seed: int) -> Problem:
    if not 0 <= index < 32:
        raise ValueError('index must lie in [0, 32)')
    n, m, k = SIZES[index % len(SIZES)]
    rng = random.Random(seed + 19937 * index)
    edges: set[tuple[int, int]] = set()

    def add(u: int, v: int) -> None:
        if u != v:
            edges.add((min(u, v), max(u, v)))

    for u in range(1, n):
        add(u, u-1)
    d = [2, 4, 8, 12][(index // 3) % 4]
    for u in range(n):
        for _ in range(d):
            kind = index % 5
            if kind == 0:
                v = rng.randrange(n)
            elif kind == 1:
                v = rng.randrange(max(0, u-5), min(n, u+6))
            elif kind == 2:
                block = max(4, n//8)
                lo = u//block*block
                v = rng.randrange(lo, min(n, lo+block))
            elif kind == 3:
                v = rng.randrange(min(n, max(1, round(n**.5))))
            else:
                v = rng.randrange(min(n, 2+u))
            add(u, v)
    adj = [[] for _ in range(n)]
    for u, v in sorted(edges):
        adj[u].append(v)
        adj[v].append(u)
    x = rng.randrange(24)
    a, b, t = [], [], []
    for u in range(n):
        aa = (u*7 + index) % 24 if index % 4 == 0 else rng.randrange(24)
        bb = rng.choice([6, 7, 8, 9, 11, 13, 14, 17, 23])
        tt = min(bb, rng.choice([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 14]))
        a.append(aa)
        b.append(bb)
        t.append(tt)
    a[0], b[0] = x, 23
    if adj[0]:
        for v in adj[0][:min(k, len(adj[0]))]:
            a[v], t[v], b[v] = x, 1, 23
    p = Problem(n, 0, k, x, m, a, b, t, adj)
    p.validate_definition()
    return p


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seed', type=int, default=20261130)
    parser.add_argument('--start', type=int, default=0)
    parser.add_argument('--count', type=int, default=16)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if not (0 <= args.start < 32 and 1 <= args.count <= 32-args.start):
        parser.error('Invalid start/count range')
    args.out.mkdir(parents=True, exist_ok=True)
    manifest = []
    for i in range(args.start, args.start + args.count):
        problem = generate(i, args.seed)
        data = problem.to_text().encode('ascii')
        filename = f'{i:02d}_temporal_n{problem.n}_m{problem.m}_k{problem.k}.in'
        (args.out / filename).write_bytes(data)
        manifest.append({'file': filename, 'index': i, 'seed': args.seed,
                         'n': problem.n, 'm': problem.m, 'k': problem.k,
                         'sha256': hashlib.sha256(data).hexdigest()})
    (args.out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(f'Generated {args.count} temporal-separation test cases')


if __name__ == '__main__':
    main()
