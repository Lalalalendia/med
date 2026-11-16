# Jiuxiao (九霄中文网) source collector

A read-only collector for texts that are in the public domain or that the operator
is authorized to reproduce. It does not bypass accounts, paywalls, robots rules,
rate limits or challenge pages.

## Verified live pilot

- Source: [故事新编 — 鲁迅](https://jiuxiaozw.com/sim/book/6ab99ea063213dfa71e9a016).
- Nine entries announced and nine distinct chapters collected (including preface).
- 79,575 characters in combined UTF-8 text and 1,141 source paragraphs.
- GitHub Actions live test validates all nine files and SHA-256.
- Chapter text comes from \`div.reader-columns p.reader-paragraph\`; original
  paragraph boundaries are kept as blank-line separators.
- The book card uses \`/sim/book/...\` but **chapter pages must use \`/book/...\`**.
  Using \`/sim/book/<book>/<chapter>\` yielded HTTP 404.

## CLI

\`\`\`bash
python -m pip install requests beautifulsoup4
python tools/jiuxiao/collector.py \
  --book-url 'https://jiuxiaozw.com/sim/book/6ab99ea063213dfa71e9a016' \
  --expected-title '故事新编' \
  --delay 2 \
  --out-dir out/jiuxiao/gushi-xinbian
\`\`\`

Outputs are \`book.txt\`, nine individual UTF-8 files under \`chapters/\`,
\`manifest.json\` (URLs, titles, hashes, paragraph counts), and \`SUMMARY.md\`.
GitHub Actions exposes them as a seven-day download artifact. The collector
never commits extracted novel text to the repository.

## Safety and data quality

- Checks \`robots.txt\` and refuses inaccessible/blocked pages.
- Uses a single low-rate request stream (at least two seconds between requests).
- Rejects HTTP errors, HTML challenges, missing content containers, implausibly
  short chapters, duplicate content and title mismatches.
- Compares unique catalog links to the site's announced chapter count.
- Checks each chapter's "next" navigation target against the next catalog URL.
- Fails without a SUCCESS manifest when any chapter is missing or invalid.
- Never treats a partial extraction as a complete book.

## Known limitation: large catalogs

The visible book card lists approximately 30 *latest* chapters plus the start
link even when a book contains hundreds or thousands of chapters. The
current collector intentionally refuses these incomplete lists. Before running
mass collection, add a reliable full catalog mechanism or follow verified
"next chapter" links from the first chapter, tracking each visited ID and
verifying the final count. For very long books, implement resumable batches,
not one time-limited GitHub Actions job.

## Tests

\`\`\`bash
python -m unittest discover -s tools/jiuxiao -p test_collector.py -v
\`\`\`

\`inspect_catalog.py\` and \`source_probe.py\` are metadata-only diagnostic
tools and are separate from the text collector.
