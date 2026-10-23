#!/usr/bin/env python3
"""Metadata-only Chinese chapter index audit for 变脸武士 / Masked Knight.

Preserves chapter identifiers and links only, never story prose. Robots policy
and site access controls are respected. Inaccessible does not mean missing.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import re
import sys
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup
from chapter_coverage_census import PoliteClient, parse_han_number

SOURCES = {
    "hetushu": "https://www.hetushu.com/book/123/index.html",
    "hetubook": "https://www.hetubook.com/book/123/index.html",
    "piaotia": "https://www.piaotia.com/html/0/387/index.html",
    "yedu266": "https://www.yedu266.com/bianlianwushi/",
    "85novel": "https://www.85novel.com/book/801674.html",
    "quanben18": "https://www.quanben18.com/bianlianwushi/",
    "legaoxs": "https://www.legaoxs.com/bianlianwushi/",
    "xs-cn": "https://www.xs.cn/bookquery/amiqjdycuren",
}
EXPECTED = 330
NUM = re.compile(r"第\s*([零〇一二三四五六七八九十百千两兩0-9]{1,12})\s*章")
CATALOG = re.compile(
    r"(?:目录|目錄|全部章节|全部章節|章节列表|章節列表|阅读全文|全文閱讀)")


def number_from_title(title: str):
    match = NUM.search(title)
    if not match:
        return None
    digits = match.group(1).replace("兩", "二").replace("两", "二")
    return int(digits) if digits.isdecimal() else parse_han_number(digits)


def index_from_html(source_url: str, html: str) -> dict:
    original = urlsplit(source_url)
    found: dict[int, dict] = {}
    conflicts: list[dict] = []
    suggestions: list[str] = []
    soup = BeautifulSoup(html, "html.parser")
    for a in soup.select("a[href]"):
        title = re.sub(r"\s+", " ", a.get_text(" ", strip=True))
        href = urljoin(source_url, a["href"]).split("#", 1)[0]
        target = urlsplit(href)
        if (target.scheme != "https" or target.hostname != original.hostname
                or target.port not in (None, 443)):
            continue
        if CATALOG.search(title) and href != source_url and len(suggestions) < 5:
            suggestions.append(href)
        ordinal = number_from_title(title)
        if ordinal is None or not 1 <= ordinal <= EXPECTED or href == source_url:
            continue
        if href.lower().endswith((".jpg", ".png", ".gif", ".pdf")):
            continue
        chapter = {"ordinal": ordinal, "title_zh": title, "url": href}
        if ordinal in found and found[ordinal]["url"] != href:
            conflicts.append({
                "ordinal": ordinal,
                "previous": found[ordinal]["url"], "new": href,
            })
            continue
        found[ordinal] = chapter
    missing = sorted(set(range(1, EXPECTED + 1)) - set(found))
    return {
        "chapters": [found[k] for k in sorted(found)],
        "catalog_count": len(found), "missing": missing,
        "duplicate_ordinals": conflicts,
        "catalog_link_candidates": sorted(set(suggestions)),
        "status": "index_complete" if len(found) == EXPECTED
                  and not conflicts else "index_partial",
    }


def audit(out: Path, delay: float) -> dict:
    if delay < 1.5:
        raise ValueError("Delay >= 1.5 seconds required")
    out.mkdir(parents=True, exist_ok=True)
    client = PoliteClient(delay)
    report = {
        "book": "变脸武士",
        "expected_story_ordinals": EXPECTED,
        "run_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "policy": "metadata only, robots fail-closed, no chapter text",
        "sources": [],
    }
    for key, url in SOURCES.items():
        row = {"source": key, "index_url": url, "status": "unverified"}
        try:
            html = client.get(url)
            if not ("变脸武士" in html or "變臉武士" in html):
                row.update(status="identity_unverified",
                           detail="Book title not found")
            else:
                row.update(index_from_html(url, html))
        except Exception as exc:
            row.update(status="unavailable", detail=str(exc)[:250])
        report["sources"].append(row)
    (out / "manifest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    with (out / "chapters_index.tsv").open(
            "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(["source", "ordinal", "title_zh", "url"])
        for source in report["sources"]:
            for row in source.get("chapters", []):
                writer.writerow([
                    source["source"], row["ordinal"],
                    row["title_zh"], row["url"],
                ])
    lines = [
        "# Masked Knight Chinese chapter index availability", "",
        "| Source | Chapters indexed / 330 | Gaps | Conflicts | Status |",
        "|---|---:|---:|---:|---|",
    ]
    for item in report["sources"]:
        n_gaps = len(item["missing"]) if "missing" in item else "?"
        lines.append(
            f"| {item['source']} | {item.get('catalog_count', 0)}/330 | "
            f"{n_gaps} | {len(item.get('duplicate_ordinals', []))} | "
            f"{item['status']} |")
        if item.get("detail"):
            lines.append(f"- {item['source']}: {item['detail']}")
    lines += ["", "Counts reflect index labels only, not validated story text."]
    (out / "summary.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path,
                        default=Path("out/masked-knight-chinese"))
    parser.add_argument("--delay", type=float, default=2.0)
    args = parser.parse_args()
    result = audit(args.out, args.delay)
    print((args.out / "summary.md").read_text(encoding="utf-8"))
    return (0 if any(i.get("status") == "index_complete"
                     for i in result["sources"]) else 1)


if __name__ == "__main__":
    sys.exit(main())
