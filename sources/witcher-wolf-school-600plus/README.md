# Witcher / 猎魔人：狼学派的狩魔手记 — RAW chapters 600+

This is an authorized source-copy task. The operator confirmed permission to
reproduce the full novel text on 2026-11-17. Text is exported only as temporary
GitHub Actions artifacts, **not** committed to Git.

## Sources

- Original publication: [Qidian 1038677367](https://www.qidian.com/book/1038677367/)
- Source being copied: [Jiuxiao book page](https://jiuxiaozw.com/sim/book/6af8d3227d54a8afba082141)
- Source-id: `6af8d3227d54a8afba082141`
- Complete public chapter index: `/api/books/<BOOK_ID>/catalog/version` then
  `/api/books/<BOOK_ID>/catalog?offset=0&limit=128&version=<VERSION>`.
  The response has a version, total, offset, and rows with title/id.
- Exact author chapter 600: `第600章 我们从正门进`, source ID
  `6af8d3237d54a8afba0823cd`,
  [chapter URL](https://jiuxiaozw.com/book/6af8d3227d54a8afba082141/6af8d3237d54a8afba0823cd).

**Do not use the API `chapter_number` field as the author's displayed chapter
number.** At author chapter 600 the API gives `chapter_number: 599`, and the
full index starts at row 599 (1-based) for author chapter 600. Titles are the
canonical author-number reference; chapters 901 through 955 contain Chinese
numerals (`第九百零一章`, etc.) and must be parsed accordingly.

## Snapshot (2026-11-17)

The verified catalog had version `4` and 1,002 indexed chapters. Author
chapter numbers 600 through 1003 form 404 entries, with no gaps in the parsed
author numbering in the selected range.

## Export and QA

[GitHub workflow](https://github.com/Lalalalendia/med/actions/workflows/witcher-raw-600.yml)
runs tests, fetches the complete versioned index, then writes an independently
verifiable sample of chapters 600–609. It continues the same output folder
through the last author-numbered chapter in the catalog snapshot, using saved
per-chapter SHA-256 hashes and a `progress.json` receipt.

- `witcher-600-609-text-pilot`: first ten chapters (already verified as a ZIP)
- `witcher-600-plus-raw-and-progress`: final combined text, individual TXT
  files, full manifest and progress; if a step fails, contains only partial
  data and must **not** be labeled as complete.

To collect from a saved versioned index manually:

```sh
python tools/jiuxiao/witcher_full_catalog.py
python tools/jiuxiao/witcher_collect_text.py \
  --catalog out/witcher-full-catalog.json \
  --start 600 --delay 2 \
  --out-dir out/witcher-600-plus
```

The collector rejects missing or duplicated author chapter numbers,
mismatched chapter titles, bad next-chapter links, login/challenge pages,
unexpected hosts, and damaged checkpoints. It preserves HTML paragraph
boundaries, records per-chapter hashes, and only writes a complete
`manifest.json` and `book-600-plus.txt` once the selected range is complete.

Resuming in the same working directory automatically verifies previously
saved chapter files before continuing. To resume across Actions runs, download
the prior artifact and restore both `progress.json` and the `chapters/`
directory, and supply **the identical versioned catalogue**. Reusing a
different version is rejected to avoid silently mixing editions.
