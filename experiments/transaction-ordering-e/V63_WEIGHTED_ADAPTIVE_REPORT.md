# Task E — v63 weighted pack + adaptive sparse ruin + budget-gate fix

Date: 2026-11-21. **Official incumbent: v43, 84.7140/100**. v46 officially scored 84.7064 (regression). **v63 has no official score yet.** No changes to main or deployment.

## Why this candidate is different from previous micro-tuning

**1. Adaptive ruin on sparse balanced graphs.** Previous v43 runs `perturb()` only for `sum(dOut)>8*n`, leaving less-conflicted balanced graphs with only random DAG reshuffling. This is a meaningful missed search operator: after a topo sort reaches a local optimum, random deletion of about 0.5–2% of selected transactions permits a different valid selected subset to be rebuilt. v63 uses:
- >8n conflicts: unchanged v43 (1%, 2%, 5% ruin every second attempt)
- >3n to 8n: 0.5%, 1%, 2% ruin every second attempt
- >n to 3n: old 1%, 2%, 5% ruin every eighth attempt
- <=n: unchanged; only topo reshuffles.
All branches preserve incumbent and rebuild via the existing validity-preserving repair. Time guard still starts final phase before 3.34s and checks 3.52s between iterations.

**2. Weighted damage in `pack()`.** Original `pack` minimizes raw numbers of discarded neighbors. For balanced moderately conflicted graphs with n>=20k and 3n<=sum(dOut)<=8n, v63 evaluates two extra packing starts with adaptive weights `w_i≈1024/sqrt(1+degree_i)`: mode 2 uses minimum in/out degree; mode 3 uses their sum. It maintains weighted live reader/writer incidence sums incrementally. A prospective choice is scored by the estimated loss of *valuable* neighbors, normalized by the candidate's own weight. All existing pack strategies are retained; the new scores are not used outside the gated workload, so dense/asymmetric/small-case behavior is unchanged.

**3. Fix stale early time bailout.** Original v43 checks `!canSpend(.25)` with a 2.75s base at the start of SCC processing and can return around 2.5s even if the final 3.52s phase has useful remaining budget. v63 returns at that stage only if `elapsed()>3.20`; SCC local improvement remains guarded by existing `canSpend` checks. This reduces large discontinuities in score caused by near-threshold timing variation. The new guard is *not* a hard deadline; official 4s limit must still be tested.

## Local benchmark, retained transactions k (not official scores)

All independent random 5-read/5-write instances used identical input for both solvers. Differences are time-sensitive and may vary between runs, especially for n=100k near the old early-bailout threshold.

| Fixed input | v43 k | v63 k | Difference |
|---|---:|---:|---:|
| n=25,000 m=100,000 seed17 | 14,958 | 15,289 | +331 |
| n=25,000 m=100,000 seed42 | 14,998 | 15,362 | +364 |
| n=100,000 m=400,000 seed108 | 58,637 | 59,736 | +1,099 |
| n=100,000 m=400,000 seed509 | 58,475 | 59,794 | +1,319 |
| n=10,000 m=75,000 seed17 | 7,977 | ~8,047 | +70 |
| n=10,000 m=60,000 seed509 | 7,308 | ~7,355–7,359 | +47–51 |

Earlier repeated baseline v43 on n=100k/m=400k sometimes quit around 2.6 seconds with about 54,200 selected, but on other runs used ~3.55 seconds and retained ~58,600. v63's new budget control and weighted pack delivered about 59,700–60,000 on the tested 100k cases while using around 3.5–3.6s locally.

Additional ablations:
- v60 = adaptive sparse LNS only; on five 25k/m100k seeds improvements over v43 ranged +156 to +243 retained.
- v61p = two additional *unweighted* pack starts; much smaller gains than weighted versions.
- v61 = weighted pack everywhere when four starts used; risked high-density regressions; replaced by v62/v63 workload-gated weighting.
- v62 = weighted pack + LNS but old early bailout; showed massive 100k fluctuations (~56k vs ~60k) depending on whether pre-SCC runtime just exceeded the old 2.50s gate.
- v63 = v62 with late SCC gate, keeping the proven dense branch unchanged.

## Independent validation

- **9,442 small cases**: 8,962 exhaustive + 480 random, independent checker reports valid and exactly optimal.
- **9 large structural stress tests**: all valid; known-optimum cases (independent, chain, 2/3 cycles, hub, dense clique) exact, including one-million-membership cases.
- Explicit end-to-end independent sequence verification on n=100,000/m400000 seed509 (k=59,794), n=25000/m100000 seed509, n=10000/m60000 seed509.
- Max local resource in large stress ~57.5 MiB RAM; the hardest random 100k input completed in ~3.62s, leaving under 0.4s headroom relative to contest 4s; this is *not* official time confirmation.

## Decision

v63 is **an experimental submission candidate** with stronger and broader local evidence, not a proven +0.286 or +1.5 official score gain. Submit as C++17, compare all 25 scored tests and runtimes with v43 (84.7140). Revert to v43 on any TLE or score regression. Do not merge or deploy this experiment.

File `solver_cpp_v63_weighted_lns_budgetfix.cpp`, SHA256 of the exact local C++ submission `8999e64dd08ecb0feeff8ae747912664fd3a1fe688a7c222ee1e9fabc2821d89`.
