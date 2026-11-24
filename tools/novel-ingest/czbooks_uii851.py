#!/usr/bin/env python3
"""Rights-confirmed export of publicly accessible CZBooks uii851 chapters.
No credentials, access-control workarounds, or novel prose in Git."""
import argparse
import hashlib
import json
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser
from zipfile import ZIP_DEFLATED, ZipFile

import requests
from bs4 import BeautifulSoup

BOOK = "https://czbooks.net/n/uii851"
TOTAL = 272
UA = "MedNovelAvailabilityAudit/1.0 (+https://github.com/Lalalalendia/med)"
NUMBER = re.compile(r"^\s*(?:第\s*)?([零〇一二三四五六七八九十百兩两0-9]+)\s*(?:章\s*|[、．.：:])")
DIGITS = dict(zip("零一二三四五六七八九", range(10))) | {"〇": 0, "兩": 2, "两": 2}
UNITS = {"十": 10, "百": 100}
BODY_SELECTORS = (".chapter-detail .content", "#chaptercontent", "#chapter-content",
                  ".chapter-content", ".read-content", "div.content", "#content")
TRASH = "script,style,iframe,noscript,nav,footer,header,button,form,.ad,.ads,.advertisement,.pagination,.chapter-nav,.book-nav,.report-error"
BLOCK = ("captcha", "verify you are human", "access denied", "請先登入",
         "登录后阅读", "付費閱讀", "付费阅读", "章節內容更新中")

def sha(data):
    return hashlib.sha256(data).hexdigest()

def chapter_number(title):
    m = NUMBER.match(title)
    if not m:
        return None
    s = m.group(1)
    if s.isascii() and s.isdigit():
        return int(s)
    if all(c in DIGITS for c in s):
        return int("".join(str(DIGITS[c]) for c in s))
    total, digit = 0, None
    for c in s:
        if c in DIGITS:
            digit = DIGITS[c]
        elif c in UNITS:
            total += (1 if digit is None else digit) * UNITS[c]
            digit = None
        else:
            raise ValueError("invalid numeral")
    return total + (digit or 0)

def safe(url):
    u = urlsplit(url)
    return (u.scheme == "https" and u.netloc == "czbooks.net"
            and not u.query and not u.fragment
            and bool(re.fullmatch(r"/n/uii851/[A-Za-z0-9_-]+", u.path)))

def catalog(html):
    soup = BeautifulSoup(html, "html.parser")
    rows = {}
    extras = {}
    for a in soup.select("a[href]"):
        url = urljoin(BOOK, a["href"])
        if not safe(url):
            continue
        title = " ".join(a.get_text(" ", strip=True).split())
        if not title:
            continue
        n = chapter_number(title)
        if n is None:
            if title in ("上架感言", "請假條", "请假条") or title.startswith("說些事情"):
                extras[url] = title
            continue
        if not 1 <= n <= TOTAL:
            raise ValueError(f"unexpected chapter number {n}")
        row = {"number": n, "title": title, "url": url}
        if n in rows and rows[n] != row:
            raise ValueError(f"conflicting catalog entry {n}")
        rows[n] = row
    gaps = sorted(set(range(1, TOTAL + 1)) - rows.keys())
    if gaps:
        raise ValueError(f"catalog incomplete: {len(rows)}/{TOTAL}; missing {gaps}")
    if len({r["url"] for r in rows.values()}) != TOTAL:
        raise ValueError("chapter URL duplicates")
    return [rows[n] for n in range(1, TOTAL + 1)], extras

def extract(html, row):
    soup = BeautifulSoup(html, "html.parser")
    page_title = soup.title.get_text(" ", strip=True) if soup.title else ""
    if any(token in page_title.lower() for token in BLOCK):
        raise ValueError("access-limited page")
    heading_candidates = [page_title] + [h.get_text(" ", strip=True)
                                          for h in soup.select("h1, .chapter-detail .name")]
    numbers = []
    for heading in heading_candidates:
        tail = re.split(r"[》〗】]", heading)[-1].strip()
        n = chapter_number(tail)
        if n is not None:
            numbers.append(n)
    if not numbers or any(n != row["number"] for n in numbers):
        raise ValueError(f"chapter heading mismatch: {numbers}, wanted {row['number']}")
    for selector in BODY_SELECTORS:
        for root in soup.select(selector):
            if root.select_one("a[href*='/n/uii851/']") and len(root.select("a")) > 10:
                continue
            for bad in root.select(TRASH):
                bad.decompose()
            if root.select_one("h1"):
                for h in root.select("h1"):
                    h.decompose()
            lines = [re.sub(r"[ \t\u00a0\u3000]+", " ", x).strip()
                     for x in root.get_text("\n", strip=True).splitlines()]
            lines = [x for x in lines if x and x != row["title"]
                     and not x.startswith(("鍵盤左右鍵", "章節錯誤回報"))]
            body = "\n".join(lines)
            han = len(re.findall(r"[\u3400-\u9fff]", body))
            if han < 250 or any(t in body[:800].lower() for t in BLOCK):
                continue
            if any(t in body for t in ("閱讀設定", "小說錯誤回報", "評論區規則")):
                continue
            return body, han, selector
    raise ValueError("valid chapter body not found")

class Client:
    def __init__(self, delay):
        self.delay = max(delay, 1.8)
        self.s = requests.Session()
        self.s.headers["User-Agent"] = UA
        r = self.s.get("https://czbooks.net/robots.txt", timeout=(10, 30),
                       allow_redirects=False)
        self.robots = RobotFileParser()
        if r.status_code == 200 and "<html" not in r.text[:500].lower():
            self.robots.parse(r.text.splitlines())
        elif r.status_code in (404, 410):
            self.robots.parse(["User-agent: *", "Allow: /"])
        else:
            raise ValueError(f"robots policy unavailable: HTTP {r.status_code}")
        self.delay = max(self.delay, self.robots.crawl_delay(UA) or 0,
                         self.robots.crawl_delay("*") or 0)
    def get(self, url):
        if url != BOOK and not safe(url):
            raise ValueError("unexpected URL")
        if not self.robots.can_fetch(UA, url):
            raise ValueError("robots disallows URL")
        for attempt in range(3):
            time.sleep(self.delay * (attempt + 1))
            try:
                r = self.s.get(url, timeout=(10, 35), allow_redirects=False)
            except (requests.Timeout, requests.ConnectionError):
                if attempt == 2:
                    raise
                continue
            if r.status_code in (500, 502, 503, 504) and attempt < 2:
                continue
            if r.status_code != 200 or r.url != url:
                raise ValueError(f"HTTP {r.status_code} or redirect at {url}")
            if "html" not in r.headers.get("Content-Type", "").lower():
                raise ValueError("unexpected content type")
            r.encoding = "utf-8" if "utf-8" in r.headers.get("Content-Type", "").lower() else (r.apparent_encoding or "utf-8")
            return r.text
        raise ValueError("request failed")

def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def collect(out, delay):
    out.mkdir(parents=True, exist_ok=True)
    (out / "chapters").mkdir(exist_ok=True)
    receipt = {"status": "INCOMPLETE", "source": BOOK, "expected": TOTAL,
               "rights_attested": True, "chapters": [], "error": None}
    try:
        client = Client(delay)
        rows, extras = catalog(client.get(BOOK))
        receipt["catalog"] = rows
        receipt["excluded_author_notices"] = extras
        receipt["catalog_sha256"] = sha(json.dumps(rows, ensure_ascii=False, sort_keys=True).encode())
        print("CATALOG", len(rows), "numbered chapters", flush=True)
        seen = set()
        for row in rows:
            body, han, selector = extract(client.get(row["url"]), row)
            digest = sha(body.encode())
            if digest in seen:
                raise ValueError(f"duplicate body at chapter {row['number']}")
            seen.add(digest)
            filename = f"chapters/{row['number']:04d}.txt"
            payload = (row["title"] + "\n\n" + body + "\n").encode("utf-8")
            (out / filename).write_bytes(payload)
            receipt["chapters"].append(row | {"file": filename, "han_chars": han,
                                           "body_sha256": digest, "file_sha256": sha(payload),
                                           "selector": selector})
            print("PASS", row["number"], han, selector, flush=True)
            write_json(out / "manifest.json", receipt)
        assert [r["number"] for r in receipt["chapters"]] == list(range(1, TOTAL+1))
        pieces = []
        for r in receipt["chapters"]:
            raw = (out / r["file"]).read_bytes()
            if sha(raw) != r["file_sha256"]:
                raise ValueError("file digest mismatch")
            pieces.append(raw.decode("utf-8").rstrip())
        combined = "\n\n".join(pieces) + "\n"
        (out / "combined.txt").write_bytes(combined.encode("utf-8"))
        receipt["combined_sha256"] = sha(combined.encode("utf-8"))
        receipt["status"] = "PASS"
        write_json(out / "manifest.json", receipt)
        archive = out / "czbooks-uii851-001-272-cn.zip"
        with ZipFile(archive, "w", ZIP_DEFLATED) as z:
            for r in receipt["chapters"]:
                z.write(out / r["file"], r["file"])
            for name in ("combined.txt", "manifest.json"):
                z.write(out / name, name)
        with ZipFile(archive) as z:
            assert len(z.namelist()) == TOTAL + 2 and z.testzip() is None
        print("FULL_PASS", TOTAL, receipt["combined_sha256"], flush=True)
        return 0
    except (ValueError, OSError, requests.RequestException, AssertionError) as e:
        receipt["status"] = "INCOMPLETE"
        receipt["error"] = str(e)
        write_json(out / "manifest.json", receipt)
        print("INCOMPLETE", len(receipt["chapters"]), str(e), flush=True)
        return 2

def self_test():
    for title, expected in [("一、測試",1), ("一十、測試",10), ("一百零一、測試",101),
                            ("二百、測試",200), ("二百七十二、大結局",272),
                            ("272、測試",272), ("上架感言",None)]:
        assert chapter_number(title) == expected, title
    assert safe(BOOK+"/uid9c") and not safe(BOOK+"/uid9c?x=1")
    assert not safe("https://other.example/n/uii851/uid9c")
    fixture = '<html><title>〖測試〗一、測試 | 小說狂人</title><div class="content">' + "測試內容。" * 80 + '<div class="ads">廣告</div></div></html>'
    text, han, _ = extract(fixture, {"number": 1, "title": "一、測試"})
    assert han >= 250 and "廣告" not in text
    print("SELF_TEST_PASS")

if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--rights-confirmed", action="store_true")
    p.add_argument("--self-test", action="store_true")
    p.add_argument("--out", type=Path, default=Path("out/uii851"))
    p.add_argument("--delay", type=float, default=1.8)
    args = p.parse_args()
    if args.self_test:
        self_test()
    else:
        if not args.rights_confirmed:
            p.error("explicit permission required")
        raise SystemExit(collect(args.out, args.delay))
