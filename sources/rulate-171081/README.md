# Rulate 171081 — 40 Russian chapters

Canonical source: [Notion book](https://app.notion.com/p/3fb32a84beec81d5a418d2aa68caf0d8) and [Rulate book 171081](https://tl.rulate.ru/book/171081).

The index is exactly 40 verified TOC links. Chapters 1–30 use Rulate IDs 12830000–12830029. Chapters 31–40 use 16542829–16542838. Titles 25, 32, 37 and 38 are descriptive strings in the Notion export; preserve them pending review. The Japanese original has 166 episodes and is not the requested Russian 40-chapter corpus.

## Automated public reader collection

Branch-specific workflow: [.github/workflows/rulate-171081-ru40.yml](../../.github/workflows/rulate-171081-ru40.yml). It runs offline tests then fetches public /ready_new pages with two-second spacing. It refuses redirects to authentication, payment, unapproved domains and other chapters; also stops on CAPTCHA or access-denied pages.

Initial GitHub Actions #39867446909 on 2026-10-23 collected 0/40: Rulate returned HTTP 403 for robots.txt on the hosted runner. No chapter text was saved. Do not bypass access-control restrictions to force CI to continue.

A successful run creates a 7-day artifact named rulate-171081-ru-001-040 with a ZIP containing chapters/001.txt through chapters/040.txt, combined.txt and manifest.json (SHA-256/lengths). **Never commit story bodies or print them in logs.** GitHub Actions artifacts in this public repo should not be treated as a private rights vault.

## Offline import of operator-authorized saved HTML

If all 40 Rulate chapters are already accessible with the appropriate permission through a normal browser, use its ordinary Save Page or HTML-only action to save 001.html through 040.html into one directory. Match each filename to the ordinal and source URL in chapters.json. The importer does not authenticate to Rulate or circumvent protected content.

Run from the root of med, using commands:

- python -m pip install requests beautifulsoup4
- python -m unittest discover -s tools/novel-ingest -p test_rulate_171081_ingest.py -v
- python tools/novel-ingest/rulate_171081_ingest.py --html-dir /path/to/saved-html --out-dir out/rulate-171081

The importer validates exactly 40 numbered HTML files, approved reader wrappers, Russian-language text size, duplicate hashes and output integrity. It creates the same ZIP locally, otherwise only a failure receipt, never an incomplete corpus. A nonempty output directory is refused.

This mode is marked operator_saved_html_unverified: filenames do not independently establish online page identity. Verify the order against the source and inspect texts before publication.

No Notion chapter pages or translations are generated. The user asserted permission for collection, but a machine-readable license was not available to this script.
