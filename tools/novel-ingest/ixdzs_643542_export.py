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
    detect_split_links, extract_catalog,
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


def fetch_all(start, end, delay, session):
    rp = check_robots(session)
    response = session.get(INDEX, timeout=(8, 25))
    response.raise_for_status()
    if urlsplit(response.url).hostname != "ixdzs.tw":
        raise ValueError("Catalog redirected to unexpected host")
    catalog = extract_catalog(response.text, response.url, start, end)
    required = list(range(start, end + 1))
    if len(catalog) != len(required):
        raise ValueError(f"Catalog has {len(catalog)} chapters but {len(required)} required")
    records = []
    seen = set()
    for num in required:
        url = catalog[num]["url"]
        if not rp.can_fetch(UA, url):
            raise ValueError(f"Source chapter forbidden by robots: {num}")
        time.sleep(delay)
        page = session.get(url, timeout=(8, 25))
        if page.status_code in (403, 429, 503):
            raise ValueError(f"Access limited at chapter {num}: {page.status_code}")
        page.raise_for_status()
        parts = urlsplit(page.url)
        match = PATH.fullmatch(parts.path)
        if (parts.scheme != "https" or parts.netloc.lower() != "ixdzs.tw"
                or not match or parts.path != urlsplit(url).path):
            raise ValueError(f"Untrusted redirect or chapter URL at {num}")
        title, text, cjk = parse_chapter(page.text, num, page.url)
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if digest in seen:
            raise ValueError(f"Duplicate chapter detected: {num}")
        seen.add(digest)
        records.append({
            "number": num, "title": title, "url": page.url,
            "url_number": int(match.group(1)), "catalog_title": catalog[num]["catalog_title"],
            "cjk_chars": cjk, "sha256": digest, "text": text
        })
        print(f"Chapter {num}: verified {cjk} Chinese characters", flush=True)
    return records


def write_zip(records, out_dir):
    if len(records) != END - START + 1 or [r["number"] for r in records] != list(range(START, END + 1)):
        raise ValueError("Incomplete chapter range: refusing export")
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"ixdzs-643542-{START}-{END}-cn.zip"
    combined = []
    manifest = []
    with ZipFile(target, "w", compression=ZIP_DEFLATED) as zipped:
        for item in records:
            label = f"第{item['number']}章 {item['title']}"
            content = f"{label}\n\n{item['text']}\n"
            zipped.writestr(f"chapters/{item['number']:04d}.txt", content)
            combined.append(content)
            manifest.append({k: v for k, v in item.items() if k != "text"})
        zipped.writestr("combined.txt", "\n\n".join(combined))
        zipped.writestr("manifest.json", json.dumps({
            "source": INDEX,
            "start": START, "end": END,
            "verified_utc": datetime.now(timezone.utc).isoformat(),
            "chapters": manifest,
            "rights_attested": True,
        }, indent=2, ensure_ascii=False))
    return target


def selftest():
    text = "這是一段測試文本。" * 80
    html = f"<h1>第660章 測試</h1><article><p>{text}</p></article>"
    title, body, n = parse_chapter(html, 660, "https://ixdzs.tw/read/643542/p660.html")
    assert title == "第660章 測試" and n >= 500 and text in body
    assert "chapters/0660.txt" == f"chapters/{660:04d}.txt"
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



def discover_latest(session):
    """Resolve the final chapter from the book's verified, contiguous catalog."""
    rp = check_robots(session)
    res = session.get(INDEX, timeout=(8, 25))
    res.raise_for_status()
    final = urlsplit(res.url)
    if final.scheme != "https" or final.netloc.lower() != "ixdzs.tw" or final.path.rstrip("/") != "/read/643542":
        raise ValueError(f"Unexpected catalog redirect: {res.url}")
    catalog = extract_catalog(res.text, res.url, START, 999999)
    mismatches = [(n, row["url_number"]) for n, row in sorted(catalog.items()) if row["number_mismatch"]]
    if mismatches:
        print("CATALOG_URL_NUMBER_MISMATCHES", mismatches[:50], flush=True)
    if not catalog or max(catalog) < START:
        raise ValueError("Chapter 660 is not present in the index")
    last = max(catalog)
    if last - START + 1 > 3000:
        raise ValueError(f"Too many chapters to collect in one safe run: {last - START + 1}")
    missing = sorted(set(range(START, last + 1)).difference(catalog))
    if missing:
        raise ValueError(f"Missing chapters in index: {missing[:30]}")
    for n in range(START, last + 1):
        if not rp.can_fetch(UA, catalog[n]["url"]):
            raise ValueError(f"robots.txt forbids chapter {n}")
    print(f"CATALOG_COMPLETE start={START} end={last} count={last-START+1}", flush=True)
    return last

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
        END = args.end if args.end is not None else discover_latest(session)
        if END < START or END - START + 1 > 3000:
            raise ValueError("Invalid chapter count or final chapter number")
        records = fetch_all(START, END, args.delay, session)
        archive = write_zip(records, args.out)
        report = {"source": INDEX, "start": START, "end": END, "count": len(records),
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
