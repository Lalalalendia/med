# IXDZS 218645 — 某美漫的鳳凰之力

- Source: https://ixdzs.tw/read/218645/
- Original title: 某美漫的鳳凰之力
- Author: 難道我是超人
- Source state: completed
- Copyright/reproduction: explicitly confirmed by the user for this collection.
- Code: [collector](../../../tools/novel-ingest/ixdzs_218645_export.py)
- Workflow: [authorized export](../../../.github/workflows/ixdzs-218645-authorized-export.yml)

## Verified source (2026-11-17)

The official IXDZS TXT ZIP was successfully downloaded and validated. The original
catalog has **197 entries**. The normalized export contains:

- 190 sequential numbered chapters (1–190), each in its own UTF-8 TXT.
- 7 unnumbered items in their precise original positions, stored separately under
  the extras/ directory. Two different items are both titled 變種人時代 and must
  not overwrite each other.
- combined.txt in catalog sequence (including all seven extras).
- manifest.json with source, per-entry SHA-256, and verification metadata.
- Original official ZIP as a separate GitHub Actions artifact.

The first exporter version accidentally attached unnumbered entries to adjacent
numbered chapters. The collector now splits **197/197** and refuses to
label incomplete or changed structure as verified. The original front-matter
website metadata and download footer are not represented as catalog entries.

## Operations

Pushes affecting this dedicated exporter on the feature branch trigger the
scoped collection. A manual run can use workflow_dispatch with
rights_confirmed=true. The workflow performs offline parser tests,
downloads the official TXT ZIP if available, checks the 190+7 record
structure, checks text hashes and ZIP CRC, and only then publishes the verified
archive. It can fall back to chapter pages only when robots.txt allows it;
no anti-bot or access controls are bypassed.

No copyrighted book prose is committed to Git. Downloadable GitHub Actions
artifacts have a 30-day retention period; save the verified archive to
permanent storage before expiration.

Acceptance run: https://github.com/Lalalalendia/med/actions/runs/44061499368

## Archive files

- ixdzs-218645-authorized-cn.zip — all 197 entries in normalized UTF-8.
- original-official-download.zip — original publisher download.
- status.json — success/failure evidence.

This job collects original-language source only; no translation is performed.
