# 修真网络时代 — verified original (CZBooks uk0ff)

Original title: `修真网络时代` / `修真網路時代`  
Author: `惟一的叶子`  
Source: https://czbooks.net/n/uk0ff  
Language: Chinese (traditional), original novel marked complete.

## Result — 2026-11-11

- **587/587 unique numbered chapters verified**.
- Source catalog: 588 entries, with two text-identical entries for chapter 476; deduplicated after SHA-256 comparison.
- **No missing chapters** across 1–587; no matching prose hashes across distinct chapter numbers.
- Chapter files and concatenated UTF-8 TXT validated against SHA-256; the resulting ZIP passed its internal CRC checks.
- First 50: [Actions run #43040881873](https://github.com/Lalalalendia/med/actions/runs/43040881873), artifact **13865391895**.
- Chapters 51–587: [Actions run #43041975355](https://github.com/Lalalalendia/med/actions/runs/43041975355), artifact **13866366299**.
- Full 1–587 combined from those two validated archives and checked a second time. The combined ZIP was delivered to the requester in the ChatGPT conversation; the original prose was **not committed to public Git**.
- First 50 combined SHA-256: `c84dda0cac3202a40cedcc16ee34dd7ee2aef4e9df6dce52dd2eb0584d24f353`.
- Chapters 51–587 combined SHA-256: `82862facc0288215936e88e8233495d5239a52e30f38d8ef34fe51a3f71f8927`.
- Full combined text SHA-256: `8792ecd3102d19e3b6ec7c1f336751b481879bfef13144a89fd26ecaa58c057c`.
- Catalog fingerprint SHA-256 (same in both shard runs): `ca81a6d1445071f0b7ca74e6070e2954dfed9334572f025cf3d27e641d0e48cd`.

## Collector and workflows

- Collector: [`tools/novel-ingest/czbooks_uk0ff.py`](../../../tools/novel-ingest/czbooks_uk0ff.py)
- First 50: [`.github/workflows/czbooks-uk0ff-first50.yml`](../../../.github/workflows/czbooks-uk0ff-first50.yml)
- Remaining chapters, three shards and verified ZIP: [`.github/workflows/czbooks-uk0ff-rest.yml`](../../../.github/workflows/czbooks-uk0ff-rest.yml)
- `rights_confirmed` must be specified for collection, requests honor robots.txt and rate limits, and the exporter rejects incomplete archives.
- Original text is distributed through temporary account-accessible GitHub Actions artifacts (retention 14 days); re-run only with the necessary permission.

## Source caveat

The previous mirror at https://bingfong.com/novel/m/book/736 returned HTTP 403 from GitHub Actions. CZBooks worked on the same runners. A checked title and a working index alone are not proof of access to whole-book text; the result above is supported by both successful acquisition runs and their manifests.
