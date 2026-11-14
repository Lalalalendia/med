# IXDZS 643542: source chapters from 660 onward

Source: https://ixdzs.tw/read/643542/

This integration targets chapters **660 through the last chapter available in the index**.
It is an ingestion job, not a translation. The chapter body is not committed to this public repository.

## Validation and safety
- Probe: first 20 chapters (660–679), metadata and SHA-256 only.
- The complete exporter discovers the latest catalog entry and requires a contiguous range.
- Each chapter must have a matching heading, nonempty prose (at least 250 CJK characters), and a distinct SHA-256.
- Abort on missing chapters, cross-host redirects, inaccessible content, CAPTCHA, split chapter pages, robots restrictions or rate limiting.
- The run reports its status separately; the ZIP is published as a temporary Actions artifact only if every requested chapter passes.
- Requests are spaced at least two seconds apart.

## Running
Use **Actions → IXDZS 643542 chapters 660+ metadata and permitted export → Run workflow** on this branch.
The export job requires explicit confirmation of permission to reproduce the chapter text.
The normal push workflow runs metadata checks only. It does not save original prose.

## Outputs
- Metadata: `ixdzs-643542-660-679-metadata`.
- Upon authorized complete success: `ixdzs-643542-660-tail-cn` containing individual TXT chapters, `combined.txt`, and `manifest.json`.
- Status: `ixdzs-643542-tail-status`.

This collection is not marked complete until GitHub Actions confirms the actual discovered end chapter and validates all chapter content.
