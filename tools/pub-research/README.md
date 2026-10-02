# PUB research harness

This directory contains two deterministic research compilers for Microsoft Publisher experiments.
It is intentionally isolated from the LesHa product crates.

## 1. TLB experiment compiler

`tlb_experiment_compiler.py` converts a machine-readable MSPUB.TLB inventory into a
conservative experiment matrix.

It does **not** launch Publisher and does **not** claim on-disk semantics.

Default admission:

- PROPERTYPUT / PROPERTYPUTREF only;
- scalar numeric, bool, or enum/user-defined values;
- hidden/restricted/nonbrowsable members excluded unless explicitly requested;
- names associated with destructive/lifecycle operations excluded;
- object references, arrays, pointers, VARIANT and strings excluded from the automatic queue.

Every emitted experiment has:

1. control: no semantic mutation → Save → Close → Reopen;
2. same-value: read current → set same value → Save → Close → Reopen;
3. changed-value: bounded alternate value → Save → Close → Reopen.

Example:

```bash
python tools/pub-research/tlb_experiment_compiler.py \
  path/to/inventory.json \
  --out out/tlb-experiments.json
```

Hidden members require an explicit flag:

```bash
python tools/pub-research/tlb_experiment_compiler.py \
  path/to/inventory.json \
  --include-hidden \
  --out out/tlb-hidden-experiments.json
```

The generated matrix is a hypothesis queue only. Promotion requires a native
Publisher Save/Close/Reopen result, reopened semantic observation, and persisted
stream/range attribution.

## 2. Operation algebra

`operation_algebra.py` generates high-information A→B versus B→A transition
experiments from a declarative operation catalog.

Generation:

```bash
python tools/pub-research/operation_algebra.py generate \
  tools/pub-research/examples/operations.json \
  --out out/operation-pairs.json
```

The generator excludes declared destructive, external-state, nondeterministic, or
high-risk operations. It prefers pairs that touch the same semantic target or are
tagged as style/precedence/inheritance/materialization/layout candidates.

Each pair contains:

- A→B → Save → Close → Reopen;
- B→A → Save → Close → Reopen;
- A-only;
- B-only;
- control.

After an external native harness captures reopened semantic, persistence, and render
fingerprints, classify the result:

```bash
python tools/pub-research/operation_algebra.py classify \
  results.json \
  --out out/operation-verdicts.json
```

Verdicts:

- `commute_exact_after_reopen`: semantic + persistence + render all agree;
- `semantic_commute_persistence_diverges`: final semantics agree, stored bytes/projections differ;
- `renderer_or_derived-state_divergence`: semantic + persistence agree, render differs;
- `non_commutative_semantic_or_hidden_precedence`: final semantics differ;
- `inconclusive`: missing/failed arm.

The particularly valuable case is semantic convergence with persistence divergence:
it isolates lifecycle/normalization/allocation/derived-state baggage from semantic
authority.

## Validation

```bash
python -m unittest discover -s tools/pub-research -p "test_*.py" -v
```

No Publisher binaries, PDBs, or proprietary artifacts belong in this repository.
Only derived metadata, experiment specs, and receipts should be committed.
