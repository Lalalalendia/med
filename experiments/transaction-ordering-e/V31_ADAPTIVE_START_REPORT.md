# Task E — v31 adaptive startup and SCC gate (2026-11-21)

**Status:** experimental C++17 candidate, **not officially judged**. The official incumbent is **v30: 84.5624/100**, all 26 tests accepted, highest judge time 3.536 s / 4 s and memory 27.82 MB. Preserve v30 as the rollback solution.

## Reproducible source

- Exact v30 base: `solver_cpp_v30_adaptive.cpp`, SHA-256 `37db4ce41b5dd3d6afc7ff6d166b42510fe07e9ea94794caffea42a9ed072e5a`.
- Candidate: `solver_cpp_v31_adaptive_budget.cpp`, SHA-256 `3945e01ba0d7f84dff6b4b07872a9a80e47a6296bf58930a3f38471dfe3b1af3`, Git blob `1e83ca628cd900ca0479a2eb93e792e95902fd04`.
- Tested on Linux with `g++ -std=c++17 -O2 -pipe`. No changes to product code, default branch, deployment or main.

## Changes

1. **Sparse classification** after degrees: `n>=40000`, total read/write counts balanced within 3:1, and `sum(dOut)<=8*n`. Dense-balanced startup behavior is unchanged.
2. In this sparse class, evaluate peel modes 0 and 1 first. If the best repaired solution already retains **at least 75%**, skip peel modes 2–6 but still run mode 7. If the result is worse than 75%, **run all the original peel modes in their original order**.
3. Keep both `pack()` variants. When the sparse class already retains at least 75%, skip the four dynamic peeling restarts, which often consumed CPU without increasing k. If below 75%, keep the original dynamic procedure.
4. **Fix premature pre-SCC exit**: old `!canSpend(.25)` means return after elapsed >=2.50 s, despite a 4 s judge limit. New conservative guard: return after 3.10 s, allowing SCC/LNS on inputs that formerly exited too early. The final LNS soft stop at 3.52 s is **unchanged**.
5. No changes to graph constraints, output format, exact solver, SCC composition, final verifier, LNS mutation, or global time hard limit. A change may alter which randomized iterations fit before a wall-clock cutoff: neither identical output nor monotonic score is guaranteed.

## Local fixed-input comparisons (retained transactions k, not official scores)

Representative sequential runs on the same bytes; results vary slightly between reruns because search ends by wall-clock time:

| Family | v30 k | v31 k | Difference |
|---|---:|---:|---:|
| n=50,000; 5 reads/5 writes; m=500,000; seed 937 | 43,566 | **43,613** | +47 |
| n=50,000; 5/5; m=200,000; seed 938 | 29,674 | **29,680** | +6 |
| n=50,000; 3/3; m=150,000; seed 939 | 41,296 | **41,348** | +52 |
| n=50,000; 5/5; m=50,000; seed 940 | 13,314 | 13,314 | 0 |
| n=30,000; asymmetric 1/9; m=500; seed 941 | 3,711 | 3,711 | 0 |
| n=100,000; 5/5; m=1,000,000; seed 414 | 86,230 | **86,681** | +451 (one run) |
| n=100,000; 5/5; m=10,000; seed 414 | 5,511 | 5,550 | +39 (time variation; dense path same) |

**Important:** on 100k/m=500k, original v30 sometimes triggers the 2.5 s early SCC exit, returning roughly 61,334; on other runs it reaches LNS and returns about 65,300–65,600. v31 consistently completed LNS on observed runs and returned about 65,300–65,400. Do **not** present the apparent 4k gap from a prematurely stopped run as a stable expected gain; the improvement is robustness to a time-based gate.

## Profiling motivation

On one fixed n=100k/m=1m sparse case:

- v30: peeling stage ended at ~0.86 s; pack ~1.27 s; dynamic peel ~2.01 s; SCC join ~2.18 s; final loop ~22 attempts by 3.52 s.
- v31: peeling ~0.34 s; pack ~0.72 s; pre-final ~0.86 s; final loop ~55 attempts by ~3.56 s.

The measured benefit comes mainly from **reallocating startup time into LNS**, not from faster `std::sort` or changed graph mathematics.

## Correctness and remaining risk

- 300 extra seeded random cases: 300 valid, no duplicates or forbidden write-before-read.
- 160 random small instances checked against exact subset-DP optimum: 160 valid and optimum.
- Known structure checks: independent n=100k -> 100k; single hot cell -> 1; chain/hub -> 100k; 50k disjoint 2-cycles -> 50k; large 3-layer cyclic construction -> 66,667.
- Measured local largest-case time ~3.54–3.75 s including process overhead, under 4 s on this machine. **No guarantee for judge CPU.** Some 100k inputs may cause one expensive final iteration to cross the soft 3.52 s stop.
- Original v30 remains official champion; v31 has **no official score yet**. The classification (8n, 75%, n>=40k) is empirical, not mathematically optimal.

## Recommendation

Submit v31 as a controlled separate C++17 test, compare all 25 per-test scores, especially cases 22–25, and watch for TLE near 4 s. Keep v30 as fallback. Do not promote v31 on the basis of a synthetic gain alone.
