#!/usr/bin/env python3
"""Metadata-only 85novel catalog audit for 变脸武士.

85novel renders a short latest-chapters list in HTML and has a public
paginated chapter-list action for the ordinary reader. Discover its actual
page ranges from HTML; do not invent IDs or follow another host. No
authentication, CAPTCHA or paywall bypass; robots.txt checked fail-closed.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlencode

from bs4 import BeautifulSoup
from chapter_coverage_census import PoliteClient
from masked_knight_cn_catalog_audit import number_from_title

BOOK_URL = "https://www.85novel.com/book/801674.html"
BOOK_ID = "801674"
EXPECTED = 330
TOKEN = re.compile(r"""x-data\s*=\s*["'][^"']*?Login\(\s*\d+\s*,\s*['"]([^'"]+)['"]""", re.I)
RANGE = re.compile(r"(\d+)\s*[~～\-]\s*(\d+)")
BAD_RESPONSE = re.compile(r"captcha|just a moment|checking your browser|"
                          r"please enable javascript|access denied|正在验证浏览器",
                          re.I)


def parse_slices(page: str) -> list[tuple[int, int]]:
    soup = BeautifulSoup(page, "html.parser")
    seen = set()
    for select in soup.select("select"):
        klass = " ".join(select.get("class", []))
        if "select-primary" not in klass and "chapters" not in klass.lower():
            continue
        for option in select.select("option"):
            for match in RANGE.finditer(option.get_text(" ", strip=True)):
                a, b = int(match.group(1)), int(match.group(2))
                if 1 <= a <= b <= 1000 and b - a < 500:
                    seen.add((a, b))
    return sorted(seen)


def token_from_page(page: str) -> str:
    match = TOKEN.search(page)
    if not match:
        raise ValueError("Public chapter-list token not present in page")
    token = match.group(1)
    # The public page token is opaque and URL-encoded before use. Its exact
    # character class and length are not an authentication guarantee.
    if (not 1 <= len(token) <= 512
            or any(ord(ch) < 32 or ord(ch) == 127 for ch in token)):
        raise ValueError("Malformed page token")
    return token


def normalize_chapter_url(raw: str) -> str:
    if not isinstance(raw, str):
        raise ValueError("ChapterUrl missing")
    raw = raw.strip()
    if not raw:
        raise ValueError("Empty ChapterUrl")
    if re.fullmatch(r"801674/\d+\.html", raw):
        raw = "/book/" + raw
    elif re.fullmatch(r"/?book/801674/\d+\.html", raw):
        raw = "/" + raw.lstrip("/")
    elif re.fullmatch(r"\d+\.html", raw):
        raw = "/book/801674/" + raw
    url = urljoin(BOOK_URL, raw)
    p = urlsplit(url)
    if (p.scheme != "https" or p.netloc != "www.85novel.com"
            or not re.fullmatch(r"/book/801674/\d+\.html", p.path)
            or p.query or p.fragment or p.username or p.password):
        raise ValueError("Foreign or unsafe chapter link")
    return url


def parse_chapters(items: list[dict], expected: int = EXPECTED) -> dict:
    by_number = {}
    conflicts = []
    bad = []
    for item in items:
        if not isinstance(item, dict):
            bad.append("non_object")
            continue
        title = item.get("ChapterName")
        if not isinstance(title, str):
            bad.append("missing_name")
            continue
        number = number_from_title(title)
        if number is None:
            # Exclude author notes and service chapters.
            continue
        if not 1 <= number <= expected:
            bad.append(f"out_of_range:{number}")
            continue
        try:
            url = normalize_chapter_url(item.get("ChapterUrl"))
        except ValueError:
            bad.append(f"bad_url:{number}")
            continue
        ch = {"ordinal": number, "title_zh": title.strip(), "url": url}
        if number in by_number and by_number[number]["url"] != url:
            conflicts.append({"ordinal": number, "first": by_number[number]["url"],
                              "second": url})
        else:
            by_number[number] = ch
    missing = sorted(set(range(1, expected + 1)) - set(by_number))
    return {"catalog_count": len(by_number), "raw_records": len(items),
            "chapters": [by_number[x] for x in sorted(by_number)],
            "missing": missing, "conflicts": conflicts, "bad_records": bad,
            "complete": len(by_number) == expected and not conflicts and not bad}


def fetch_slice(client: PoliteClient, token: str, block: tuple[int, int]) -> list[dict]:
    url = BOOK_URL + "?" + urlencode({"_xsrf": token})
    allowed, crawl_delay, host = client.allowed(url)
    if not allowed:
        raise RuntimeError("robots.txt disallows chapter-list endpoint")
    wait = max(client.delay, crawl_delay) - (time.monotonic() - client.last.get(host, 0))
    if wait > 0:
        time.sleep(wait)
    try:
        response = client.session.post(
            url, json={"action": "chapters", "slice": list(block)},
            headers={"Referer": BOOK_URL, "Accept": "application/json"},
            timeout=(8, 22), allow_redirects=False)
    except Exception as exc:
        raise RuntimeError("Chapter-list request failure: " + type(exc).__name__) from exc
    client.last[host] = time.monotonic()
    if response.status_code != 200:
        raise RuntimeError(f"Chapter-list HTTP {response.status_code}")
    if "json" not in response.headers.get("Content-Type", "").lower():
        raise RuntimeError("Chapter-list returned non-JSON page")
    if BAD_RESPONSE.search(response.text[:4000]):
        raise RuntimeError("Chapter-list access challenge")
    try:
        data = response.json()
    except ValueError as exc:
        raise RuntimeError("Chapter-list invalid JSON") from exc
    if not isinstance(data, dict) or not isinstance(data.get("result"), dict):
        raise RuntimeError("Chapter-list invalid schema")
    chapters = data["result"].get("chapters")
    if not isinstance(chapters, list):
        raise RuntimeError("Chapter-list not an array")
    return chapters


def run(delay: float, out: Path) -> dict:
    if delay < 1.5:
        raise ValueError("Request interval >=1.5s")
    out.mkdir(parents=True, exist_ok=True)
    report = {"book": "变脸武士", "url": BOOK_URL,
              "started_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
              "requested": EXPECTED, "body_text_downloaded": False,
              "status": "unverified", "slices": [], "chapter_metadata": []}
    try:
        client = PoliteClient(delay)
        page = client.get(BOOK_URL)  # robots fail closed, normal public GET
        if "變臉武士" not in page and "变脸武士" not in page:
            raise RuntimeError("Book identity mismatch")
        blocks = parse_slices(page)
        if not blocks:
            # Publisher's separate catalog contains 425 positions including
            # auxiliaries. Probe only a bounded set of public reader pages.
            report["note"] = "No slice controls; bounded fallback through position 600"
            blocks = [(1, 200), (201, 400), (401, 600)]
        report["slices"] = [list(block) for block in blocks]
        token = token_from_page(page)  # never print or store it
        items = []
        for block in blocks:
            items.extend(fetch_slice(client, token, block))
        parsed = parse_chapters(items)
        report.update({k: v for k, v in parsed.items() if k != "chapters"})
        report["chapter_metadata"] = parsed["chapters"]
        report["status"] = "COMPLETE_INDEX" if parsed["complete"] else "PARTIAL_INDEX"
    except Exception as exc:
        report["status"] = "BLOCKED_OR_UNAVAILABLE"
        report["error"] = type(exc).__name__ + ": " + str(exc)[:180]
    (out / "manifest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = ["# Masked Knight 85novel public catalog audit", "",
               f"Status: {report['status']}",
               f"Story chapters indexed: {report.get('catalog_count',0)}/{EXPECTED}",
               f"Slices: {report['slices']}",
               f"Missing: {report.get('missing',[])[:50]}",
               f"Conflicts: {len(report.get('conflicts',[]))}",
               f"Bad: {len(report.get('bad_records',[]))}",
               f"Error: {report.get('error','none')}", "",
               "No story text downloaded. Uses public site chapter-list action."]
    (out / "summary.md").write_text("\n".join(summary) + "\n", encoding="utf-8")
    return report


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", type=Path, default=Path("out/masked-knight-85novel"))
    p.add_argument("--delay", type=float, default=2)
    args = p.parse_args()
    report = run(args.delay, args.out)
    print((args.out / "summary.md").read_text(encoding="utf-8"))
    return 0 if report["status"] == "COMPLETE_INDEX" else 1


if __name__ == "__main__":
    sys.exit(main())
