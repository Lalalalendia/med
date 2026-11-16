# 巫师：从技能树开始肝经验 / 巫师：我有一棵技能树 — RAW 500+

Status on 2026-11-16: **500–942 collected and permanently committed to the collection branch; 943–984 unresolved.**

- Author: 悠悠不吃草.
- Collection branch: `collect/wizard-skill-tree-500-tail-20261116`
- Collector: `tools/novel-ingest/witch_skill_tree.py`
- Successful GitHub Actions run: https://github.com/Lalalalendia/med/actions/runs/43857390899
- Artifact: `witch-skill-tree-500-tail-43857390899` (GitHub Actions ZIP).
- Durable texts: `novels/witch-skill-tree/raw/` (443 files), `novels/witch-skill-tree/combined.txt` and `novels/witch-skill-tree/witch-skill-tree-raw.zip` (4,103,078 bytes).
- Persistence run: https://github.com/Lalalalendia/med/actions/runs/43860343551 — SUCCESS, SHA-256 and ZIP CRC checked before commit.

## Verified collection

- RAW source: `https://sto55.com/book/62763/ajax_index.html`
- Chapters 500–942, inclusive: 443/443 fetched, no missing ordinals.
- 443 unique SHA-256 hashes in log, min/median/max extracted length 2067/4224/4688 characters.
- Files in the run artifact: `raw/*.txt`, `combined.txt`, `manifest.json`, `summary.md`, `witch-skill-tree-raw.zip`.
- Verification is technical (content node, heading, minimum length, sequential ordinals), not a full independent editorial comparison.

## Known remainder

- Chapter 943 title: `狩猎天使` (source: official-affiliated catalog and indexes).
- Multiple index pages as of 2026-11-16 list up to 984: `大地的裂变`. **This is an index maximum, not a full-text acquisition claim.**
- **943–984 are NOT in the verified artifact.** The novel is marked ongoing.

## Candidate source checks

| Site | Catalog | Result |
|---|---|---|
| sto55.com/book/62763 | Through 942 | Chapter body works; used for verified collection |
| suduguu.com/2024 | Through 942 | Catalog available; no later chapter at time of check |
| ppwx.net/49/49309 | Through 982 | REJECTED: chapter text consists of unrelated excerpts |
| cbiquge.com/49/49309 | Through 984 | REJECTED: 984 text is unrelated excerpts, shared across mirror clones |
| xbiquge.info/49/49309 | Through 984 | REJECTED: same contaminated text as cbiquge |
| cmfu.cc/49/49309 | Through 982 | REJECTED: unrelated mixed novel fragments in article |
| wxff.net/zdzdmu/mulu_10.html | Through 952 | REJECTED: Base64 in `#booktxt` decodes, but 942/943/952 text is too short and includes unrelated stories |
| idejian.com/book/13664849 | Search lists through 953 | HTTP 202 from runner, no article body; unverified |
| bqg000.cc/read/176663 | 500+ listed | Chapter pages show `加载中` placeholder; not usable |
| jumeichai.com, chyntn.com | 984 visible in search index | Cannot verify full bodies from runner (blocked/unavailable) |

Source audits:

- https://github.com/Lalalalendia/med/actions/runs/43859254345 (catalog and sample content)
- https://github.com/Lalalalendia/med/actions/runs/43859739584 (Base64 decode)
- https://github.com/Lalalalendia/med/actions/runs/43859885251 (reader access check)

## Acceptance criteria for a later source

1. Index has chapter 943 through an explicit last chapter; validate sequential numbering.
2. Retrieve complete body from at least 943 and two nonadjacent later chapters.
3. Cross-check source's chapter 942 against verified sto55 942 for content continuity, not only heading.
4. Reject short, repeated, unrelated, paywalled, blocked, or placeholder bodies. Do not infer success from HTTP 200.
5. Collect missing chapters only, with source URLs, unique hashes, errors, and gap report; produce final combined ZIP.
6. Retain existing 500–942 artifact and never overwrite it based on unverified sources.

No deployment or main-branch modification was performed.
