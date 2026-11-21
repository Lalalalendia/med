# Task E — v30 adaptive LNS candidate (2026-11-21)

**Official incumbent:** C++ v20, **84.1064 points**, 26/26 accepted. C++ v22 officially scored 84.1060 (slight regression). **v30 has not been submitted to the official judge.**

## Mechanism

This is an isolated C++17 solver under the contest experimentation directory, not a production change.

The profiler exposed an allocation mistake: for a balanced medium-density 100k transaction instance, all eight peeling starts consumed about 0.78s while only 21,171 transactions were retained; the alternative two packing starts reached 23,016. Dense 100k was similar: peeling best 3721, packing best 4657. For the sparse 100k input, however, peeling is better (84,291 versus 82,538 for packing), so blanket removal of peeling is wrong.

v30 applies:

1. `startupDense = (sum(dOut) > 8*n) && (read_count/write_count between 1/3 and 3)`.
2. For dense balanced inputs, evaluate only 2 peeling starts first, then 2 packing starts.
3. **Fallback protection:** if packing does not beat those peeling starts by 5%, or n<=10k, evaluate the other 6 peeling starts as usual. Sparse/asymmetric starts remain unchanged.
4. Fix the old final phase gate `canSpend(.85)`, which could skip an otherwise useful phase whenever elapsed time was >1.90 seconds despite the 4-second test budget. The balanced final phase starts if elapsed <3.34 seconds and is bounded by a 3.52-second inner deadline.
5. Mix topological reorder-and-repair with **ruin-and-recreate**. On every second attempt in the balanced dense branch, remove about 1%, 2%, or 5% of already retained transactions (depending on iteration) and rebuild by feasibility-preserving greedy insertion. Only accept a strictly longer resulting order. With a time guard, allow up to 400 combined attempts.
6. **Proved upper-bound cutoff:** each nontrivial SCC forces the removal of at least one transaction. If the current selected size equals `n - #nontrivial_SCC`, no further search can improve it. Return immediately. This dramatically reduces waste on disjoint directed 2-/3-cycles, but cannot falsely claim optimum where there are longer complex cycles.

The memory-cell incidence graph stays implicit; no quadratic expansion of transaction conflicts.

## Local head-to-head (validity independently verified)

Representative **fixed 100k transaction files**. Time-dependent randomized iteration results vary slightly across reruns. Numbers below are one comparable sequential pass; do not treat them as exact distribution means.

| Input | v20 k | v30 k |
|---|---:|---:|
| 5/5 accesses, m=100,000 | 25,669 | **26,083** |
| 5/5 accesses, m=10,000 | 5,434 | **5,584** |
| 5/5 accesses, m=1,000,000 | around 86,651–86,722 (sometimes an earlier gate skips the final stage and yields ~84,323) | around 86,650–86,683 |
| 1/9 and 9/1 accesses, m=100 | 9,749 / 9,693 | same on verified representative runs |
| stacked SCC structure, n=100k | 75,698 | same |

Additional **12 independent seeded 25k inputs** with independent validity checks:

| Group | v20 aggregate | v29/v30 strategy aggregate | Gain |
|---|---:|---:|---:|
| 3 medium-density 5/5 cases, m=25,000 | 19,568 | 20,039 | **+471** |
| 3 high-density 5/5 cases, m=2,500 | 4,123 | 4,293 | **+170** |
| 3 read-heavy and 3 write-heavy | same | same | **0** |

v30 differs from v29 only by a safe optimality stopping rule. On random giant SCCs the bound is not met, so the same main algorithm runs. The random generator results are *not official contest scores* and do not prove improvement on the judge.

## Independent tests

- 8,962 exhaustive small inputs, all **correct and equal to the exact optimum**.
- Another 480 seeded random small inputs up to 12 transactions, all **correct and optimal**.
- Nine structural stress tests, including 100,000 vertices and 1,000,000 read/write memberships, all outputs valid. Known-optimum cases hit the optimum.
- Disjoint 3-cycles (99,999 transactions): k=66,666 with v30 ~0.17s, versus ~3.55s spent by v29 without the SCC upper bound.
- Disjoint 2-cycles (100,000 transactions): k=50,000 with v30 ~0.18s versus ~3.54s for v29.
- Latest medium-density 100k test ran ~3.57 seconds locally; largest input and judge CPU can differ.

## Safety / judge caveats

v30 is experimental and **has no official result yet**. The last officially accepted v20 had maximum 3.614s/4s. v30's expensive balanced branch is capped at 3.52s in the code, but each individual candidate evaluation can run beyond the check; no hard 4s guarantee on the judge. Preserve v20 source as rollback. Don't deploy or merge into the application.

**Ready to submit C++17:** `solver_cpp_v30_adaptive.cpp` (local SHA256 `37db4ce41b5dd3d6afc7ff6d166b42510fe07e9ea94794caffea42a9ed072e5a`).
