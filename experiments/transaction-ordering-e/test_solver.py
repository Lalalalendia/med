#!/usr/bin/env python3
"""Regression + adversarial + stress benchmark for transaction_ordering.py.

This is a diagnostic script; it is not submitted to the contest.
"""
import importlib.util
import itertools
import os
import random
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOLVER = HERE / 'solver.py'
CPP = HERE / 'transaction_ordering_cpp'


def encode(rs, ws, m):
    out = [f'{len(rs)} {m}\n']
    for r, w in zip(rs, ws):
        out.append(f'{len(r)} {len(w)}\n')
        out.append(' '.join(map(str, r)) + '\n')
        out.append(' '.join(map(str, w)) + '\n')
    return ''.join(out).encode()


def verify(ids, rs, ws, m):
    if len(ids) != len(set(ids)):
        return 'duplicate id'
    seen_write = bytearray(m+1)
    for j in ids:
        if not (1 <= j <= len(rs)):
            return f'out-of-range id {j}'
        for loc in rs[j-1]:
            if seen_write[loc]:
                return f'earlier writer conflicts with reader transaction {j} at {loc}'
        for loc in ws[j-1]:
            seen_write[loc] = 1
    return None


def run_solver(payload, solver, test_all=False):
    with tempfile.NamedTemporaryFile(mode='w+', delete=False) as f:
        tmppath = f.name
    env = dict(os.environ)
    if test_all:
        env['TRANSACTION_TEST_ALL'] = '1'
    try:
        start = time.perf_counter()
        # /usr/bin/time is used to record the PEAK RESIDENT memory of the child.
        have_time_command = Path('/usr/bin/time').exists()
        command = (['/usr/bin/time', '-f', '%e %M', '-o', tmppath] if have_time_command else []) + solver
        proc = subprocess.run(command, input=payload, capture_output=True,
                               timeout=100, env=env)
        elapsed = time.perf_counter()-start
        if proc.returncode:
            raise RuntimeError(f'solver failed: {proc.returncode}, {proc.stderr.decode(errors="replace")[:800]}')
        nums = [int(s) for s in proc.stdout.split()]
        if not nums or nums[0] != len(nums)-1:
            raise ValueError('count does not match output')
        metrics = Path(tmppath).read_text().strip().split() if have_time_command else []
        return nums[1:], elapsed, int(metrics[1]) / 1024 if metrics else float('nan')
    finally:
        os.unlink(tmppath)


def optimum(rs, ws):
    n = len(rs)
    out_edges = [0]*n
    for i in range(n):
        for j in range(n):
            if i != j and set(rs[i]) & set(ws[j]):
                out_edges[i] |= 1 << j
    # O(n*2^n) dynamic programming: any acyclic subset has a source node.
    dag = bytearray(1 << n)
    dag[0] = 1
    best = 0
    for mask in range(1, 1 << n):
        t = mask
        while t:
            p = t & -t
            node = p.bit_length()-1
            smaller = mask ^ p
            if dag[smaller] and (out_edges[node] & smaller) == 0:
                dag[mask] = 1
                c = mask.bit_count()
                if c > best:
                    best = c
                break
            t ^= p
    return best


def family(name, n, m, max_total=1_000_000, seed=0):
    rng = random.Random(seed)
    if name == 'chain':
        m=n
        rs = [[i, *([] if i == n else [i+1])] for i in range(1,n+1)]
        ws = [[i] for i in range(1,n+1)]
    elif name == 'independent':
        m=n
        rs=[[i] for i in range(1,n+1)]
        ws=[[i] for i in range(1,n+1)]
    elif name == 'one_cell_all':
        m=1
        rs=[[1] for i in range(n)]
        ws=[[1] for i in range(n)]
    elif name == 'shared_read':
        m=n+1
        rs=[[1] for i in range(n)]
        ws=[[i+2] for i in range(n)]
    elif name == 'many_disjoint_3cycles':
        n = 3*(n//3)
        m=n
        rs = [[(i//3)*3+((i+1)%3)+1] for i in range(n)]
        ws = [[i+1] for i in range(n)]
    elif name == 'many_disjoint_2cycles':
        n=2*(n//2)
        m=n
        rs = [[i+1 if i%2==1 else i-1] for i in range(1,n+1)]
        ws = [[i] for i in range(1,n+1)]
    elif name == 'hub_2cycles':
        n=min(n,200_000)
        m=n-1
        rs=[list(range(1,n))]+[[i] for i in range(1,n)]
        ws=[list(range(1,n))]+[[i] for i in range(1,n)]
    elif name == 'complete_dag':
        m=n
        rs=[list(range(i,n+1)) for i in range(1,n+1)]
        ws=[[i] for i in range(1,n+1)]
    elif name == 'clique_dense':
        m=m
        cells = list(range(1,m+1))
        rs=[cells]*n
        ws=[cells]*n
    elif name == 'random_sparse':
        rs=[[rng.randrange(1,m+1)] for _ in range(n)]
        ws=[[rng.randrange(1,m+1)] for _ in range(n)]
    elif name.startswith('random_r'):  # random_r10_w10 etc
        r=int(name.split('_r')[1].split('_w')[0]); w=int(name.split('_w')[1])
        rs=[rng.sample(range(1,m+1), r) for _ in range(n)]
        ws=[rng.sample(range(1,m+1), w) for _ in range(n)]
    else:
        raise ValueError(name)
    total = sum(len(r)+len(w) for r,w in zip(rs,ws))
    if total > max_total:
        raise ValueError(f'{name}: memberships {total} > {max_total}')
    return n,m,rs,ws,total


def run_small():
    spec = importlib.util.spec_from_file_location('transaction_ordering', SOLVER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    rng = random.Random(20261121)
    results = []
    total = 0
    suboptimal = 0
    worst_gap=0
    for n in range(1,11):
        for j in range(130):
            m = rng.randrange(1,11)
            rs = [rng.sample(range(1,m+1),rng.randrange(1, min(m,4)+1)) for _ in range(n)]
            ws = [rng.sample(range(1,m+1),rng.randrange(1, min(m,4)+1)) for _ in range(n)]
            ids = module.solve(encode(rs,ws,m))
            err=verify(ids,rs,ws,m)
            if err:
                raise AssertionError((n,j,err,rs,ws,ids))
            opt = optimum(rs,ws)
            if len(ids)<opt:
                suboptimal+=1
                worst_gap=max(worst_gap,opt-len(ids))
            total+=1
    print(f'SMALL_RANDOM: {total} correctness PASS, suboptimal {suboptimal} ({suboptimal/total:.1%}), worst_gap {worst_gap}')
    return total, suboptimal


def run_exhaustive():
    spec = importlib.util.spec_from_file_location('transaction_ordering', SOLVER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    cases_checked = 0
    suboptimal = 0
    for n, m in [(2, 3), (4, 2)]:
        nonempty = [tuple(i+1 for i in range(m) if mask & (1 << i))
                    for mask in range(1, 1 << m)]
        types = list(itertools.product(nonempty, repeat=2))
        for desc in itertools.product(types, repeat=n):
            rs, ws = zip(*desc)
            result = module.solve(encode(rs, ws, m))
            err = verify(result, rs, ws, m)
            if err:
                raise AssertionError((n, m, desc, err))
            opt = optimum(rs, ws)
            if len(result) < opt:
                suboptimal += 1
            cases_checked += 1
    print(f'EXHAUSTIVE: {cases_checked} correctness PASS; '
          f'suboptimal {suboptimal} ({suboptimal/cases_checked:.1%})')


def run_stress():
    cases = [
        ('chain',100_000,100_000),
        ('independent',100_000,100_000),
        ('one_cell_all',100_000,1),
        ('shared_read',100_000,100_001),
        ('many_disjoint_3cycles',99_999,99_999),
        ('many_disjoint_2cycles',100_000,100_000),
        ('hub_2cycles',100_000,99_999),
        ('complete_dag',1200,1200),
        ('clique_dense',1000,450),
        ('random_sparse',100_000,1_000_000),
        ('random_r10_w10',50_000,10_000),
        ('random_r100_w100',4000,1000),
    ]
    results = []
    for name,n,m in cases:
        n,m,rs,ws,total=family(name,n,m)
        payload=encode(rs,ws,m)
        py_res,py_time,peak_mb=run_solver(payload,[sys.executable,str(SOLVER)])
        err=verify(py_res,rs,ws,m)
        if err:
            raise AssertionError((name,err))
        if name in ('chain','independent','shared_read','complete_dag'):
            optimal=n
        elif name=='one_cell_all' or name=='clique_dense':
            optimal=1
        elif name=='many_disjoint_3cycles':
            optimal=n*2//3
        elif name=='many_disjoint_2cycles':
            optimal=n//2
        elif name=='hub_2cycles':
            optimal=n-1
        else:
            optimal=None
        if optimal is not None and len(py_res)!=optimal:
            print('SUBOPTIMAL',name,len(py_res),optimal)
        cpp_k=None
        if CPP.is_file():
            cr,ct,cmem=run_solver(payload,[str(CPP)])
            cpp_k=len(cr)
            err=verify(cr,rs,ws,m)
            if err:
                raise AssertionError((name,'CPP',err))
        rec=(name, n,m,total, len(payload),len(py_res), optimal,cpp_k, round(py_time,3), round(peak_mb,1))
        print('STRESS:',repr(rec), flush=True)
        results.append(rec)
    with open(HERE/'transaction_ordering_bench.csv','w') as f:
        f.write('test,n,m,memberships,input_bytes,python_k,known_optimum,cpp_k,python_seconds,python_peak_mb\n')
        for rec in results:
            f.write(','.join(map(lambda x:'' if x is None else str(x),rec))+'\n')
    return results


if __name__=='__main__':
    if '--small' in sys.argv:
        run_small()
    elif '--exhaustive' in sys.argv:
        run_exhaustive()
    elif '--stress' in sys.argv:
        run_stress()
    else:
        run_small()
        run_stress()
