# Aibenshu 141911 — verified public chapter collection

**Book:** 民俗从傩戏班子开始, author 夜半探窗.

**Source:** https://www.aibenshu.com/book/141911/

**Verified range:** 237–395 inclusive: 159 chapters, 318 source pages. Verification dated 2026-11-01.

**Status:** PASS, zero missing chapters. Two independent successful builds produced identical SHA-256 hashes for every chapter.

The book's original RAW text is generated as a downloadable GitHub Actions artifact, not committed into this public repository. Artifacts expire after 14 days. To reproduce the file, open **Actions → Aibenshu 141911 - verified RAW collection → Run workflow** on `main` and use `start=237`, `end=0`, leaving `only` blank. The artifact includes `combined.txt`, `chapters/`, `manifest.json`, and `summary.md`.

- [Verified complete one-pass run](https://github.com/Lalalalendia/med/actions/runs/41326834486)
- [Independent merged verification run](https://github.com/Lalalalendia/med/actions/runs/41326884402)
- [Machine-readable verification record](verified.json)

**Source-specific integrity checks:** AES-CBC/PKCS7 decoding of publicly rendered encrypted chapter bodies; correlation against the visible prefix (including dangling `<` markup); pagination validation; rejection of unloaded placeholders, short bodies, incorrect chapter titles, and incomplete ranges. Do not use the older run 41324867138: it incorrectly passed truncated HTML previews.

In case only a few chapters fail, run the collector with `--only` and use `tools/novel-ingest/aibenshu_merge.py` to merge with the previously verified partial batch. Its expected full range is 237–395.
