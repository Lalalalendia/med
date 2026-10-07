# Faloo public chapter fetcher

Manual-only helper for checking chapter pages that are already publicly returned by Faloo.

It does **not** use credentials, cookies, browser automation, CAPTCHA solving, paywall bypass, or anti-bot circumvention. If a page is not present in the public HTML response, it is recorded as `blocked`, `missing`, or `needs_check`.

## Files

- `fetch_public_chapters.py` — fetcher/parser.
- `.github/workflows/faloo-public-chapters.yml` — manual GitHub Action.

The workflow has only `workflow_dispatch`, so commits do not trigger it.

## Book 1046066 numbering

Use Faloo **page ordinals** 1–79 rather than assuming ordinal = story chapter number.

- 1–65 = story chapters 1–65.
- ordinal 66 = `上架感言`.
- ordinal 67 = story chapter 66.
- ordinal 77 = story chapter 76.
- ordinal 78 = expected story chapter 77 (the published finale).
- Faloo reports 79 total updates, so ordinal 79 is a non-story/service entry.

The workflow defaults to 1–79 so the inserted service entry does not make the final story chapter disappear from a run.
