# MTL book radar — discovery by ID and new-book lists

**Scope:** WTR-LAB and TomatoMTL are active during the first pilot; FanMTL, Ranobes and MTL-Novel are configured but initially disabled until tested. This is a **metadata-only** discovery tool: it stores book ID, title, URL and time first observed. It never downloads chapters, bypasses access limits, or publishes translations.

The legacy Rulate/Royal Road configuration is **not** used. The numeric-ID behavior of each MTL site must be validated by a live pilot. The WTR-LAB site explicitly documents `/novel/[novel_id]`, and its homepage has numeric IDs. The other sites use different patterns. TomatoMTL uses Fanqie IDs of roughly 19 digits: **never increment these IDs by 1**. WTR-LAB IDs can have gaps and additions out of order. Only WTR-LAB enables bounded numerical probing, and only between the last observed frontier and a higher ID found on the latest catalogue page.

## Install

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python watch.py --config sites.json --state state/mtl-book-watch.json --events state/mtl-discoveries.jsonl --report reports/mtl-book-watch.md
```

For a local server, run `mkdir -p logs` before installing `cron.example` into `crontab -e`. In GitHub use `.github/workflows/mtl-book-radar.yml`: it schedules daily runs at 02:37 UTC, tests on PR, and writes cumulative state and results to a separate `mtl-book-radar-state` branch (not `main`). Keep `state/` persistent and back it up. The baseline run saves the currently visible book IDs **without declaring them newly published**. Later runs emit `first_seen` events, never presumed original publication dates. Uncertain/blocked sources report errors and do not mark absent books as missing.

## Source strategies

- **WTR-LAB**: `/en/novel/<ID>/<slug>`, newest listing `/en/novel-list`. A site changelog documents the ID-only form `/novel/<ID>`; live testing of redirects is still required. The site publishes `https://wtr-lab.com/novels/index.xml` as a sitemap in robots.txt; prefer incorporating the sitemap after verifying its format in a live pilot. This initial script only uses the public catalog + bounded numeric gap checks, not forbidden `/api` routes.
- **TomatoMTL**: `/book/<long Fanqie ID>`, data is retrieved from Fanqie in real time (per site's own explanation). The user-voted list may be browser-rendered, so the script stops with `NO_BOOK_LINKS` if its HTML lacks discoverable IDs; no undocumented API, browser challenge bypass, or pretend-success.
- **FanMTL**: `/novel/<mixed code or slug>.html`; newest books on homepage. This is a listing watcher, **not** numeric scanning.
- **Ranobes**: `/novels/<number>-<slug>.html`, but the original title may change and some content requires login; the catalog lists MTL/AI MTL items. This is a listing watcher, not direct ID guessing.
- **MTL-Novel**: `/novel/<slug>/`; newest books section on homepage; listing watcher only.

## Limits and reliability

1. Checks live `robots.txt` before fetching each source; unreachable or disallowing it **blocks that source**. No credential or anti-bot bypass.
2. Uses an explicit per-host delay, serial requests, HTTPS only; blocks cross-host redirects and 403/429.
3. A catalog page showing zero matching book links is reported as parser failure, not zero new books.
4. Only same-host URLs matching the expected book structure are accepted.
5. WTR numeric holes are retained and retried. A temporary error stops scanning without advancing cursor. The script never assumes no gaps or reliable absolute chronology.
6. Results are **first seen on MTL site**, not first publication or rights to use the work. Detailed literary quality, original title and existing RU translations must be checked separately before entering a translation queue.
7. If an MTL site only exposes its catalogue through JavaScript, extend its adapter only after identifying an officially permitted route; otherwise use another source.
8. Saved outputs can be imported into the existing Notion candidate database after title/original/duplicate checks. The script deliberately never modifies Notion itself.

## Not yet verified

The execution container has no external DNS connectivity; tests are local fixtures only. This package is **not deployed** and no cron task has been installed. Test on a permitted connected host, inspect the first report and fix any site-specific extraction changes before scheduling regular runs.

## GitHub Actions installation

Place the Python files in `tools/mtl-book-radar/` and `.github/workflows/mtl-book-radar.yml` in the repository default branch. The first workflow run is a baseline and should not report historical catalog entries as newly published. Subsequent runs compare source IDs and store `data/mtl-book-radar/state.json`, `discoveries.jsonl`, and `latest.md` in a separate state branch. Requires Actions permissions allowing `GITHUB_TOKEN` to write repository contents. CI tests run on pull requests without scraping sites or modifying persistent state. The scheduled workflow follows the same cron expression as `cron.example`, but executes on GitHub-hosted runners, not the user’s server.

Do not confuse `tomatomtl.com/recommended-novels` with a newest-books feed. It is a weekly user vote; entries count only as newly **observed** on that list, not as new uploads or original book releases. A preferred future improvement is a verified public chronological source on TomatoMTL.

**Crash consistency:** state.json is canonical and holds discovery history (`schema=2`). The discoveries.jsonl report is recreated atomically from that state, preventing lost events after interrupted file writes. Existing version-1 states are upgraded using their adjacent discoveries.jsonl.
