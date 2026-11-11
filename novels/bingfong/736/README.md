# Bingfong book 736: source verification and permitted original assembly

- Original Chinese title: `修真网络时代` (traditional: `修真網路時代`).
- Author: `惟一的叶子` (traditional: `惟一的葉子`).
- Source: https://bingfong.com/novel/m/book/736
- Expected numbered chapters: **1-587**; novel marked complete at source.
- Collector: [`tools/novel-ingest/bingfong_736.py`](../../../tools/novel-ingest/bingfong_736.py)
- Workflow: [Bingfong 736 chapter audit and permitted TXT](../../../.github/workflows/bingfong-736.yml)

## Known source irregularity

The mirror exposes **588 consecutive reading IDs**, spanning 1135947-1136534,
for **587 numbered chapters**. The two source pages for chapter 476 are:

- https://bingfong.com/novel/m/read/1136422/3013962
- https://bingfong.com/novel/m/read/1136423/3013963

They have the same heading and appeared text-identical in public spot checks.
The collector compares their complete normalized fingerprints; if they differ,
it refuses to discard either page. All other pages must agree with the expected
number-to-source-ID mapping. This avoids silently shifting chapters 477-587.

## Verification / production

`probe` inspects the chapter pages for numbers 1, 300, both 476 copies, and 587.
`audit` inspects all 588 source pages and records only metadata (chapter number,
URL, Chinese character count and SHA-256 fingerprint). No prose is retained.

`collect` is disabled unless the operator explicitly confirms the necessary
rights to reproduce the entire novel. After a complete verified run it generates
an Actions artifact containing:

- `bingfong-736-001-587-cn.zip`
  - `chapters/0001.txt` through `chapters/0587.txt`
  - `combined.txt`
  - `manifest.json`
  - `summary.md`
- `manifest.json` and `summary.md` outside the ZIP for quick inspection.

The collector rejects incomplete runs, mismatched chapter labels, access-gated
pages, disallowed robots, unexpected redirects, unexpected duplicates, and
unmatched chapter-476 bodies. No partial ZIP is published. The repository
contains the reusable source code and receipts, not the copyrighted novel text.

### Launch

Open GitHub **Actions > Bingfong 736 chapter audit and permitted TXT > Run workflow**.
Select `probe`, `audit`, or (with permission for reproduction) `collect`.
For collection enable `rights_confirmed` and retain the minimum 2-second delay.
Artifacts expire after 14 days.

### Status

- 2026-11-11: Verified public landing page, chapter 1, chapter 300, both
  source pages for chapter 476, and chapter 587 in browser research.
- Offline synthetic parser/integrity tests: **6/6 PASS**.
- Full live 588-page audit and book export: **not yet run**; no completed RAW
  archive is claimed by this README.

## Production source switch — 2026-11-11

Bingfong returned HTTP 403 during GitHub Actions live checks. The validated full
novel was instead obtained from **CZBooks uk0ff** with chapter-by-chapter checks.
See [verified 587/587 acquisition receipt](../../czbooks/uk0ff/README.md).
The Bingfong collection workflow is retained for diagnostics; it was not used
to produce the delivered full-book archive.
