# Task E — official v43 and neutral plateau walk v46 (2026-11-21)

## Official score

**C++ v43 officially scored 84.7140/100**, all 26 tests OK; peak time **3.551s / 4s**, peak memory **28.32 MB / 256 MB**.

Previous record v37 was **84.6956**. Improvement **+0.0184** from changes in only three scored tests:
- Test 22: 3.3284 → 3.3428 (**+0.0144**).
- Test 24: 3.3460 → 3.3476 (**+0.0016**).
- Test 25: 3.4064 → 3.4088 (**+0.0024**).
- Test 23: **3.2872 unchanged**, all others unchanged.

Notice v43's extended LNS loop caused some low-scoring tests to consume much more CPU without any score gain (e.g. test 13: 1.774s; test 17: 3.527s). Increasing final iteration count further is not the best next step. The confirmed gap to 85 points is **0.2860**.

## Proposed v46: neutral and near-neutral incumbent walk

Source: `solver_cpp_v46_neutral_walk.cpp`. Local exact SHA256: `d3bc910491b3571baa84543d0874e9e2157663426aacc80998d4d2d92ed85b0a`.

The old final phase of v43 always performed topological reorders and ruin/recreate from **the all-time best sequence**, and retained only strictly larger solutions.

v46 maintains two sequences:
- `best`: globally largest valid solution, used for the final output (never overwritten by an equal/worse sequence).
- `current`: temporary search state. After the first four modes, reorders and ruins sometimes run on `current`. Accept `current` states within **one transaction** of `best` as opportunities to traverse a flat local neighborhood. Restart `current` from `best` every 29 attempts.

On each iteration, accept the outcome into `best` only if its length is strictly greater; otherwise use selected neutral/slightly-worse outcomes to continue exploring. Existing feasibility-preserving repair and DAG reorder routines are unchanged, as are the contest output and time budget: **final deadline remains 3.52s**.

## Independent 25k input benchmarks (v43 vs v46)

All 12 tests independent; same exact input bytes per pair, independent solution verifier. These are **retained transaction counts, NOT judge points**.

### Medium-density balanced 5/5, n=25000, m=25000

| Seed | v43 k | v46 k | Gain |
|---|---:|---:|---:|
| 1 | 6872 | 6976 | +104 |
| 2 | 6912 | 6951 | +39 |
| 3 | 6914 | 6990 | +76 |
| 4 | 6845 | 6967 | +122 |
| 5 | 6894 | 6978 | +84 |
| 6 | 6898 | 6973 | +75 |
| **Sum** | **41335** | **41835** | **+500** |

### High-density balanced 5/5, n=25000, m=2500

| Seed | v43 k | v46 k | Gain |
|---|---:|---:|---:|
| 1 | 1477 | 1492 | +15 |
| 2 | 1453 | 1499 | +46 |
| 3 | 1506 | 1528 | +22 |
| 4 | 1465 | 1503 | +38 |
| 5 | 1471 | 1522 | +51 |
| 6 | 1488 | 1521 | +33 |
| **Sum** | **8860** | **9065** | **+205** |

All **12/12** seeded tests improved, total **+705** retained vertices. This is a strong signal on these random-generator families, but their structure may differ from hidden judge tests.

### Fixed n=100000 test files

Representative paired runs:

| Input | v43 k | v46 k | Gain |
|---|---:|---:|---:|
| 5+5, m=100000 | 26607 | 26625 | +18 |
| 5+5, m=10000 | 5692 | 5672 | -20 |
| 5+5, m=1000000 | 86683 | 86667 | -16 |
| 1 read/9 writes m=100 | 9749 | 9749 | 0 |
| 9 reads/1 write m=100 | 9693 | 9693 | 0 |
| Stacked SCC n=100000 | 75698 | 75698 | 0 |

For 100k balanced inputs the solver uses a wall-clock cutoff; repeated v43 runs have shown fluctuations of dozens of vertices. The small positive/negative deltas in this table do not establish a reliable gain or regression.

## Correctness

- **8,962 exhaustive small instances** versus the independent exact oracle: valid output and optimal count on every case.
- **480 seeded random small instances**: 100% valid and optimal; combined **9,442** small cases.
- **9 structural large stress instances**: independent transactions, one-cell clique, long chain, disjoint 2-/3-cycles, a shared hub, 5000-vertex dense clique with one million membership occurrences, random 100 reads/100 writes with one million memberships, and 100k random one-read/one-write sparse. All outputs valid, all known exact optima achieved. Maximum observed stress memory ~57.5 MiB.
- Locally expensive runs last ~3.53–3.63s; official 4s judge bound **not verified** for v46.

## Rejected earlier attempt

v44 attempted targeted insertion of an excluded transaction after removing its minimum-conflict blocking selected vertices. It had a mixed/negative result on 25k medium inputs (+26/-17/-20) and 100k dense (-119). A dense-only condition v45 still underperformed on the large dense fixed case. They are not promoted.

## Decision

v43 (**84.7140** officially) is the confirmed fallback. v46 is a **new experimental C++17 submission candidate** with held-out 25k wins but no official score, and time-sensitive mixed n=100k results. Submit to judge and evaluate all 25 scores and TLE; preserve v43 if the result is not superior. Do not merge the experiment into `main` or deploy.
