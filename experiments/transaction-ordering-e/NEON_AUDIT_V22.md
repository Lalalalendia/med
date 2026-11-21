# Task E — independent audit of "Neon" suggestions (2026-11-21)

Baseline official submission: **C++ v20, 84.1064 points**, all tests OK; maximum judged wall time 3.614 s of 4 s.

## Verified from exact current code

1. **SCC range 97..128 is skipped**. The list `interesting` includes groups up to 128, `TinyGraph` supports q <= 128, but exact handles q<=17 and `smallLocal` only q<=96. This is a missed optimization, not a correctness bug.
2. **Budget inconsistency is real**. `canSpend(reserve)` has a 2.75s base. The balanced final stage uses `if(canSpend(.85))` (thus starts only while elapsed <1.90s) but its loop nominally continues until 3.60s. On certain inputs it skips a potentially valuable final stage even when time remains.
3. **`exchange()` runs only in the asymmetric branch** as a deliberate historical optimization. The balanced branch favors DAG reorderings after previous exchange ablations delivered small gains at high cost; it is not evidence of a correctness bug.
4. **`bound > 192` overcounts**: `bound` sums selected read/write incidence counts before deduplicating transaction IDs. It is NOT the number of unique neighboring transactions. This can wrongly prune a potentially useful exchange. A capped unique-neighbor scan is a better proposed experiment than blindly raising threshold to 1024.
5. **`repair` uses earliest feasible slot `lo`** and can be symmetrized with latest feasible slot `hi`; the latter is a valid idea, but local experiments were mixed (three 100k balanced tests: -10, +6, -2 versus v20; an appended reverse pass: 0, -9, +1 in independently time-boxed runs). No clear reason to promote it yet.
6. **The proposed rank sign is inverted for the present code**. `reshuffle` uses a min-heap (`greater<Elem>`). `dOut` denotes writer targets of a read transaction (reader-like); `dIn` denotes readers of a writer transaction (writer-like). A smaller rank is processed first, so `dOut - dIn` would prioritize writers before readers, the opposite of the accompanying prose. A directional weighting experiment should test the correct sign and its impact on repair.
7. **Exact DP threshold to 20 was already tried**, including the later v19 post-SCC exact search: official score remained 84.0608 on all test cases versus v18. Synthetic SCC experiments can improve, but simply increasing thresholds is not an automatic global win.
8. **2-cycles imply vertex-cover constraints**. Their conflict graph gives a lower bound on necessary removals, but avoiding all 2-cycles is not enough for full DAG validity if longer cycles remain. Treat a vertex-cover strategy as a subroutine, not a replacement for DFVS.

## Test of SCC 97..128 patch

A naive global change `q<=96` -> `q<=128` improved small synthetic SCC families but *regressed* on 1000 SCCs of 100 vertices because it displaced the final global DAG reorder stage.

### Local fixed source, independent validity check

| Input | v20 kept | Naive q<=128 kept | Explanation |
|---|---:|---:|---|
| 2 x SCC 110 | 90 | 95 | Useful local phase |
| 5 x SCC 110 | 257 | 274 | Useful local phase |
| 8 x SCC 100 | 262 | 275 | Useful local phase |
| 5 x SCC 128 | 328 | 346 | Useful local phase |
| 300 x SCC 100 | 24828 | 25137 | More SCCs benefit |
| 1000 x SCC 100 | 86770 | **85871** | Local budget displaces stronger final stage |

### Budgeted SCC candidate `solver_cpp_v22_scc_budget.cpp`

- Process 97..128 SCCs for at most ~0.34s in total, and only while elapsed <1.67s. The existing <=96 SCC logic remains unchanged. The final reorder stage is unmodified.
- Benchmark same synthetic blocks and seed:
  - 5 x 110: 257 -> 274.
  - 300 x 100: 24828 -> 24988.
  - 1000 x 100: roughly 86598 -> 86818; note that results are time-sensitive and can vary with machine load.
- Six 100k fixed cases: changes +16, +8, +29, 0, 0, 0 transactions. Outputs all independently validated.
- 12 additional seeded samples, each 25k: 12 exact ties against v20; all outputs valid.
- 8,962 exhaustive + 1,400 random small cases: zero invalid, zero suboptimal against exact oracle.
- **The official contest has not evaluated v22. The 4s deadline remains a risk**: measured wall-time on some 100k cases was up to 3.82s locally.

## Next priorities

1. Preserve v20 as official proven fallback; submit v22 only as an optional experiment, not an expected +1 point improvement.
2. Make early-stage budget adaptive; use remaining time for global optimization instead of expensive SCC work when it has low marginal benefit.
3. Investigate `exchange()` incidence-overcount cutoff with deduplicated neighbor scan; this is a concrete source of missed candidates.
4. Try bounded two-cycle-aware selection and proper local exchange with accurate scoring; benchmark against v20 with identical time budgets and held-out generators.
5. Do not combine unmeasured changes or blindly increase iteration counts, because v20's judge peak 3.614s leaves only 0.386s of wall-time margin.

No deployment or modifications to `main`. 
