# PUB constraint lab

Standalone proof-of-concept for compiling mature PUB interaction laws into executable cross-projection constraints.

This crate is intentionally **not** a PUB parser or writer. It operates on already-extracted observations with provenance and authority weights.

Current proof:
- 8 seed constraints representing mature PUB joins;
- missing observations are `NotEvaluable`, not corruption;
- violations preserve exact witness facts;
- relation-only repair candidates are ranked by independent-source authority support;
- ties remain ambiguous and are never auto-applied;
- non-repairable constraints only diagnose.

Canonical Law/Claim IDs are deliberately not invented in this lab crate. `authority_ref` labels must be replaced with exact registry relations during integration into the real PUB codebase.
