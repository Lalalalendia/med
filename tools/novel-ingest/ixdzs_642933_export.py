#!/usr/bin/env python3
"""Rights-gated TXT export for IXDZS book 642933, chapters 186-205.

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

from ixdzs_642933_probe import (
    BLOCK, INDEX, PATH, SELECTORS, UA, NUM,
    detect_split_links, extract_catalog,
)

START, END = 186, 205


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
                or not match or int(match.group(1)) != num):
            raise ValueError(f"Untrusted redirect or chapter URL at {num}")
        title, text, cjk = parse_chapter(page.text, num, page.url)
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if digest in seen:
            raise ValueError(f"Duplicate chapter detected: {num}")
        seen.add(digest)
        records.append({
            "number": num, "title": title, "url": page.url,
            "cjk_chars": cjk, "sha256": digest, "text": text
        })
        print(f"Chapter {num}: verified {cjk} Chinese characters", flush=True)
    return records


def write_zip(records, out_dir):
    if len(records) != END - START + 1 or [r["number"] for r in records] != list(range(START, END + 1)):
        raise ValueError("Incomplete chapter range: refusing export")
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "ixdzs-642933-186-205-cn.zip"
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
    html = f"<h1>第186章 測試</h1><article><p>{text}</p></article>"
    title, body, n = parse_chapter(html, 186, "https://ixdzs.tw/read/642933/p186.html")
    assert title == "第186章 測試" and n >= 500 and text in body
    assert "chapters/0186.txt" == f"chapters/{186:04d}.txt"
    try:
        parse_chapter("<h1>第186章</h1><article>短</article>", 186, INDEX + "p186.html")
    except ValueError:
        pass
    else:
        raise AssertionError("Short chapter was not rejected")
    try:
        parse_chapter(html + '<a href="/read/642933/p186_2.html">下一頁</a>', 186,
                      "https://ixdzs.tw/read/642933/p186.html")
    except ValueError:
        pass
    else:
        raise AssertionError("Split chapter was not rejected")
    print("EXPORT_SELFTEST_PASS")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--rights-confirmed", action="store_true",
                   help="Operator confirms they hold permission to copy/reproduce these chapters")
    p.add_argument("--start", type=int, default=START)
    p.add_argument("--end", type=int, default=END)
    p.add_argument("--delay", type=float, default=2.0)
    p.add_argument("--out", type=Path, default=Path("out/authorized-ixdzs-642933"))
    p.add_argument("--selftest", action="store_true")
    args = p.parse_args()
    if args.selftest:
        selftest()
        return
    if not args.rights_confirmed:
        p.error("Explicit permission/rights confirmation required before export")
    if args.start != START or args.end != END:
        p.error("Only chapters 186-205 of book 642933 are supported")
    if args.delay < 2:
        p.error("Delay must be at least 2 seconds")
    session = requests.Session()
    session.headers["User-Agent"] = UA
    records = fetch_all(args.start, args.end, args.delay, session)
    archive = write_zip(records, args.out)
    print("COMPLETE", len(records), str(archive))


if __name__ == "__main__":
    main()
