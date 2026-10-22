# Aura Farming English RAW backfill

`tools/novel-ingest/aura_farming_backfill.py` reuses the existing verified Royal Road scraper.
The original chapters 001-025 and 096 are already stored in the canonical Notion book database;
this backfill does **not** download or overwrite them. Its fixed plan downloads 026-095 and 097
(71 numbered chapters), in verified batches of up to ten with a 2-second spacing.

The workflow runs offline tests on pull requests. A merge to `main` triggers a single live
collection; it may be rerun manually in GitHub Actions. It uploads per-chapter UTF-8 text,
SHA-256 manifest, source links, per-chapter receipts and a combined **missing-only** TXT. A partial
batch fails CI but keeps its verified texts and receipts as an artifact for recovery.

The workflow **does not** copy text into Notion or claim a translation is complete. Use
`handoff.json` for a separate verified import to the existing RAW database and only mark a
chapter `RAW есть` after attaching and re-reading the full TXT with matching SHA-256. Do not
commit the generated story corpus to the application's main branch.
