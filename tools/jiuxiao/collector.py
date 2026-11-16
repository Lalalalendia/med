#!/usr/bin/env python3
"""Jiuxiao book collector: preserve paragraphs, verify chapter order, fail closed.

Use only with content you are entitled to reproduce. Live CI pilot is Lu Xun's
public-domain '故事新编'. No browser automation or challenge bypass is used.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import unicodedata
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

HOST = "jiuxiaozw.com"
BOOK_ID_RE = re.compile(r"[0-9a-f]{24}")
URL_BOOK_RE = re.compile(r"^/(?:sim/)?book/([0-9a-f]{24})/?$")
CHAPTER_RE = re.compile(r"^/(?:sim/)?book/([0-9a-f]{24})/([0-9a-f]{24})/?$")
CHAPTER_NUMBER_RE = re.compile(r"^第\s*([0-9]+)\s*章")
CATALOG_COUNT_RE = re.compile(r"(?:完整(?:目錄|目录)|共|全)\s*([0-9,]+)\s*章")
CHALLENGE = ("cf-chl", "captcha", "just a moment", "访问过于频繁", "安全验证", "access denied")
USER_AGENT = "MED-Jiuxiao-Book-Pilot/1.0 (responsible read-only archival testing)"


@dataclass(frozen=True)
class Entry:
    ordinal: int
    title: str
    url: str
    id: str


def clean(s: str) -> str:
    return unicodedata.normalize("NFC", s.replace("\xa0", " ").replace("\u200b", "")).strip()


def sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def chapter_url(url: str, book_id: str) -> tuple[str, str] | None:
    u = urlparse(urljoin("https://" + HOST, url))
    if u.hostname not in (HOST, "www." + HOST) or u.scheme != "https":
        return None
    m = CHAPTER_RE.fullmatch(u.path)
    return (m.group(2), "https://" + HOST + "/book/" + m.group(1) + "/" + m.group(2)) if m and m.group(1) == book_id else None


def parse_catalog(html: str, book_url: str) -> tuple[dict, list[Entry]]:
    parsed = urlparse(book_url)
    if parsed.hostname not in (HOST, "www." + HOST) or parsed.scheme != "https":
        raise ValueError("Untrusted book host")
    bm = URL_BOOK_RE.fullmatch(parsed.path)
    if not bm:
        raise ValueError("Not a Jiuxiao book URL")
    bid = bm.group(1)
    soup = BeautifulSoup(html, "html.parser")
    title = soup.select_one("h1")
    if not title:
        raise ValueError("Missing book heading")
    expected = None
    for b in soup.select("button.book-latest-catalog,button.mobile-catalog"):
        match = CATALOG_COUNT_RE.search(b.get_text(" ", strip=True))
        if match:
            expected = int(match.group(1).replace(",", ""))
            break
    if expected is None:
        raise ValueError("Missing authoritative catalog count")
    if not 1 <= expected <= 20000:
        raise ValueError("Unexpected catalog count")
    candidates: dict[str, tuple[str,str]] = {}
    for a in soup.select("a[href]"):
        matched = chapter_url(a["href"], bid)
        if not matched:
            continue
        cid, url = matched
        label = clean(a.get_text(" ", strip=True))
        if not label or label in ("开始阅读", "開始閱讀", "立即阅读", "立即閱讀"):
            continue
        if cid not in candidates:
            # Remove the UI-only displayed word count without touching the actual title.
            label = re.sub(r"\s+[0-9,]+\s*字\s*$", "", label).strip()
            candidates[cid] = (label, url)
    if len(candidates) != expected:
        raise ValueError(f"Catalog incomplete: {len(candidates)} unique links vs {expected} announced")
    # The 'latest chapters' panel is reverse-chronological.
    order = list(reversed(list(candidates.items())))
    entries = [Entry(i, label, url, cid) for i, (cid, (label,url)) in enumerate(order,1)]
    numbered = [int(m.group(1)) for e in entries if (m := CHAPTER_NUMBER_RE.match(e.title))]
    if numbered != sorted(numbered) or len(set(numbered)) != len(numbered):
        raise ValueError("Reverse-chronological catalog assumption failed: numbered chapters out of order")
    page_title = soup.title.get_text(" ", strip=True) if soup.title else ""
    author = page_title.split(" - ")[1] if " - " in page_title else None
    return {
        "book_id": bid,
        "title": clean(title.get_text(" ",strip=True)),
        "author": author,
        "source_url": book_url,
        "announced_catalog_count": expected,
        "detected_unique_chapters": len(entries),
    }, entries


def parse_chapter(html: str, entry: Entry) -> tuple[str, list[str], str | None]:
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.select_one("h1")
    if h1 is None:
        raise ValueError("Missing chapter H1")
    heading = clean(h1.get_text(" ",strip=True))
    if heading != entry.title:
        raise ValueError(f"Chapter title mismatch ordinal {entry.ordinal}: catalog={entry.title!r}, page={heading!r}")
    content = soup.select_one("div.reader-columns")
    if content is None:
        raise ValueError(f"Chapter {entry.ordinal} missing reader-columns")
    elements = content.select("p.reader-paragraph")
    if len(elements) < 2:
        raise ValueError(f"Chapter {entry.ordinal} contains too few paragraphs: {len(elements)}")
    paragraphs = []
    for el in elements:
        inner = el.select_one(".reader-paragraph-text") or el
        raw = inner.get_text("",strip=False)
        value = clean(raw)
        if value:
            paragraphs.append(value)
    joined = "\n\n".join(paragraphs)
    cjk = len(re.findall(r"[\u3400-\u9fff]", joined))
    if cjk < 100 or len(joined) < 180:
        raise ValueError(f"Chapter {entry.ordinal} implausibly short: {len(joined)} chars, {cjk} CJK")
    if any(x.lower() in joined[:600].lower() for x in ("just a moment", "请先登录", "请登录后", "access denied")):
        raise ValueError(f"Chapter {entry.ordinal} has a login/challenge instead of text")
    next_url = None
    for a in soup.select("a[href]"):
        label = clean(a.get_text(" ",strip=True))
        if label in ("下一章", "下壹章"):
            next_url = urljoin(entry.url,a.get("href"))
            break
    return heading, paragraphs, next_url


def check_next(entry: Entry, next_url: str | None, following: Entry | None) -> None:
    if following:
        if next_url is None:
            raise ValueError(f"No next chapter link after {entry.ordinal}")
        if urlparse(next_url).path.rsplit("/",1)[-1] != following.id:
            raise ValueError(f"Next chapter mismatch after {entry.ordinal}")
    elif next_url is not None:
        # Some sites link last chapter to an afterword; a true full catalog must contain it.
        raise ValueError("Catalog claims final chapter, but navigation has a next chapter")


class RespectfulClient:
    def __init__(self, wait: float = 2):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent":USER_AGENT,"Accept-Language":"zh-CN,zh;q=0.9"})
        self.wait = max(2.0,float(wait))
        self.last_request = 0.0
        response = self.session.get("https://" + HOST + "/robots.txt",timeout=25)
        if response.status_code != 200 or "html" in response.headers.get("Content-Type","").lower():
            raise RuntimeError("robots.txt unavailable; refusing to collect")
        self.robots = RobotFileParser()
        self.robots.parse(response.text.splitlines())
        self.wait = max(self.wait,float(self.robots.crawl_delay(USER_AGENT) or 0))
        self.last_request = time.monotonic()

    def get(self, url: str) -> str:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname != HOST or not self.robots.can_fetch(USER_AGENT,url):
            raise RuntimeError("Host or robots.txt restriction rejects URL")
        r = None
        for attempt in range(3):
            elapsed = time.monotonic()-self.last_request
            if elapsed < self.wait:
                time.sleep(self.wait-elapsed)
            try:
                r = self.session.get(url,timeout=45)
            except (requests.ConnectionError, requests.Timeout) as exc:
                self.last_request = time.monotonic()
                if attempt == 2:
                    raise RuntimeError("Transient request failed after 3 attempts") from exc
                time.sleep(2 ** (attempt+1))
                print(f"TRANSIENT_RETRY attempt={attempt+1} reason=network",flush=True)
                continue
            self.last_request = time.monotonic()
            if r.status_code in (502,503,504):
                if attempt == 2:
                    raise RuntimeError(f"Transient HTTP {r.status_code} after 3 attempts")
                time.sleep(2 ** (attempt+1))
                print(f"TRANSIENT_RETRY attempt={attempt+1} reason=http_{r.status_code}",flush=True)
                continue
            break
        if r is None:
            raise RuntimeError("No HTTP response received")
        if r.status_code != 200 or "html" not in r.headers.get("Content-Type","").lower():
            raise RuntimeError(f"Invalid HTTP status/content type: {r.status_code} {r.headers.get('Content-Type')}")
        if r.url.startswith("https://"+HOST+"/") is False:
            raise RuntimeError("Unexpected redirect host")
        if any(marker in r.text[:12000].lower() for marker in CHALLENGE):
            raise RuntimeError("Challenge detected; not attempting bypass")
        return r.text


def safe_filename(title: str) -> str:
    name = re.sub(r"[^\w\u3400-\u9fff\-]+", "_", title,flags=re.UNICODE).strip("_")
    return name[:64] or "chapter"


def collect(url: str, output: Path, delay: float, expected_title: str | None) -> dict:
    client = RespectfulClient(delay)
    metadata, chapters = parse_catalog(client.get(url), url)
    if expected_title is not None and metadata["title"] != expected_title:
        raise ValueError(f"Wrong book: {metadata['title']} != {expected_title}")
    output.mkdir(parents=True,exist_ok=True)
    (output/"chapters").mkdir(exist_ok=True)
    book_fragments = []
    chapter_rows = []
    sha_set = set()
    for index, entry in enumerate(chapters):
        html = client.get(entry.url)
        heading, paragraphs, next_link = parse_chapter(html,entry)
        check_next(entry,next_link,chapters[index+1] if index+1 < len(chapters) else None)
        text = "\n\n".join(paragraphs).rstrip()+"\n"
        digest = sha256(text)
        if digest in sha_set:
            raise ValueError("Duplicate chapter contents")
        sha_set.add(digest)
        filename = f"{entry.ordinal:04d}_{safe_filename(heading)}.txt"
        (output/"chapters"/filename).write_text(text,encoding="utf-8")
        chapter_rows.append({**asdict(entry),"filename":filename,"characters":len(text),
                             "paragraphs":len(paragraphs),"sha256":digest})
        book_fragments.append(f"{heading}\n\n{text.rstrip()}")
        print(f"CHAPTER {entry.ordinal}/{len(chapters)} chars={len(text)} paragraphs={len(paragraphs)} sha256={digest[:12]}",flush=True)
    all_text="\n\n\n".join(book_fragments).rstrip()+"\n"
    (output/"book.txt").write_text(all_text,encoding="utf-8")
    final={"status":"SUCCESS","collected_at_utc":datetime.now(timezone.utc).isoformat(),
           **metadata,"chapters_collected":len(chapter_rows),
           "missing":[],"text_characters":len(all_text),"sha256_book_txt":sha256(all_text),
           "chapter_rows":chapter_rows}
    (output/"manifest.json").write_text(json.dumps(final,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (output/"SUMMARY.md").write_text(
        "# Jiuxiao public-domain book pilot\n\n"
        f"- Title: {metadata['title']}\n- Author: {metadata['author']}\n"
        f"- Chapters: {len(chapter_rows)}/{metadata['announced_catalog_count']}\n"
        f"- Characters in book.txt: {len(all_text)}\n"
        f"- SHA-256: {sha256(all_text)}\n- Status: SUCCESS\n",encoding="utf-8")
    print("RESULT",json.dumps({k:final[k] for k in ("status","title","chapters_collected","text_characters","sha256_book_txt")},ensure_ascii=False),flush=True)
    return final


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--book-url",required=True)
    parser.add_argument("--out-dir",type=Path,default=Path("out/jiuxiao/pilot-book"))
    parser.add_argument("--delay",type=float,default=2)
    parser.add_argument("--expected-title")
    args=parser.parse_args()
    collect(args.book_url,args.out_dir,args.delay,args.expected_title)


if __name__=="__main__":
    try:
        main()
    except Exception as exc:
        print("COLLECTION_FAILED",type(exc).__name__,str(exc),file=sys.stderr,flush=True)
        sys.exit(1)
