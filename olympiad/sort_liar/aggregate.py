#!/usr/bin/env python3
"""Aggregate sharded sort-liar GitHub Actions reports; no external packages."""
from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict
from pathlib import Path

from judge import Result, render_markdown


def load_reports(root: Path) -> list[Result]:
    rows: list[Result] = []
    keys: set[tuple] = set()
    for file in sorted(root.rglob('results.json')):
        for data in json.loads(file.read_text()):
            row = Result(**data)
            key = (row.solver, row.suite, row.n, row.k, row.q,
                   row.strategy, row.shape, row.trial, row.seed)
            if key in keys:
                raise ValueError(f'duplicate result for {key} in {file}')
            keys.add(key)
            rows.append(row)
    if not rows:
        raise ValueError(f'no simulation results found under {root}')
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--baseline', default='adaptive_v5')
    args = parser.parse_args()
    rows = load_reports(args.input)
    args.output.mkdir(parents=True, exist_ok=True)
    markdown = render_markdown(rows, [], baseline=args.baseline)
    (args.output / 'summary.md').write_text(markdown)
    (args.output / 'results.json').write_text(json.dumps([asdict(r) for r in rows], indent=2))
    with (args.output / 'results.csv').open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(asdict(rows[0])))
        writer.writeheader()
        writer.writerows(asdict(r) for r in rows)
    print(f'Aggregated {len(rows)} results across {len(set(r.suite for r in rows))} suites')
    print(markdown)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
