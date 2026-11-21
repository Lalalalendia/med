# Ahintek B: reproducible offline contest laboratory

This directory implements a **purely numerical simulation** of the programming
contest task "Самораспространяющийся вирус". It does not implement malware,
network traffic, installation, persistence or communication with any real device.

## Components

| File | Responsibility |
| --- | --- |
| `model.py` | Formal input specification and independent validation of every reported transmission. Supports repeated activations, cyclic work windows, instant sends, quota `k` and simultaneous arrivals. |
| `generator.py` | Deterministic input generator, seed-driven families (ring, star, hubs, dense, communities, phase traps, disconnected). Enforces `N*m <= 1e6` and at most `5e5` undirected edges. |
| `oracle.py` | Exponential *exact* solver for tiny instances (`n<=6, m<=14`) for checking heuristic gaps. |
| `milp_oracle.py` | Optional SciPy/HiGHS exact time-expanded integer program; provides optimal witnesses and certified upper bounds on small/medium instances. |
| `diagnostics.py` | Rigorous (usually loose) upper bound from individually reachable device-hour activation states. Computation is capped to avoid dense-graph blowups. |
| `bench.py` | Compile C++23 candidates, run with a 2-second wall-time and 256 MiB address-space cap, validate outputs, report performance and activation counts. |
| `solvers/` | Historical V12 Cache and V21, V24 reachability reduction, V27 exact state-DP to 12 nodes, V29 one-hour subset beam, and V32 early wide beam with expanded exact search. |
| `tests/` | Parser, boundary, rule-enforcement and exact-oracle tests. |

## GitHub Actions

Workflow: **Ahintek B - offline simulation** (`.github/workflows/ahintech-b-offline-simulation.yml`).

* Runs on PRs touching only this laboratory and on manual `workflow_dispatch`.
* Manual inputs: `suite` (`smoke` / `standard` / `stress` / `paired` / `research`), and reproducible integer `seed`. The `paired` suite appends 150 unreachable devices to each base case; optimal score is invariant under this transformation.
* Runs unit tests, generates cases, compiles V12/V21/V24/V27/V29, independently validates output, and uploads inputs, SHA-256 manifest, per-case CSV/JSON, Markdown report and failing outputs as an artifact (30 days).
* The `research` suite installs SciPy and runs an optional MILP oracle with a four-second per-case ceiling, reporting certified optima when found. Default smoke CI does not need SciPy.
* Uses `permissions: contents: read`. No tokens, secrets, external network, or mutation of the rest of the repository are required.

## Local reproduction

From the repository root:

```bash
python3 -m unittest discover -s tools/ahintech_sim/tests -v
python3 tools/ahintech_sim/generator.py --suite standard --seed 20261121 --out /tmp/ahintech_cases
python3 tools/ahintech_sim/bench.py --cases /tmp/ahintech_cases --out /tmp/ahintech_results \
  --time-limit-ms 2000 --memory-mb 256 --oracle --reachability-bound \
  --solver v12=tools/ahintech_sim/solvers/v12_cache.cpp \
  --solver v21=tools/ahintech_sim/solvers/v21_p0.cpp \
  --solver v24=tools/ahintech_sim/solvers/v24_reachable.cpp \
  --solver v27=tools/ahintech_sim/solvers/v27_exactmedium.cpp \
  --solver v29=tools/ahintech_sim/solvers/v29_subset_beam.cpp \
  --solver v32=tools/ahintech_sim/solvers/v32_certified_beam.cpp
```

Add a candidate with another `--solver name=/path/to/solution.cpp` argument.
To validate a single output in Python:

```python
from pathlib import Path
from tools.ahintech_sim.model import Problem, validate_output
p = Problem.parse(Path('case.in').read_bytes())
print(validate_output(p, Path('case.out').read_bytes()))
```

## Rules and methodology

The initial activation occurs at absolute time `x`; subsequent send times in the
answer are also **absolute**, not relative offsets. A receiver `v` starting at
`s` succeeds if `(s-a[v]) mod 24 + t[v] <= b[v]`, and `s+t[v] <= x+m-1`.
On an active source event, at most `k` different adjacent recipients can be
selected. A device can be reinfected after its prior unpacking completes.
Successful output lines can be unordered; the validator sorts them by send time.

**This is NOT the official judge.** Generated graphs and the "ratio to best
tested solver" are a comparative research metric, not the hidden competition
distribution or the official scoring formula. In particular, `n*m <= 1e6`
bounds the number of device-hour states, **not** the total number of graph edge
visits performed by an algorithm. The wall-time cap is measured by the runner,
which may differ from the contest's CPU-time accounting.

To improve reproducibility, publish the test seed, input SHA-256 manifest,
solver commit SHA, raw activation counts, validation results, runtime and RSS.
Compare new policies on both a development set and a disjoint hold-out set.

## V24 experimental optimization

V24 first compresses the graph to the connected component of `p`. When a
bounded forward search in the time-expanded DAG finishes, it can also eliminate
all vertices with no possible successful activation from `(p,x)`. The relaxation
ignores occupancy and `k` (both can only remove paths), so removed vertices
cannot affect the optimal score. It can shorten a provably dead tail of the
horizon as well. Original input device IDs are restored when outputting events.

**Proof does not imply that a heuristic solution is monotone across arbitrary
relabelings.** V24 uses conservative thresholds before applying temporal
compression to avoid changing small components for marginal reductions.
Test with fresh seeds and the independent validator before treating it as a
candidate for the judge. No claim is made that V24 is globally optimal.

To reproduce adversarial unreachable-padding pairs:

```bash
python3 tools/ahintech_sim/generator.py --suite paired --seed 20261121 --out /tmp/ahin_pairs
```

If `--reachability-bound` is enabled, reports include a rigorous per-case
state-reachability upper bound (or a blank when work is capped). This bound
relaxes collisions and sender quotas and may be far above the real optimum.

## Exact-teacher experiments (V27/V29)

The `tests/cases/dev_gap_*.in` files are synthetic **development/regression** fixtures, not a hidden-test distribution or independent hold-out. Their `*.opt.out` witnesses and `certified_optima.json` were generated by SciPy HiGHS MILP with proof of optimality; the independent validator checks the witnesses.

| Fixture | Certified optimum | V24 | V27 | V29 | V32 |
|---|---:|---:|---:|---:|---:|
| `dev_gap_seed12_n9_m60` | 52 | 49 | 49 | 49 | **52** |
| `dev_gap_seed18_n7_m30` | 56 | 55 | 55 | **56** | **56** |
| `dev_gap_seed19_n11_m30` | 39 | 35 | **39** | **39** | **39** |

V27 extends the small-component exact state DP to `n<=12` using collision-free `(hour, packed remaining times)` keys and a fixed 0.19-second search cap. It falls back to V24 when exact computation cannot finish. V29 additionally explores full feasible **target subsets** via a capacitated matching DP inside a bounded, time-aware beam (at most ten vertices and 120 hours). This can choose fewer recipients now to prevent conflicts later. The exact solver is genuinely optimal only when it completes; V29 is still heuristic.

To run the optional exact MILP on generated research cases:

```bash
python3 -m pip install scipy
python3 tools/ahintech_sim/generator.py --suite research --seed 20261121 --out /tmp/ahin_research
python3 tools/ahintech_sim/bench.py --cases /tmp/ahin_research --out /tmp/ahin_research_out \
  --milp --milp-time-limit 4 --oracle --reachability-bound --fail-on-invalid \
  --solver v24=tools/ahintech_sim/solvers/v24_reachable.cpp \
  --solver v29=tools/ahintech_sim/solvers/v29_subset_beam.cpp \
  --solver v32=tools/ahintech_sim/solvers/v32_certified_beam.cpp
```

A valid strategy may still be below the certified optimum; do not interpret wall-clock budget use or generated-case activation gains as official contest scores.

V32 raises the exact DP transition/state exploration caps without increasing its 0.19-second deadline, which solves more small instances outright. It prioritizes a wider exact-subset beam (1024 states for `n<=9`, 256 for `n=10`) before randomized greedy restarts, under its own interruptible wall-clock limit. The three certified fixture scores sum to 147 for V32 versus 139 for V24. This is an intentionally small *development* sample, not an estimate of hidden judge performance.

## V33: counterfactual ejection and suffix reconstruction

V33 preserves V32's exact small-graph and subset beam searches. During
large-neighborhood search, a subset of trials now samples one *actual*
incumbent transmission, freezes earlier transmissions, **forbids the sampled
recipient for that one hour**, and reconstructs the suffix with a different
policy. Unlike simply randomizing a suffix, this forces the solver to try a
structurally different branch. Only schedules with more successful activations
replace the current incumbent.

Development (seed 20261124) and held-out (seed 20261125) workloads were
generated with `counterfactual.py`. At the same 0.65s budget on 32 development
cases V33 added 422 activations vs V32 (13 wins, 0 losses); at the full 2s
budget on 32 separate evaluation cases it added 262 activations (19 wins,
0 losses). These are **synthetic activation counts, not official contest
points**. The six existing stress scenarios passed independent validation
and had the same counts as V32. The V33 candidate has not been officially
scored.

Run a reproducible subset locally:

```bash
python3 tools/ahintech_sim/counterfactual.py --seed 20261125 --count 16 --out /tmp/ahin_v33
python3 tools/ahintech_sim/bench.py --cases /tmp/ahin_v33 --out /tmp/ahin_v33_results \
  --time-limit-ms 2000 --memory-mb 256 --fail-on-invalid \
  --solver v32=tools/ahintech_sim/solvers/v32_certified_beam.cpp \
  --solver v33=tools/ahintech_sim/solvers/v33_ejection_lns.cpp
```

For the same workload in GitHub Actions select `counterfactual` in
`workflow_dispatch`. Full 32-case research evaluation can be run locally
with `--count 32`. This is a validation suite, not evidence of hidden-test
generalization.

## Periodic-orbit research: a different algorithmic model

Use `periodic_oracle.py` + `bridge_oracle.py` to separate **long-run
throughput** from **reachability from one initial activation**.

The stationary HiGHS MILP uses binary variables `y[v,h]` for active copies
and `z[u,v,h]` for transmissions at hour `h` modulo 24. The constraints
require: each active copy has exactly one incoming copy from the preceding
period; sender quota `k` holds for every activation; and processing intervals
on each receiver never overlap, including across midnight. The objective
maximizes completions in **one repeating 24-hour period**.

This is **not an upper bound for an arbitrary finite horizon**, and a period
may be impossible to reach from the initial copy. E.g. a single initial
copy with `k=1` cannot produce two independent circulating copies, but the
stationary model may admit two such cycles without a specified bootstrap.

The `bridge_oracle.py` MILP therefore enforces the original single-copy start,
then requires the chosen stationary transmissions after a specified join hour.
A bridge is independently validated against the original contest constraints;
if found, it is a **valid finite-horizon strategy**. A missing bridge does not
prove the 24-hour rate unachievable: the optimizer might have chosen a different
equally good orbit, or the provided join time may be wrong.

### Reproduce the breakthrough experiment

```bash
python3 -m pip install scipy==1.14.1
python3 -m unittest discover -s tools/ahintech_sim/tests -p 'test_periodic_research.py' -v
python3 tools/ahintech_sim/periodic_study.py --seed 20261125 \
  --indices 1,9 --horizons 96,144 --out /tmp/ahin_periodic
```

The first synthetic graph (30 devices, `k=4`) has a certified stationary
rate of **205 completions per 24 hours**. A feasible bridge solution scores
**792 vs V33's 735** over 96 hours and **1202 vs V33's 1109** over 144
hours (local SciPy/HiGHS run). Other graphs exhibit much smaller gains or
unreachable templates. Every witness is validated independently.

Manual and PR testing: `.github/workflows/ahintech-b-periodic-research.yml`.
The normal 2-second C++ contestant does not call SciPy or this MILP; finding
a fast online approximation to the repeating orbit and its bootstrap was
the motivation for the standalone V38 experiment below; it is not a claim of optimality.

## V38: causal closed-day planning in standalone C++23

`solvers/v38_periodic_bridge.cpp` implements a new **self-contained**
C++23 heuristic. It requires no external MILP solver and has the same
2-second / 256-MiB judge limits as V33.

For selected long-horizon small-to-medium graphs, it:

1. Builds a feasible incumbent by retaining the V33 exact/beam/greedy/LNS core.
2. Chooses an interior day boundary and reads the state of every computer:
   idle, just activated, or hours remaining until activation.
3. Computes shortest causal paths from currently scheduled activations in a
   **24-hour time-expanded graph**. A randomized, backtracking planner
   reserves *all mandatory predecessor chains* needed to reproduce the
   identical state 24 hours later.
4. Fills remaining send capacity chronologically, never overlapping these
   reserved chains; optional transmissions must finish before the day ends.
5. Repeats the verified closed 24-hour pattern. An induction on day-boundary
   states proves the repeated schedule feasible; late transmissions that
   cannot finish before the global horizon are omitted.
6. Retains the incumbent unless a proposed full-horizon schedule has more
   successful activations. A brief probe examines several possible day
   boundaries. If no improvement is found, remaining CPU budget returns to
   the V33 LNS instead of being wasted on an unsuitable periodic strategy.

The exact MILP is a *research teacher*, not used at judge time. The periodic
heuristic is bounded to `n<=64`, `n*m<=30000`, `edge2<=1000`, sufficiently
long horizons and `k>=2`; all other inputs use the V33 policy. On supported
inputs the split between V33 and periodic optimization depends on horizon.
The output remains independently checked by `model.validate_output`.

### Reproduce

```bash
python3 -m unittest discover -s tools/ahintech_sim/tests -p test_cpp_periodic_bridge.py -v
python3 tools/ahintech_sim/counterfactual.py --seed 20261129 --count 12 --out /tmp/ahin_v38_cases
python3 tools/ahintech_sim/bench.py --cases /tmp/ahin_v38_cases \
  --out /tmp/ahin_v38_results --time-limit-ms 2000 --memory-mb 256 \
  --fail-on-invalid \
  --solver v33=tools/ahintech_sim/solvers/v33_ejection_lns.cpp \
  --solver v38=tools/ahintech_sim/solvers/v38_periodic_bridge.cpp
```

On the **synthetic development** instance `index1_n30_m144_k4` V33 yielded
1109 and V38 yielded **1181** valid activations, in around 1.8 seconds.
A separate held-out family with seed `20261129` yielded improvements on
some cases and ties on others; **these counts are not official competition
points**. CPU scheduling can affect results of time-bounded stochastic
heuristics. Official hidden test inputs are unavailable.


## V51: temporal deferral

See [the V51 method](docs/v51_temporal_separation.md). This standalone C++23 variant can omit a current transmission when a scheduled future sender offers a better recipient activation phase. Its ablation test verifies the mechanism. The `temporal` workflow suite provides reproducible synthetic comparisons; official score unknown.
