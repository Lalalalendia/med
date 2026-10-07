# Faloo public chapter fetcher

Manual-only helper for checking chapter pages that are already publicly returned by Faloo.

It does **not** use credentials, cookies, browser automation, CAPTCHA solving, paywall bypass, or anti-bot circumvention. If a chapter is not present in the public HTML response, it is recorded as `blocked`, `missing`, or `needs_check`.

## Files

- `fetch_public_chapters.py` — fetcher/parser.
- `.github/workflows/faloo-public-chapters.yml` — manual GitHub Action.

The workflow has only `workflow_dispatch`, so commits do not trigger it.

For book `1046066`, the intended manual range is 1–77.
