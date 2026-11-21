# Task E: Ordering Transactions — isolated experiment

**Status:** exploratory contest code, not a LesHa application change. Baseline: submitted PyPy solution, approximately 51 points across 25 scored cases. The improved version has **not been judged officially**.

## Improvement

Bidirectional topological peeling plus static drop-order heuristics may discard transactions that become feasible again after other cyclic vertices have been removed.

Given a valid sequence S, an excluded transaction t can be inserted after the **last selected reader** of any cell it writes, but no later than the **first selected writer** of any cell it reads:

- lo(t) = max(last_selected_reader_position[l]+1 for l in WS[t]), default 0
- hi(t) = min(first_selected_writer_position[l] for l in RS[t]), default k

For lo <= hi, bucket the excluded vertex into insertion slot lo. Scan slots in increasing order and admit each candidate only if none of its reads have been previously written by inserted or existing transactions. This checks conflicts *between* reinserts, preserves the original sequence, and can never decrease the selected count.

Additional work: O(n+m+S) time and O(n+m) auxiliary memory, where S is the total number of read/write memberships.

## Local results

CPython 3.13.5 on Linux. Every reported output independently checked for validity. These are not PyPy official times.

| Test | Baseline | Repaired |
|---|---:|---:|
| Suboptimal outputs among 1,300 random small cases, exact optimum | 177 | **55** |
| Suboptimal outputs among 8,962 exhaustive small cases | 148 | **0** |
| n=100,000, m=1,000,000, 5 reads + 5 writes | 82,556 | **84,291** |
| n=100,000, m=100,000, 5+5 | 13,101 | **20,922** |
| n=100,000, m=10,000, 5+5 | 1,198 | **3,508** |
| n=100,000, m=100, 1+9 | 9,067 | **9,325** |
| n=100,000, m=100, 9+1 | 8,956 | **9,185** |

Known-optimum families (chain, disjoint cycles, shared hub, single-cell clique) retained their previous optimum. Largest measured CPython times for the revised cases were around 3.5s, so this is **not yet guaranteed to fit 4s on arbitrary judge hardware**. The official PyPy evaluation is still necessary.

## Reproduce

From this directory:

    python test_solver.py --small
    python test_solver.py --exhaustive
    python compare.py --quick
    python compare.py --output results.csv

Files:
- `solver_baseline.py`: original 51-point submission algorithm, for reproducible comparisons.
- `solver.py`: baseline with postprocessing insertion/repair.
- `test_solver.py`: independent output checker, exact oracle for small inputs and structured stress generators.
- `compare.py`: reproducible head-to-head comparisons.

No deploy or changes to the existing LesHa application.
