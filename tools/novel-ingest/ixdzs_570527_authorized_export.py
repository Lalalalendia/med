#!/usr/bin/env python3
"""Authorized collection of Chinese RAW for IXDZS book 570527, chapter 1164 onward.

This collector is intended only for material the operator has permission to reproduce.
It does not bypass site access restrictions, login, CAPTCHA, or rate limits.
It validates each chapter, detects pagination and only publishes a complete range.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlsplit
from urllib.robotparser import RobotFileParser
from zipfile import ZIP_DEFLATED, ZipFile

import requests
from bs4 import BeautifulSoup

BOOK_ID = "570527"
TITLE = "惊悚游戏：开局帮鬼怪做选择"
ALTERNATE_TITLE = "谁拉他进来的，惊悚世界被薅秃了"
AUTHOR = "美味的口蘑"
SOURCES = ("https://ixdzs8.com/read/570527/",
           "https://ixdzs.tw/read/570527/")
START = 1164
MIN_KNOWN_END = 1187
UA = "Mozilla/5.0 (compatible; MedAuthorizedChapterCollection/1.0)"
CHAPTER_RE = re.compile(r"第\s*([0-9０-９]+)\s*章")
PATH_RE = re.compile(r"^/read/570527/p([0-9]+)\.html$")
MULTI_RE = re.compile(r"^/read/570527/p([0-9]+)[_-]([2-9][0-9]*)\.html$")
BLOCK = ("captcha", "access denied", "just a moment", "verify you are human",
         "人机验证", "人機驗證", "安全验证", "安全驗證", "正在验证")
SELECTORS = ("article", "#chaptercontent", "#chapter-content", "#content",
             "#txtcontent", "#chapter", ".chapter-content", ".read-content",
             ".chapter", ".content", ".txt-content", "#txt")
DROP = "script,style,nav,form,iframe,footer,header,aside,.advertisement,.ads,#ads,.adsbygoogle"
NOISE = re.compile(r"^(上一章|下一章|返回目录|返回目錄|目录|目錄|加入书架|加入書架|本章完|喜欢本书|点击下一页|點擊下一頁|手机版阅读|手機版閱讀)$")
CJK = re.compile(r"[\u3400-\u9fff]")
TIMEOUT = (10, 35)


def chapter_num(s: str) -> int | None:
    m = CHAPTER_RE.search(s)
    if not m:
        return None
    return int(m.group(1).translate(str.maketrans("０１２３４５６７８９", "0123456789")))


def get(session: requests.Session, url: str, host: str) -> requests.Response:
    r = session.get(url, timeout=TIMEOUT, allow_redirects=True)
    if r.status_code in (403, 429, 503):
        raise ValueError(f"Restricted access: HTTP {r.status_code} at {url}")
    r.raise_for_status()
    p = urlsplit(r.url)
    if p.scheme != "https" or p.hostname != host:
        raise ValueError(f"Untrusted redirect from {url} to {r.url}")
    return r


def robots(session: requests.Session, host: str) -> RobotFileParser | None:
    """Honor explicit robots rules when a valid rules file is provided."""
    url = f"https://{host}/robots.txt"
    r = session.get(url, timeout=TIMEOUT)
    if r.status_code == 404:
        return None
    if r.status_code != 200 or "user-agent:" not in r.text.lower():
        raise ValueError(f"Robots policy cannot be verified: {r.status_code}")
    rp = RobotFileParser()
    rp.parse(r.text.splitlines())
    return rp


def allowed(policy: RobotFileParser | None, url: str) -> bool:
    return policy is None or policy.can_fetch(UA, url)


def read_catalog(session: requests.Session, index: str):
    host = urlsplit(index).hostname
    policy = robots(session, host)
    if not allowed(policy, index):
        raise ValueError("Source catalog disallowed by robots")
    r = get(session, index, host)
    soup = BeautifulSoup(r.content, "html.parser")
    heading = soup.title.get_text(" ", strip=True) if soup.title else ""
    if any(k in heading.lower() for k in BLOCK):
        raise ValueError("Challenge page instead of book catalog")
    if not any(k in soup.get_text(" ", strip=True)[:18000] for k in
               ("惊悚游戏", "驚悚遊戲", "谁拉他进来的", "誰拉他進來的")):
        raise ValueError("Unexpected book catalog; title was not present")
    catalog = {}
    for a in soup.select("a[href]"):
        url = urljoin(r.url, a["href"]).split("#", 1)[0]
        p = urlsplit(url)
        if p.hostname != host:
            continue
        m = PATH_RE.fullmatch(p.path)
        if not m:
            continue
        n = int(m.group(1))
        name = a.get_text(" ", strip=True)
        num = chapter_num(name)
        if num is not None and num != n:
            raise ValueError(f"Index label {num} differs from chapter URL {n}")
        if n in catalog and catalog[n] != url:
            raise ValueError(f"Multiple URLs for chapter {n}")
        catalog[n] = url
    last = max(catalog, default=0)
    if last < MIN_KNOWN_END:
        raise ValueError(f"Catalog has only up to {last}; expected >= {MIN_KNOWN_END}")
    if last > START + 200:
        raise ValueError(f"Unexpected maximum chapter {last}")
    return host, policy, catalog, last


def continuation_links(soup, current, chapter, host):
    found = []
    parsed = urlsplit(current)
    for a in soup.select("a[href]"):
        url = urljoin(current, a["href"])
        p = urlsplit(url)
        if p.scheme != "https" or p.hostname != host:
            continue
        m = MULTI_RE.fullmatch(p.path)
        if m and int(m.group(1)) == chapter:
            found.append((int(m.group(2)), url))
            continue
        qs = parse_qs(p.query)
        label = a.get_text(" ", strip=True)
        if (p.path == parsed.path and p.query != parsed.query
                and ("page" in qs or "p" in qs)
                and any(s in label for s in ("下一页", "下一頁", "继续", "繼續"))):
            try:
                page = int((qs.get("page") or qs["p"])[0])
            except (ValueError, IndexError):
                continue
            found.append((page, url))
    return sorted(set(found))


def parse_page(raw: bytes, number: int, url: str, host: str):
    soup = BeautifulSoup(raw, "html.parser")
    title_el = soup.select_one("h1") or soup.title
    heading = title_el.get_text(" ", strip=True) if title_el else ""
    if any(k in heading.lower() for k in BLOCK):
        raise ValueError(f"Access challenge at chapter {number}")
    if chapter_num(heading) != number:
        raise ValueError(f"Chapter title mismatch at {number}: {heading[:110]}")
    candidates = []
    for selector in SELECTORS:
        candidates.extend(soup.select(selector))
    # Fallback: inspect content areas, never silently select the whole document.
    if not candidates:
        raise ValueError(f"No recognizable chapter content node at {number}")
    roots = []
    for node in candidates:
        duplicate = BeautifulSoup(str(node), "html.parser")
        for junk in duplicate.select(DROP):
            junk.decompose()
        if not duplicate.get_text(" ", strip=True):
            continue
        lines = duplicate.get_text("\n", strip=True).splitlines()
        text = []
        for item in lines:
            item = re.sub(r"\s+", " ", item).strip()
            if not item or NOISE.fullmatch(item):
                continue
            if item in (heading, TITLE, ALTERNATE_TITLE, AUTHOR):
                continue
            if re.search(r"(https?://|www\.ixdzs|下载本书|下載本書)", item):
                continue
            text.append(item)
        body = "\n\n".join(text)
        count = len(CJK.findall(body))
        if count:
            roots.append((count, body))
    if not roots:
        raise ValueError(f"No Chinese prose at chapter {number}")
    count, body = max(roots, key=lambda x: x[0])
    if count < 450:
        raise ValueError(f"Suspiciously short chapter {number}: {count} CJK")
    return heading, body, count, continuation_links(soup, url, number, host)


def collect_one(session, host, policy, number, url, delay):
    parts = urlsplit(url)
    if parts.hostname != host or not PATH_RE.fullmatch(parts.path):
        raise ValueError(f"Unexpected chapter URL: {url}")
    if not allowed(policy, url):
        raise ValueError(f"Chapter {number} disallowed by robots")
    pages = [(1, url)]
    seen_pages, texts = set(), []
    chapter_heading = ""
    for _ in range(15):
        if not pages:
            break
        pos, page_url = pages.pop(0)
        if page_url in seen_pages:
            continue
        if not allowed(policy, page_url):
            raise ValueError(f"Continuation of chapter {number} disallowed by robots")
        time.sleep(max(0.3, delay))
        r = get(session, page_url, host)
        heading, body, cjk, discovered = parse_page(r.content, number, r.url, host)
        seen_pages.add(r.url)
        chapter_heading = chapter_heading or heading
        texts.append((pos, body))
        for nextpos, link in discovered:
            if nextpos > pos and link not in seen_pages:
                pages.append((nextpos, link))
        pages = sorted(set(pages))
    else:
        raise ValueError(f"Too many continuation pages at {number}")
    if pages:
        raise ValueError(f"Uncollected continuation pages at {number}")
    if not texts:
        raise ValueError(f"No chapter text at {number}")
    text = "\n\n".join(body for _, body in sorted(texts))
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return {
        "number": number,
        "title": chapter_heading,
        "url": url,
        "pages": [u for _, u in sorted([(i, u) for i, u in [(1, url)]])],
        "page_count": len(seen_pages),
        "cjk_chars": len(CJK.findall(text)),
        "characters": len(text),
        "sha256": digest,
        "text": text,
    }


def save(records, index, end, out: Path, include_archive=True):
    expected = list(range(START, end + 1))
    assert [row["number"] for row in records] == expected, "Incomplete range"
    hashes = {row["sha256"] for row in records}
    assert len(hashes) == len(expected), "Duplicate chapter bodies"
    out.mkdir(parents=True, exist_ok=True)
    chapters = out / "raw"
    chapters.mkdir(parents=True, exist_ok=True)
    combination, metadata = [], []
    for row in records:
        number, heading, body = row["number"], row["title"], row["text"]
        display = re.sub(r"^.*?第\s*[0-9０-９]+\s*章\s*", "", heading).strip()
        content = f"第{number}章 {display}\n\n{body.strip()}\n"
        file_name = f"{number:04d}.txt"
        (chapters / file_name).write_text(content, encoding="utf-8")
        combination.append(content.rstrip())
        metadata.append({k:v for k,v in row.items() if k != "text"})
        metadata[-1]["file"] = f"raw/{file_name}"
    merged = "\n\n" + "=" * 72 + "\n\n"
    (out / f"combined-cn-{START}-{end}.txt").write_text(
        merged.join(combination) + "\n", encoding="utf-8")
    manifest = {
        "title_cn": TITLE, "alternate_title_cn": ALTERNATE_TITLE,
        "author_cn": AUTHOR, "source": index, "first": START, "last": end,
        "chapter_count": len(records), "status": "complete",
        "rights_confirmed_by_user": True,
        "collected_utc": datetime.now(timezone.utc).isoformat(),
        "chapters": metadata,
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = (
        f"# IXDZS 570527 RAW {START}-{end}\n\n"
        f"Title: {TITLE}\nAuthor: {AUTHOR}\nSource: {index}\n"
        f"Requested: {len(expected)}\nCollected: {len(records)}\n"
        f"Total Chinese characters: {sum(r['cjk_chars'] for r in records)}\n"
        f"Total HTML chapter pages: {sum(r['page_count'] for r in records)}\n"
        f"Unique chapter fingerprints: {len(hashes)}\n"
        "Completeness: PASS (index, title, length, duplicates, pagination)\n"
        "Editorial review against an independent authorized source has not been done.\n"
    )
    (out / "summary.md").write_text(report, encoding="utf-8")
    if include_archive:
        archive = out / f"ixdzs-570527-cn-{START}-{end}.zip"
        with ZipFile(archive, "w", ZIP_DEFLATED, compresslevel=9) as zipf:
            for file in sorted(out.rglob("*")):
                if file.is_file() and file != archive:
                    zipf.write(file, file.relative_to(out))
    return report


def selftest():
    paragraph = "这是一个用于测试解析逻辑的模拟段落。" * 100
    url = "https://ixdzs8.com/read/570527/p1164.html"
    html = f"<h1>第1164章 熬吧</h1><article><p>{paragraph}</p></article>"
    a = parse_page(html.encode("utf-8"), 1164, url, "ixdzs8.com")
    assert a[2] > 450 and paragraph in a[1]
    try:
        parse_page(html.encode("utf-8"), 1165, url, "ixdzs8.com")
    except ValueError:
        pass
    else:
        raise AssertionError("Chapter mismatch passed")
    assert continuation_links(BeautifulSoup('<a href="/read/570527/p1164_2.html">下一页</a>', "html.parser"), url, 1164, "ixdzs8.com")
    print("SELFTEST_PASS", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rights-confirmed", action="store_true")
    parser.add_argument("--start", type=int, default=START)
    parser.add_argument("--delay", type=float, default=1.1)
    parser.add_argument("--output", type=Path, default=Path("novels/ixdzs/570527"))
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        selftest()
        return 0
    if not args.rights_confirmed or args.start != START:
        parser.error("This authorized run requires rights confirmation and start=1164")
    if args.delay < 0.75:
        parser.error("Delay must be at least 0.75 seconds")
    session = requests.Session()
    session.headers.update({"User-Agent": UA})
    failures = []
    for index in SOURCES:
        try:
            host, policy, catalog, last = read_catalog(session, index)
            print(f"Using source {index}; latest numbered chapter: {last}", flush=True)
            records = []
            for number in range(START, last+1):
                url = catalog.get(number, urljoin(index, f"p{number}.html"))
                row = collect_one(session, host, policy, number, url, args.delay)
                if row["cjk_chars"] < 800:
                    print(f"NOTE: chapter {number} is short ({row['cjk_chars']} CJK)", flush=True)
                records.append(row)
                print(f"PASS {number}: {row['cjk_chars']} CJK, {row['page_count']} pages", flush=True)
            summary = save(records, index, last, args.output)
            print(summary, flush=True)
            return 0
        except Exception as exc:
            failures.append({"source": index, "error": f"{type(exc).__name__}: {exc}"})
            print(f"Source failed {index}: {exc}", flush=True)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "failure-audit.json").write_text(
        json.dumps(failures, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("No accessible fully verified source; refusing incomplete export", flush=True)
    return 2


if __name__ == "__main__":
    sys.exit(main())
