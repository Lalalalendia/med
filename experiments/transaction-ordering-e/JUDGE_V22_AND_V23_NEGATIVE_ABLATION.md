# Task E — official v22 and local v23/v24 ablations

Date: 2026-11-21. Contest score per scored test = 4*k/n. 25 scored tests, test 1 unscored.

## Official v22 vs v20

- **v20 official: 84.1064** — best confirmed score so far.
- **v22 official: 84.1060** — all 26 verdicts OK.
- Exactly one difference: test 25: 3.3872 (v20) -> 3.3868 (v22); delta -0.0004.
- Maximum time v22: 3.625s/4s; v20: 3.614s/4s; maximum memory <=27.82 MB in both.
- The 97..128 SCC local search patch helped some constructed instances but did not increase the official score. Retain v20 as best official.

## Local experiment v23: remove incorrect overcount cutoff in exchange()

Original exchange() checks bound = sum of selected writer/reader *incidences* for all read/write cells and skips candidates when bound >192. This counts the same selected transaction repeatedly. Candidate version first screens with the existing cheap count; only if it exceeds 192, it scans selected adjacency using epoch-stamped vertex IDs and stops after 193 *distinct* vertices. If distinct count <=192, evaluate the candidate with the original event sweep.

All outputs passed an independent validity checker. Same input bytes on Linux C++17 -O2:

| Family | v20 kept | v23a kept | v20 elapsed | v23a elapsed |
|---|---:|---:|---:|---:|
| n=100000, r1/w9, m=100 | 9749 | 9749 | 1.119s | 1.252s |
| n=100000, r9/w1, m=100 | 9693 | 9693 | 1.060s | 1.177s |
| n=100000, r5/w5, m=100000 | 25672 | 25659 | 3.670s | 3.645s |
| n=100000, r5/w5, m=10000 | 5433 | 5430 | 3.626s | 3.620s |
| n=100000, r5/w5, m=1000000 | 86638 | 86683 | 3.742s | 3.716s |
| n=100000, stacked SCC | 75698 | 75698 | 1.963s | 1.986s |

**Interpretation:** no robust improvement. The balanced branch never calls exchange() in original v20, so small balanced differences are caused by time-sensitive execution/RNG conditions, not by the corrected bound itself. The asymmetric branch's actual affected cases showed no gain and slightly more runtime. Keep patch experimental, not a contest candidate.

Also tried running one bounded exchange() *after* balanced DAG reorderings, only when elapsed <3.20. It did not show stable improvement on the six test inputs and usually cannot run when the final reordering exhausts the time budget. Not promoted.

## Local experiment v24: randomized GRASP-like tie breaking in pack()

Replace only the second pack() variant's equal-cost ties with a reproducible random 0..15 perturbation after multiplying the original integer cost by 16.

| Family | v20 kept | v24 kept |
|---|---:|---:|
| r1/w9, m=100 | 9749 | 9749 |
| r9/w1, m=100 | 9693 | 9693 |
| r5/w5, m=100000 | 25665 | 25613 |
| r5/w5, m=10000 | 5433 | 5436 |

No stable improvement; the 52-transaction regression on m=100000 is larger than the small gain on m=10000. Not promoted. Additional independent seeds would be needed before drawing distributional conclusions.

## Decision

Do **not** submit v22, v23 or v24 as score-improving solutions based on these experiments. Continue to use v20 (84.1064) as official incumbent. Future development should target algorithmic changes with sufficiently large gains to justify performance/TLE risk; v20 has only 0.386s headroom on its worst official test.

No merge, no deployment, no modifications to main.
