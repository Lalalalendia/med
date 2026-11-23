"""Reproducible research-only miner of provable gaps in contest task B.

Uses deterministic synthetic graphs and SciPy/HiGHS. The contest C++ binary
never imports or links this code. The MILP witness is independently validated.

Example:
  python counterexample_miner.py --solver solvers/v51_time_separation.cpp \
      --seed 20261213 --count 12 --out /tmp/ahintek_mined --milp-seconds 5
"""
from __future__ import annotations
import argparse
import hashlib
import json
import random
import subprocess
import tempfile
from dataclasses import asdict
from pathlib import Path

from model import Problem,validate_output
from milp_oracle import solve_milp,TooLarge


def make_case(seed:int)->Problem:
    rng=random.Random(seed)
    n=rng.choice([10,11,12,14]);m=rng.choice([40,48,60,72])
    k=rng.choice([2,3,4,6]);x=rng.randrange(24)
    edges=set((u,u+1) for u in range(n-1))
    for u in range(n):
        for _ in range(rng.choice([1,2,3,5])):
            v=rng.randrange(n)
            if u!=v:edges.add(tuple(sorted((u,v))))
    adj=[[] for _ in range(n)]
    for u,v in sorted(edges):
        adj[u].append(v);adj[v].append(u)
    a=[rng.randrange(24) for _ in range(n)]
    b=[rng.choice([9,12,15,18,22,23]) for _ in range(n)]
    t=[rng.choice([1,1,2,2,3,3,4,5,6]) for _ in range(n)]
    a[0]=x;b[0]=23
    a[1]=x;b[1]=23;t[1]=1
    g=Problem(n,0,k,x,m,a,b,t,adj)
    g.validate_definition()
    return g


def mine(*,source:Path,out:Path,seed:int,count:int,
         milp_seconds:float,max_variables:int,cpp_budget:float)->list[dict]:
    out.mkdir(parents=True,exist_ok=True)
    records=[]
    with tempfile.TemporaryDirectory(prefix='ahintek-mine-') as td:
        executable=Path(td)/'baseline'
        subprocess.run(['g++','-std=c++23','-O2','-pipe',str(source),'-o',str(executable)],
                       check=True,timeout=90)
        for i in range(count):
            case_seed=seed+9199*i
            g=make_case(case_seed)
            raw=g.to_text().encode('ascii')
            name=f'mine_{i:02}_n{g.n}_m{g.m}_k{g.k}'
            process=subprocess.run([str(executable)],input=raw,stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,check=True,timeout=cpp_budget+0.5,
                        env=__import__('os').environ|{'AHINTEK_BUDGET_SEC':str(cpp_budget)})
            baseline=validate_output(g,process.stdout)['A']
            try:
                result=solve_milp(g,time_limit=milp_seconds,
                                  max_variables=max_variables)
                milp=dict(asdict(result));milp.pop('witness')
                certified=bool(result.optimal and result.activations is not None)
                gap=(result.activations-baseline) if certified else None
                if certified and result.activations<baseline:
                    raise AssertionError('MILP optimum smaller than validated C++ output')
                if result.witness and (certified or gap is not None):
                    (out/(name+'.opt.out')).write_text(result.witness,encoding='ascii')
            except TooLarge as exc:
                milp={'status':str(exc)}
                gap=None;certified=False
            record=dict(name=name,seed=case_seed,n=g.n,m=g.m,k=g.k,
                        baseline=baseline,proven_gap=gap,certified=certified,
                        input_sha256=hashlib.sha256(raw).hexdigest(),milp=milp)
            (out/(name+'.in')).write_bytes(raw)
            records.append(record)
            (out/'results.json').write_text(json.dumps(records,ensure_ascii=False,indent=2)+'\n')
            print(f'{name}: C++={baseline}, MILP={milp.get("activations")}, '
                  f'proven_gap={gap}',flush=True)
    md=['# Exact-gap mining (synthetic inputs)','',
        'Only certified optimal MILP results yield a proven gap.',
        'This is not an official hidden-test set.','',
        '| Case | Baseline A | MILP optimum | Proven gap |',
        '|---|---:|---:|---:|']
    for r in records:
        score=r['milp'].get('activations')
        md.append(f'| {r["name"]} | {r["baseline"]} | '
                  f'{score if score is not None else "—"} | '
                  f'{r["proven_gap"] if r["proven_gap"] is not None else "not certified"} |')
    (out/'report.md').write_text('\n'.join(md)+'\n',encoding='utf-8')
    return records


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--solver',type=Path,default=Path(__file__).parent/'solvers'/'v51_time_separation.cpp')
    ap.add_argument('--seed',type=int,default=20261213)
    ap.add_argument('--count',type=int,default=12)
    ap.add_argument('--out',type=Path,required=True)
    ap.add_argument('--milp-seconds',type=float,default=5.)
    ap.add_argument('--max-variables',type=int,default=16000)
    ap.add_argument('--cpp-budget',type=float,default=2.)
    args=ap.parse_args()
    mine(source=args.solver,out=args.out,seed=args.seed,count=args.count,
         milp_seconds=args.milp_seconds,max_variables=args.max_variables,
         cpp_budget=args.cpp_budget)

if __name__=='__main__':main()
