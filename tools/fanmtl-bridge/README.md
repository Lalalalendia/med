# English MTL bridge

This directory contains an evidence fetcher; it **does not perform EN-to-RU translation** or publish to Rulate. Use only publicly accessible pages, with no authentication bypass.

## Historical profile: witch (66–77)
- Book: 美漫中餐馆：员工绯红女巫
- Story 66 maps to source position 67; story 77 maps to position 78.
- The next source position belongs to a different book: retained strict guard at 78.
- Default source: Wuxiaspot. Old workflow `fanmtl-bridge.yml` is unchanged.
- EN/MTL is not Chinese RAW and always requires source review.

## OA profile: 221–290
- Book: 美漫：悟性逆天，我创造OA神力 (Kasha).
- Registered slug: `american-comics-my-understanding-is-incredible-i-create-oa-magical-power`.
- Mapping: story number = source position, offset 0; range 221–290; at most 10 chapters per run.
- Default public mirror: **Wuxiabox**. FanMTL returned HTTP 403 on a GitHub runner (2026-10-08).
- Direct chapter URLs, page series identity, chapter number, minimum text size, access blocks and book boundaries are checked. Unknown or mismatched pages are never saved as `ok`.
- Successful records include the chapter's SHA-256 in `manifest.jsonl` and `summary.md`.
- A nonzero exit with `--strict` indicates at least one unverified / blocked chapter.

Command for a locally runnable source check:

```bash
python tools/fanmtl-bridge/fetch_fanmtl_bridge.py \
  --book oa --source wuxiabox --story-start 221 --story-end 225 \
  --delay 2.0 --strict --out-dir out/oa-mtl
```

The [OA EN MTL bridge 221-290](../../.github/workflows/oa-mtl-bridge.yml) workflow supports manual `workflow_dispatch` on `main`. Choose a maximum of ten story chapters per invocation. It uploads TXT files, combined text, manifest and summary as a 30-day artifact.

### Hosted source receipts
- [Clean EN 221–245: 25/25](https://github.com/Lalalalendia/med/actions/runs/37831159060), artifact ID 11573048323.
- [Clean EN 246–290: 45/45](https://github.com/Lalalalendia/med/actions/runs/37831696594), artifact ID 11573882761.
- Combined audit: **70/70 chapters 221–290, 70 unique SHA-256, 66,926 EN/MTL words, no missing or contaminated Wuxiabox UI**. Source artifacts remain available for 30 days from their run dates.
- The old 221–235 archives from runs 37828487140 and 37829027821 contained a 148-word navigation/recommendations tail per chapter; they are **obsolete** and must not be the translation base.
- These are **English machine translations**, not verified Chinese RAW or Russian draft chapters. The EN text still contains author promotions and rough MTL wording; editorial QA is required before any RU draft is marked complete.

Translation work lives in [Notion's OA book](https://app.notion.com/p/3f332a84beec81a8b8c4d524db15e2cb); full-quality / published status requires separate translation and QA. A pre-existing Russian Rulate project (105168) does not constitute permission for an independent publication.

## Wuxiabox extraction hygiene (2026-10-09)
The Wuxiabox HTML `article` can include a navigation / recommendation tail after the actual prose. For OA pages the fetcher removes this tail only when all six known UI tokens occur in order, recomputes `chars`, `words` and SHA-256 on the cleaned story, and quarantines any residual recommendation markers (`needs_check`). Older 221-235 artifacts include the site chrome and are superseded by cleaned reruns. Regression tests cover exact tail removal and unknown-UI rejection; no change to the witch book parser path.
