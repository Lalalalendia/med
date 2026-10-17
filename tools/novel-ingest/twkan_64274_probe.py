#!/usr/bin/env python3
"""Read-only Twkan 64274 catalog/boundary probe.

Only collects chapter links, response status, text length and SHA-256. No
book content is printed, committed, or uploaded. Honors robots.txt, rate
limits, and challenge pages; never attempts authentication or bypass.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import hashlib
import json
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

BASE = "https://twkan.com"
BOOK = "64274"
CATALOG = f"{BASE}/ajax_novels/chapterlist/{BOOK}.html"
INDEX = f"{BASE}/book/{BOOK}/index.html"
TARGETS = (634, 635, 636, 700, 1000, 1454, 1455, 1456)
KNOWN_LAST = {
    1454: f"{BASE}/txt/{BOOK}/47302751",
    1455: f"{BASE}/txt/{BOOK}/47302752",
    1456: f"{BASE}/txt/{BOOK}/47302753",
}
USER_AGENT = "MedChapterProbe/1.0 (+https://github.com/Lalalalendia/med; metadata only)"
HAN = {ch: i for i, ch in enumerate("零一二三四五六七八九")}
HAN.update({"〇": 0, "兩": 2, "两": 2})
UNITS = {"十": 10, "百": 100, "千": 1000}
TITLE_RE = re.compile(r"^第\s*([0-9]+|[零〇一二三四五六七八九十百千兩两]+)\s*章")
BLOCK_TERMS = ("just a moment", "checking your browser", "captcha",
               "cloudflare challenge", "verify you are human", "cf-chl-")
SELECTORS = ("#txtcontent0", "#txtcontent", "#content", "#chaptercontent",
             ".read-content", ".chapter-content", ".novel-content")
SESSION_TIMEOUT = (7, 18)


def han_number(value: str) -> int | None:
    if value.isdecimal():
        return int(value)
    subtotal = 0
    digit = 0
    for ch in value:
        if ch in UNITS:
            subtotal += (digit or 1) * UNITS[ch]
            digit = 0
        elif ch in HAN:
            digit = HAN[ch]
        else:
            return None
    return subtotal + digit


def title_number(title: str) -> int | None:
    match = TITLE_RE.match(title.strip())
    return han_number(match.group(1)) if match else None


def parse_catalog(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    result = []
    for a in soup.select('a[href*="/txt/64274/"]'):
        url = urljoin(BASE, a.get("href", "")).split("?", 1)[0]
        parsed = urlparse(url)
        if parsed.netloc != "twkan.com" or not re.fullmatch(r"/txt/64274/\d+/?", parsed.path):
            continue
        title = a.get_text(" ", strip=True)
        number = title_number(title)
        if number is not None:
            result.append({"number": number, "title": title, "url": url})
    return result


def analyze_catalog(entries: list[dict]) -> dict:
    by_number = collections.Counter(x["number"] for x in entries)
    numbers = sorted(by_number)
    return {
        "parsed_links": len(entries),
        "unique_numbers": len(numbers),
        "min_number": numbers[0] if numbers else None,
        "max_number": numbers[-1] if numbers else None,
        "missing_numbers_1_to_1456": [i for i in range(1, 1457) if i not in by_number],
        "duplicate_numbers": {str(i): c for i, c in by_number.items() if c > 1},
        "target_links": {
            str(n): [x for x in entries if x["number"] == n]
            for n in TARGETS
        },
    }


def inspect_body(html: str) -> dict:
    lower = html.lower()
    if any(x in lower for x in BLOCK_TERMS):
        return {"state": "challenge", "cjk_chars": 0}
    soup = BeautifulSoup(html, "html.parser")
    root = next((soup.select_one(selector) for selector in SELECTORS
                 if soup.select_one(selector) is not None), None)
    if root is None:
        return {"state": "content_selector_missing", "cjk_chars": 0}
    for tag in root.select("script,style,nav,iframe,form,.ads,.advertisement"):
        tag.decompose()
    plain = " ".join(root.stripped_strings)
    cjk_chars = len(re.findall(r"[\u3400-\u9fff]", plain))
    status = "readable" if cjk_chars >= 300 else "too_short"
    return {
        "state": status,
        "cjk_chars": cjk_chars,
        "text_chars": len(plain),
        "sha256": hashlib.sha256(plain.encode("utf-8")).hexdigest() if plain else None,
    }


def request(session: requests.Session, url: str) -> tuple[requests.Response | None, dict]:
    try:
        resp = session.get(url, timeout=SESSION_TIMEOUT, allow_redirects=True)
        info = {
            "url": url, "final_url": resp.url, "status": resp.status_code,
            "bytes": len(resp.content),
            "content_type": resp.headers.get("Content-Type", ""),
        }
        return resp, info
    except requests.RequestException as error:
        return None, {"url": url, "error": type(error).__name__ + ": " + str(error)[:160]}


def robots_check(session: requests.Session) -> tuple[RobotFileParser | None, dict]:
    resp, info = request(session, f"{BASE}/robots.txt")
    if resp is None:
        info["state"] = "unavailable; stop"
        return None, info
    if resp.status_code == 404:
        info["state"] = "not_found; ordinary public pages allowed"
        rp = RobotFileParser()
        rp.parse([])
        return rp, info
    if resp.status_code != 200:
        info["state"] = "robots_response_error; stop"
        return None, info
    if "user-agent:" not in resp.text.lower():
        info["state"] = "robots_unrecognized; stop"
        return None, info
    rp = RobotFileParser()
    rp.parse(resp.text.splitlines())
    info["state"] = "parsed"
    return rp, info


def self_test() -> None:
    html = """
    <ul>
      <li data-num="633"><a href="/txt/64274/111">第634章 接連死亡！</a></li>
      <li data-num="634"><a href="/txt/64274/222">第六百三十五章 求你了</a></li>
      <li data-num="635"><a href="/txt/64274/333">第636章 幸好</a></li>
      <li><a href="/txt/64275/3">第637章 WRONG</a></li>
    </ul>"""
    parsed = parse_catalog(html)
    assert [x["number"] for x in parsed] == [634, 635, 636], parsed
    assert analyze_catalog(parsed)["target_links"]["635"][0]["url"].endswith("/222")
    sample_body = '<div id="txtcontent0">' + ("白淵又一次看見恐怖的鬼影。" * 50) + "</div>"
    assert inspect_body(sample_body)["state"] == "readable"
    assert inspect_body("<h1>No text</h1>")["state"] == "content_selector_missing"
    assert inspect_body("<p>Just a moment...</p>")["state"] == "challenge"
    print("SELF_TEST_OK")


def run(out_dir: Path, targets: tuple[int, ...], delay: float) -> dict:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "zh-TW,zh;q=0.9"})
    report = {
        "book_id": BOOK, "source": BASE,
        "checked_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "scope": "metadata-only; no book bodies saved",
        "targets": targets,
    }
    rp, report["robots"] = robots_check(session)
    if rp is None:
        report["state"] = "robots_unavailable_stop"
        return report
    if not rp.can_fetch(USER_AGENT, CATALOG):
        report["state"] = "robots_disallow_catalog"
        return report

    time.sleep(delay)
    catalog_response, report["catalog_request"] = request(session, CATALOG)
    if catalog_response is None or catalog_response.status_code != 200:
        report["state"] = "catalog_unavailable"
        return report
    if any(term in catalog_response.text.lower() for term in BLOCK_TERMS):
        report["state"] = "catalog_challenge"
        return report

    entries = parse_catalog(catalog_response.text)
    report["catalog"] = analyze_catalog(entries)
    report["state"] = "catalog_parsed" if entries else "catalog_empty_or_unrecognized"
    link_map = {x["number"]: x["url"] for x in entries if x["number"] in targets}
    report["chapters"] = {}
    for number in targets:
        url = link_map.get(number) or KNOWN_LAST.get(number)
        if url is None:
            report["chapters"][str(number)] = {"state": "url_not_in_catalog"}
            continue
        if not rp.can_fetch(USER_AGENT, url):
            report["chapters"][str(number)] = {"url": url, "state": "robots_disallow"}
            continue
        time.sleep(delay)
        page_response, item = request(session, url)
        if page_response is None:
            item["state"] = "network_error"
        elif page_response.status_code in (403, 429, 503):
            item["state"] = "blocked_stop"
            report["chapters"][str(number)] = item
            report["state"] = "access_blocked"
            break
        elif page_response.status_code != 200:
            item["state"] = "http_error"
        else:
            item.update(inspect_body(page_response.text))
        report["chapters"][str(number)] = item
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--out", type=Path, default=Path("out/twkan-64274"))
    parser.add_argument("--delay", type=float, default=1.5)
    parser.add_argument("--targets", nargs="+", type=int, default=TARGETS)
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if args.delay < 1.0:
        parser.error("Delay must be at least 1 second")
    args.out.mkdir(parents=True, exist_ok=True)
    report = run(args.out, tuple(args.targets), args.delay)
    (args.out / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    catalog = report.get("catalog", {})
    with (args.out / "summary.md").open("w", encoding="utf-8") as f:
        f.write("## Twkan 64274 boundary probe\n\n")
        f.write(f"- Outcome: **{report['state']}**\n")
        f.write(f"- Catalog parsed links: {catalog.get('parsed_links', 0)}\n")
        f.write(f"- Missing numbered chapters: {len(catalog.get('missing_numbers_1_to_1456', []))}\n")
        for number, entry in report.get("chapters", {}).items():
            f.write(f"- Chapter {number}: **{entry['state']}**; "
                    f"CJK characters: {entry.get('cjk_chars', 0)}\n")
        f.write("\nDetailed evidence (URLs, checksums, HTTP status): report.json artifact.\n")
    print(json.dumps({
        "state": report["state"],
        "catalog_parsed": catalog.get("parsed_links", 0),
        "chapter_states": {n: x["state"] for n, x in report.get("chapters", {}).items()}
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
