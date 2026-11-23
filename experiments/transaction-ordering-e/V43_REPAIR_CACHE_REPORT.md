# Task E — v43: cache repair ordering; spend savings on LNS (2026-11-21)

## Status

**Official incumbent is v37 = 84.6956/100**, all 26 tests OK, peak official time 3.547 s of 4 s, peak memory 27.82 MiB. Previously v30 officially scored 84.5624 and v20 scored 84.1064.

**v43 is experimental and has not been submitted to the official judge.** No inference from the local k counts to +0.3, +0.9, or +1.5 official points is warranted.

Source: `solver_cpp_v43_cached_repair.cpp`. SHA-256 (local exact compiled source): `e57f6c2409825d2fd4efab9f7be79a22d072f6ca35c65d7501b2c82aec2ac4dc`.

## Exact algorithm change from v37

Repeated `repair(old, mode=1)` used to:

1. Build the list of all currently excluded vertices.
2. Sort that entire list by **static** `dIn` descending, then ID descending.
3. Use the sorted list to bucket eligible reinsertion candidates into feasible windows.

The key depends only on the transaction, not on the current selected subset. In v43, the exact total order is precomputed **once** after `degrees()`: `repairOrder1`. Every `repair(...,1)` scans it while skipping selected IDs. The order within each bucket is unchanged. Other repair modes retain their original logic.

The spared sorting CPU time is used for up to **3000** final topological reorder / ruin-and-recreate iterations, previously **400** in v37. The *time guard is unchanged*: balanced final stage begins before 3.34 s and checks the elapsed-time cutoff of **3.52 s** between iterations. This is a soft cutoff, **not** a proof of runtime under 4 s on the judge.

No changes to pack, SCC, LNS pattern, feasibility conditions, transaction ordering constraints, or accepted-score objective.

## Local comparisons (identical input data)

k = selected transactions; not points. Timings measured on Linux C++17 `-O2`, subject to time-dependent solver iteration variance.

### 25k inputs, independent random seeds

| Family | Seed | v37 k | v43 k | Difference |
| --- | ---: | ---: | ---: | ---: |
| Balanced 5 reads/5 writes, m=25,000 | 1 | 6786 | 6869 | +83 |
| Balanced 5/5, m=25,000 | 2 | 6793 | 6912 | +119 |
| Balanced 5/5, m=25,000 | 3 | 6786 | 6914 | +128 |
| Balanced 5/5, m=2,500 | 1 | 1426 | 1477 | +51 |
| Balanced 5/5, m=2,500 | 2 | 1423 | 1452 | +29 |
| Balanced 5/5, m=2,500 | 3 | 1444 | 1507 | +63 |

Total medium 20,365 -> 20,695 (+330); dense 4,293 -> 4,436 (+143). All selected transaction sequences were independently validated for duplicates and forbidden write-before-read conflicts.

With a 1400-iteration cap, gains were smaller: medium 6867/6905/6910, dense 1456/1445/1500. Thus recovered time is still useful but marginal returns diminish. The 3000-iteration cap mostly hits the 3.52s soft deadline rather than running all 3000 attempts on expensive inputs.

### 100k fixed inputs

| Family | v37 k | v43 k | Gain |
| --- | ---: | ---: | ---: |
| 5/5, m=100,000 | 26487 | 26659 | +172 |
| 5/5, m=10,000 | 5590 | 5689 | +99 |
| 5/5, m=1,000,000 | 86667 | 86683 | +16 |

Some other repeat runs gave 26482 -> 26655 and 5590 -> 5707 when comparing a 400-iteration cache variant. This is a stochastic, wall-clock-cut-off search; compare multiple runs rather than treating one value as exact expected improvement.

Other families checked with a 400-iteration cache variant: 1/9, m=100 = 9749 both; 9/1 = 9693 both; stacked SCC = 75698 both. They share identical algorithms in v43's asymmetric branch.

### Rejected alternative experiments

- v38: uniformly sample **live-only** vertices (32/64/96/144 draws) instead of 192 random vertex IDs, and compact the ranking at reranks. Improved one 100k medium input but had mixed independent seed outcomes. Not adopted.
- v41: combine live-only sampling and repair cache with extra LNS. Three medium seeds: 6886/6854/6967 vs v40 6867/6905/6910 (mixed); three dense seeds tied v40 exactly. Not promoted.
- v42: contiguous-interval ruin instead of dispersed random deletion on some LNS attempts. All three medium seeds regressed versus v40 (6864/6863/6870 vs 6867/6905/6910). Not promoted.
- Keep old v37 as official fallback until the new judge feedback.

## Correctness

- **8,962 exhaustive small cases**, all outputs valid and equal to the exact independent oracle.
- **480 random small cases**, n up to 12, all valid and exactly optimal.
- **9 large stress cases** independently checked:
  * independent n=100,000: k=100,000 (optimal)
  * single shared cell n=100,000: k=1 (optimal)
  * chain n=100,000: k=100,000 (optimal)
  * 99,999 disjoint 3-cycles: k=66,666 (optimal)
  * 100,000 disjoint 2-cycles: k=50,000 (optimal)
  * hub n=5,000: k=4,999 (optimal)
  * clique of n=5,000, one million accesses: k=1 (optimal)
  * random 100 reads/100 writes with one million accesses: k=2 (correct, optimality not asserted)
  * random one-read/one-write n=100,000, m=1,000,000: k=100,000 (correct).
- Large-stress max observed RSS ~57.4 MiB; local max runtimes on expensive cases ~3.55s.

## Decision

Submit **v43 as C++17** as an independent contest candidate. Compare all 25 scored test points and all time/resource values to official **v37 = 84.6956**. Keep v37 if v43 regresses or exceeds 4s. Do not deploy or merge this experimental branch into the application.
