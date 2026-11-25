# Reference provenance and offline inventory checkpoint

Date: 2026-11-25

## Reference provenance

- Historical publisher comparison: https://github.com/Lalalalendia/med/actions/runs/45486390556
- Historical publisher catalog consensus: https://github.com/Lalalalendia/med/actions/runs/45491887337
- Latest provenance audit: https://github.com/Lalalalendia/med/actions/runs/45611375366
- Synthetic normalization and fingerprint tests: PASS.
- XS8, Readnovel, Hongxiu: HTTP 200; public opening sample container absent on each endpoint.
- Verdict: `reference_unverified`. This is not a publisher fingerprint mismatch.
- The historical 3604-Han container hash and local 3600-Han paragraph hash refer to different representations. Do not compare them directly.
- Do not infer definitive substitution from 0/28 matches until reference provenance is independently established.

## Existing inventory

Historical source artifacts (availability checked on 2026-11-25):

| Artifact ID | Description | Expiry (UTC) |
| --- | --- | --- |
| 14966022264 | Official catalog: 928 numbered chapters and two additional entries | 2026-12-08 |
| 14960786836 | Hongyeshuzhal partial inventory | 2026-12-08 |
| 14966712060 | Biquting section candidates | 2026-12-01 |
| 14966331165 | Canghaishuge chapter candidates | 2026-12-01 |
| 15020575745 | Reference provenance JSON | 2026-12-09 |

The earlier checkpoint remains 725 structurally identified chapter candidates out of 928, not 725 independently authenticated complete chapter bodies. No new chapter accepted.

An offline metadata inventory workflow has been added in commit 2ca4b33b9fbdf066ac58ed29f69264861fa7ce57. It checks publisher title consensus, original manifest counts, repeated printed numbers, normalized title alignment, and within-source duplicate body hashes. It does not compare incompatible section numbering, extract or republish chapter bodies, or request new chapter text. Its execution result was not yet registered at the time of this checkpoint.

Resume by reviewing the offline inventory result, then use an author- or publisher-authorized complete export or independently verifiable samples for any remaining body-quality checks. Do not promote metadata-only matches into accepted complete chapters.
