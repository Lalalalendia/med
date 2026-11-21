"""Run contestants offline with judge-style wall/memory caps and validate output.

Competition's hidden scoring metric is UNKNOWN. The report intentionally uses
raw successful activations and ratios against best solution among evaluated
solvers, never claims to predict the official contest score.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path
import resource
import shutil
import statistics
import subprocess
import time

from model import Problem, InvalidSolution, validate_output
from oracle import TooComplex, format_solution, solve_exact
from diagnostics import time_expanded_upper_bound


def limit_memory(limit_bytes: int) -> None:
    resource.setrlimit(resource.RLIMIT_AS, (limit_bytes, limit_bytes))
    # Timeout in the parent process enforces wall time; CPU limit is backup.
    resource.setrlimit(resource.RLIMIT_CPU, (4, 5))


def compile_solver(path: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    cmd = ['g++', '-O2', '-std=c++23', '-pipe', '-o', str(target), str(path)]
    subprocess.run(cmd, check=True)


def execute(binary: Path, data: bytes, wall_limit: float, memory_mb: int,
            case_name: str, solver_name: str, outdir: Path, problem: Problem) -> dict:
    base = {'case':case_name, 'solver':solver_name, 'A':0, 'status':None,
            'wall_ms':None, 'peak_rss_kb':None, 'error':None}
    timer_path = outdir / f'{case_name}_{solver_name}.rss'
    use_time = Path('/usr/bin/time').is_file()
    command = ([str(Path('/usr/bin/time')), '-f','%M','-o',str(timer_path)] if use_time else []) + [str(binary.resolve())]
    before = time.perf_counter()
    try:
        p = subprocess.run(command, input=data, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, timeout=wall_limit,
                           preexec_fn=lambda: limit_memory(memory_mb*1024*1024),
                           check=False)
    except subprocess.TimeoutExpired:
        base.update(status='TLE', wall_ms=round((time.perf_counter()-before)*1000,2))
        return base
    except OSError as exc:
        base.update(status='RTE', error=str(exc))
        return base
    base['wall_ms'] = round((time.perf_counter()-before)*1000,2)
    if use_time and timer_path.is_file():
        try:
            base['peak_rss_kb'] = int(timer_path.read_text().strip().splitlines()[-1])
        except (ValueError,IndexError):
            pass
        timer_path.unlink(missing_ok=True)
    if p.returncode != 0:
        base.update(status='RTE',error=f'Exit {p.returncode}: {p.stderr.decode(errors="replace")[-300:]}')
        return base
    try:
        info = validate_output(problem, p.stdout)
    except (InvalidSolution,ValueError) as exc:
        base.update(status='WA',error=str(exc))
        (outdir / 'failures').mkdir(parents=True,exist_ok=True)
        (outdir/'failures'/f'{case_name}_{solver_name}.out').write_bytes(p.stdout[:500_000])
        return base
    base.update(status='OK', A=info['A'])
    return base


def write_reports(rows: list[dict], outdir: Path, *, oracle_scores: dict[str,int],
                  upper_bounds: dict[str,int]) -> None:
    outdir.mkdir(parents=True,exist_ok=True)
    case_best: dict[str,int] = {}
    for row in rows:
        case_best[row['case']] = max(case_best.get(row['case'], 0), row['A'])
    for row in rows:
        best = case_best[row['case']]
        row['ratio_to_best_tested'] = round(row['A']/best,6) if best else 0
        row['reachable_upper_bound'] = upper_bounds.get(row['case'])
        row['gap_to_reachability_bound'] = (upper_bounds[row['case']]-row['A']) if row['case'] in upper_bounds and row['status']=='OK' else None
        row['exact_optimum'] = oracle_scores.get(row['case'])
        row['gap_to_exact'] = (oracle_scores[row['case']] - row['A']) if row['case'] in oracle_scores and row['status']=='OK' else None
    (outdir/'results.json').write_text(json.dumps(rows,indent=2)+'\n',encoding='utf-8')
    if rows:
        with (outdir/'results.csv').open('w',newline='',encoding='utf-8') as f:
            writer = csv.DictWriter(f,fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
    solvers = sorted(set(r['solver'] for r in rows))
    summary = {}
    for solver in solvers:
        group = [r for r in rows if r['solver']==solver]
        ok = [r for r in group if r['status']=='OK']
        summary[solver] = {
            'ok':len(ok),'total':len(group),
            'sum_A':sum(r['A'] for r in ok),
            'mean_ratio_to_best_tested':round(statistics.mean(r['ratio_to_best_tested'] for r in group),6),
            'max_wall_ms':max((r['wall_ms'] or 0 for r in group),default=0),
            'worst_statuses':{s:sum(r['status']==s for r in group) for s in ('TLE','WA','RTE')},
        }
    (outdir/'summary.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8')
    text = ['# Ahintek B offline simulation', '',
            'Scores below are **raw activations**, not official judge points. Ratios use the best tested solver on each generated case.', '',
            '| Solver | OK | Sum A | Mean ratio | Max wall (ms) | TLE | WA | RTE |',
            '|---|---:|---:|---:|---:|---:|---:|---:|']
    for solver in solvers:
        s = summary[solver]
        text.append(f'| {solver} | {s["ok"]}/{s["total"]} | {s["sum_A"]} | {s["mean_ratio_to_best_tested"]:.4f} | {s["max_wall_ms"]:.1f} | {s["worst_statuses"]["TLE"]} | {s["worst_statuses"]["WA"]} | {s["worst_statuses"]["RTE"]} |')
    text += ['', '## Per-case results', '',
             '| Case | Solver | Status | A | Ratio | Wall (ms) | RSS (KiB) | Exact gap | Relaxed UB | Gap to UB |',
             '|---|---|---|---:|---:|---:|---:|---:|---:|---:|']
    for row in rows:
        text.append(f'| {row["case"]} | {row["solver"]} | {row["status"]} | {row["A"]} | {row["ratio_to_best_tested"]:.3f} | {row["wall_ms"] or "-"} | {row["peak_rss_kb"] or "-"} | {row["gap_to_exact"] if row["gap_to_exact"] is not None else "-"} | {row["reachable_upper_bound"] if row["reachable_upper_bound"] is not None else "-"} | {row["gap_to_reachability_bound"] if row["gap_to_reachability_bound"] is not None else "-"} |')
    text += ['', '## Reproduce', '', '`python3 tools/ahintech_sim/generator.py --suite smoke --seed 20261121 --out /tmp/ahin_cases`',
             '', 'The actual case input files and manifest are saved as workflow artifacts.']
    (outdir/'report.md').write_text('\n'.join(text)+'\n',encoding='utf-8')
    print('\n'.join(text[:9]))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--cases',type=Path,required=True)
    ap.add_argument('--out',type=Path,required=True)
    ap.add_argument('--solver',action='append',required=True,help='name=path-to-cpp-or-binary')
    ap.add_argument('--time-limit-ms',type=int,default=2000)
    ap.add_argument('--memory-mb',type=int,default=256)
    ap.add_argument('--oracle',action='store_true',help='Run exponential optimum only for n<=6,m<=14')
    ap.add_argument('--reachability-bound',action='store_true',help='Compute relaxed temporal upper bound with capped work')
    ap.add_argument('--fail-on-invalid', action='store_true')
    args=ap.parse_args()
    args.out.mkdir(parents=True,exist_ok=True)
    compiled = {}
    for spec in args.solver:
        name, sep, path = spec.partition('=')
        if not sep or not name.isidentifier() or name in compiled:
            ap.error('Each --solver must be a unique name=path')
        p = Path(path)
        if not p.is_file():
            ap.error(f'Missing solver: {p}')
        if p.suffix in ('.cpp','.cc','.cxx'):
            binary = (args.out/'bin'/name)
            compile_solver(p,binary)
        else:
            binary=p
        compiled[name] = binary
    rows, exact, upper_bounds = [], {}, {}
    cases = sorted(args.cases.glob('*.in'))
    if not cases:
        ap.error('No .in files in --cases')
    for inputfile in cases:
        data=inputfile.read_bytes()
        problem=Problem.parse(data)
        if args.reachability_bound:
            bound=time_expanded_upper_bound(problem)
            if bound is not None:
                upper_bounds[inputfile.stem]=bound.upper_bound
        if args.oracle and problem.n<=6 and problem.m<=14:
            try:
                answer=solve_exact(problem)
                validate_output(problem,format_solution(answer))
                exact[inputfile.stem]=answer[0]
            except TooComplex:
                pass
        for name,binary in compiled.items():
            rec=execute(binary,data,args.time_limit_ms/1000,args.memory_mb,
                        inputfile.stem,name,args.out,problem)
            rows.append(rec)
            print(f'{inputfile.stem}: {name}: {rec["status"]}, A={rec["A"]}, {rec["wall_ms"]} ms',flush=True)
    write_reports(rows,args.out,oracle_scores=exact,upper_bounds=upper_bounds)
    if args.fail_on_invalid and any(r['status']!='OK' for r in rows):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
