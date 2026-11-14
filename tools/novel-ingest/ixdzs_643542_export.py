#!/usr/bin/env python3
"""Rights-gated TXT export for IXDZS book 643542, chapters 660 onward.

Only use this to copy text when the operator has reproduction permission.
No CAPTCHA, login, verification, robots.txt or rate-limit bypass is attempted.
No original prose is committed to the repository; Actions artifacts are temporary.
"""
import argparse
import hashlib
import json
import re
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser
from zipfile import ZIP_DEFLATED, ZipFile

import requests
from bs4 import BeautifulSoup

from ixdzs_643542_probe import (
    BLOCK, INDEX, PATH, SELECTORS, UA, NUM,
    detect_split_links, extract_catalog, backfill_missing_prefix,
)

START, END = 660, 679


def parse_chapter(html, number, current_url):
    """Return title and prose for an allowed chapter; refuse ambiguous pages."""
    soup = BeautifulSoup(html, "html.parser")
    title_el = soup.select_one("h1") or soup.title
    title = title_el.get_text(" ", strip=True) if title_el else ""
    if any(word in title.lower() for word in BLOCK):
        raise ValueError(f"Challenge page at {number}")
    m = NUM.search(title)
    if not m or int(m.group(1)) != number:
        raise ValueError(f"Title-number mismatch at chapter {number}")
    if detect_split_links(html, number, current_url):
        raise ValueError(f"Chapter {number} appears split over multiple pages; refusing partial export")
    roots = [soup.select_one(sel) for sel in SELECTORS]
    roots = [el for el in roots if el is not None]
    if not roots:
        raise ValueError(f"No prose container at chapter {number}")
    root = max(roots, key=lambda el: len(el.get_text(" ", strip=True)))
    for bad in root.select("script,style,nav,form,iframe,footer,header,aside"):
        bad.decompose()
    paragraphs = [part.strip() for part in root.stripped_strings if part.strip()]
    body = "\n\n".join(paragraphs)
    chinese_chars = len(re.findall(r"[\u3400-\u9fff]", body))
    if chinese_chars < 250:
        raise ValueError(f"Short or invalid chapter {number}: {chinese_chars} CJK")
    return title, body, chinese_chars


def check_robots(session):
    robots = session.get("https://ixdzs.tw/robots.txt", timeout=(8, 20))
    if robots.status_code != 200 or "user-agent:" not in robots.text.lower():
        raise ValueError("Cannot verify robots policy; stopping")
    rp = RobotFileParser()
    rp.parse(robots.text.splitlines())
    if not rp.can_fetch(UA, INDEX):
        raise ValueError("Source index not permitted by robots")
    return rp


def fetch_all(start, end, delay, session, first_locator, last_locator):
    """Visit consecutive physical pages; do not assume pNNN is chapter N."""
    rp = check_robots(session)
    if first_locator < 1 or last_locator < first_locator or last_locator - first_locator > 3000:
        raise ValueError("Invalid physical locator bounds")
    records = []
    seen_hashes = set()
    seen_numbers = set()
    for locator in range(first_locator, last_locator + 1):
        url = f"https://ixdzs.tw/read/643542/p{locator}.html"
        if not rp.can_fetch(UA, url):
            raise ValueError(f"robots.txt forbids p{locator}")
        time.sleep(delay)
        page = session.get(url, timeout=(8, 25))
        if page.status_code in (403, 429, 503):
            raise ValueError(f"Source limited access at p{locator}: HTTP {page.status_code}")
        page.raise_for_status()
        dest = urlsplit(page.url)
        if (dest.scheme != "https" or dest.netloc.lower() != "ixdzs.tw"
                or dest.path != f"/read/643542/p{locator}.html"):
            raise ValueError(f"Untrusted redirect at p{locator}: {page.url}")
        soup = BeautifulSoup(page.text, "html.parser")
        heading_el = soup.select_one("h1") or soup.title
        heading = heading_el.get_text(" ", strip=True) if heading_el else ""
        match = NUM.search(heading)
        if not match:
            raise ValueError(f"Chapter number unavailable at p{locator}: {heading[:100]}")
        number = int(match.group(1))
        if number < start or number > end:
            raise ValueError(f"Unexpected chapter {number} at p{locator}; expected {start}-{end}")
        number_regression = bool(records and number < records[-1]["number"])
        title, body, cjk = parse_chapter(page.text, number, page.url)
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        if digest in seen_hashes:
            raise ValueError(f"Duplicate body at p{locator}")
        seen_hashes.add(digest)
        duplicate_number = number in seen_numbers
        seen_numbers.add(number)
        records.append({"number": number, "url_number": locator, "url": page.url,
                        "title": title, "cjk_chars": cjk, "sha256": digest,
                        "duplicate_ordinal": duplicate_number, "number_regression": number_regression,
                        "text": body})
        print(f"p{locator} -> {number}, {cjk} CJK, duplicate_number={duplicate_number}", flush=True)
    missing = sorted(set(range(start, end + 1)) - seen_numbers)
    if missing:
        print("SOURCE_HEADING_GAPS", missing, flush=True)
    print(f"FULL_RANGE_VERIFIED {start}-{end}: pages={len(records)}, distinct={len(seen_numbers)}, missing_headings={len(missing)}", flush=True)
    return records

def chapter_filename(item):
    return f"chapters/{item['number']:04d}_p{item['url_number']:04d}.txt"


def write_zip(records, out_dir):
    numbered = {r["number"] for r in records}
    wanted = set(range(START, END + 1))
    if not records or records[0]["number"] != START or records[-1]["number"] != END:
        raise ValueError("Source endpoint headings are not the requested start/end")
    locators = [r["url_number"] for r in records]
    if locators != list(range(min(locators), max(locators) + 1)):
        raise ValueError("Nonconsecutive physical pages")
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"ixdzs-643542-{START}-{END}-cn.zip"
    combined = []
    manifest = []
    with ZipFile(target, "w", compression=ZIP_DEFLATED) as zipped:
        for item in records:
            content = f"{item['title']}\n\n{item['text']}\n"
            zipped.writestr(chapter_filename(item), content)
            combined.append(content)
            manifest.append({k: v for k, v in item.items() if k != "text"})
        zipped.writestr("combined.txt", "\n\n".join(combined))
        zipped.writestr("manifest.json", json.dumps({
            "source": INDEX, "start": START, "end": END,
            "physical_pages": len(records), "unique_chapter_numbers": len(numbered),
            "duplicate_numbered_pages": len(records) - len(numbered),
            "missing_printed_ordinals": sorted(wanted - numbered),
            "number_regressions": [r["url_number"] for r in records if r["number_regression"]],
            "verified_utc": datetime.now(timezone.utc).isoformat(),
            "chapters": manifest, "rights_attested": True,
        }, indent=2, ensure_ascii=False))
    with ZipFile(target) as check:
        if check.testzip() is not None or len(check.namelist()) != len(records) + 2:
            raise ValueError("ZIP integrity check failed")
    return target

def selftest():
    text = "這是一段測試文本。" * 80
    html = f"<h1>第660章 測試</h1><article><p>{text}</p></article>"
    title, body, n = parse_chapter(html, 660, "https://ixdzs.tw/read/643542/p660.html")
    assert title == "第660章 測試" and n >= 500 and text in body
    assert chapter_filename({"number": 660, "url_number": 648}) == "chapters/0660_p0648.txt"
    assert chapter_filename({"number": 660, "url_number": 649}) != chapter_filename({"number": 660, "url_number": 648})
    try:
        parse_chapter("<h1>第660章</h1><article>短</article>", 660, INDEX + "p660.html")
    except ValueError:
        pass
    else:
        raise AssertionError("Short chapter was not rejected")
    try:
        parse_chapter(html + '<a href="/read/643542/p660_2.html">下一頁</a>', 660,
                      "https://ixdzs.tw/read/643542/p660.html")
    except ValueError:
        pass
    else:
        raise AssertionError("Split chapter was not rejected")
    print("EXPORT_SELFTEST_PASS")



def discover_latest(session, delay):
    """Find actual locator boundaries despite an index missing middle chapters."""
    rp = check_robots(session)
    res = session.get(INDEX, timeout=(8, 25))
    res.raise_for_status()
    dest = urlsplit(res.url)
    if dest.scheme != "https" or dest.netloc.lower() != "ixdzs.tw" or dest.path.rstrip("/") != "/read/643542":
        raise ValueError(f"Unexpected catalog URL: {res.url}")
    catalog = extract_catalog(res.text, res.url, START, 999999)
    if not catalog:
        raise ValueError("No numbered chapters in source catalog")
    end = max(catalog)
    if end < START or end - START + 1 > 3000:
        raise ValueError("Invalid final numbered chapter")
    prefix = backfill_missing_prefix(session, rp, catalog, START, min(catalog), delay)
    if START not in catalog:
        raise ValueError("Could not locate chapter 660")
    first_locator = catalog[START]["url_number"]
    last_locator = catalog[end]["url_number"]
    if last_locator < first_locator or last_locator - first_locator > 3000:
        raise ValueError("Invalid locator range")
    print("DISCOVERED", {"start_chapter": START, "first_url": first_locator,
                         "last_chapter": end, "last_url": last_locator,
                         "catalog_count": len(catalog), "prefix": prefix}, flush=True)
    return end, first_locator, last_locator

def main():
    global END
    p = argparse.ArgumentParser()
    p.add_argument("--rights-confirmed", action="store_true",
                   help="Operator confirms they hold permission to copy/reproduce these chapters")
    p.add_argument("--start", type=int, default=START)
    p.add_argument("--end", type=int, default=None)
    p.add_argument("--delay", type=float, default=2.0)
    p.add_argument("--out", type=Path, default=Path("out/authorized-ixdzs-643542"))
    p.add_argument("--selftest", action="store_true")
    args = p.parse_args()
    if args.selftest:
        selftest()
        return
    if not args.rights_confirmed:
        p.error("Explicit permission/rights confirmation required before export")
    if args.start != START:
        p.error("This collection must begin at chapter 660")
    if args.delay < 2:
        p.error("Delay must be at least 2 seconds")
    session = requests.Session()
    session.headers["User-Agent"] = UA
    try:
        found_end, first_locator, last_locator = discover_latest(session, args.delay)
        END = args.end if args.end is not None else found_end
        if END != found_end:
            raise ValueError("Use the full discovered range; partial export is not supported")
        records = fetch_all(START, END, args.delay, session, first_locator, last_locator)
        archive = write_zip(records, args.out)
        report = {"source": INDEX, "start": START, "end": END, "count": len(records),
                  "distinct_numbers": len({r["number"] for r in records}),
                  "missing_printed_ordinals": sorted(set(range(START, END + 1)) - {r["number"] for r in records}),
                  "archive": archive.name, "completed": True, "rights_confirmed": True}
        (args.out / "status.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
        print("COMPLETE", len(records), str(archive))
    except Exception as error:
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "status.json").write_text(json.dumps(
            {"source": INDEX, "start": START, "end": END, "completed": False,
             "error_type": type(error).__name__, "error": str(error)[:500]},
            ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
        raise


if __name__ == "__main__":
    main()
