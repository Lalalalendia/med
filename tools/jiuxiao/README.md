# Jiuxiao (九霄中文网) source collector

A read-only collector for texts that are in the public domain or that the operator
is authorized to reproduce. It does not bypass accounts, paywalls, robots rules,
rate limits or challenge pages.

## Verified live pilot

- Source: [故事新编 — 鲁迅](https://jiuxiaozw.com/sim/book/6ab99ea063213dfa71e9a016).
- Nine entries announced and nine distinct chapters collected (including preface).
- 79,575 characters in combined UTF-8 text and 1,141 source paragraphs.
- GitHub Actions live test validates all nine files and SHA-256.
- Chapter text comes from `div.reader-columns p.reader-paragraph`; original
  paragraph boundaries are kept as blank-line separators.
- The book card uses `/sim/book/...` but **chapter pages must use `/book/...`**.
  Using `/sim/book/<book>/<chapter>` yielded HTTP 404.

## CLI

```bash
python -m pip install requests beautifulsoup4
python tools/jiuxiao/collector.py \
  --book-url 'https://jiuxiaozw.com/sim/book/6ab99ea063213dfa71e9a016' \
  --expected-title '故事新编' \
  --delay 2 \
  --out-dir out/jiuxiao/gushi-xinbian
```

Outputs are `book.txt`, nine individual UTF-8 files under `chapters/`,
`manifest.json` (URLs, titles, hashes, paragraph counts), and `SUMMARY.md`.
GitHub Actions exposes them as a seven-day download artifact. The collector
never commits extracted novel text to the repository.

## Safety and data quality

- Checks `robots.txt` and refuses inaccessible/blocked pages.
- Uses a single low-rate request stream (at least two seconds between requests).
- Rejects HTTP errors, HTML challenges, missing content containers, implausibly
  short chapters, duplicate content and title mismatches.
- Compares unique catalog links to the site's announced chapter count.
- Checks each chapter's "next" navigation target against the next catalog URL.
- Fails without a SUCCESS manifest when any chapter is missing or invalid.
- Never treats a partial extraction as a complete book.

## Large catalogs and resumable batches

Book cards with thousands of chapters usually expose only ~30 latest links plus
the first chapter. The **one-shot** collector intentionally refuses such
incomplete catalogs. A separate **linked batch collector** follows verified
"next chapter" links instead, using chapter headings and IDs in the reader.

For a permitted book whose card has a truncated catalog:

```bash
python tools/jiuxiao/linked_collector.py \
  --book-url 'https://jiuxiaozw.com/sim/book/<BOOK_ID>' \
  --limit 50 --delay 2 --out-dir out/book/batch01
```

Every successful batch writes a receipt (`manifest.json`) with `next_url` and
`next_ordinal`, source title, IDs, SHA-256, paragraphs and exact saved files.
The batch has status `BATCH_COMPLETE`, **not** `SUCCESS` for a full book.

Continue using the returned values as `--start-url` and `--start-ordinal`:

```bash
python tools/jiuxiao/linked_collector.py \
  --book-url 'https://jiuxiaozw.com/sim/book/<BOOK_ID>' \
  --start-url '<NEXT_URL_FROM_PREVIOUS_MANIFEST>' \
  --start-ordinal 51 --limit 50 --delay 2 \
  --out-dir out/book/batch02
```

After retrieving every batch:

```bash
python tools/jiuxiao/assemble_batches.py \
  out/book/batch01 out/book/batch02 \
  --out-dir out/book/assembled
```

Assembly rejects gaps, overlaps, wrong book IDs, broken cross-batch links,
bad checksums, missing paragraphs and an incomplete final chapter. Only a
fully verified book gets a `SUCCESS` assembled manifest.

The linked navigation was checked against the first five chapters of the
1,667-entry novel `玄鉴仙族` (31 chapter links visible on its book card).
The two-batch workflow also re-collected the nine-chapter public-domain
sample as 1–3 and 4–9, then reconstructed a **byte-identical book** with the
same SHA-256 as the original one-shot collector.

This is still **sequential** and intentionally rate-limited. Full 1,667-chapter
collection requires multiple bounded runs. Automatic scheduling, persistent
checkpoints outside artifacts, and runtime rechecking of book revisions are
future improvements; do not claim them as implemented.

## Tests

```bash
python -m unittest discover -s tools/jiuxiao -p 'test_*.py' -v
```

`inspect_catalog.py` and `source_probe.py` are metadata-only diagnostic
tools and are separate from the text collector.
