#!/usr/bin/env python3
"""Publisher vacancy radar for the public Trudvsem (Работа России) API.

The radar deliberately uses deterministic rules.  It is intended to find
companies whose current vacancies connect Microsoft Publisher to an actual
publishing / prepress / document-production duty, while suppressing generic
job-board skill-tag noise.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

API_URL = "https://opendata.trudvsem.ru/api/v1/vacancies"
DEFAULT_QUERIES = (
    "Microsoft Publisher",
    "MS Publisher",
    "Publisher 2019",
    "Publisher 2016",
)

PUBLISHER_RE = re.compile(
    r"(?i)(?<![\w])(?:(?:microsoft|ms)\s+)?publisher(?:\s*(?:2007|2010|2013|2016|2019|2021|365))?(?![\w])"
)

# These terms indicate that Publisher is plausibly part of a real production
# workflow rather than an unrelated skill tag.
OPERATIONAL_TERMS = (
    "верст", "вёрст", "макет", "предпечат", "полиграф", "типограф",
    "печат", "этикет", "маркиров", "каталог", "брошюр", "буклет",
    "листов", "визит", "бюллет", "newsletter", "layout", "prepress",
    "desktop publishing", "dtp", "publication", "brochure", "catalog",
    "label", "print-ready", "printing", "imposition", "дизайн",
)

# Negative controls seen in vacancy mirrors where Publisher is often merely an
# imported hard-skill tag.  A real publishing duty always wins over this list.
NOISE_TITLE_TERMS = (
    "фармацевт", "провизор", "врач", "фельдшер", "медицинск", "грузчик",
    "кассир", "продавец", "уборщик", "охранник", "водитель", "повар",
    "пристав", "слесарь", "электромонтер", "электромонтёр", "машинист",
    "кладовщик", "разнорабоч", "санитар",
)

SKILL_PATH_TERMS = ("skill", "навык", "hard-skill", "soft-skill")
TEXT_PRIORITY_KEYS = (
    "job-name", "duty", "requirement", "requirements", "additional_requirements",
    "job_description", "description", "education", "qualification",
)


@dataclass(frozen=True)
class ClassifiedVacancy:
    source: str
    key: str
    vacancy_id: str
    url: str
    employer: str
    employer_inn: str
    employer_code: str
    job_name: str
    region: str
    creation_date: str
    modified_date: str
    classification: str
    classification_reason: str
    operational_hits: tuple[str, ...]
    publisher_paths: tuple[str, ...]
    publisher_context: tuple[str, ...]
    query_matches: tuple[str, ...]


def _norm(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split())


def _first(mapping: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = mapping.get(key)
        if value not in (None, ""):
            return _norm(value)
    return ""


def flatten_strings(value: Any, path: str = "") -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            out.extend(flatten_strings(child, child_path))
    elif isinstance(value, list):
        for i, child in enumerate(value):
            out.extend(flatten_strings(child, f"{path}[{i}]"))
    elif isinstance(value, (str, int, float)):
        text = _norm(value)
        if text:
            out.append((path, text))
    return out


def _publisher_context(flat: Iterable[tuple[str, str]]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    paths: list[str] = []
    contexts: list[str] = []
    for path, text in flat:
        if PUBLISHER_RE.search(text):
            paths.append(path)
            # One API field is usually short enough to be a useful review excerpt.
            contexts.append(text[:700])
    return tuple(sorted(set(paths))), tuple(dict.fromkeys(contexts))


def _operational_hits(flat: Iterable[tuple[str, str]]) -> tuple[str, ...]:
    blob = "\n".join(text.casefold() for _, text in flat)
    return tuple(term for term in OPERATIONAL_TERMS if term in blob)


def classify_vacancy(vacancy: dict[str, Any]) -> tuple[str, str, tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    flat = flatten_strings(vacancy)
    pub_paths, pub_context = _publisher_context(flat)
    if not pub_paths:
        return "N", "publisher_not_present", (), (), ()

    op_hits = _operational_hits(flat)
    if op_hits:
        return "A", "publisher_plus_operational_duty", op_hits, pub_paths, pub_context

    job_name = _first(vacancy, "job-name", "job_name", "name").casefold()
    title_is_noise = any(term in job_name for term in NOISE_TITLE_TERMS)
    publisher_only_in_skills = all(
        any(skill_term in path.casefold() for skill_term in SKILL_PATH_TERMS)
        for path in pub_paths
    )

    if title_is_noise and publisher_only_in_skills:
        return "C", "unrelated_role_and_skill_tag_only", (), pub_paths, pub_context
    if title_is_noise:
        return "C", "unrelated_role_without_publishing_duty", (), pub_paths, pub_context
    if publisher_only_in_skills:
        return "B", "publisher_skill_only", (), pub_paths, pub_context
    return "B", "publisher_mentioned_without_operational_context", (), pub_paths, pub_context


def _stable_key(vacancy: dict[str, Any]) -> str:
    vacancy_id = _first(vacancy, "id", "vacancy-id", "vacancy_id")
    if vacancy_id:
        return f"trudvsem:{vacancy_id}"
    company = vacancy.get("company") if isinstance(vacancy.get("company"), dict) else {}
    parts = [
        _first(company, "name"),
        _first(vacancy, "job-name", "job_name", "name"),
        _first(vacancy, "vac_url", "url"),
        _first(vacancy, "creation-date", "creation_date"),
    ]
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:20]
    return f"trudvsem:sha256:{digest}"


def normalize_vacancy(vacancy: dict[str, Any], queries: Iterable[str]) -> ClassifiedVacancy:
    classification, reason, op_hits, pub_paths, pub_context = classify_vacancy(vacancy)
    company = vacancy.get("company") if isinstance(vacancy.get("company"), dict) else {}
    region = vacancy.get("region") if isinstance(vacancy.get("region"), dict) else {}
    return ClassifiedVacancy(
        source="trudvsem",
        key=_stable_key(vacancy),
        vacancy_id=_first(vacancy, "id", "vacancy-id", "vacancy_id"),
        url=_first(vacancy, "vac_url", "url"),
        employer=_first(company, "name", "company_name"),
        employer_inn=_first(company, "inn"),
        employer_code=_first(company, "companycode", "company-code", "code"),
        job_name=_first(vacancy, "job-name", "job_name", "name"),
        region=_first(region, "name"),
        creation_date=_first(vacancy, "creation-date", "creation_date"),
        modified_date=_first(
            vacancy,
            "modified-date", "modification-date", "update-date", "date-modification",
            "creation-date", "creation_date",
        ),
        classification=classification,
        classification_reason=reason,
        operational_hits=op_hits,
        publisher_paths=pub_paths,
        publisher_context=pub_context,
        query_matches=tuple(sorted(set(queries))),
    )


def request_json(url: str, params: dict[str, Any], *, timeout: int = 60, attempts: int = 3) -> dict[str, Any]:
    query = urllib.parse.urlencode(params)
    req = urllib.request.Request(
        f"{url}?{query}",
        headers={"User-Agent": "chaptera-pub-vacancy-radar/1.0 (+https://github.com/Lalalalendia/med)"},
    )
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                payload = json.load(response)
            if str(payload.get("status", "200")) != "200":
                raise RuntimeError(f"Trudvsem API status={payload.get('status')}: {payload.get('meta')}")
            return payload
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, RuntimeError) as exc:
            last_error = exc
            if attempt + 1 == attempts:
                break
            time.sleep(2 ** attempt)
    assert last_error is not None
    raise last_error


def fetch_trudvsem(
    query: str,
    modified_from: str | None,
    *,
    limit: int = 100,
    max_pages: int = 100,
    requester: Callable[[str, dict[str, Any]], dict[str, Any]] = request_json,
) -> list[dict[str, Any]]:
    """Fetch one Trudvsem text query with bounded pagination."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for offset in range(max_pages):
        params: dict[str, Any] = {"text": query, "limit": limit, "offset": offset}
        if modified_from:
            params["modifiedFrom"] = modified_from
        payload = requester(API_URL, params)
        raw = payload.get("results", {}).get("vacancies", [])
        if not isinstance(raw, list):
            raise ValueError("unexpected Trudvsem payload: results.vacancies is not a list")

        before = len(out)
        for item in raw:
            vacancy = item.get("vacancy", {}) if isinstance(item, dict) else {}
            if not isinstance(vacancy, dict):
                continue
            key = _stable_key(vacancy)
            if key in seen:
                continue
            seen.add(key)
            out.append(vacancy)

        total_raw = payload.get("meta", {}).get("total")
        try:
            total = int(total_raw)
        except (TypeError, ValueError):
            total = None
        if not raw or len(raw) < limit:
            break
        if total is not None and len(out) >= total:
            break
        if len(out) == before and raw:
            # Defensive guard against an API that ignores offset and repeats a page.
            break
    return out


def run_scan(
    queries: Iterable[str],
    modified_from: str | None,
    *,
    fetcher: Callable[[str, str | None], list[dict[str, Any]]] = fetch_trudvsem,
) -> list[ClassifiedVacancy]:
    by_key: dict[str, dict[str, Any]] = {}
    matched_queries: dict[str, set[str]] = {}
    for query in queries:
        for vacancy in fetcher(query, modified_from):
            key = _stable_key(vacancy)
            by_key.setdefault(key, vacancy)
            matched_queries.setdefault(key, set()).add(query)

    rows = [normalize_vacancy(v, matched_queries[key]) for key, v in by_key.items()]
    rows.sort(key=lambda row: (row.classification, row.employer.casefold(), row.job_name.casefold(), row.key))
    return rows


def _row_dict(row: ClassifiedVacancy) -> dict[str, Any]:
    data = asdict(row)
    for field in ("operational_hits", "publisher_paths", "publisher_context", "query_matches"):
        data[field] = list(data[field])
    return data


def write_outputs(rows: list[ClassifiedVacancy], out_dir: Path, modified_from: str | None) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    buckets = {
        "all": rows,
        "qualified": [r for r in rows if r.classification == "A"],
        "review": [r for r in rows if r.classification == "B"],
        "rejected": [r for r in rows if r.classification == "C"],
    }
    # With an incremental modifiedFrom scan, "new-qualified" means A-class rows
    # returned in this explicit scan window.  It does not claim historical novelty.
    buckets["new-qualified"] = list(buckets["qualified"])

    for name, items in buckets.items():
        path = out_dir / f"{name}.json"
        path.write_text(
            json.dumps([_row_dict(r) for r in items], ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    csv_path = out_dir / "qualified.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        fields = [
            "key", "employer", "employer_inn", "job_name", "region", "creation_date",
            "modified_date", "url", "classification_reason", "operational_hits",
            "publisher_context", "query_matches",
        ]
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in buckets["qualified"]:
            data = _row_dict(row)
            writer.writerow({
                **{field: data.get(field, "") for field in fields},
                "operational_hits": " | ".join(data["operational_hits"]),
                "publisher_context": " | ".join(data["publisher_context"]),
                "query_matches": " | ".join(data["query_matches"]),
            })

    counts = {k: len(v) for k, v in buckets.items() if k != "new-qualified"}
    lines = [
        "# Publisher vacancy radar",
        "",
        f"- Scan window: modifiedFrom `{modified_from or 'not set'}`",
        f"- Total Publisher-matching vacancies: **{counts['all']}**",
        f"- A — operational: **{counts['qualified']}**",
        f"- B — manual review: **{counts['review']}**",
        f"- C — rejected noise: **{counts['rejected']}**",
        "",
        "## A — operational signals",
        "",
    ]
    if not buckets["qualified"]:
        lines.append("No A-class vacancies in this scan window.")
    else:
        for row in buckets["qualified"]:
            hits = ", ".join(row.operational_hits[:8])
            lines.append(f"- **{row.employer or '(unknown employer)'} — {row.job_name or '(unknown role)'}**")
            lines.append(f"  - region: {row.region or '-'}")
            lines.append(f"  - signals: {hits or '-'}")
            lines.append(f"  - url: {row.url or '-'}")
            if row.publisher_context:
                lines.append(f"  - Publisher context: {row.publisher_context[0][:300]}")
    (out_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def iso_from_lookback(hours: int) -> str:
    dt = datetime.now(timezone.utc) - timedelta(hours=hours)
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default="out/pub-market")
    parser.add_argument("--query", action="append", dest="queries", help="repeatable search query")
    parser.add_argument("--modified-from", help="ISO-8601 timestamp passed to Trudvsem modifiedFrom")
    parser.add_argument("--lookback-hours", type=int, default=72, help="used when --modified-from is omitted")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    if args.modified_from and args.lookback_hours < 0:
        raise SystemExit("--lookback-hours must be non-negative")
    modified_from = args.modified_from or iso_from_lookback(args.lookback_hours)
    queries = tuple(args.queries or DEFAULT_QUERIES)
    rows = run_scan(queries, modified_from)
    write_outputs(rows, Path(args.output_dir), modified_from)
    counts = {klass: sum(r.classification == klass for r in rows) for klass in ("A", "B", "C")}
    print(f"publisher vacancy radar: total={len(rows)} A={counts['A']} B={counts['B']} C={counts['C']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
