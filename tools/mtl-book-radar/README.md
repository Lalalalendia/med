# MTL book radar — discovery by ID and new-book lists

**Scope:** WTR-LAB and MTL-Novel are active. TomatoMTL is disabled by robots; FanMTL returns 403 and Ranobes 503 on the GitHub runner. ReadNovelMTL is a preflight candidate, not active until robots and catalogue validation. This is a **metadata-only** discovery tool: it stores book ID, title, URL and time first observed. It never downloads chapters, bypasses access limits, or publishes translations.

The legacy Rulate/Royal Road configuration is **not** used. The numeric-ID behavior of each MTL site must be validated by a live pilot. The WTR-LAB site explicitly documents `/novel/[novel_id]`, and its homepage has numeric IDs. The other sites use different patterns. TomatoMTL uses Fanqie IDs of roughly 19 digits: **never increment these IDs by 1**. WTR-LAB IDs can have gaps and additions out of order. Numeric probing is **disabled** in production: the documented ID-only URLs currently return 404, even for known published book IDs. Use the verified catalogue listing until an ID-to-slug mapping or sitemap path is validated.

## Install

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python watch.py --config sites.json --state state/mtl-book-watch.json --events state/mtl-discoveries.jsonl --report reports/mtl-book-watch.md
```

For a local server, run `mkdir -p logs` before installing `cron.example` into `crontab -e`. In GitHub use `.github/workflows/mtl-book-radar.yml`: it schedules daily runs at 02:37 UTC, tests on PR, and writes cumulative state and results to a separate `mtl-book-radar-state` branch (not `main`). Keep `state/` persistent and back it up. The baseline run saves the currently visible book IDs **without declaring them newly published**. Later runs emit `first_seen` events, never presumed original publication dates. Uncertain/blocked sources report errors and do not mark absent books as missing.

## Source strategies

- **WTR-LAB**: `/en/novel/<ID>/<slug>` in the newest listing `/en/novel-list`. **Live verified 2026-10-15:** both `/novel/107269` and `/en/novel/107269` return 404 for a known book; the full slug route works. Disable numeric-only probes until a verified resolver exists. The publicly advertised sitemap `https://wtr-lab.com/novels/index.xml` is a promising next adapter, pending read-only verification. No `/api` requests.
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

## First live scan — 2026-10-15

[Run #38721520577](https://github.com/Lalalalendia/med/actions/runs/38721520577): WTR-LAB successfully established a baseline of 10 cards; TomatoMTL explicitly disallowed `/recommended-novels` in robots.txt. State and the report were saved to the dedicated branch. Tomato was therefore disabled rather than repeatedly requesting a forbidden route.

## Second live preflight — 2026-10-15

[PR #58](https://github.com/Lalalalendia/med/pull/58): live read-only GitHub checks returned FanMTL 403 on both homepage and new-book list, Ranobes 503 on catalogue, MTL-Novel homepage 28 links (mixed sections) and `/novel/` catalogue **10 valid book cards**. The scheduled reader therefore uses `/novel/` and enables only MTL-Novel. ReadNovelMTL is being checked as an additional MTL alternative.

## WTR short-ID regression discovered — 2026-10-15

[GitHub preflight #38724358386](https://github.com/Lalalalendia/med/actions/runs/38724358386) tested known novel `107269`: both short forms returned **404**, while the full `/en/novel/107269/<slug>` produced the correct title. The first production scan wasted 30 numbered probes. The production config now suppresses numeric probes rather than creating false hole records; it still catches newly seen books via the public listing. The numeric scanner remains covered by isolated tests for a future site with a proven ID-only route.
