#!/usr/bin/env python3
"""Collect public chapters of a user-authorized book from xiaoshuoren.

Fail closed on unavailable text, mismatched catalog, duplicate or short body.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

BOOK = "https://www.xiaoshuoren.com/daizhezhanshimobanhunmanwei/"
HOST = "www.xiaoshuoren.com"
SLUG = "/daizhezhanshimobanhunmanwei/"
CHAPTER = re.compile(r"^/daizhezhanshimobanhunmanwei/(\d+)/?$")
CJK = re.compile(r"[\u3400-\u9fff]")
RANGE = re.compile(r"第\s*(\d+)\s*章\s*[~～]\s*(\d+)\s*章\s*/\s*共\s*(\d+)\s*章")
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/130.0.0.0 Safari/537.36"
SELECTORS = (
    "#content", "#chaptercontent", "#chapterContent", "#read-content",
    "#readContent", "#BookText", "#booktext", ".chapter-content",
    ".chapter_content", ".read-content", ".read_content", ".novel-content",
    ".novel_content", ".txtnav", ".txt", ".content",
    ".book-content", ".article-content",
)
JUNK = re.compile(
    r"^(?:上一章|下一章|返回目录|返回书页|目录|章节目录|本章完|加入书架|"
    r"手机阅读|求书阁小说网|最新网址|点击阅读|投票推荐|收藏本站|"
    r"请收藏本站|上一页|下一页|首页|尾页|[\s\-—]*\d+\s*/\s*\d+[\s\-—]*)$"
)

def now_iso():
    return datetime.now(timezone.utc).isoformat()

def clean_text(node):
    node = BeautifulSoup(str(node), "html.parser")
    for tag in node.select("script,style,iframe,form,button,nav,header,footer,aside,noscript,svg"):
        tag.decompose()
    for tag in node.select('[class*="advert"],[class*="_ad"],[id*="advert"],[id*="_ad"],.page,.pages,.pagination,.chapter-nav'):
        tag.decompose()
    for br in node.find_all("br"):
        br.replace_with("\n")
    for p in node.find_all("p"):
        p.append("\n")
    raw = node.get_text("\n", strip=True).replace("\u3000", " ")
    lines = [re.sub(r"[ \t]+", " ", x).strip() for x in raw.splitlines()]
    return "\n".join(x for x in lines if x and not JUNK.fullmatch(x)).strip()

def get(session, url):
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.netloc not in (HOST, "xiaoshuoren.com") or not parts.path.startswith(SLUG):
        raise RuntimeError("Unexpected URL outside requested book: " + url)
    last = None
    for attempt in range(4):
        try:
            r = session.get(url, timeout=(12, 35), allow_redirects=True)
            if r.status_code in (401, 403, 404):
                raise RuntimeError("HTTP %s for %s (no bypass attempted)" % (r.status_code, url))
            if r.status_code == 429:
                raise RuntimeError("HTTP 429 rate limit, stopping without bypass")
            if r.status_code in (500, 502, 503, 504):
                last = "HTTP " + str(r.status_code)
                time.sleep(min(4 + 3 * attempt, 13))
                continue
            r.raise_for_status()
            if urlsplit(r.url).netloc not in (HOST, "xiaoshuoren.com"):
                raise RuntimeError("Redirected to unrelated host: " + r.url)
            r.encoding = r.apparent_encoding or r.encoding or "utf-8"
            return BeautifulSoup(r.text, "html.parser"), r.url
        except requests.RequestException as exc:
            last = str(exc)
            time.sleep(min(3 * (attempt + 1), 10))
    raise RuntimeError("%s: %s" % (url, last))

def catalog(session, delay):
    pages, chapters = [], []
    total, page = None, 0
    while True:
        if page >= 12:
            raise RuntimeError("Too many index pages")
        url = BOOK if page == 0 else urljoin(BOOK, "index_%d.html" % (page + 1))
        soup, actual = get(session, url)
        m = RANGE.search(soup.get_text(" ", strip=True))
        if not m:
            raise RuntimeError("Missing chapter range and total at " + actual)
        begin, end, current_total = map(int, m.groups())
        if total is None:
            total = current_total
        if total != current_total or begin != page * 100 + 1 or end != min(total, (page + 1) * 100):
            raise RuntimeError("Inconsistent index range %s-%s/%s at %s" % (begin, end, current_total, actual))
        expected = end - begin + 1
        links = []
        for a in soup.select("a[href]"):
            href = urljoin(actual, a["href"])
            u = urlsplit(href)
            if u.netloc not in (HOST, "xiaoshuoren.com") or not CHAPTER.fullmatch(u.path):
                continue
            title = a.get_text(" ", strip=True)
            if title:
                links.append((href.rstrip("/") + "/", title))
        if len(links) < expected:
            raise RuntimeError("Only %d links for %d chapters on %s" % (len(links), expected, actual))
        # The website places a latest-12 teaser before the proper index.
        # Therefore take the last expected number of chapter links.
        selected = links[-expected:]
        if len({u for u, _ in selected}) != expected:
            raise RuntimeError("Duplicate chapter links on " + actual)
        for offset, (href, title) in enumerate(selected):
            chapters.append({"ordinal": begin + offset, "title": title, "url": href})
        pages.append({"page": page + 1, "url": actual, "range": [begin, end], "candidate_links": len(links)})
        print("INDEX %d: %d-%d/%d (%d candidate links)" % (page + 1, begin, end, total, len(links)), flush=True)
        page += 1
        if end == total:
            break
        time.sleep(delay)
    if len(chapters) != total or len({c["url"] for c in chapters}) != total:
        raise RuntimeError("Catalog total/unique mismatch: %d vs %d" % (len(chapters), total))
    return chapters, pages

def chapter_body(session, item):
    soup, final = get(session, item["url"])
    h = soup.find("h1")
    heading = h.get_text(" ", strip=True) if h else ""
    candidates = []
    for selector in SELECTORS:
        for node in soup.select(selector):
            body = clean_text(node)
            cjk = len(CJK.findall(body))
            if cjk >= 180:
                candidates.append((cjk, len(body), selector, body))
    if not candidates:
        for node in soup.select("article,main,section,div"):
            if len(node.select("a[href]")) > 20:
                continue
            body = clean_text(node)
            cjk = len(CJK.findall(body))
            if cjk >= 200 and cjk / max(len(body), 1) > .25:
                candidates.append((cjk, len(body), node.name, body))
    if not candidates:
        raise RuntimeError("No substantial chapter body found; h1=%r" % heading)
    candidates.sort(reverse=True)
    cjk, _, selector, body = candidates[0]
    if cjk < 200 or len(body) < 300:
        raise RuntimeError("Short body, potential preview: chars=%d, cjk=%d" % (len(body), cjk))
    if "loading..." in body.lower() or "请开启javascript" in body.lower() or "加载中" == body.strip():
        raise RuntimeError("Unloaded script placeholder")
    return {"text": body, "heading": heading, "selector": selector, "resolved": final, "cjk": cjk}

def collect(args):
    root = Path(args.output)
    (root / "chapters").mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9", "Referer": BOOK})
    report = {"book_url": BOOK, "title": "带着战士模板混漫威", "author": "木耳炒猪肉",
              "started_utc": now_iso(), "catalog_total": None, "index_pages": [],
              "requested": 0, "chapters": [], "failures": [], "status": "RUNNING"}
    seen, combined = {}, []
    try:
        chapter_list, pages = catalog(session, max(args.delay, .5))
        report["catalog_total"] = len(chapter_list)
        report["index_pages"] = pages
        (root / "catalog.json").write_text(json.dumps(chapter_list, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        selected = chapter_list[:args.limit] if args.limit else chapter_list
        report["requested"] = len(selected)
        for i, entry in enumerate(selected, 1):
            try:
                fetch = chapter_body(session, entry)
                body = fetch["text"]
                sha = hashlib.sha256(body.encode("utf-8")).hexdigest()
                if sha in seen:
                    raise RuntimeError("Duplicate body identical to chapter %d" % seen[sha])
                seen[sha] = entry["ordinal"]
                text = "%s\nSource: %s\n\n%s\n" % (entry["title"], entry["url"], body)
                fname = "%04d.txt" % entry["ordinal"]
                (root / "chapters" / fname).write_text(text, encoding="utf-8")
                combined.append(text)
                report["chapters"].append({**entry, "file": "chapters/" + fname,
                    "chars": len(body), "cjk_chars": fetch["cjk"], "sha256": sha,
                    "page_heading": fetch["heading"], "selector": fetch["selector"]})
                print("%d/%d: %d OK, chars=%d, CJK=%d" % (
                    i, len(selected), entry["ordinal"], len(body), fetch["cjk"]), flush=True)
            except Exception as exc:
                report["failures"].append({"ordinal": entry["ordinal"], "url": entry["url"], "error": str(exc)})
                print("FAILED chapter %d: %s" % (entry["ordinal"], exc), flush=True)
                if "HTTP 403" in str(exc) or "HTTP 429" in str(exc):
                    print("Stopped to respect access restrictions", flush=True)
                    break
            time.sleep(max(args.delay, .5))
    except Exception as exc:
        report["failures"].append({"stage": "catalog", "error": str(exc)})
        print("CATALOG ERROR:", exc, flush=True)
    if combined:
        (root / "combined.txt").write_text("\n\n" + ("\n\n" + "=" * 60 + "\n\n").join(combined), encoding="utf-8")
    report["finished_utc"] = now_iso()
    report["ok_count"] = len(report["chapters"])
    report["failure_count"] = len(report["failures"])
    report["status"] = ("PASS" if report["requested"] and report["ok_count"] == report["requested"]
                        and not report["failures"] else "INCOMPLETE")
    (root / "manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = ("# 带着战士模板混漫威\n\nStatus: **%s**\n\nCatalog: %s\n\nRequested: %d\n\n"
               "Verified: %d\n\nFailures: %d\n\nSource: %s\n") % (
                   report["status"], report["catalog_total"], report["requested"],
                   report["ok_count"], report["failure_count"], BOOK)
    (root / "summary.md").write_text(summary, encoding="utf-8")
    archive = root.parent / (root.name + ("-pilot" if args.limit else "-full") + ".zip")
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=8) as z:
        for path in sorted(root.rglob("*")):
            if path.is_file():
                z.write(path, path.relative_to(root.parent))
    with zipfile.ZipFile(archive) as z:
        if z.testzip():
            raise RuntimeError("ZIP integrity failed")
    print("RESULT", report["status"], report["ok_count"], "/", report["requested"],
          "ZIP", archive, "BYTES", archive.stat().st_size, flush=True)
    return 0 if report["status"] == "PASS" else 1

def self_test():
    soup = BeautifulSoup('<div id="content"><p>第一段故事内容</p><p>第二段故事<br>第三行文字</p><div class="pagination">下一章</div></div>', "html.parser")
    result = clean_text(soup.select_one("#content"))
    assert "第一段故事内容" in result and "第三行文字" in result
    assert "下一章" not in result
    assert CHAPTER.fullmatch("/daizhezhanshimobanhunmanwei/353394/")
    assert RANGE.search("章节列表，第1章~ 100章/共297章 倒序").groups() == ("1", "100", "297")
    print("SELF-TEST PASS")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", default="out/xiaoshuoren-marvel")
    ap.add_argument("--limit", type=int, default=0, help="0 means all chapters")
    ap.add_argument("--delay", type=float, default=.8)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        self_test()
    else:
        raise SystemExit(collect(args))
