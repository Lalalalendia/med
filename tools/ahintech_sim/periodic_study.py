"""Reproducible experiment: stationary 24h schedule plus finite bootstrap bridge.

The stationarity optimum assumes a preexisting periodic activation state.
A bridge is a valid finite output starting from one initial activation.
These are numerical simulations and cannot be used to spread real malware.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from dataclasses import asdict
from pathlib import Path

from model import Problem, validate_output
from counterfactual import generate
from periodic_oracle import solve_stationary
from bridge_oracle import solve_bridge


def compile_cpp(source: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True,exist_ok=True)
    subprocess.run(['g++','-std=c++23','-O2','-pipe','-o',str(dest),str(source)],check=True)


def study(*, out: Path, indices: list[int], horizons: list[int], seed: int,
          stationary_seconds: float, bridge_seconds: float,
          baseline_cpp: Path) -> list[dict]:
    out.mkdir(parents=True,exist_ok=True)
    binary=out/'v33'
    compile_cpp(baseline_cpp,binary)
    rows=[]
    for i in indices:
        original=generate(i,seed)
        orbit=solve_stationary(original,time_limit=stationary_seconds,max_variables=60000)
        for horizon in horizons:
            if original.n*horizon > 1_000_000:
                continue
            g=Problem(original.n,original.p,original.k,original.x,horizon,
                      original.a,original.b,original.t,original.adj)
            dat=g.to_text().encode('ascii')
            stem=f'index{i}_n{g.n}_m{horizon}_k{g.k}'
            (out/(stem+'.in')).write_bytes(dat)
            baseline=subprocess.run([str(binary)],input=dat,stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE,timeout=2.1,check=True)
            A=validate_output(g,baseline.stdout)['A']
            row=dict(name=stem,n=g.n,m=horizon,k=g.k,x=g.x,seed=seed,
                     input_sha256=hashlib.sha256(dat).hexdigest(),baseline_A=A,
                     stationary_rate_per_day=orbit.rate,
                     stationary_optimal=orbit.optimal,
                     stationary_bound=orbit.bound,
                     stationarity_seconds=round(orbit.seconds,3),bridge_A=None,
                     bridge_optimal=False,join_hour=None,improvement=0,
                     bridge_details=[])
            if orbit.rate is not None and orbit.rate>0:
                best=None
                for B in (24,48,72,96):
                    if B>=horizon:continue
                    br=solve_bridge(g,orbit,join_hour=B,time_limit=bridge_seconds,
                                    max_variables=60000)
                    row['bridge_details'].append(dict(join_hour=B,A=br.score,
                                   sec=round(br.seconds,3),status=br.status,
                                   proven_optimal=br.optimal))
                    if br.score is not None and (best is None or br.score>best.score):
                        best=br;row['join_hour']=B
                if best is not None:
                    row['bridge_A']=best.score
                    row['bridge_optimal']=best.optimal
                    row['improvement']=best.score-A
                    validate_output(g,best.witness)
                    (out/(stem+'.bridge.out')).write_text(best.witness,encoding='ascii')
            rows.append(row)
            print(f'{stem}: V33={A} periodic={orbit.rate}/day '
                  f'bridge={row["bridge_A"]} gain={row["improvement"]}',flush=True)
    (out/'periodic_report.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n')
    md=['# Periodic numerical planning experiment','',
        'A periodic-orbit optimum assumes preexisting activation states; '
        'it is **not** automatically achievable from one initial copy.',
        'A bridge witness is independently validated and respects the original start.',
        '', '| Case | V33 | Stationary / 24h | Finite bridge | Gain |',
        '|---|---:|---:|---:|---:|']
    for r in rows:
        md.append(f'| {r["name"]} | {r["baseline_A"]} | '
                  f'{r["stationary_rate_per_day"] if r["stationary_rate_per_day"] is not None else "?"} | '
                  f'{r["bridge_A"] if r["bridge_A"] is not None else "Not found"} | '
                  f'{r["improvement"]:+d} |')
    md.extend(['','Only synthetic inputs; no official hidden test or official ranking score.',
               'A missing bridge may mean infeasibility, an unreachable orbit, or the solver time cap.',''])
    (out/'periodic_report.md').write_text('\n'.join(md),encoding='utf-8')
    return rows


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--out',required=True,type=Path)
    ap.add_argument('--indices',default='1,9,10')
    ap.add_argument('--horizons',default='96,144')
    ap.add_argument('--seed',default=20261125,type=int)
    ap.add_argument('--stationary-seconds',default=4.,type=float)
    ap.add_argument('--bridge-seconds',default=4.,type=float)
    ap.add_argument('--baseline',type=Path,default=Path(__file__).parent/'solvers'/'v33_ejection_lns.cpp')
    args=ap.parse_args()
    study(out=args.out,indices=[int(x) for x in args.indices.split(',')],
          horizons=[int(x) for x in args.horizons.split(',')],seed=args.seed,
          stationary_seconds=args.stationary_seconds,bridge_seconds=args.bridge_seconds,
          baseline_cpp=args.baseline)

if __name__=='__main__': main()
