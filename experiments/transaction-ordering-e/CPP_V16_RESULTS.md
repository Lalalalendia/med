# C++ v16: packing + randomized topological reorder (2026-11-21)

## Official benchmark baseline

Last **official** result: v13b, **76.8064 / 100** over 25 scored cases (all 26 verdicts OK). v12 scored 76.7776 / 100. The reported leaderboard competitor scored approximately 85 / 100. **No official judge result for v16 yet.**

## New idea

The v13b approach favors **deleting** cycle-breaking vertices, then reinserts those compatible with a fixed order. In v16 we also construct an independent solution by **committing** a transaction at either end:

- If an active source exists (no active predecessors), commit it to the left.
- Otherwise, if an active sink exists, commit it to the right.
- When only cycles remain, sample up to 24 currently active candidates of low static degree and compute approximate forward/backward cost from **current** read/write incidence counts.
- Commit the least expensive candidate on the less expensive side and discard only remaining vertices now incompatible with that action.
- Return `left + reverse(right)`; it is a valid order by construction. Independently validate with a write-before-read checker.
- A randomized Kahn topological order is also generated for the selected DAG; a postpass then attempts to reinsert rejected transactions in different orderings.
- If packing improves the best score by **more than 2%**, skip a costly dynamic-degree peeling pass. This frees CPU time for SCC-based assembly and later local-search refinement.

The graph is implicit and never materializes all edges for a hot memory location.

## Local head-to-head on six 100k/large cases

Results are from fixed generated input files and independently verified conflict-free; CPU wall times can affect heuristics due to time-budget branching. All scores shown below are **number of transactions retained**, not competition points.

| Case | v13b | v16 | Gain |
|---|---:|---:|---:|
| n=100000, r5/w5, m=1,000,000 | 84,331 | 85,040 | +709 |
| n=100000, r5/w5, m=100,000 | 21,695 | 24,031 | +2,336 |
| n=100000, r5/w5, m=10,000 | 4,344 | 4,971 | +627 |
| n=100000, r1/w9, m=100 | 9,474 | 9,749 | +275 |
| n=100000, r9/w1, m=100 | 9,510 | 9,693 | +183 |
| n=100000, stacked SCCs | 75,698 | 75,698 | unchanged |

Nominal local wall time was around 0.9–2.7 s on these samples. The official platform's 4 s limit still requires separate verification.

## Secondary seeded tests

On 12 independent generated 25k-transaction inputs (3 seeds each for 4 families), v16 beat v13b in all 12 and never failed the independent checker.

Sample: n=25000, m=25000, r5/w5:
- seed0: 5,350 -> 6,007
- seed1: 5,472 -> 5,973
- seed2: 5,476 -> 5,995

At n=25000, m=2500, r5/w5:
- seed0: 1,107 -> 1,258
- seed1: 1,100 -> 1,270
- seed2: 1,097 -> 1,264

## Correctness and known optima

- 8,962 exhaustive small inputs: zero invalid, zero suboptimal (exact oracle).
- 1,400 randomized small inputs up to 14 vertices: zero invalid, zero suboptimal (exact oracle).
- 100k disconnected vertices: 100,000 / 100,000.
- 100k-node chain: 100,000 / 100,000.
- 100k all reading and writing one cell: 1 / 1.
- 99,999 vertices in disjoint 3-cycles: 66,666 / 66,666.
- 100k vertices in disjoint 2-cycles: 50,000 / 50,000.
- 5000-vertex shared hub: 4,999 / 4,999.
- 5000 vertices each reading and writing the same 100 cells (1 million incidences): 1 / 1.

The stress cases with random 100/100 accesses and random sparse 1/1 accesses were also valid. **These do not establish an upper bound for the hidden contest tests.**

## Reproduce

From this directory:

```bash
g++ -O3 -std=c++17 -pipe solver_cpp_v13b.cpp -o solver_cpp_v13b
g++ -O3 -std=c++17 -pipe solver_cpp_v16.cpp -o solver_cpp_v16
./solver_cpp_v16 < sample.in > sample.out
```

Source blob SHA (Git): `d76c602b12cf061bcad5336027c489f0eaaf501f`, matches the locally compiled source byte-for-byte. SHA256: `e033597034a9194ab896de59d3eb03001ad6fe7193e63f23a9f30ed54156b9d8`.

This is a **draft experiment**, not a merged product change. `med/main` and all production services remain untouched.
