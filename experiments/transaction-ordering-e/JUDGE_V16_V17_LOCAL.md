# Task E — official C++ v16 result and local v17 experiment

Date: 2026-11-21. Isolated contest experiment, not a LesHa runtime change.

## Official feedback for v16

- 25 scored tests and one unscored test; all 26 verdicts **OK**.
- Score: **83.3880/100** versus v13b **76.8064/100**, delta **+6.5816**.
- Improved in 13 of 25 scored tests, unchanged in 12, no regressions.
- Peak judge time **2.106 s / 4 s**, peak memory **27.82 MB / 256 MB**.
- The user reports a leaderboard entry near 85. The numerical gap is 1.612 points. Neither 85 nor 100 is a proved instancewise optimum.

## v17: time redistribution instead of wider greedy window

Profiling v16 shows topological reordering yields hundreds of additional retained transactions on dense and medium-density inputs, while the last (expensive) neutral-exchange stage often yields only a few. A naive increase of pack candidate window 24 -> 48/96 regressed on asymmetric cases, therefore was **rejected**.

New candidate solver `solver_cpp_v17_hybrid.cpp`:

- For balanced total read/write counts (ratio at most 3:1), run up to 20 topological reordering attempts; the first four use the original best DAG, later attempts use the most recent best DAG. After each reordering, run re-insertion repair and retain only strict improvements.
- For highly asymmetric counts (ratio above 3:1), preserve the original v16 last-stage policy: four reorderings and then bounded local exchange.
- The chosen subset is independently verified by the existing internal checker. The output always remains a valid previously accepted solution or a strictly longer valid one.
- No use of an explicit quadratic conflict graph.

## Local head-to-head, fixed input bytes

All rows were independently checked for duplicate transactions and forbidden write-before-read conflicts. Results are number of transactions kept, not contest points.

| n | Read/write per transaction | m | v16 k | v17 k |
|---:|---|---:|---:|---:|
| 100000 | 5/5 | 1000000 | 85040 | **86257** |
| 100000 | 5/5 | 100000 | 24031 | **25303** |
| 100000 | 5/5 | 10000 | 4971 | **5315** |
| 100000 | 1/9 | 100 | 9749 | 9749 |
| 100000 | 9/1 | 100 | 9693 | 9693 |
| 100000 | structured stacked SCC | - | 75698 | 75698 |

Additional 12 seeded cases, 25000 transactions each: v17 improved all 6 balanced 5/5 cases (examples: 6007 -> 6386; 1258 -> 1337); asymmetry branch matched v16 (including when experimental unbranched reorderings had regressed).

## Correctness and known-optimum checks

- 8,962 exhaustive small cases: **0 invalid, 0 suboptimal**.
- 1,400 random small cases with exact oracle: **0 invalid, 0 suboptimal**.
- Independent transactions: 100000/100000.
- Long chain: 100000/100000.
- 99,999 vertices in disjoint 3-cycles: 66,666 kept, exact optimum.
- 100,000 vertices in disjoint 2-cycles: 50,000 kept, exact optimum.
- 5,000-vertex common hub: 4,999 kept, exact optimum.
- Full conflict clique on 5000 vertices: 1 kept, exact optimum.
- 1 million read/write incidences tested on dense input: correct.

Local largest measured v17 time in 100k cases was approximately 2.6 s; judge runtime remains unmeasured and CPU profiles can differ.

## Status and next check

**v17 has not been submitted to the official contest judge.** Preserve v16 as the proven 83.3880 submission. Upload `solver_cpp_v17_hybrid.cpp` as C++17, compare all 25 scored cases, especially 17, 22-26. Accept v17 only if overall score improves and time remains under 4 seconds.

No merge, deploy, or production changes.
