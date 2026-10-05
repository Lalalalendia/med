#!/usr/bin/env python3
"""Credential-free HeadHunter RSS discovery queue for Microsoft Publisher.

The RSS feed is intentionally treated as candidate-discovery evidence only.
It proves that HeadHunter search matched the exact query and provides stable
vacancy identity/provenance, but it does not expose enough vacancy text to
assign the production A/B/C classifier.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

RSS_URL = "https://hh.ru/search/vacancy/rss"
USER_AGENT = "ChapteraPublisherRadar/1.0 (+https://github.com/Lalalalendia/med)"
DEFAULT_QUERIES = ("Microsoft Publisher", "MS Publisher")
DEFAULT_AREA = "113"  # Russia
MAX_BYTES = 2 * 1024 * 1024
TIMEOUT_SECONDS = 45

VACANCY_ID_RE = re.compile(r"/vacancy/(\d+)(?:[/?#]|$)")
HTML_TAG_RE = re.compile(r"<[^>]+>")
FIELD_PATTERNS = {
    "employer": re.compile(r"(?:^|\n)Вакансия компании:\s*(.+?)(?:\n|$)", re.I),
    "created_label": re.compile(r"(?:^|\n)Создана:\s*(.+?)(?:\n|$)", re.I),
    "region": re.compile(r"(?:^|\n)Регион:\s*(.+?)(?:\n|$)", re.I),
    "salary": re.compile(
        r"(?:^|\n)Предполагаемый уровень месячного дохода:\s*(.+?)(?:\n|$)",
        re.I,
    ),
}


@dataclass(frozen=True)
class HHRssCandidate:
    source: str
    source_id: str
    key: str
    url: str
    title: str
    employer: str
    region: str
    salary: str
    published_at: str
    created_label: str
    query_matches: tuple[str, ...]
    evidence_level: str
    qualification_status: str


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].casefold()


def _first_text(node: ET.Element, names: Iterable[str]) -> str:
    wanted = {name.casefold() for name in names}
    for child in node.iter():
        if _local_name(child.tag) in wanted and child.text:
            text = " ".join(child.text.split())
            if text:
                return text
    return ""


def _entry_link(node: ET.Element) -> str:
    for child in node.iter():
        if _local_name(child.tag) != "link":
            continue
        href = (child.attrib.get("href") or "").strip()
        if href:
            return href
        if child.text:
            text = " ".join(child.text.split())
            if text:
                return text
    return ""


def _description_text(node: ET.Element) -> str:
    raw = _first_text(node, ("description", "summary", "content"))
    if not raw:
        return ""
    text = re.sub(r"(?i)</p\s*>", "\n", raw)
    text = HTML_TAG_RE.sub(" ", text)
    text = html.unescape(text).replace("\u00a0", " ")
    return "\n".join(" ".join(line.split()) for line in text.splitlines() if line.strip())


def _field(description: str, name: str) -> str:
    match = FIELD_PATTERNS[name].search(description)
    return " ".join(match.group(1).split()) if match else ""


def _source_id(link: str, guid: str) -> str:
    for value in (link, guid):
        match = VACANCY_ID_RE.search(value)
        if match:
            return match.group(1)
    return ""


def build_feed_url(query: str, *, area: str = DEFAULT_AREA) -> str:
    return RSS_URL + "?" + urllib.parse.urlencode({"text": query, "area": area})


def fetch_feed(query: str, *, area: str = DEFAULT_AREA) -> bytes:
    url = build_feed_url(query, area=area)
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/rss+xml, application/xml;q=0.9, text/xml;q=0.8",
        },
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        data = response.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError(f"HH RSS response exceeds {MAX_BYTES} bytes")
    return data


def parse_feed(data: bytes, query: str) -> list[HHRssCandidate]:
    root = ET.fromstring(data)
    out: list[HHRssCandidate] = []
    for node in root.iter():
        if _local_name(node.tag) not in {"item", "entry"}:
            continue
        title = _first_text(node, ("title",))
        link = _entry_link(node)
        guid = _first_text(node, ("guid", "id"))
        source_id = _source_id(link, guid)
        if not source_id:
            continue
        description = _description_text(node)
        published = _first_text(node, ("pubdate", "published", "updated", "date"))
        out.append(
            HHRssCandidate(
                source="hh_rss",
                source_id=source_id,
                key=f"hh:{source_id}",
                url=link or guid,
                title=title,
                employer=_field(description, "employer"),
                region=_field(description, "region"),
                salary=_field(description, "salary"),
                published_at=published,
                created_label=_field(description, "created_label"),
                query_matches=(query,),
                evidence_level="search_match_only",
                qualification_status="unverified",
            )
        )
    return out


def merge_candidates(groups: Iterable[Iterable[HHRssCandidate]]) -> list[HHRssCandidate]:
    by_key: dict[str, HHRssCandidate] = {}
    queries: dict[str, set[str]] = {}
    for group in groups:
        for row in group:
            by_key.setdefault(row.key, row)
            queries.setdefault(row.key, set()).update(row.query_matches)

    merged: list[HHRssCandidate] = []
    for key, row in by_key.items():
        merged.append(
            HHRssCandidate(
                **{
                    **asdict(row),
                    "query_matches": tuple(sorted(queries[key])),
                }
            )
        )
    merged.sort(key=lambda row: (row.published_at, row.key), reverse=True)
    return merged


def run_discovery(
    queries: Iterable[str],
    *,
    area: str = DEFAULT_AREA,
    fetcher: Any = fetch_feed,
) -> list[HHRssCandidate]:
    groups = [parse_feed(fetcher(query, area=area), query) for query in queries]
    return merge_candidates(groups)


def _row_dict(row: HHRssCandidate) -> dict[str, Any]:
    data = asdict(row)
    data["query_matches"] = list(row.query_matches)
    return data


def write_outputs(rows: list[HHRssCandidate], out_dir: Path, area: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "candidates.json").write_text(
        json.dumps([_row_dict(row) for row in rows], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    with (out_dir / "candidates.csv").open("w", encoding="utf-8", newline="") as fh:
        fields = [
            "key", "source_id", "title", "employer", "region", "salary",
            "published_at", "created_label", "url", "query_matches",
            "evidence_level", "qualification_status",
        ]
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            data = _row_dict(row)
            writer.writerow({
                **{field: data.get(field, "") for field in fields},
                "query_matches": " | ".join(data["query_matches"]),
            })

    lines = [
        "# HeadHunter Publisher RSS discovery",
        "",
        f"- Area: {area}",
        f"- Unique candidates: **{len(rows)}**",
        "- Evidence boundary: RSS search match only; **no A/B/C classification**.",
        "- Qualification status: all rows are unverified until duties/skills are recovered from an independent public evidence surface or credentialed HH detail API.",
        "",
        "## Candidates",
        "",
    ]
    if not rows:
        lines.append("No candidates in the current RSS feeds.")
    else:
        for row in rows:
            matches = ", ".join(row.query_matches)
            lines.append(f"- **{row.employer or '(unknown employer)'} — {row.title or '(untitled)'}**")
            lines.append(f"  - published: {row.published_at or row.created_label or '-'}")
            lines.append(f"  - region: {row.region or '-'}")
            lines.append(f"  - query: {matches}")
            lines.append(f"  - url: {row.url or '-'}")

    (out_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default="out/pub-market-hh-rss")
    parser.add_argument("--query", action="append", dest="queries")
    parser.add_argument("--area", default=DEFAULT_AREA)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    queries = tuple(args.queries or DEFAULT_QUERIES)
    rows = run_discovery(queries, area=args.area)
    write_outputs(rows, Path(args.output_dir), args.area)
    print(f"HH Publisher RSS discovery: total={len(rows)} area={args.area}")
    for row in rows:
        print(
            "candidate: "
            f"employer={row.employer!r} role={row.title!r} region={row.region!r} "
            f"published={row.published_at!r} key={row.key} url={row.url!r}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
