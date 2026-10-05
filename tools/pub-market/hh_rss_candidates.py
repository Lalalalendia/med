#!/usr/bin/env python3
"""Credential-free HeadHunter RSS candidate queue for Publisher signals.

This is discovery only. RSS entries are not sufficient evidence for A/B/C
classification because the feed does not expose full vacancy duties/skills.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

HH_RSS_URL = "https://hh.ru/search/vacancy/rss"
DEFAULT_QUERIES = ("Microsoft Publisher", "MS Publisher")
DEFAULT_AREA = "113"
USER_AGENT = "ChapteraPublisherRadar/1.0 (+https://github.com/Lalalalendia/med)"
TAG_RE = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class HHRssCandidate:
    source: str
    vacancy_id: str
    url: str
    title: str
    employer: str
    region: str
    published: str
    query_matches: tuple[str, ...]
    evidence_level: str = "candidate_only"


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _first(node: ET.Element, names: Iterable[str]) -> str:
    wanted = {name.lower() for name in names}
    for child in node.iter():
        if _local(child.tag) in wanted and child.text:
            value = " ".join(child.text.split())
            if value:
                return value
    return ""


def _link(node: ET.Element) -> str:
    for child in node.iter():
        if _local(child.tag) != "link":
            continue
        if child.attrib.get("href"):
            return child.attrib["href"].strip()
        if child.text:
            return " ".join(child.text.split())
    return ""


def _clean_html(value: str) -> str:
    return " ".join(
        html.unescape(TAG_RE.sub(" ", value or "")).replace("\u00a0", " ").split()
    )


def _extract_label(text: str, label: str, next_labels: Iterable[str]) -> str:
    stop = "|".join(re.escape(x) for x in next_labels)
    pattern = rf"{re.escape(label)}:\s*(.+?)(?=\s+(?:{stop}):|$)"
    match = re.search(pattern, text, re.IGNORECASE)
    return match.group(1).strip() if match else ""


def parse_hh_rss(data: bytes, query: str) -> list[HHRssCandidate]:
    root = ET.fromstring(data)
    rows: list[HHRssCandidate] = []
    for node in root.iter():
        if _local(node.tag) not in {"item", "entry"}:
            continue
        url = _link(node)
        vacancy_id = url.rstrip("/").rsplit("/", 1)[-1] if url else _first(node, ("guid", "id"))
        body = _clean_html(_first(node, ("description", "summary", "content")))
        employer = _extract_label(body, "Вакансия компании", ("Создана", "Регион", "Зарплата"))
        region = _extract_label(
            body,
            "Регион",
            ("Предполагаемый уровень дохода", "Зарплата", "Создана"),
        )
        rows.append(
            HHRssCandidate(
                source="hh-rss",
                vacancy_id=vacancy_id,
                url=url,
                title=_first(node, ("title",)),
                employer=employer,
                region=region,
                published=_first(node, ("pubdate", "published", "updated", "date")),
                query_matches=(query,),
            )
        )
    return rows


def request_hh_rss(
    query: str,
    area: str,
    *,
    timeout: int = 30,
    opener: Callable[[urllib.request.Request, int], Any] | None = None,
) -> bytes:
    params = {"text": query, "area": area}
    req = urllib.request.Request(
        f"{HH_RSS_URL}?{urllib.parse.urlencode(params)}",
        headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml"},
    )
    if opener is None:
        def opener(request: urllib.request.Request, seconds: int):
            return urllib.request.urlopen(request, timeout=seconds)
    with opener(req, timeout) as response:
        return response.read(2 * 1024 * 1024)


def run_candidate_scan(
    queries: Iterable[str],
    area: str,
    *,
    fetcher: Callable[[str, str], bytes] = request_hh_rss,
) -> list[HHRssCandidate]:
    by_id: dict[str, HHRssCandidate] = {}
    matches: dict[str, set[str]] = {}
    for query in queries:
        for row in parse_hh_rss(fetcher(query, area), query):
            key = row.vacancy_id or row.url
            if not key:
                continue
            by_id.setdefault(key, row)
            matches.setdefault(key, set()).add(query)

    result: list[HHRssCandidate] = []
    for key, row in by_id.items():
        result.append(
            HHRssCandidate(
                source=row.source,
                vacancy_id=row.vacancy_id,
                url=row.url,
                title=row.title,
                employer=row.employer,
                region=row.region,
                published=row.published,
                query_matches=tuple(sorted(matches[key])),
            )
        )
    result.sort(key=lambda row: (row.published, row.vacancy_id), reverse=True)
    return result


def write_outputs(rows: list[HHRssCandidate], out_dir: Path, area: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = []
    for row in rows:
        data = asdict(row)
        data["query_matches"] = list(row.query_matches)
        payload.append(data)
    (out_dir / "candidates.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    lines = [
        "# HH Publisher RSS candidate queue",
        "",
        f"- Area: `{area}`",
        f"- Unique candidates: **{len(rows)}**",
        "- Evidence level: **candidate-only**; do not infer A/B/C from RSS alone.",
        "",
    ]
    for row in rows:
        lines.append(
            f"- {row.published} — **{row.employer or '(unknown employer)'} — "
            f"{row.title or '(unknown role)'}** — {row.region or '-'} — {row.url}"
        )
    (out_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default="out/pub-market-hh-rss")
    parser.add_argument("--area", default=DEFAULT_AREA)
    parser.add_argument("--query", action="append", dest="queries")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    queries = tuple(args.queries or DEFAULT_QUERIES)
    rows = run_candidate_scan(queries, args.area)
    write_outputs(rows, Path(args.output_dir), args.area)
    print(f"HH RSS Publisher candidates: total={len(rows)} area={args.area}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
