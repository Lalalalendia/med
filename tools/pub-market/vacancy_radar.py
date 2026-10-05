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
HH_API_BASE = "https://api.hh.ru"
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

# Generic editing verbs are too broad to qualify a vacancy on their own.
# They count only when Publisher is named in the same top-level evidence field.
PUBLISHER_LOCAL_EDIT_TERMS = (
    "редактир", "замен", "корректир", "edit", "replace",
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
class NormalizedVacancy:
    source: str
    source_id: str
    url: str
    employer: str
    employer_inn: str
    employer_code: str
    job_name: str
    region: str
    creation_date: str
    modified_date: str
    evidence: tuple[tuple[str, str], ...]
    skills: tuple[str, ...]


@dataclass(frozen=True)
class ClassifiedVacancy:
    source: str
    key: str
    mirror_key: str
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


def _top_level_key(path: str) -> str:
    return path.split(".", 1)[0].split("[", 1)[0].casefold()


def _priority_evidence(flat: Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
    return [
        (path, text)
        for path, text in flat
        if _top_level_key(path) in TEXT_PRIORITY_KEYS
    ]


def _operational_hits(flat: Iterable[tuple[str, str]]) -> tuple[str, ...]:
    # Only vacancy-authored evidence fields may provide operational context.
    # Nested metadata such as company.description must not promote a skill tag.
    blob = "\n".join(text.casefold() for _, text in _priority_evidence(flat))
    return tuple(term for term in OPERATIONAL_TERMS if term in blob)


def _publisher_local_edit_hits(flat: Iterable[tuple[str, str]]) -> tuple[str, ...]:
    hits: list[str] = []
    for _, text in _priority_evidence(flat):
        if not PUBLISHER_RE.search(text):
            continue
        folded = text.casefold()
        for term in PUBLISHER_LOCAL_EDIT_TERMS:
            if term in folded and term not in hits:
                hits.append(term)
    return tuple(hits)


def normalize_trudvsem_source(vacancy: dict[str, Any]) -> NormalizedVacancy:
    company = vacancy.get("company") if isinstance(vacancy.get("company"), dict) else {}
    region = vacancy.get("region") if isinstance(vacancy.get("region"), dict) else {}

    evidence: list[tuple[str, str]] = []
    for key in TEXT_PRIORITY_KEYS:
        if key in vacancy:
            evidence.extend(flatten_strings(vacancy[key], key))

    skills: list[str] = []
    for path, text in flatten_strings(vacancy):
        if any(skill_term in path.casefold() for skill_term in SKILL_PATH_TERMS):
            skills.append(text)

    return NormalizedVacancy(
        source="trudvsem",
        source_id=_first(vacancy, "id", "vacancy-id", "vacancy_id"),
        url=_first(vacancy, "vac_url", "url"),
        employer=_first(company, "name", "company_name"),
        employer_inn=_first(company, "inn"),
        employer_code=_first(company, "companycode", "company-code", "code"),
        job_name=_first(vacancy, "job-name", "job_name", "name"),
        region=_first(region, "name"),
        creation_date=_first(vacancy, "creation-date", "creation_date"),
        # Do not substitute creation-date here. Trudvsem documents modifiedFrom
        # as a server-side change filter, but vacancy payloads do not always expose
        # the corresponding modification timestamp. An empty value is more honest
        # than inventing a modification date from the creation date.
        modified_date=_first(
            vacancy,
            "modified-date", "modification-date", "update-date", "date-modification",
        ),
        evidence=tuple(evidence),
        skills=tuple(dict.fromkeys(skills)),
    )


def _strip_html(value: Any) -> str:
    text = _norm(value)
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    return " ".join(text.replace("&nbsp;", " ").split())


def normalize_hh_source(vacancy: dict[str, Any]) -> NormalizedVacancy:
    employer = vacancy.get("employer") if isinstance(vacancy.get("employer"), dict) else {}
    area = vacancy.get("area") if isinstance(vacancy.get("area"), dict) else {}
    snippet = vacancy.get("snippet") if isinstance(vacancy.get("snippet"), dict) else {}

    evidence: list[tuple[str, str]] = []
    job_name = _first(vacancy, "name")
    if job_name:
        evidence.append(("job-name", job_name))

    description = _strip_html(vacancy.get("description"))
    if description:
        evidence.append(("description", description))

    snippet_requirement = _strip_html(snippet.get("requirement"))
    if snippet_requirement:
        evidence.append(("requirement", snippet_requirement))
    snippet_responsibility = _strip_html(snippet.get("responsibility"))
    if snippet_responsibility:
        evidence.append(("duty", snippet_responsibility))

    skills: list[str] = []
    raw_skills = vacancy.get("key_skills")
    if isinstance(raw_skills, list):
        for item in raw_skills:
            if isinstance(item, dict):
                name = _first(item, "name")
                if name:
                    skills.append(name)
            elif isinstance(item, str):
                name = _norm(item)
                if name:
                    skills.append(name)

    return NormalizedVacancy(
        source="hh",
        source_id=_first(vacancy, "id"),
        url=_first(vacancy, "alternate_url", "url"),
        employer=_first(employer, "name"),
        employer_inn="",
        employer_code=_first(employer, "id"),
        job_name=job_name,
        region=_first(area, "name"),
        creation_date=_first(vacancy, "initial_created_at", "created_at", "published_at"),
        modified_date=_first(vacancy, "updated_at"),
        evidence=tuple(evidence),
        skills=tuple(dict.fromkeys(skills)),
    )


def request_hh_json(
    path: str,
    params: dict[str, Any],
    *,
    access_token: str,
    user_agent: str,
    timeout: int = 60,
    attempts: int = 3,
) -> dict[str, Any]:
    if not access_token:
        raise ValueError("HH access token is required")
    if not user_agent:
        raise ValueError("HH-User-Agent is required")

    query = urllib.parse.urlencode(params)
    url = f"{HH_API_BASE}{path}"
    if query:
        url = f"{url}?{query}"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {access_token}",
            "HH-User-Agent": user_agent,
            "Accept": "application/json",
        },
    )
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                payload = json.load(response)
            if not isinstance(payload, dict):
                raise ValueError("unexpected HeadHunter payload")
            return payload
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
            last_error = exc
            if attempt + 1 == attempts:
                break
            time.sleep(2 ** attempt)
    assert last_error is not None
    raise last_error


def fetch_hh(
    query: str,
    date_from: str | None,
    *,
    access_token: str,
    user_agent: str,
    per_page: int = 100,
    max_pages: int = 20,
    requester: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None,
) -> list[NormalizedVacancy]:
    """Fetch HeadHunter search hits and hydrate each hit from the full vacancy endpoint."""
    if not (1 <= per_page <= 100):
        raise ValueError("HH per_page must be between 1 and 100")
    if not (1 <= max_pages <= 20):
        raise ValueError("HH max_pages must be between 1 and 20")

    if requester is None:
        def requester(path: str, params: dict[str, Any]) -> dict[str, Any]:
            return request_hh_json(
                path,
                params,
                access_token=access_token,
                user_agent=user_agent,
            )

    ids: list[str] = []
    seen: set[str] = set()
    for page in range(max_pages):
        params: dict[str, Any] = {
            "text": query,
            "page": page,
            "per_page": per_page,
        }
        if date_from:
            params["date_from"] = date_from

        payload = requester("/vacancies", params)
        items = payload.get("items", [])
        if not isinstance(items, list):
            raise ValueError("unexpected HeadHunter payload: items is not a list")

        for item in items:
            if not isinstance(item, dict):
                continue
            vacancy_id = _first(item, "id")
            if vacancy_id and vacancy_id not in seen:
                seen.add(vacancy_id)
                ids.append(vacancy_id)

        pages_raw = payload.get("pages")
        try:
            pages = int(pages_raw)
        except (TypeError, ValueError):
            pages = None
        if not items:
            break
        if pages is not None and page + 1 >= pages:
            break
        if len(items) < per_page:
            break

    records: list[NormalizedVacancy] = []
    for vacancy_id in ids:
        detail = requester(f"/vacancies/{urllib.parse.quote(vacancy_id, safe='')}", {})
        records.append(normalize_hh_source(detail))
    return records


def _record_flat(record: NormalizedVacancy) -> list[tuple[str, str]]:
    return [
        *record.evidence,
        *((f"skills[{i}]", skill) for i, skill in enumerate(record.skills)),
    ]


def classify_record(record: NormalizedVacancy) -> tuple[str, str, tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    flat = _record_flat(record)
    pub_paths, pub_context = _publisher_context(flat)
    if not pub_paths:
        return "N", "publisher_not_present", (), (), ()

    op_hits = _operational_hits(flat)
    local_edit_hits = _publisher_local_edit_hits(flat)
    if op_hits or local_edit_hits:
        evidence_hits = tuple(dict.fromkeys((*op_hits, *local_edit_hits)))
        return "A", "publisher_plus_operational_duty", evidence_hits, pub_paths, pub_context

    title_is_noise = any(term in record.job_name.casefold() for term in NOISE_TITLE_TERMS)
    publisher_only_in_skills = all(path.casefold().startswith("skills[") for path in pub_paths)

    if title_is_noise and publisher_only_in_skills:
        return "C", "unrelated_role_and_skill_tag_only", (), pub_paths, pub_context
    if title_is_noise:
        return "C", "unrelated_role_without_publishing_duty", (), pub_paths, pub_context
    if publisher_only_in_skills:
        return "B", "publisher_skill_only", (), pub_paths, pub_context
    return "B", "publisher_mentioned_without_operational_context", (), pub_paths, pub_context


def classify_vacancy(vacancy: dict[str, Any]) -> tuple[str, str, tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    return classify_record(normalize_trudvsem_source(vacancy))


def _record_key(record: NormalizedVacancy) -> str:
    if record.source_id:
        return f"{record.source}:{record.source_id}"
    parts = [
        record.source,
        record.employer,
        record.job_name,
        record.url,
        record.creation_date,
    ]
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:20]
    return f"{record.source}:sha256:{digest}"


def _mirror_key(record: NormalizedVacancy) -> str:
    if not all((record.employer, record.job_name, record.region, record.creation_date)):
        return ""
    parts = [
        record.employer.casefold(),
        record.job_name.casefold(),
        record.region.casefold(),
        record.creation_date[:10],
    ]
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:20]
    return f"mirror:sha256:{digest}"


def _stable_key(vacancy: dict[str, Any]) -> str:
    return _record_key(normalize_trudvsem_source(vacancy))


def normalize_vacancy(vacancy: dict[str, Any], queries: Iterable[str]) -> ClassifiedVacancy:
    record = normalize_trudvsem_source(vacancy)
    classification, reason, op_hits, pub_paths, pub_context = classify_record(record)
    return ClassifiedVacancy(
        source=record.source,
        key=_record_key(record),
        mirror_key=_mirror_key(record),
        vacancy_id=record.source_id,
        url=record.url,
        employer=record.employer,
        employer_inn=record.employer_inn,
        employer_code=record.employer_code,
        job_name=record.job_name,
        region=record.region,
        creation_date=record.creation_date,
        modified_date=record.modified_date,
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
            "key", "mirror_key", "employer", "employer_inn", "job_name", "region", "creation_date",
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
    for row in rows:
        if row.classification == "A":
            print(
                "qualified vacancy: "
                f"employer={row.employer!r} role={row.job_name!r} "
                f"region={row.region!r} url={row.url!r} key={row.key}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
