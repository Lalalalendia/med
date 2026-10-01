# Validation status

Canonical repository: `Lalalalendia/med`.

Peer/Mesh M0 strict CI validation:
- validated source HEAD: `a3f9aa9f06f756dbefa7b285acf15b1f4b9d2df9`
- GitHub Actions run: `36915270138`
- `cargo check --workspace`: PASS
- `cargo test --workspace`: PASS
- `cargo fmt --all -- --check`: PASS
- `cargo clippy --workspace --all-targets -- -D warnings`: PASS

Deterministic mesh simulator coverage now includes:
- runtime execution of `CoreEffect` values;
- simulated durable state and compare-before-write presence commits;
- authenticated two-ended session routing;
- timer delivery with stale-timer tolerance;
- targeted packet-drop faults;
- `FailBeforeCommit` and `CommitThenCrash` persistence faults;
- two-node golden flow: successful PING/ACK, dropped ACK, SUSPECT, durable incarnation bump, ALIVE refutation;
- exact trace replay comparison for identical seeds/fault plans;
- deterministic non-cryptographic trace fingerprint;
- startup crash boundaries around durable incarnation activation;
- self-suspicion refutation crash boundaries:
  - fail-before-commit never emits an uncommitted ALIVE;
  - commit-then-crash never emits the committed-but-unacknowledged incarnation and restart advances to the next incarnation;
- simulated process crash tears down both authenticated link endpoints and surfaces `SessionClosed(TransportLost)` to the peer.

The simulator milestone is still not complete enough to mark EXP-MESH-SIM-01 PASS.

Remaining P0 work:
- integrate/rebase the Storage M0 draft so Peer Core can reuse the shared `lesha-canonical` crate;
- define canonical peer message/state/effect encoding and cryptographic trace/state digest;
- add explicit re-authentication/reconnect scenario after process restart;
- broaden liveness invariant/property tests: membership immutability, stale events, generation isolation, monotonic incarnation and multi-seed deterministic repetitions;
- freeze a golden trace root only after canonical encoding is in place.

M1 indirect probes / ActiveView / PassiveView remain blocked until these M0 gates are complete.
