# Может ли обычный человек полюбить гения? — N6792EM

- Rulate project (user reports book taken into work): https://tl.rulate.ru/book/268337
- Original title: それでも平凡は天才を愛せるか？
- Author: 由比ヶ浜 在人
- Narou original: https://ncode.syosetu.com/n6792em/
- Known source total on 2026-10-30: 113 episodes; finished.
- Notion working tracker: https://app.notion.com/p/40932a84beec816dab9ef5b62c1c7fd6

## Collect and assemble Japanese source

Run the GitHub Actions workflow `.github/workflows/narou-n6792em-source-113.yml` on the default branch, or locally:

```sh
python -m pip install requests beautifulsoup4
python -m unittest discover -s tools/novel-ingest -p test_narou_ingest.py -v
python -m unittest discover -s tools/novel-ingest -p test_n6792em_package.py -v
python tools/novel-ingest/narou_ingest.py --ncode n6792em --expected 113 --min-chars 120 --delay 1.5 --out-dir out/narou-n6792em
python tools/novel-ingest/n6792em_package.py --source out/narou-n6792em --output out/narou-n6792em-japanese-original-001-113.zip
```

The ZIP contains all 113 Japanese originals as `chapters/001.txt`–`chapters/113.txt`, a single `combined.txt` (in episode order, with source links), and `manifest.json` with SHA-256 and source receipts. Packaging fails if any chapter is missing, duplicated or has mismatched checksum. Incomplete retrieval never produces a falsely labelled complete book.

**Important:** the source text is copyrighted; the repository is public and chapter bodies are intentionally **not committed**. GitHub Actions uses a private-to-repository temporary artifact, retained for 7 days. Download and handle it only in accordance with applicable permissions. Having source files does not mean the Russian translation has been prepared or publication rights granted.

## Verified source build — 2026-10-30

- **STATUS: PASS 113/113** (source catalog 113, Japanese body count 113; failed 0; missing 0; extras 0).
- [Successful GitHub Actions run #41055451071](https://github.com/Lalalalendia/med/actions/runs/41055451071).
- Artifact: `narou-n6792em-japanese-original-001-113`, ID `12977410860`; expires 2026-11-06 (GitHub Actions retention: 7 days).
- The verified inner ZIP includes `chapters/001.txt` through `113.txt`, `combined.txt`, and `manifest.json` (115 entries).
- SHA-256 of the inner ZIP: `624e58fdac898b3066c3ccf7042b387dc7235ce81812c5c453d4b359ed301327`.
- Distinct verified chapter body SHA-256: **113/113**; original Japanese source chars without whitespace, per parser: **277656**.
- Independent verification: ZIP CRC check, 113 chapter files, every body hash and URL matched the manifest, and all 113 `combined.txt` headings appeared once in ascending episode order.
- **Editorial caveat:** the 113 entries are *episodes*, not automatically 113 numbered Russian chapters. Some Japanese section titles reset their internal numbering and include prologues/epilogues.
- A separate private Google Drive backup was saved to protect against expiry of GitHub Actions artifacts. The public repository contains no Japanese novel bodies.
- **Russian translation: 0 confirmed chapters; published on Rulate: 0** (owner's 2026-10-30 update). Translation publication/rights permissions remain unverified.

Next: prepare a terminology and character glossary, compare the Rulate title/description with the Narou source, and start the Russian working draft from **episode 001** only after clarifying publication rights. Keep source text out of public commits.

## Current status

Original Japanese source is fully collected and mechanically validated (113/113). The Russian draft has not been started. See `source_receipt_2026-10-30.json` for metadata-only verification.
