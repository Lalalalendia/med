# Behemoth / N9107EE: authorized Japanese text import

Work: Ｓランクモンスターの《ベヒーモス》だけど、猫と間違われてエルフ娘の騎士（ペット）として暮らしてます  
Author: 銀翼のぞみ  
Official original: https://ncode.syosetu.com/n9107ee/  
Official Narou work ID: `N9107EE`  
Reference count at inspection (2026-11-16): **217 episodes**. This is a publication snapshot, not a claim that all episode text was retrieved.

## Source and access restrictions

The Japanese publisher's terms prohibit automated access / data collection outside official APIs. The author can export **their own** Narou work from the management screen (the official `テキスト形式でダウンロード` command). The ordinary reader TXT download was discontinued in March 2026. Do not use the older HTML scraper in this repository against Narou, even if `robots.txt` permits a URL. Obtain a licensed source export from the author or rights holder.

Official references:
- https://syosetu.com/site/rule/
- https://syosetu.com/helpcenter/helppage/helppageid/90
- https://blog.syosetu.com/article/view/article_id/5114/
- https://kakuyomu.jp/help/entry/download_works

## Offline import commands

From the repository root, for an author-provided Kakuyomu backup ZIP (contains `episode_0001.txt` etc.):

```bash
python3 tools/novel-ingest/authorized_export_assembler.py \
  --mode kakuyomu-zip \
  --input /path/to/authorized_kakuyomu_backup.zip \
  --output output/n9107ee/ \
  --ncode N9107EE \
  --expected 217
```

For an authorized folder containing numbered episodes `1.txt`, `002.txt`, `chapter_003.txt`, etc.:

```bash
python3 tools/novel-ingest/authorized_export_assembler.py \
  --mode episode-directory \
  --input /path/to/authorized_episode_files/ \
  --output output/n9107ee/ \
  --expected 217
```

For the author-generated Narou backup (ZIP containing `N9107EE.txt`, or a standalone `N9107EE.txt`):

```bash
python3 tools/novel-ingest/authorized_export_assembler.py \
  --mode narou-author \
  --input /path/to/N9107EE.zip \
  --output output/n9107ee-author/ \
  --expected 217
```

The Narou backup also contains publication metadata, afterwords, and potentially other fields. Since its internal episode delimiters have not been verified on a real author-supplied backup, this mode **preserves the whole original export** and records `UNSEGMENTED_AUTHOR_BACKUP`; it does not claim 217 clean chapters or create a misleading completed archive. Split and verify boundaries from the actual supplied file, then re-run the directory mode.

All modes work entirely from local files and make **no HTTP requests**. ZIP is read without extracting path names to the filesystem; malicious paths, duplicate episode numbers, suspicious sizes, invalid encodings, and missing episodes are rejected. No copyrighted source text is committed to GitHub.

With all 217 numbered episodes present, outputs are:
- `episodes/0001.txt` through `episodes/0217.txt`, UTF-8;
- `combined_ja.txt`, preserving Japanese text and original ruby notation;
- `manifest.json`, with per-episode and aggregate SHA-256 hashes;
- `complete_ja.zip`, checked by CRC.

If the expected range has gaps, the importer only emits `manifest.json` with `PARTIAL` and missing positions. It does not produce a deceptive `combined_ja.txt`.

## Offline validation

```bash
python3 -m unittest discover -s tools/novel-ingest -p 'test_authorized_export_assembler.py' -v
```

No deployment, release or changes to the `main` branch are required.
