# TWBook public fetcher + deobfuscator

Fetches publicly accessible chapter pages from `twbook.cc`, removes site chrome, and reconstructs text hidden behind TWBook's randomized Hangul substitutions.

## Target novel

`美恐在我當重生當佬大` — `https://www.twbook.cc/0912500831/dir`

## How deobfuscation works

TWBook does **not** use one stable global Hangul→Chinese dictionary. The same Hangul code point can represent different Chinese characters in different responses.

The fetcher therefore works per chapter:

1. fetch a public rendering;
2. if the body contains Hangul substitutions, fetch independent renderings of the same chapter;
3. align equal-length renderings position-by-position;
4. at each position, use the ordinary Chinese/punctuation character exposed by any rendering;
5. fail closed if a position remains Hangul in every rendering;
6. reject short 200-OK placeholder/anti-bot bodies instead of treating them as chapters.

The old `mapping.json` remains only as a diagnostic/bootstrap artifact and is not used to decode chapter bodies.

## Run

```bash
python -m pip install requests beautifulsoup4 pytest
python tools/twbook-public/fetch_twbook.py \
  --book-id 0912500831 \
  --start 1 --end 382 \
  --delay 0.8 \
  --out-dir out/twbook-0912500831
```

Outputs:

- `chapters/NNN.txt` — only clean chapters with zero unresolved Hangul substitutions;
- `unresolved/NNN.json` — unresolved positions/contexts;
- `short/NNN.json` — repeated short/placeholder responses that never yielded a plausible chapter;
- `manifest.jsonl` — per-chapter status;
- `catalog.tsv` — discovered catalog;
- `summary.md` — closure report;
- `combined.txt` — all clean chapters in order.

Use `--save-html` for debugging. Use `--allow-incomplete` only for diagnostics; by default any incomplete chapter makes the run fail.

## CI

Normal pushes run a fast 20-chapter closure sample. A commit message containing `[full]` runs all 382 chapters. Manual dispatch can choose any range.

## Scope

The fetcher uses ordinary public HTTP GETs only. It does not authenticate, solve CAPTCHAs, bypass paywalls, or defeat access controls. It only reconciles multiple representations of text already returned publicly by the site.
