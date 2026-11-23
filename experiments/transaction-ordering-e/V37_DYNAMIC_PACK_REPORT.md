# Task E — C++17 v37 dynamic pack reranking (2026-11-21)

## Status
- **Official incumbent: v20, 84.1064 / 100**, all 26 judge verdicts OK, peak 3.614s of 4s.
- **v37 is a new candidate, never judged officially.** It builds on v30's adaptive startup, SCC handling, and ruin/recreate.
- This is a source-only experiment in `experiments/transaction-ordering-e/`. Do not merge/deploy.

## New algorithmic element

The old `pack()` evaluated only the first 24 alive vertices of a **statically sorted** list. After many removals the dynamic `min(front,back)` costs change significantly, so vertices which became attractive can remain buried.

v37 adds two complementary methods **only for medium-density, balanced workloads** (global startup-density gate plus n/2 <= m <= 3n):

1. **Dynamic reranking**: at approximately 70%, 45.5%, 29.6%, and 19.2% remaining vertices, recalculate live `front = Σ read_count[WS_i]` and `back = Σ write_count[RS_i]` for all remaining vertices. Stable-sort their local candidate ranking by the *current* insertion cost; at most four rerankings per `pack()`.
2. **Randomized candidate sample**: in two extra packing starts (modes 2 and 3), score 192 pseudorandom live vertex IDs in addition to the first 24 ranking candidates. This sample is deterministic and does not consume the global reshuffle RNG.
3. **Safety switch**: on sparse (m>3n), dense-hot-cell (m<n/2), small, or asymmetric workloads, do not add these rerankings or extra sampled starts. Preserve v30's previous tested choice. All candidates are checked by the same feasibility-preserving repair and internal verifier.

This addresses an actual stale-ranking limitation rather than just allowing more time. More pack starts are not unconditionally better.

## Local head-to-head: count of kept transactions (NOT judge points)

### Fixed 100,000-transaction corpus

Representative paired runs, execution time for medium/dense cases ~3.53–3.59s locally (soft deadline; judge hardware not yet evaluated):

| Family | v30 kept | v37 kept | Notes |
|---|---:|---:|---|
| 5 reads + 5 writes, m=100,000 | 26,085 | **26,477** | +392 on one paired run |
| 5+5, m=10,000 | 5,590 | 5,589 | 1-vertex difference within time-sensitive variance; no demonstrated gain |
| 5+5, m=1,000,000 | 86,638 | 86,638 | identical after sparse branch preserved |
| 1+9, m=100 | 9,749 | 9,749 | result equal on checked run |
| 9+1, m=100 | 9,693 | 9,693 | result equal on checked run |
| stacked SCC graph | 75,698 | 75,698 | equal |

The 100k medium input has time-sensitive results varying by dozens of vertices across runs. **Do not infer an exact expected judge gain from one comparison.**

### Independent seeded 25,000-transaction corpus

| Family | Seed | v30 kept | v37 pack strategy kept |
|---|---:|---:|---:|
| 5+5, m=25,000 | 1 | 6,682 | 6,786 |
| 5+5, m=25,000 | 2 | 6,656 | 6,793 |
| 5+5, m=25,000 | 3 | 6,701 | 6,786 |
| 5+5, m=2,500 | 1 | 1,426 | 1,426 |
| 5+5, m=2,500 | 2 | 1,423 | 1,423 |
| 5+5, m=2,500 | 3 | 1,444 | 1,444 |

Medium-density aggregate: 20,039 -> 20,365 (+326). Dense aggregate: equal 4,293. These six runs used exactly v34, from which v37 differs only by disabling reranking when m>3n. Thus the behavior for m<=3n is identical to the recorded runs.

## Validity / optimum checks

- v34 passed **8,962 exhaustive** small inputs and **480 random** small inputs, with output independently verified and count equal to the exact optimum every time.
- v37 alters only the high-n sparse-workload switch; for n<=1,000 the algorithm is identical to v34. Hence those 9,442 small-case results cover v37's small-case logic.
- v34 passed **9 large structural stress tests**: independent transactions, one shared cell, long chain, 99,999 disjoint 3-cycles, 100,000 disjoint 2-cycles, 5,000-vertex hub, dense clique with one million accesses, high-density random accesses with one million memberships, and 100,000 one-read/one-write sparse random transactions. Known optima attained.
- v37 passed a direct smoke test and selected 100k head-to-head tests; no invalid output was observed.
- A directed rank bias in `reshuffle` (v35) worsened the fixed balanced tests (medium -42, dense -27 compared with the control), so rejected. Increasing pack starts from 4 to 8 (v36) also regressed on the medium 100k input (26,516 -> 26,423), despite a minor dense gain, so rejected.
- Local binaries: `solver_v34_combo`, `solver_v37_selective`. Current deliverable source: `solver_cpp_v37_selective_pack.cpp`.

## Caveats and next action

**No official score for v30/v37 yet.** To exceed the reported 85-point leaderboard mark, v20 needs +0.8936 points; to improve by 1.5 points, 85.6064. This experiment can only establish local heuristic improvements, not a guaranteed contest-score delta. If the contest tester accepts another submission, try v37 as C++17, inspect test-by-test results and peak runtime, and fall back to official v20 on TLE/regressions.

SHA-256 of the local compiled C++ v37 source: `da7da35533845bbc165fbe341ec40e28fa225445ea8e7486d09465a37f990e9f`.
