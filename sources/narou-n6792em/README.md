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

## Current status

Workflow and packager prepared. A successful GitHub Actions run and a verified 113/113 source corpus must be confirmed separately. No Japanese source or Russian translation has been added to the Git history.
