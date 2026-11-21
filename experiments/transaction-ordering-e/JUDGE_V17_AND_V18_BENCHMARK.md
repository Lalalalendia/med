# Task E — official C++ v17 score and C++ v18 time-boxed benchmark

Date: 2026-11-21. This experiment remains isolated from LesHa runtime and main.

## Official v17 submission

25 scored cases plus an unscored first case; **all 26 verdicts OK**.

- v16: **83.3880** points.
- v17: **83.9124** points.
- Improvement: **+0.5244** points (7 improved, 18 unchanged, 0 regressed).
- A reported competitor had **85** points; difference **1.0876** points.
- Peak judge runtime **2.133 s / 4 s**; peak judge memory **27.82 MB / 256 MB**.

Changes in score (v16 -> v17): 
17: 3.1960 -> 3.2000; 19: 3.3480 -> 3.3560; 20: 3.4280 -> 3.4400;
22: 3.1544 -> 3.2332; 23: 2.5988 -> 2.7492; 24: 3.1428 -> 3.2672;
25: 3.1924 -> 3.3392. All remaining tests unchanged.

## What we tested after v17

- **Rejected**: predecessor-reachability augmentation of the selected DAG *before* reordering. It could save extra vertices on dense data but displaced successful final reorders and regressed 86,257 -> 84,650 and 25,303 -> 23,588 in two large local tests. Running augmentation *after* full v17 preserved the preceding work but yielded only small improvements (+25, +17 on two cases) at additional runtime. Not promoted.
- **Rejected**: prioritizing Kahn's topological choices by estimated demand from excluded transactions. Tested demand, inverse demand, alternating, and demand-only variants. All regressed on medium and dense fixed inputs compared with v17. Not promoted.
- **Rejected**: switching final re-insertion priority mode from 1 to 0/2 and alternating priorities; medium/sparse regressions.
- **Promoted to experimental v18**: extend only the final balanced read/write topological shuffle from at most 20 iterations (global cap 2.53 s) to at most 65 iterations under an **absolute 3.12 s soft cutoff**; all earlier heuristics and the asymmetric strategy are unchanged. Note that the final iteration could overrun this cutoff slightly.

## v18 local large head-to-head

Results are retained transaction counts, *not official judge scores*.
Local Linux C++17 O2, exact same input files:

| Input | v17 | v18 | Gain |
|---|---:|---:|---:|
| 100k transactions, 5 reads + 5 writes, m=1,000,000 | 86,257 | 86,546 | +289 |
| 100k transactions, 5+5, m=100,000 | 25,303 | 25,615 | +312 |
| 100k transactions, 5+5, m=10,000 | 5,315 | 5,409 | +94 |
| 100k transactions, 1+9, m=100 | 9,749 | 9,749 | 0 |
| 100k transactions, 9+1, m=100 | 9,693 | 9,693 | 0 |
| 100k stacked SCC structure | 75,698 | 75,698 | 0 |

The n=100,000 sparse output varied by about 15 retained vertices on reruns with the same input due to time-based termination; do not treat a 1-digit/2-digit change as stable.

**Independent seeds**: 12 cases with 25,000 transactions. Across 3 medium-density balanced 5/5 samples, v18 gained +102/+114/+104; across 3 high-density 5/5, +32/+32/+25. On 6 asymmetric 1/9 and 9/1 cases, all results identical. All outputs passed an independent conflict checker.

Local time on the three 100k balanced examples: ~3.0–3.15 s; highly asynchronous judge hardware may run slower, so the 4 s official limit is **not guaranteed**.

## Correctness

- 8,962 exhaustive small instances; exact optimum matched in all.
- 1,400 random small instances (n<=14); exact optimum matched in all.
- 9 large structural tests: all valid, and known optimum reached for independent vertices, long chains, 2-cycles, 3-cycles, a hub, and a complete conflict clique.
- Dense 1,000,000 read/write incidences: valid result.
- Judge has **not** evaluated v18.

## Submission candidate

`solver_cpp_v18_timeboxed.cpp` — SHA256 of locally compiled test source: `a56b1e4decaa7346d389e188ec4292f8d9dcfdfd90c67f72502f1bcf0361b7bf`.

**Do not merge or deploy**. Preserve the proven 83.9124-point v17 until official testing confirms v18. Small gains on synthetic random data do not prove a corresponding gain on hidden tests.
