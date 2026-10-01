# Validation status

Canonical repository: `Lalalalendia/med`.

Current M0 validation:
- `cargo check --workspace`: required CI gate
- `cargo test --workspace`: required CI gate
- `cargo fmt --all -- --check`: required CI gate
- `cargo clippy --workspace --all-targets -- -D warnings`: required CI gate

Deterministic mesh simulator coverage now includes:
- runtime execution of CoreEffect values;
- simulated durable state and compare-before-write presence commits;
- authenticated two-ended session routing;
- timer delivery with stale-timer tolerance;
- targeted packet drop faults;
- `FailBeforeCommit` and `CommitThenCrash` persistence faults;
- two-node golden flow: successful PING/ACK, dropped ACK, SUSPECT, durable incarnation bump, ALIVE refutation;
- exact trace replay comparison for identical seeds/fault plans;
- deterministic non-cryptographic trace fingerprint.

The simulator milestone is still not complete enough to mark EXP-MESH-SIM-01 PASS. Remaining P0 work:
- canonical protocol/state encoding and cryptographic trace/state digest;
- explicit crash-boundary tests around self-suspicion refutation, not only startup activation;
- restart/session teardown semantics;
- broader liveness invariant/property tests;
- indirect probe path (M1) only after the M0 gates above are complete.
