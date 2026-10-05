# PUB vacancy radar

A dependency-free market-intelligence tool for finding current Russian vacancies where Microsoft Publisher is tied to a real publishing, prepress, labeling, catalogue, brochure, or document-production workflow.

The initial source is the official open-data API of «Работа России» (`opendata.trudvsem.ru`). The API supports text search, pagination and `modifiedFrom`, so scheduled runs can scan only a bounded recent window.

## Why a classifier is necessary

Vacancy mirrors sometimes attach `MS Publisher` as a generic imported skill to unrelated jobs. Counting those rows would produce a fake market. The radar therefore emits three classes:

- **A — operational**: Publisher plus a plausible publishing/print/document-production duty. These are company-level qualification candidates.
- **B — review**: Publisher is present, but the operational connection is not strong enough for automatic promotion.
- **C — rejected noise**: Publisher is attached to an unrelated role without publishing duties (negative controls include pharmacist/doctor/loader/cashier-style rows).

A-class does **not** mean that the employer definitely owns active `.pub` files. It means the vacancy is strong enough to ask that question.

## Run

```bash
python tools/pub-market/vacancy_radar.py \
  --output-dir out/pub-market \
  --lookback-hours 72
```

Use an explicit deterministic window when needed:

```bash
python tools/pub-market/vacancy_radar.py \
  --modified-from 2026-10-01T00:00:00Z \
  --output-dir out/pub-market
```

Additional text queries can be supplied with repeated `--query` arguments. Defaults:

- `Microsoft Publisher`
- `MS Publisher`
- `Publisher 2019`
- `Publisher 2016`

## Outputs

- `all.json` — every Publisher-matching normalized vacancy in the scan window.
- `qualified.json` — A-class operational signals.
- `new-qualified.json` — A-class signals returned by this explicit `modifiedFrom` window; this does not claim all-time novelty.
- `review.json` — B-class rows for manual review.
- `rejected.json` — C-class negative controls/noise.
- `qualified.csv` — compact review table.
- `summary.md` — human-readable run summary.

No output is written to Notion or CRM automatically in V1. Review precision first, then add promotion automation only after false-positive behavior is measured.

## Source contract

Source adapters must normalize their payloads into `NormalizedVacancy` before classification. The classifier consumes only:

- explicit vacancy evidence fields such as title/duty/requirement/description;
- an explicit skills collection;
- normalized employer/role/region/date provenance.

Source-specific metadata is not classification evidence.

Each source keeps its own stable `source:id` key. A separate `mirror_key` is emitted only when employer, role, region, and creation date are all known. It is a cross-source mirror candidate, not permission to silently delete one of the records.

This allows future sources such as HeadHunter to reuse the same classifier and gold corpus without teaching the classifier each provider's JSON schema.

### HeadHunter adapter status

A credential-gated HeadHunter adapter is implemented but intentionally not enabled in the scheduled workflow yet.

It uses the official API shape:

- search: `GET https://api.hh.ru/vacancies`;
- hydration: `GET https://api.hh.ru/vacancies/{id}`;
- `date_from` for bounded publication windows;
- `page` / `per_page` with `per_page <= 100` and a maximum 20 pages (2,000 search results);
- explicit `Authorization: Bearer ...` and `HH-User-Agent`.

The adapter never falls back to HTML scraping.

### One-time HeadHunter setup

The repository does not store HeadHunter credentials. Before the first live HH validation:

1. Register the application in the HeadHunter developer console.
2. Generate an **application access token** for that application.
3. Add repository secret `HH_APP_ACCESS_TOKEN` with that token.
4. Add repository secret `HH_USER_AGENT` with a contact-bearing value such as `ChapteraPublisherRadar/1.0 (contact@example.com)`.
5. Run the **PUB vacancy radar HH** workflow manually with `workflow_dispatch`. The default validation window is 720 hours (30 days).

The HH workflow is manual-only by design. It first runs fixture/contract tests and only then starts the live job. A daily schedule must not be enabled until one credentialed live run proves search → full-vacancy hydration → normalization → classification → artifacts end to end.

Application-token values and contact details must remain outside the repository and logs.

## Tests

```bash
python -m unittest discover -s tools/pub-market -p "test_*.py" -v
```
