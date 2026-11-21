# Task E — official judge feedback for C++17 v12 (2026-11-21)

The user provided official per-test results for the C++17 file `transaction_ordering_cpp17.cpp` (same locally tested source as `solver_cpp_v12.cpp`). The branch currently holds earlier Python baselines and research; this report does **not** claim that the C++ source has already been committed.

- **C++17: 76.7776** over 25 scored cases (test 1 unscored). All 26 verdicts `ok`.
- Prior Python v2: **56.4136**.
- Gain: **+20.3640 points**, 16 improved tests, 9 unchanged, 0 regressions.
- Reported leaderboard competitor: approximately 85; remaining gap **8.2224** points (not an upper bound on the optimum).
- Peak judge runtime: **1.057 seconds** on test 25, against 4 s limit.
- Peak judge memory: **27.57 MB** on test 26, against 256 MB limit.

| Test | Python v2 | C++17 v12 | Delta |
|---:|---:|---:|---:|
| 2 | 3.2000 | 3.2000 | 0.0000 |
| 3 | 3.6000 | 3.6000 | 0.0000 |
| 4 | 4.0000 | 4.0000 | 0.0000 |
| 5 | 3.6000 | 3.6000 | 0.0000 |
| 6 | 3.2000 | 3.2000 | 0.0000 |
| 7 | 0.9600 | 2.2400 | 1.2800 |
| 8 | 0.8400 | 3.0400 | 2.2000 |
| 9 | 3.4000 | 3.4000 | 0.0000 |
| 10 | 3.4400 | 3.4400 | 0.0000 |
| 11 | 1.8800 | 3.5200 | 1.6400 |
| 12 | 1.3200 | 3.0400 | 1.7200 |
| 13 | 1.9600 | 3.2800 | 1.3200 |
| 14 | 3.3600 | 3.3600 | 0.0000 |
| 15 | 2.1200 | 3.4400 | 1.3200 |
| 16 | 3.5200 | 3.5200 | 0.0000 |
| 17 | 0.1440 | 1.7520 | 1.6080 |
| 18 | 0.5760 | 2.5160 | 1.9400 |
| 19 | 1.3760 | 3.3200 | 1.9440 |
| 20 | 0.6000 | 2.3240 | 1.7240 |
| 21 | 1.1960 | 3.3800 | 2.1840 |
| 22 | 2.5984 | 2.8084 | 0.2100 |
| 23 | 1.4488 | 2.2324 | 0.7836 |
| 24 | 2.7476 | 2.9388 | 0.1912 |
| 25 | 2.2328 | 2.4220 | 0.1892 |
| 26 | 3.0940 | 3.2040 | 0.1100 |

## Largest gaps to four available points (not proven achievable)

- Test 17: 1.752, headroom 2.248.
- Test 7: 2.24, headroom 1.76.
- Test 23: 2.2324, headroom 1.7676.
- Test 20: 2.324, headroom 1.676.
- Test 25: 2.422, headroom 1.578.
- Test 18: 2.516, headroom 1.484.

**Important**: score = 4*k/n. A low raw score doesn't prove suboptimality on a specific test; maximum feasible k is unknown. The ~85 competing total shows room for aggregate improvement, not which particular tests can be improved.

## Negative ablation (local, not judge)

Tried 10 noisy random multistarts after deterministic peeling on the same C++ v12 solver. Preserving the same deadline reduced time available for SCC/local exchange: on the 100k/m=100k random 5+5 case this version retained **21,171** vs **21,690** baseline, while consuming 2.619 vs 2.465 seconds in an illustrative local measurement. It did not improve other completed cases, so **do not promote** that version. An apparent optimization can regress because it displaces stronger later stages.

## Next experiments

1. SCC-specific algorithms, especially medium/large SCCs and bidirectional (2-cycle) conflicts.
2. Controlled zero-gain exchange chains with tabu and best-state rollback; baseline global exchange accepts only immediate +1 improvements.
3. Reorder within a selected DAG before reinsertion (randomized topological ordering) with a strict measured budget.
4. Bench on known-optimum graphs, large random seeds, and adversarial graphs, then check on official judge.

No deploy; this result is test feedback only.
