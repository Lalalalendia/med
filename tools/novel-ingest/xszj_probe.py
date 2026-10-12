#!/usr/bin/env python3
"""Public X SZJ page-shape probe. Writes metadata, NEVER story text or raw HTML.

This is deliberately not an extractor. It discovers the DOM content wrapper and
per-page title format for the separately indexed 81-chapter continuation.
"""
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

USER_AGENT = "ChapteraSourceIndexProbe/1.0 (public metadata check, no credentials)"
SELECTORS = (
    "#content", "#chaptercontent", "#chapter-content", "#txt",
    "#read-content", "#readContent", ".chapter-content", ".read-content",
    ".readContent", ".content", ".article-content", ".chapter-body",
    ".novelcontent", ".text", "article", "main",
)
HOST = "xszj.org"
MAX_BYTES = 2_000_000


def request_public(session: requests.Session, url: str) -> requests.Response:
    u = urlsplit(url)
    if u.scheme != "https" or u.hostname != HOST or u.username or u.password or u.port:
        raise ValueError("Refusing non-xszj HTTPS URL")
    response = session.get(url, timeout=20, allow_redirects=False, stream=True)
    if response.is_redirect:
        response.close()
        raise ValueError(f"Redirect refused: HTTP {response.status_code}")
    content = bytearray()
    for chunk in response.iter_content(64 * 1024):
        content.extend(chunk)
        if len(content) > MAX_BYTES:
            response.close()
            raise ValueError("Response exceeds maximum bytes")
    response._content = bytes(content)
    response._content_consumed = True
    response.close()
    return response


def robots_allow(session: requests.Session, urls: list[str]) -> tuple[bool, str]:
    try:
        response = request_public(session, "https://xszj.org/robots.txt")
    except (requests.RequestException, ValueError) as error:
        return False, f"robots check unavailable: {type(error).__name__}"
    if response.status_code in (404, 410):
        return True, f"robots absent (HTTP {response.status_code})"
    if response.status_code != 200:
        return False, f"robots check returned HTTP {response.status_code}"
    parser = RobotFileParser()
    parser.parse(response.text.splitlines())
    if not all(parser.can_fetch(USER_AGENT, url) for url in urls):
        return False, "robots disallows one or more requested URLs"
    delay = parser.crawl_delay(USER_AGENT)
    if delay is not None and delay > 10:
        return False, f"robots delay {delay}s exceeds probe budget"
    return True, f"robots allows requested URLs; crawl-delay={delay}"


def inspect_html(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    title = soup.find("h1")
    name = re.sub(r"\s+", " ", title.get_text(" ", strip=True)) if title else ""
    # Report only a compact number from a chapter heading; never print a book excerpt.
    heading_numbers = re.findall(r"\d{1,5}", name)[:4]
    matches = []
    for selector in SELECTORS:
        nodes = soup.select(selector)
        if nodes:
            matches.append({
                "selector": selector,
                "count": len(nodes),
                "chars": [len(n.get_text(" ", strip=True)) for n in nodes[:3]],
                "tags": [n.name for n in nodes[:3]],
            })
    # Also expose tag and class of the largest text-bearing div for diagnosis.
    divs = sorted(soup.select("div"), key=lambda n: len(n.get_text(" ", strip=True)), reverse=True)
    largest = [
        {"tag": d.name, "id": (d.get("id") or "")[:50],
         "classes": d.get("class", [])[:4], "chars": len(d.get_text(" ", strip=True))}
        for d in divs[:6]
    ]
    return {"has_h1": bool(title), "heading_numbers": heading_numbers,
            "selectors": matches, "largest_divs": largest}


def run(manifest: Path, ordinals: list[int], out: Path) -> dict:
    data = json.loads(manifest.read_text(encoding="utf-8"))
    wanted = set(ordinals)
    chapters = [r for r in data["chapters"] if r["catalog_ordinal"] in wanted]
    if len(chapters) != len(wanted):
        raise ValueError("Requested ordinal missing")
    urls = [url for r in chapters for url in r["part_urls"]]
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "text/html"})
    allowed, robots_reason = robots_allow(session, urls)
    rows = []
    if allowed:
        for entry in chapters:
            for part, url in enumerate(entry["part_urls"], 1):
                row = {"ordinal": entry["catalog_ordinal"], "part": part,
                       "url": url, "status": "not_fetched"}
                try:
                    response = request_public(session, url)
                    row["http_status"] = response.status_code
                    row["bytes"] = len(response.content)
                    row["content_type"] = response.headers.get("Content-Type", "").split(";")[0]
                    if response.status_code == 200 and "html" in row["content_type"].lower():
                        row["shape"] = inspect_html(response.text)
                        row["status"] = "inspected"
                    else:
                        row["status"] = "not_html_or_http_error"
                except (requests.RequestException, ValueError) as error:
                    row["status"] = "request_error"
                    row["error_type"] = type(error).__name__
                rows.append(row)
                time.sleep(1.5)
    report = {"schema_version": 1, "source": "xszj.org",
              "robots_allowed": allowed, "robots_reason": robots_reason,
              "chapter_ordinals": sorted(wanted), "pages": rows,
              "inspected_count": sum(r["status"] == "inspected" for r in rows)}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--ordinals", type=int, nargs="+", required=True)
    parser.add_argument("--out", type=Path, default=Path("out/xszj-probe/report.json"))
    opts = parser.parse_args()
    result = run(opts.manifest, opts.ordinals, opts.out)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["inspected_count"] < 1:
        raise SystemExit("No public HTML pages inspected; inspect report without treating as a pass")


if __name__ == "__main__":
    main()
