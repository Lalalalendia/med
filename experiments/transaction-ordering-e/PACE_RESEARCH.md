# Task E: published approaches, research plan (2026-11-21)

## Score context
The contest scores `4*k/n` per evaluated case, 25 scoring cases; known user submissions: v1 51.0772, v2 56.4136 / 100. User reports a leaderboard competitor near 85. The latter demonstrates significant aggregate headroom, but it does **not** give per-instance optima.

## Exact formal equivalence

Construct a directed graph with a vertex per transaction and **only for distinct transactions** `u != v`, an arc `u -> v` iff `R_u intersect W_v != empty`. A chosen set of transactions has a conflict-free order iff its induced digraph is acyclic. Therefore maximum retained transactions = maximum induced acyclic subgraph = `n - min directed feedback vertex set` (DFVS).

**Careful**: if a transaction reads and writes the same cell, that is NOT a self-loop in the competition. Any graph construction that introduces a synthetic `i -> i` can discard valid transactions.

The input has at most 1,000,000 total membership incidences, NOT at most that many graph arcs. One hot memory cell can induce quadratic many arcs. Naively expanding the entire conflict graph will fail on dense cases.

## Related published research (primary papers and public code)

1. PACE 2022: same core DFVS problem; https://pacechallenge.org/2022/ and survey https://doi.org/10.4230/LIPIcs.IPEC.2022.26 .
2. DiVerSeS (PACE 2022 heuristic winner), code https://github.com/swacisko/pace-2022 and methods https://doi.org/10.4230/LIPIcs.IPEC.2022.27 . Key techniques: kernelization (SCC, IN0/OUT0, IN1/OUT1 and stronger rules), agent flow to estimate cycle participation, specialized vertex cover routines for highly bidirected instances, local improvement.
3. DreyFVS (runner-up), code https://github.com/Nanored4498/DreyFVS and paper https://doi.org/10.4230/LIPIcs.IPEC.2022.31 . Initialization with Sinkhorn-Knopp, then vertex swap and ordering perturbations.
4. Hust-Solver (third), paper https://doi.org/10.4230/LIPIcs.IPEC.2022.29 . Simulated annealing and vertex cover for bidirected edges.
5. A PACE survey describes a very actionable **maximum induced acyclic subgraph local search**: given a topological order `T` of selected vertices and a rejected vertex `u`, try an insertion slot `p`. Conflicting selected vertices are (a) writers of cells u reads that appear **before** p, and (b) readers of cells u writes that appear **after** p. Minimize the number of distinct conflicting vertices over slots, compute gain = `1 - conflicts`, and accept even a zero-gain move to escape local minima. The published variants also shift neighboring vertices while maintaining DAG order and periodically randomize a topological order. Original survey above, section 3.2.
6. Mostly bidirected graphs: exact/approximation often reduces to **vertex cover**; see https://doi.org/10.4230/LIPIcs.SEA.2023.10 .

## Why existing v2/v6 approaches lag

- Current solver drops vertices with static degree-based scores; degree is only a proxy for how many cycles a transaction breaks.
- Postprocessing can reinsert rejected vertices **only into the existing topological order**, which may be suboptimal even for the current selected DAG.
- Current experiments decompose by weak undirected connected components; **strongly connected components** are the correct cyclic units. DAG bridges between SCCs need not be optimized jointly.
- Combining best candidates per weak component helps, but can be ineffective on giant components joined by acyclic arcs.
- Current local repair never accepts a neutral swap (gain=0), so it gets stuck at local minima.

## Next experiments — prioritized

1. Build graph statistics without expanding quadratic conflict arcs: count incidences, distinguish hot cells, estimate two-cycle prevalence; compute exact SCC only when safe or using proven self-edge-safe implicit adjacency.
2. Prototype **topological-order perturbation + local exchange** on small instances and compare against exact optimum. For a rejected u, find a slot p minimizing
   `cost(u,p)=|{v selected before p: W_v intersects R_u} union {v selected after p: R_v intersects W_u}|`.
   Use **unique transaction IDs** in counts; duplicated arcs from multiple cells must not overcount. When cost=0 insert for +1; when cost=1, insert u/drop conflicting v (neutral move) and then rerun repair. Bound number of moves by runtime.
3. Compare with 2-cycle-aware heuristics and componentwise exact solving for small SCCs (up to about 12-20, budget dependent).
4. Construct two input categories with provable optimum: oriented DAGs (all n keepable) and groups with known min DFVS (disjoint cycles, planted vertex-cover components). Add counterexamples where fixed topological order prevents reinsertion.
5. Measure PyPy 3.11 wall-time with 4 s limit; retain v2 as safe fallback; independent validation after every attempt. Do not infer official score from synthetic data; submit only promising candidates to judge.

## Results available locally, not yet checked by official judge

A local v6 hybrid (multiple dropping strategies + two repair priorities + weak-component assembly) passed 8,962 exhaustive inputs with 0 suboptimal answers; on 5 independent random seeds of 1,300 small inputs, nonoptimal counts were 13, 17, 12, 15, 23 (max gap 1 vertex). **Those are small synthetic cases**, not evidence of score near 85.

No code from external repositories has been copied. Existing contest code is Python, whereas PACE reference implementations commonly target C++ and much longer time limits.
