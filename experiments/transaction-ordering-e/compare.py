#!/usr/bin/env python3
"""Reproducible baseline-vs-repair experiments for contest task E."""
import argparse
import csv
import sys
from pathlib import Path
from test_solver import encode, family, run_solver, verify

ROOT = Path(__file__).resolve().parent
CASES = [
    ('chain', 100000, 100000),
    ('many_disjoint_3cycles', 99999, 99999),
    ('hub_2cycles', 100000, 99999),
    ('one_cell_all', 100000, 1),
    ('random_r5_w5', 100000, 1000000),
    ('random_r5_w5', 100000, 100000),
    ('random_r5_w5', 100000, 10000),
    ('random_r1_w9', 100000, 100),
    ('random_r9_w1', 100000, 100),
    ('random_r100_w100', 5000, 1000),
]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--quick', action='store_true', help='Use two representative cases')
    parser.add_argument('--output', default='results.csv')
    args = parser.parse_args()
    cases = CASES if not args.quick else [CASES[1], CASES[5]]
    records = []
    for name, n, m in cases:
        n, m, reads, writes, memberships = family(name, n, m, seed=0)
        data = encode(reads, writes, m)
        row = {'family': name, 'n': n, 'm': m, 'memberships': memberships}
        for label, path in [('baseline', ROOT / 'solver_baseline.py'), ('repaired', ROOT / 'solver.py')]:
            result, elapsed, mb = run_solver(data, [sys.executable, str(path)])
            error = verify(result, reads, writes, m)
            if error:
                raise AssertionError(f'{name}, {label}: {error}')
            row[label + '_k'] = len(result)
            row[label + '_seconds'] = round(elapsed, 3)
            row[label + '_ram_mb'] = round(mb, 1)
        row['relative_gain_percent'] = round(100 * (row['repaired_k'] / row['baseline_k'] - 1), 2)
        print(row, flush=True)
        records.append(row)
    with open(args.output, 'w', newline='', encoding='utf8') as f:
        writer = csv.DictWriter(f, fieldnames=records[0].keys())
        writer.writeheader()
        writer.writerows(records)

if __name__ == '__main__':
    main()
