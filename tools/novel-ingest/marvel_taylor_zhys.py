#!/usr/bin/env python3
"""Verified Chinese RAW collector for Marvel Taylor from the ZHYS catalog.

Uses full catalog order as ordinal identity (printed chapter numbers repeat).
Public pages only; respects robots.txt and aborts on login / anti-bot blocks.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

BOOK_URL = "https://cn.zhys.tw/book/2268838.html"
HOST = "cn.zhys.tw"
BOOK_ID = 2268838
CHAPTER_RE = re.compile(r"^/read/2268838/(\d+)\.html$")
NUMBER_RE = re.compile(r"第\s*(\d+)\s*章")
HAN_RE = re.compile(r"[\u3400-\u9fff]")
HANGUL_RE = re.compile(r"[\uac00-\ud7a3]")
USER_AGENT = "MedVerifiedNovelIngest/1.0 (public Chinese chapters; no auth)"
ERROR_MARKERS = ("just a moment", "captcha", "verify you are human",
                 "access denied", "enable javascript", "正在验证", "正在驗證",
                 "登录后阅读", "登入後閱讀", "购买本章", "購買本章", "章节已锁定")
JUNK = ("script,style,noscript,iframe,svg,header,footer,nav,aside,"
        "form,button,figure,figcaption,.ad,.ads,.advertisement,.ad-banner,"
        ".chapter-nav,.reading-progress,.comments,.related,.breadcrumbs,"
        "[role=navigation],[data-ad-slot]")


class CollectionError(Exception):
    def __init__(self, state: str, message: str):
        self.state = state
        super().__init__(message)


@dataclass(frozen=True)
class Chapter:
    ordinal: int
    source_id: int
    title: str
    author_number: int | None
    url: str


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def canon(url: str, *, catalog=False) -> str:
    p = urlsplit(url)
    if (p.scheme != "https" or p.hostname != HOST or p.username or p.password
            or p.port not in (None, 443) or p.query or p.fragment):
        raise CollectionError("unsafe_url", "Untrusted URL: " + url)
    if catalog:
        if p.path == f"/book/{BOOK_ID}.html":
            return url
        raise CollectionError("unsafe_url", "Wrong catalog URL")
    if CHAPTER_RE.fullmatch(p.path):
        return url
    raise CollectionError("unsafe_url", "Wrong book/chapter URL: " + url)


def policy_for(session):
    try:
        r = session.get("https://" + HOST + "/robots.txt", timeout=20,
                        allow_redirects=False)
    except requests.RequestException as exc:
        raise CollectionError("robots_unavailable", str(exc)) from exc
    policy = RobotFileParser()
    if r.status_code in (404, 410):
        policy.parse(["User-agent: *", "Allow: /"])
    elif r.status_code == 200 and "<html" not in r.text[:500].lower():
        policy.parse(r.text.splitlines())
    else:
        raise CollectionError("robots_unavailable", f"robots HTTP {r.status_code}")
    return policy


class Client:
    def __init__(self, session, policy, delay, sleep=time.sleep):
        self.session, self.policy, self.sleep = session, policy, sleep
        self.delay = max(float(delay), float(policy.crawl_delay(USER_AGENT) or 0))
        self.request_count = 0

    def read(self, url: str, *, catalog=False) -> str:
        canon(url, catalog=catalog)
        if not self.policy.can_fetch(USER_AGENT, url):
            raise CollectionError("robots_disallow", url)
        if self.request_count:
            self.sleep(self.delay)
        self.request_count += 1
        try:
            r = self.session.get(url, timeout=35, allow_redirects=False)
        except requests.RequestException as exc:
            raise CollectionError("network_error", type(exc).__name__) from exc
        if r.status_code in (401, 402, 403, 429, 451) or 300 <= r.status_code < 400:
            raise CollectionError("blocked", f"HTTP {r.status_code}")
        if r.status_code != 200:
            raise CollectionError("http_error", f"HTTP {r.status_code}")
        if "html" not in r.headers.get("Content-Type", "").lower():
            raise CollectionError("invalid_response", "Expected HTML")
        if not r.encoding or r.encoding.lower() == "iso-8859-1":
            r.encoding = r.apparent_encoding or "utf-8"
        source = r.text
        if any(marker in source[:15000].lower() for marker in ERROR_MARKERS):
            raise CollectionError("blocked", "Challenge/login/lock detected")
        return source


def parse_catalog(html: str) -> list[Chapter]:
    soup = BeautifulSoup(html, "html.parser")
    if not soup.title or "漫威" not in soup.title.get_text(" ", strip=True):
        raise CollectionError("wrong_book", "Catalog title does not match Marvel")
    content = soup.select_one("section#full-catalog")
    if not content:
        raise CollectionError("catalog_missing", "No complete catalog section")
    chapters = []
    seen = set()
    for a in content.select("a[href]"):
        url = urljoin(BOOK_URL, a.get("href") or "")
        try:
            canon(url)
        except CollectionError:
            continue
        match = CHAPTER_RE.fullmatch(urlsplit(url).path)
        number = int(match.group(1))
        label = re.sub(r"\s+", " ", a.get_text(" ", strip=True)).strip()
        if number in seen:
            raise CollectionError("catalog_duplicate_id", str(number))
        seen.add(number)
        m = NUMBER_RE.search(label)
        chapters.append(Chapter(len(chapters)+1, number, label or f"Entry {number}",
                                int(m.group(1)) if m else None, url))
    if not chapters:
        raise CollectionError("catalog_missing", "No same-book chapter links")
    return chapters


def clean_body(html: str, min_han=180) -> str:
    soup = BeautifulSoup(html, "html.parser")
    article = soup.select_one("article")
    if article is None:
        raise CollectionError("missing_body", "No article element")
    fragment = BeautifulSoup(str(article), "html.parser")
    article = fragment.select_one("article")
    for node in list(article.select(JUNK)):
        node.decompose()
    for node in list(article.select("a[href]")):
        node.decompose()
    # Most ZHYS article markup contains headings and the full chapter prose.
    lines = []
    for raw in article.get_text("\n", strip=True).splitlines():
        line = re.sub(r"[\u00a0\t ]+", " ", raw).strip()
        if line and not (line in ("上一章", "下一章", "目录", "目錄", "返回目录")
                         or line.startswith("发现阅读记录")
                         or line.startswith("上次阅读")):
            lines.append(line)
    body = "\n".join(lines).strip()
    if len(HAN_RE.findall(body)) < min_han:
        raise CollectionError("too_short", f"Han chars: {len(HAN_RE.findall(body))}")
    if HANGUL_RE.search(body):
        raise CollectionError("obfuscated", "Unexpected Hangul characters")
    return body


def write_text(path: Path, value: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(value, encoding="utf-8")
    temp.replace(path)


def write_json(path: Path, data):
    write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def collect(*, out: Path, start: int, end: int, expected: int = 318,
            min_han: int = 180, delay: float = 1.25, session=None,
            sleep=time.sleep):
    if not (1 <= start <= end <= 5000 and 1 <= expected <= 5000):
        raise ValueError("Invalid range")
    if delay < 0.75 or min_han < 100:
        raise ValueError("Delay must be >= 0.75 and min_han >= 100")
    if out.exists() and any(out.iterdir()):
        raise ValueError("Output directory must be empty")
    out.mkdir(parents=True, exist_ok=True)
    session = session or requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "zh-CN,zh;q=0.9"})
    report = {
        "schema_version": 1, "book_key": "marvel-who-rescued-him",
        "source": "zhys", "catalog_url": BOOK_URL, "book_id": BOOK_ID,
        "expected": expected, "requested": {"start": start, "end": end},
        "status": "INITIALIZING", "catalog_count": 0,
        "catalog": [], "chapters": [], "notion_sync": "not_performed",
    }
    try:
        client = Client(session, policy_for(session), delay, sleep)
        catalog = parse_catalog(client.read(BOOK_URL, catalog=True))
    except CollectionError as exc:
        report.update(status="BLOCKED" if exc.state in ("blocked", "robots_disallow", "robots_unavailable")
                      else "CATALOG_ERROR",
                      catalog_error={"status": exc.state, "detail": str(exc)})
        write_json(out / "manifest.json", report)
        return report
    report["catalog_count"] = len(catalog)
    report["catalog"] = [asdict(x) for x in catalog]
    for n in range(start, end+1):
        if n > len(catalog):
            report["chapters"].append({"ordinal": n, "status": "missing_from_catalog"})
            continue
        ch = catalog[n-1]
        row = asdict(ch)
        try:
            body = clean_body(client.read(ch.url), min_han=min_han)
            text = ch.title + "\n\n" + body + "\n"
            target = f"raw/{ch.ordinal:04d}_id{ch.source_id}.txt"
            write_text(out / target, text)
            row.update(status="ok", file=target, han=len(HAN_RE.findall(body)),
                       chars=len(body), sha256=sha256(text),
                       body_sha256=sha256(re.sub(r"\s+", "", body)))
        except CollectionError as exc:
            row.update(status=exc.state, error=str(exc))
        except OSError as exc:
            row.update(status="write_error", error=str(exc))
        report["chapters"].append(row)
        if n % 10 == 0 or n == end:
            write_json(out / "manifest.json", report)
            print(json.dumps({"range": [start,end], "processed": n-start+1,
                              "last": n, "failures": sum(x["status"]!="ok" for x in report["chapters"])},
                             ensure_ascii=False), flush=True)
    good = [x for x in report["chapters"] if x["status"] == "ok"]
    duplicate_bodies = {}
    for row in good:
        prev = duplicate_bodies.get(row["body_sha256"])
        if prev is not None:
            row.update(status="duplicate_body", duplicate_of=prev)
        else:
            duplicate_bodies[row["body_sha256"]] = row["ordinal"]
    report["ok_count"] = sum(x["status"]=="ok" for x in report["chapters"])
    report["failed_count"] = len(report["chapters"]) - report["ok_count"]
    report["status"] = ("PASS" if report["failed_count"] == 0
                        and len(catalog) == expected else "PARTIAL")
    write_json(out / "manifest.json", report)
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--start", type=int, required=True)
    p.add_argument("--end", type=int, required=True)
    p.add_argument("--expected", type=int, default=318)
    p.add_argument("--min-han", type=int, default=180)
    p.add_argument("--delay", type=float, default=1.25)
    a=p.parse_args()
    result=collect(out=a.out_dir,start=a.start,end=a.end,expected=a.expected,
                   min_han=a.min_han,delay=a.delay)
    print(json.dumps({"status":result["status"],"catalog_count":result["catalog_count"],
                      "ok_count":result.get("ok_count",0),
                      "failed_count":result.get("failed_count",0)},ensure_ascii=False))
    if result["status"]!="PASS":
        raise SystemExit(2)


if __name__=="__main__":
    main()
