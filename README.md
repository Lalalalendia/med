# LesHa

Canonical implementation workspace for the LesHa local-first resilient medical information system.

## Current milestone

M0: deterministic Peer Manager core and simulator substrate.

Workspace crates:

- `lesha-types` — typed identities and monotonic time values
- `lesha-peer-core` — deterministic event/effect state machine
- `lesha-mesh-sim` — virtual clock, event queue, durable-state and trace scaffolding

The peer core intentionally has no async runtime, socket, TLS, filesystem, or OS-clock dependency.

## Validate

```bash
cargo test --workspace
```

See `STATUS.md` for the current validation state.
