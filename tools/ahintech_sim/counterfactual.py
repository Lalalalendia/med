"""Deterministic training/evaluation workload for counterfactual LNS.

This is a SYNTHETIC numerical benchmark and not the contest's judge distribution.
The cases were designed to expose long-horizon branch conflicts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path

from model import Problem

# Multiple scales subject to n*m <= 1,000,000.
SIZES = [(20,500),(30,300),(50,500),(100,500),(200,200),(500,300),
         (1000,300),(1500,300),(10,600),(12,300),(15,900),(80,1000),
         (300,1000),(1000,1000),(2000,400),(10000,100)]


def generate(index: int, seed: int) -> Problem:
    if not 0 <= index < 32:
        raise ValueError('index must be in [0, 32)')
    n, m = SIZES[index % len(SIZES)]
    kind = index // len(SIZES)
    rng = random.Random(seed + index * 19937)
    k = [2,4,8,12][(index+kind) % 4]
    d = max(3,min(n//2,[3,6,12,20][index%4]))
    edges: set[tuple[int,int]] = set()
    if index % 5 == 0:
        for u in range(n-1):
            edges.add((u,u+1))
        if n > 2:
            edges.add((0,n-1))
    elif index % 5 == 1:
        for u in range(1,n):
            edges.add((rng.randrange(min(u,max(1,int(n**0.5)))),u))
    elif index % 5 == 2:
        for u in range(n-1):
            edges.add((u,u+1))
        for u in range(n):
            for _ in range(d):
                v=rng.randrange(n)
                if u!=v:
                    edges.add(tuple(sorted((u,v))))
    elif index % 5 == 3:
        block=max(2,n//6)
        for u in range(n-1):
            edges.add((u,u+1))
        for u in range(n):
            for _ in range(d):
                v=rng.randrange(u//block*block,min(n,u//block*block+block))
                if u!=v:
                    edges.add(tuple(sorted((u,v))))
    else:
        for u in range(n):
            for _ in range(d):
                v=rng.randrange(n)
                if u!=v:
                    edges.add(tuple(sorted((u,v))))
    adj=[[] for _ in range(n)]
    for u,v in sorted(edges):
        adj[u].append(v)
        adj[v].append(u)
    x=rng.randrange(24)
    aa,bb,tt=[],[],[]
    for u in range(n):
        b=(rng.choice([12,16,20,23]) if kind==0
           else rng.choice([9,12,15,23]))
        a=(rng.randrange(24) if index%3 else (u*7+index)%24)
        t=(rng.choice([1,1,2,2,3,4,5]) if kind==0
           else rng.choice([1,2,2,3,4,6,8]))
        aa.append(a);bb.append(b);tt.append(min(t,b))
    aa[0]=x
    bb[0]=23
    if adj[0]:
        first=adj[0][0]
        aa[first]=x;tt[first]=1;bb[first]=23
    p=Problem(n=n,p=0,k=min(k,n),x=x,m=m,a=aa,b=bb,t=tt,adj=adj)
    p.validate_definition()
    return p


def main() -> None:
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out',type=Path,required=True)
    ap.add_argument('--seed',type=int,default=20261125)
    ap.add_argument('--start',type=int,default=0)
    ap.add_argument('--count',type=int,default=16)
    args=ap.parse_args()
    if not 0<=args.start<32 or not 1<=args.count<=32-args.start:
        ap.error('start/count must select 1..32 indices')
    args.out.mkdir(parents=True,exist_ok=True)
    manifest=[]
    for index in range(args.start,args.start+args.count):
        p=generate(index,args.seed)
        data=p.to_text().encode('ascii')
        name=f'{index:02d}_counterfactual_n{p.n}_m{p.m}_k{p.k}.in'
        (args.out/name).write_bytes(data)
        manifest.append(dict(name=name,n=p.n,m=p.m,k=p.k,x=p.x,seed=args.seed,
                             index=index,sha256=hashlib.sha256(data).hexdigest()))
    (args.out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(f'Generated {len(manifest)} counterfactual synthetic cases in {args.out}')


if __name__=='__main__':
    main()
