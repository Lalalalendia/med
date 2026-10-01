# Validation status

Canonical repository: `Lalalalendia/med`.

GitHub Actions validation for the M0 baseline:
- `cargo check --workspace`: passed
- `cargo test --workspace`: passed
- `cargo fmt --all -- --check`: advisory during M0
- `cargo clippy --workspace --all-targets -- -D warnings`: advisory during M0

M0 is now compile/test validated on GitHub-hosted Rust. Deterministic replay, crash-boundary tests, canonical state hashing, and the full simulator remain open before EXP-MESH-SIM-01 can be marked PASS.
