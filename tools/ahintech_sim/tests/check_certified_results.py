"""CI gate: V32 must reproduce certified small development examples.

This is a regression guard, NOT a measure of generalization to unseen inputs.
"""
import json
import sys
from pathlib import Path


def main():
    if len(sys.argv)!=2:
        raise SystemExit('Usage: check_certified_results.py /path/to/results.json')
    results=json.loads(Path(sys.argv[1]).read_text())
    base=Path(__file__).resolve().parent/'cases'
    known=json.loads((base/'certified_optima.json').read_text())
    observed={(r['case'],r['solver']):r for r in results}
    for key,record in known.items():
        case='99_'+key
        row=observed.get((case,'v32'))
        if row is None or row['status']!='OK' or row['A']<record['optimum']:
            raise SystemExit(f'{case}: V32 must reach certified {record["optimum"]}, got {row}')
        print(f'{case}: V32 {row["A"]}/{record["optimum"]} OK')
    print(f'All {len(known)} certified V32 development fixtures passed')


if __name__=='__main__':
    main()
