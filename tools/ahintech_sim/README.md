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
| `diagnostics.py` | Rigorous (usually loose) upper bound from individually reachable device-hour activation states. Computation is capped to avoid dense-graph blowups. |
| `bench.py` | Compile C++23 candidates, run with a 2-second wall-time and 256 MiB address-space cap, validate outputs, report performance and activation counts. |
| `solvers/` | Historical V12 Cache and V21 P0 plus experimental V24 (reachable-component and temporal-state reduction). |
| `tests/` | Parser, boundary, rule-enforcement and exact-oracle tests. |

## GitHub Actions

Workflow: **Ahintek B - offline simulation** (`.github/workflows/ahintech-b-offline-simulation.yml`).

* Runs on PRs touching only this laboratory and on manual `workflow_dispatch`.
* Manual inputs: `suite` (`smoke` / `standard` / `stress` / `paired`), and reproducible integer `seed`. The `paired` suite appends 150 unreachable devices to each base case; optimal score is invariant under this transformation.
* Runs unit tests, generates cases, compiles V12/V21/V24, independently validates their output, and uploads inputs, SHA-256 manifest, per-case CSV/JSON, Markdown report and failing outputs as an artifact (30 days).
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
  --solver v24=tools/ahintech_sim/solvers/v24_reachable.cpp
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
