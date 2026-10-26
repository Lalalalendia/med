# 漫威，谁把他救出来的？！ — Chinese RAW collection

- Chinese title: 漫威，谁把他救出来的？！
- Author: 雨夜下刀不带伞
- Primary collection source: https://cn.zhys.tw/book/2268838.html (318 catalog links)
- Comparison witnesses: https://www.twbook.cc/1901458316/dir , https://www.novel543.com/0511558316/dir , https://m.abbshu.net/book/309042/
- Notion source record: https://app.notion.com/p/3da32a84beec81349a03f8d56814e4ea

## Source findings, 26 October 2026

A live GitHub Actions mirror probe found:

| Site | Access | Suitability |
| --- | --- | --- |
| ZHYS | Public book catalog and sample chapter readable; robots permits | **Selected**: complete 318-entry catalog |
| Twbook | Public /dir catalog and chapter readable; robots permits | Korean Hangul glyph substitutions in prose; use separate deobfuscation/QC before using |
| Novel543 | robots.txt disallows the book /dir | Do not crawl with this collector |
| ABBSHU | robots.txt HTTP 403; permission not established | Not used by automated collector |

The source catalog contains distinct entries with repeated *printed chapter numbers* near the end. Use catalog ordinal 1–318 as identity, preserving printed labels separately. Do not deduplicate by chapter title or printed number.

## Current pipeline

Run `Marvel Taylor - verified Chinese RAW` in GitHub Actions. On the feature branch it launches four parallel ZHYS shard jobs (1–80, 81–160, 161–240, 241–318) and a strict merger. Each shard produces individual TXT chapter files, a catalog snapshot and checksums. Only if the shard manifests cover all ordinals, all 318 files validate SHA-256, catalogs are identical, and bodies are not duplicated does the merger emit:

- `raw/0001.txt` … `raw/0318.txt`
- `combined.txt` containing the 318 verified entries
- `manifest.json` with per-chapter source URL, printed number, length and SHA-256
- `summary.md`

GitHub Action artifacts are retained for seven days. These artifacts may be accessible to other users of a public repository; do not store anything outside the authorized corpus.

For local runs:

```bash
python -m pip install requests beautifulsoup4
python tools/novel-ingest/marvel_taylor_zhys.py --out-dir out/marvel-taylor-a --start 1 --end 80 --expected 318 --delay 1.25
```

The script honors robots.txt, does not bypass logins/anti-bot restrictions, and flags missing/short/obfuscated chapter bodies as failures rather than pretending success. The independent source probe remains at `tools/novel-ingest/marvel_taylor_mirror_probe.py`.

Earlier Novel543-only collector and tests are retained as diagnostic scaffolding; current primary collection uses ZHYS instead.

**Scope boundaries:** raw Chinese only. No Russian translation, Notion synchronization or Rulate publication is implied by a successful source artifact. Use the verified artifact only after the merge reports PASS.
