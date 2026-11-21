# Task E — v19 official result and v20 extended time box (2026-11-21)

## Official results

- v18 C++17: **84.0608 / 100**.
- v19 C++17: **84.0608 / 100**, exactly the same scores across all 25 scored test cases (case 1 unscored), all 26 `OK`.
- Maximum v19 judge wall time: **2.249 s**; maximum v18 judge wall time: **2.307 s**. The difference is too small to infer speed gains.
- Small SCC post-exact phase did not improve hidden tests. Stop prioritizing exact SCC expansions for this contest.

## v20 algorithm

File: `solver_cpp_v20_extended.cpp` (SHA-256 `ff173bcb8341a4c910588a323d76c82d92aceadea21f2125291e9d52a1831760`).

Identical to the proven v18 algorithm **except** the final balanced-case random DAG reorder + reinsertion loop now uses up to 130 iterations and a 3.60-second local cutoff, versus 65 iterations with a 3.12-second cutoff. Asymmetric cases retain original v18 logic. All solutions are checked by the existing independent verifier. Best-result-only updates avoid decreasing selected count within a given run, but time-based termination can make comparisons slightly nondeterministic across separate runs.

## Local comparison (same fixed data files, C++17 -O2)

| Case, 100,000 transactions unless otherwise noted | v18 retained | v20 retained | Delta |
|---|---:|---:|---:|
| random 5/5, m=1,000,000 | 86,511 | 86,713 | +202 |
| random 5/5, m=100,000 | 25,619 | 25,653 | +34 |
| random 5/5, m=10,000 | 5,408 | 5,427 | +19 |
| random 1/9, m=100 | 9,749 | 9,749 | 0 |
| random 9/1, m=100 | 9,693 | 9,693 | 0 |
| stacked SCC, n=100,000 | 75,698 | 75,698 | 0 |

The result changes slightly on repeated runs (cutoff depends on wall time). A random-Kahn traversal variant and a late global exchange variant were also tested and were weaker than simply adding more existing topological reorder attempts.

## Correctness

- Exhaustive 8,962 cases: **0 invalid, 0 suboptimal**.
- Random 1,400 small cases: **0 invalid, 0 suboptimal** against the exact oracle.
- Nine stress scenarios: independent n=100k, single-cell clique n=100k, chain n=100k, 3-cycles n=99,999, 2-cycles n=100k, hub n=5k, clique dense with 1m memberships, random 100 reads+100 writes with 1m memberships, sparse n=100k. All passed validation; known optima reached.

## Performance and risk

On the local Linux machine, v20 takes **up to 3.7-3.75 seconds** on 100k balanced inputs. This comes close to the contest's 4-second limit, though the contest previously measured v18 at <=2.307 seconds. Runtime on the contest machine remains **unverified** and TLE is possible.

The synthetic gain is modest. **Do not imply v20 will yield +0.94 or +1.2 official points.** The supported expectation is only that extending a previously effective finishing strategy is worth a final trial. Submit v20 as C++17 while retaining v18 as the proven 84.0608-point fallback.

No deployment, merge, or main changes.
