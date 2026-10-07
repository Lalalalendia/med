# TWBook public fetcher + deobfuscator

Fetches publicly accessible chapter pages from `twbook.cc`, removes site chrome, decodes the site's stable Hangul-for-Chinese character substitutions, and **fails closed** if any unknown substituted character remains in the extracted chapter body.

## Target novel

`美恐在我當重生當佬大` — `https://www.twbook.cc/0912500831/dir`

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

- `chapters/NNN.txt` — only chapters with zero unresolved Hangul substitutions;
- `unresolved/NNN.json` — all unresolved symbols with local contexts;
- `manifest.jsonl` — per-chapter status;
- `catalog.tsv` — discovered catalog;
- `summary.md` — closure report and unresolved-character counts;
- `combined.txt` — all clean chapters in order.

Use `--save-html` for debugging. Use `--allow-incomplete` only for diagnostics; by default any incomplete chapter makes the run fail.

## Scope

The fetcher uses ordinary public HTTP GETs only. It does not authenticate, solve CAPTCHAs, bypass paywalls, or defeat access controls. The deobfuscator only reverses the stable character substitution present in HTML already returned publicly by the site.
