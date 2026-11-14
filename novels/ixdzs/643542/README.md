# IXDZS 643542: source chapters from 660 onward

Source: https://ixdzs.tw/read/643542/

This integration targets chapters **660 through the last chapter available in the index**.
It is an ingestion job, not a translation. The chapter body is not committed to this public repository.

## Validation and safety
- Probe: first 20 chapters (660–679), metadata and SHA-256 only.
- The complete exporter discovers the latest chapter (currently 891 in the catalog) and uses **physical source URL locators** rather than equating pNNN with chapter number.\n- The catalog lists only a sparse subset of chapter links. The importer finds the first chapter by validating earlier pages, then walks consecutive page locators to the latest listed chapter, checking every page's H1 and body.\n- Distinct pages with a repeated chapter heading are retained separately by appending the source locator to the TXT filename; no chapter is silently overwritten.
- Each chapter must have a matching numbered heading, nonempty prose (at least 250 CJK characters), and a distinct SHA-256. Numbering irregularities are recorded in the manifest, not silently corrected. Every physical source page between the verified endpoints must be read and preserved.
- Abort on missing chapters, cross-host redirects, inaccessible content, CAPTCHA, split chapter pages, robots restrictions or rate limiting.
- The run reports its status separately; the ZIP is published as a temporary Actions artifact only if every source page in the physical range passes validation. Printed chapter-number gaps and duplicates are recorded explicitly.
- Requests are spaced at least two seconds apart.

## Running
Use **Actions → IXDZS 643542 chapters 660+ metadata and permitted export → Run workflow** on this branch.
The export job requires explicit confirmation of permission to reproduce the chapter text.
The normal push workflow runs metadata checks only. It does not save original prose.

## Outputs
- Metadata: `ixdzs-643542-660-679-metadata`.
- Upon authorized complete success: `ixdzs-643542-660-tail-cn` containing individual TXT chapters named by ordinal **and physical locator**, `combined.txt`, and `manifest.json`.
- Status: `ixdzs-643542-tail-status`.

This collection is not marked complete until GitHub Actions confirms the actual discovered end chapter and validates all chapter content.

The unnumbered postscript/bonus material listed after the final numbered chapter is outside the current verified numbered-range export and needs separate validation.

## Verified first block (2026-11-14)
The metadata-only acceptance run [#43572525446](https://github.com/Lalalalendia/med/actions/runs/43572525446)
verified **20/20 chapters** in the range 660-679, with 20 unique body SHA-256 hashes.
In this exact range, printed chapter 660 is `p648.html` and printed chapter 679 is
`p667.html`; **do not extrapolate that offset** to other parts of the book.
The public index is sparse, so all later physical pages must be independently validated.

