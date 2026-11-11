#!/usr/bin/env python3
"""Verified RAW collector for 修真网络时代 from czbooks.net/n/uk0ff.

Requires permission to copy the text. Never commits novel prose. Uses only
index-linked, robots-permitted chapter pages. Refuses partial final archives.
"""
import argparse
import hashlib
import json
import re
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser
from zipfile import ZipFile, ZIP_DEFLATED

import requests
from bs4 import BeautifulSoup

BOOK = "https://czbooks.net/n/uk0ff"
HOST = "czbooks.net"
EXPECTED = 587
PAGES = 588
UA = "MedNovelAvailabilityAudit/1.0 (+https://github.com/Lalalalendia/med)"
NUMBER_RE = re.compile(r"第\s*([零〇一二三四五六七八九十百千万萬两兩0-9]+)\s*章")
READERS = ("#content", "#chaptercontent", ".chapter-content", ".read-content",
           ".content", "article", "main")
TRASH = ("script,style,noscript,iframe,form,nav,footer,header,aside,button,"
         ".ad,.ads,.advertisement,.pagination,.chapter-nav,.book-nav")
CHALLENGES = ("captcha", "verify you are human", "access denied",
              "請先登入", "登录后阅读", "付費閱讀", "付费阅读")
DIGITS = {v: i for i, v in enumerate("零一二三四五六七八九")}
DIGITS.update({"〇": 0, "两": 2, "兩": 2})
UNITS = {"十": 10, "百": 100, "千": 1000}

def numeric(raw):
    if raw.isascii() and raw.isdigit():
        return int(raw)
    total = 0
    current = 0
    for char in raw:
        if char in DIGITS:
            current = DIGITS[char]
        elif char in UNITS:
            total += (current or 1) * UNITS[char]
            current = 0
        else:
            raise ValueError("unsupported numeral: " + raw)
    return total + current

def number_from(title):
    match = NUMBER_RE.search(title)
    return numeric(match.group(1)) if match else None

def safe_chapter(url):
    bits = urlsplit(url)
    return (bits.scheme == "https" and bits.netloc == HOST
            and bits.username is None and bits.password is None
            and not bits.query and not bits.fragment
            and bool(re.fullmatch(r"/n/uk0ff/[A-Za-z0-9_-]+", bits.path)))

def policy(session):
    r = session.get("https://czbooks.net/robots.txt", timeout=(8, 25),
                    allow_redirects=False)
    rp = RobotFileParser()
    if r.status_code == 200 and "<html" not in r.text[:400].lower():
        rp.parse(r.text.splitlines())
    elif r.status_code in (404, 410):
        rp.parse(["User-agent: *", "Allow: /"])
    else:
        raise ValueError("robots policy unavailable: HTTP " + str(r.status_code))
    if not rp.can_fetch(UA, BOOK):
        raise ValueError("robots disallows source catalog")
    return rp

def load(session, rp, url, delay):
    if not (url == BOOK or safe_chapter(url)):
        raise ValueError("unexpected or unsafe URL: " + url)
    if not rp.can_fetch(UA, url):
        raise ValueError("robots disallows URL: " + url)
    time.sleep(delay)
    r = session.get(url, timeout=(8, 35), allow_redirects=False)
    if r.status_code != 200:
        raise ValueError("HTTP " + str(r.status_code) + " at " + url)
    if "html" not in r.headers.get("Content-Type", "").lower():
        raise ValueError("unexpected content type: " + url)
    if r.url != url:
        raise ValueError("redirected source URL")
    r.encoding = r.apparent_encoding or "utf-8"
    return r.text

def catalog(html):
    soup = BeautifulSoup(html, "html.parser")
    chapters = defaultdict(list)
    urls = set()
    for anchor in soup.select("a[href]"):
        title = re.sub(r"\s+", " ", anchor.get_text(" ", strip=True))
        n = number_from(title)
        if not n or n > EXPECTED:
            continue
        url = urljoin(BOOK, anchor["href"])
        if not safe_chapter(url):
            continue
        if url in urls:
            continue
        urls.add(url)
        chapters[n].append({"number": n, "title": title[:160], "url": url})
    missing = sorted(set(range(1, EXPECTED + 1)) - set(chapters))
    duplicates = {n: len(rows) for n, rows in chapters.items() if len(rows) != 1}
    if missing or sum(map(len, chapters.values())) != PAGES or duplicates != {476: 2}:
        raise ValueError("catalog mismatch: links=%s missing=%s duplicates=%s"
                         % (len(urls), missing[:15], duplicates))
    all_rows = [r for n in sorted(chapters) for r in chapters[n]]
    digest = hashlib.sha256(json.dumps(all_rows, ensure_ascii=False,
                                      sort_keys=True).encode("utf-8")).hexdigest()
    return chapters, digest

def extract(html, title, expected_number):
    soup = BeautifulSoup(html, "html.parser")
    page_title = soup.title.get_text(" ", strip=True) if soup.title else ""
    page_n = number_from(page_title)
    if page_n is not None and page_n != expected_number:
        raise ValueError("chapter title number mismatch")
    if any(ch in page_title.lower() for ch in CHALLENGES):
        raise ValueError("challenge page")
    roots = [soup.select_one(selector) for selector in READERS]
    roots = [root for root in roots if root is not None]
    if not roots:
        raise ValueError("chapter content not found")
    root = max(roots, key=lambda x: len(x.get_text(" ", strip=True)))
    for bad in root.select(TRASH):
        bad.decompose()
    lines = [re.sub(r"[ \t\u00a0]+", " ", line).strip()
             for line in root.get_text("\n", strip=True).splitlines()]
    body = "\n".join(line for line in lines if line)
    han = len(re.findall(r"[\u3400-\u9fff]", body))
    if han < 250 or any(token in body[:1000].lower() for token in CHALLENGES):
        raise ValueError("empty, short or access-limited chapter (%s Han)" % han)
    return body, han

def inspect_duplicates(rows):
    by_num = defaultdict(list)
    for row in rows:
        by_num[row["number"]].append(row)
    for number, pages in by_num.items():
        if len(pages) > 1 and (number != 476 or len(pages) != 2
                              or pages[0]["body_sha256"] != pages[1]["body_sha256"]):
            raise ValueError("unreconciled duplicate: " + str(number))
    return by_num

def collect(args):
    out = args.out
    (out / "chapters").mkdir(parents=True, exist_ok=True)
    (out / "manifests").mkdir(parents=True, exist_ok=True)
    receipt = {"source": BOOK, "status": "INCOMPLETE", "range": [args.start, args.end],
               "rights_attested": True, "chapters": [], "errors": [],
               "utc": datetime.now(timezone.utc).isoformat()}
    try:
        s = requests.Session()
        s.headers["User-Agent"] = UA
        rp = policy(s)
        chapters, index_sha = catalog(load(s, rp, BOOK, args.delay))
        receipt["catalog_sha256"] = index_sha
        all_entries = [item for n in range(args.start, args.end + 1)
                       for item in chapters[n]]
        seen_bodies = set()
        rows = []
        for item in all_entries:
            try:
                body, han = extract(load(s, rp, item["url"], args.delay),
                                    item["title"], item["number"])
                digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
                row = dict(item, han_chars=han, body_sha256=digest)
                rows.append(row)
                if item["number"] not in seen_bodies:
                    filename = "chapters/%04d.txt" % item["number"]
                    prose = item["title"] + "\nSource: " + item["url"] + "\n\n" + body + "\n"
                    (out / filename).write_text(prose, encoding="utf-8")
                    row["file"] = filename
                    row["file_sha256"] = hashlib.sha256(prose.encode("utf-8")).hexdigest()
                    seen_bodies.add(item["number"])
                receipt["chapters"].append(row)
                print("PASS", item["number"], han, item["url"], flush=True)
            except Exception as err:
                receipt["errors"].append({"chapter": item["number"], "url": item["url"],
                                          "error": str(err)[:300]})
                raise
        by = inspect_duplicates(rows)
        canonical = [by[n][0] for n in range(args.start, args.end + 1)]
        if len(canonical) != args.end - args.start + 1:
            raise ValueError("missing chapter in shard")
        if len({r["body_sha256"] for r in canonical}) != len(canonical):
            raise ValueError("different chapter numbers have identical text")
        receipt["status"] = "PASS"
    except (ValueError, requests.RequestException) as err:
        receipt["errors"].append({"error": str(err)[:300]})
        print("INCOMPLETE", err, flush=True)
    (out / "manifests" / ("part-%04d.json" % args.start)).write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if receipt["status"] == "PASS" else 2

def pilot(args):
    s = requests.Session()
    s.headers["User-Agent"] = UA
    rp = policy(s)
    chapters, digest = catalog(load(s, rp, BOOK, args.delay))
    print("CATALOG", len(chapters), "unique chapters, sha", digest, flush=True)
    rows = []
    for n in [1, 300, 476, 587]:
        for row in chapters[n]:
            body, han = extract(load(s, rp, row["url"], args.delay), row["title"], n)
            data = dict(row, han_chars=han,
                        body_sha256=hashlib.sha256(body.encode("utf-8")).hexdigest())
            rows.append(data)
            print("PILOT", n, han, row["url"], flush=True)
    inspect_duplicates(rows)
    print("PILOT_PASS", len(rows), flush=True)
    return 0

def assemble(args):
    if not args.rights_confirmed:
        raise ValueError("permission required")
    root = args.from_dir
    paths = sorted((root / "manifests").glob("part-*.json"))
    if len(paths) != 3:
        raise ValueError("expected three shard manifests")
    records = []
    catalog_shas = set()
    cover = set()
    for p in paths:
        shard = json.loads(p.read_text(encoding="utf-8"))
        if shard.get("status") != "PASS" or not shard.get("rights_attested"):
            raise ValueError("incomplete or unauthorized shard " + p.name)
        catalog_shas.add(shard["catalog_sha256"])
        first, last = shard["range"]
        expected = set(range(first, last + 1))
        if cover & expected:
            raise ValueError("overlapping shards")
        cover |= expected
        group = inspect_duplicates(shard["chapters"])
        for n in expected:
            if n not in group:
                raise ValueError("missing number " + str(n))
            item = group[n][0]
            relative = "chapters/%04d.txt" % n
            raw = (root / relative).read_bytes()
            if hashlib.sha256(raw).hexdigest() != item["file_sha256"]:
                raise ValueError("incorrect SHA256 for chapter " + str(n))
            records.append(item)
    if cover != set(range(1, EXPECTED + 1)) or len(catalog_shas) != 1:
        raise ValueError("range gaps or changed source index")
    records.sort(key=lambda item: item["number"])
    if len({r["body_sha256"] for r in records}) != EXPECTED:
        raise ValueError("duplicate prose across different chapters")
    args.out.mkdir(parents=True, exist_ok=True)
    combined = "\n\n".join((root / ("chapters/%04d.txt" % n)).read_text(encoding="utf-8")
                           for n in range(1, EXPECTED + 1))
    digest = hashlib.sha256(combined.encode("utf-8")).hexdigest()
    manifest = {"source": BOOK, "title": "修真网络时代", "author": "惟一的叶子",
                "status": "PASS", "chapters": records,
                "total": EXPECTED, "catalog_sha256": next(iter(catalog_shas)),
                "combined_sha256": digest, "rights_attested": True,
                "utc": datetime.now(timezone.utc).isoformat()}
    (args.out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.out / "summary.md").write_text(
        "# 修真网络时代 — verified RAW\n\n"
        "- Status: PASS\n- Chapters: 587/587\n"
        "- Source: https://czbooks.net/n/uk0ff\n"
        "- Duplicate 476: verified and deduplicated\n"
        "- Chinese text not committed to public repository\n"
        f"- Combined SHA256: {digest}\n", encoding="utf-8")
    archive = args.out / "xiuzhen-wangluo-shidai-001-587-cn.zip"
    with ZipFile(archive, "w", ZIP_DEFLATED) as z:
        for n in range(1, EXPECTED + 1):
            z.write(root / ("chapters/%04d.txt" % n), "chapters/%04d.txt" % n)
        z.writestr("combined.txt", combined)
        z.write(args.out / "manifest.json", "manifest.json")
        z.write(args.out / "summary.md", "summary.md")
    print("FULL_PASS", len(records), "ZIP", archive, "SHA256", digest, flush=True)
    return 0

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=("pilot", "collect", "assemble"), required=True)
    p.add_argument("--rights-confirmed", action="store_true")
    p.add_argument("--start", type=int, default=1)
    p.add_argument("--end", type=int, default=587)
    p.add_argument("--delay", type=float, default=2.0)
    p.add_argument("--out", type=Path, default=Path("out/czbooks-736"))
    p.add_argument("--from-dir", type=Path, default=Path("staging"))
    args = p.parse_args()
    if args.mode in ("collect", "assemble") and not args.rights_confirmed:
        p.error("explicit permission required")
    if args.start < 1 or args.end > EXPECTED or args.end < args.start or args.delay < 1.5:
        p.error("invalid range or delay")
    if args.mode == "pilot":
        return pilot(args)
    if args.mode == "collect":
        return collect(args)
    return assemble(args)

if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, requests.RequestException) as exc:
        print("FAIL:", exc, file=sys.stderr)
        sys.exit(2)
