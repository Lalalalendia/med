# C++ v13b — controlled neutral swaps (2026-11-21)

**Status: local candidate only. No official score.** The last official C++17 v12 submission scored **76.7776** out of 100 on 25 scoring cases, all `ok`. A reported leaderboard competitor had approximately 85.

## Mechanism

The global one-vertex exchange of v12 formerly rejected every swap which did not immediately increase the number of retained transactions. The new candidate keeps the best-ever valid selection, but permits up to six **neutral 1-for-1 swaps**, then tries insertion repair again. It never returns the temporary inferior sequence. It still bounds local search by elapsed time and its implicit read/write incidence representation.

## Local experiments (same fixed input bytes, independent no-conflict checker)

| Family | C++ v12 k | v13b k | v12 wall clock | v13b wall clock |
|---|---:|---:|---:|---:|
| 100k tx, r5/w5, m=1,000,000 | 84,327 | **84,332** | 1.89s | 2.81s |
| 100k tx, r5/w5, m=100,000 | 21,690 | **21,696** | 2.49s | 2.73s |
| 100k tx, r5/w5, m=10,000 | 4,329 | **4,349** | 1.12s | 2.58s |
| 100k tx, r1/w9, m=100 | 9,474 | 9,474 | 0.92s | 0.87s |
| 100k tx, r9/w1, m=100 | 9,510 | 9,510 | 1.03s | 1.43s |
| 100k tx, stacked SCC structure | 75,698 | 75,698 | 2.31s | 2.74s |

**Correctness**: 8,962 exhaustive small inputs with exact-optimal selections; 1,400 randomized small instances, again exact-optimal; six large inputs independently checked for valid output. All these refer to local experiments on the same machine, *not* official judge performance.

An attempted alternative adding 10 random multistarts was discarded: it consumed time that would otherwise be spent on more valuable SCC improvement and regressed 21,690 -> 21,171 on the medium-density dataset.

## Interpretation

Neutral moves did help modestly, with substantially increased CPU. The largest synthetic improvement (20 more retained out of 100k) is small. No reliable prediction of improvement on hidden judge tests is available. Upload to the contest only if willing to measure; preserve the proven 76.7776 v12 submission as fallback.

The local generated source is `transaction_ordering_cpp17_v13b.cpp` and has not yet been committed to this PR; this entry logs results and method only. No LesHa runtime changes and no deployment.
