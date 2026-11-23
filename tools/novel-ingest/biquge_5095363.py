#!/usr/bin/env python3
"""Permission-confirmed collection of the 229 public chapters of Biquge 5095363.

Fail closed on access blocks, robots restrictions, missing chapter ordinals,
unexpected redirects, short/duplicate bodies, and source inconsistencies.
Save chapter files as well as an audit trail; never silently claim completeness.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
import zipfile
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

BOOK_ID = "5095363"
SOURCE = f"https://www.biquge.tw/book/{BOOK_ID}/"
BOOK_TITLE = "美漫：收容异常物从战锤征兵开始"
BOOK_AUTHOR = "我可是破绽"
EXPECTED_CHAPTERS = 229
USER_AGENT = "MEDAuthorizedNovelCollector/1.0 (+https://github.com/Lalalalendia/med)"
NUMBER = re.compile(r"第\s*(\d+)\s*章")
HAN = re.compile(r"[\u3400-\u9fff]")
BLOCK_MARKERS = (
    "captcha", "verify you are human", "just a moment",
    "access denied", "安全验证", "人机验证", "请先登录",
    "付费阅读", "购买本章", "访问频繁",
)
CONTENT_SELECTORS = (
    "#chaptercontent", "#content", "#contentbox", "#txtcontent",
    "#ChapterContent", ".chapter-content", ".read-content", ".content",
    "article", "main",
)
STRIP_SELECTORS = (
    "script, style, noscript, iframe, form, nav, header, footer, aside, "
    "button, .ad, .ads, .advertisement, .pagination, .read-page"
)


def assert_safe_url(url: str, *, chapter: bool = False) -> None:
    p = urlsplit(url)
    if p.scheme != "https" or p.hostname not in ("www.biquge.tw", "biquge.tw"):
        raise ValueError(f"Unsafe host/scheme: {url}")
    if p.username or p.password or p.port not in (None, 443) or p.query or p.fragment:
        raise ValueError(f"Unexpected URL components: {url}")
    if chapter:
        if not re.fullmatch(r"/book/5095363/\d+\.html", p.path):
            raise ValueError(f"Unexpected chapter path: {url}")
    elif p.path not in ("/book/5095363/", "/book/5095363.html"):
        raise ValueError(f"Unexpected index path: {url}")


def robots_policy(session: requests.Session) -> RobotFileParser:
    r = session.get("https://www.biquge.tw/robots.txt",
                    timeout=(12, 30), allow_redirects=False)
    policy = RobotFileParser()
    if r.status_code in (404, 410):
        policy.parse(["User-agent: *", "Allow: /"])
    elif r.status_code == 200 and "<html" not in r.text[:500].lower():
        policy.parse(r.text.splitlines())
    else:
        raise ValueError(f"Cannot confirm robots policy: HTTP {r.status_code}")
    return policy


def fetch_html(session: requests.Session, policy: RobotFileParser, url: str,
               delay: float, *, chapter: bool = False) -> str:
    assert_safe_url(url, chapter=chapter)
    if not policy.can_fetch(USER_AGENT, url):
        raise ValueError(f"robots.txt disallows {url}")
    transient = (500, 502, 503, 504)
    for attempt in range(3):
        time.sleep(delay if attempt == 0 else delay * (attempt + 2))
        try:
            r = session.get(url, timeout=(12, 45), allow_redirects=False)
        except (requests.ConnectionError, requests.Timeout):
            if attempt < 2:
                continue
            raise
        if r.status_code in transient and attempt < 2:
            continue
        if r.status_code != 200:
            raise ValueError(f"HTTP {r.status_code} at {url}")
        if "html" not in r.headers.get("Content-Type", "").lower():
            raise ValueError(f"Unexpected content type at {url}")
        if urlsplit(r.url).hostname not in ("www.biquge.tw", "biquge.tw"):
            raise ValueError(f"Untrusted final host at {url}")
        r.encoding = r.apparent_encoding or "utf-8"
        if any(marker in r.text[:15000].lower() for marker in BLOCK_MARKERS):
            raise ValueError(f"Potential access/verification block at {url}")
        return r.text
    raise ValueError(f"Failed after retries: {url}")


def parse_catalog(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    result: dict[int, dict] = {}
    for link in soup.select("a[href]"):
        label = re.sub(r"\s+", " ", link.get_text(" ", strip=True))
        match = NUMBER.search(label)
        if not match:
            continue
        ordinal = int(match.group(1))
        if not 1 <= ordinal <= EXPECTED_CHAPTERS + 50:
            continue
        url = urljoin(SOURCE, link["href"])
        try:
            assert_safe_url(url, chapter=True)
        except ValueError:
            continue
        row = {"number": ordinal, "title": label, "url": url}
        if ordinal in result and result[ordinal]["url"] != url:
            raise ValueError(f"Ambiguous catalog entry for chapter {ordinal}")
        result[ordinal] = row
    if sorted(result) != list(range(1, EXPECTED_CHAPTERS + 1)):
        missing = [n for n in range(1, EXPECTED_CHAPTERS + 1) if n not in result]
        extra = [n for n in result if n > EXPECTED_CHAPTERS]
        raise ValueError(f"Catalog mismatch: found={len(result)}, missing={missing[:25]}, extra={extra[:25]}")
    urls = [row["url"] for row in result.values()]
    if len(set(urls)) != len(urls):
        raise ValueError("Different chapter ordinals share the same URL")
    return [result[n] for n in range(1, EXPECTED_CHAPTERS + 1)]


def parse_chapter(html: str, expected: dict) -> tuple[str, str, int]:
    soup = BeautifulSoup(html, "html.parser")
    headings = [x.get_text(" ", strip=True) for x in soup.select("h1, h2")]
    matching = [x for x in headings
                if (m := NUMBER.search(x)) and int(m.group(1)) == expected["number"]]
    if not matching:
        raise ValueError(f"Chapter heading mismatch for {expected['number']}: {headings[:3]}")
    title = matching[0]
    selected = []
    for selector in CONTENT_SELECTORS:
        for node in soup.select(selector):
            size = len(HAN.findall(node.get_text(" ", strip=True)))
            selected.append((size, node))
    if not selected:
        raise ValueError(f"Missing content container at chapter {expected['number']}")
    size, root = max(selected, key=lambda item: item[0])
    if size < 100:
        raise ValueError(f"Content container too short: {size} Han")
    for element in root.select(STRIP_SELECTORS):
        element.decompose()
    for br in root.select("br"):
        br.replace_with("\n")
    text = root.get_text("\n", strip=True)
    paragraphs = [re.sub(r"[ \t\u00a0]+", " ", x).strip()
                  for x in text.splitlines()]
    paragraphs = [x for x in paragraphs if x and x != title
                  and not re.fullmatch(r"(上一章|下一章|返回目录|加入书架|目录|章节目录)", x)]
    body = "\n\n".join(paragraphs).strip()
    han_count = len(HAN.findall(body))
    if han_count < 120:
        raise ValueError(f"Chapter {expected['number']} suspiciously short ({han_count} Han)")
    if any(marker in body[:3000].lower() for marker in BLOCK_MARKERS):
        raise ValueError(f"Chapter {expected['number']} seems gated")
    if "本章未完" in body or "下一页继续阅读" in body:
        raise ValueError(f"Chapter {expected['number']} appears split across pages")
    return title, body, han_count


def write_status(out: Path, data: dict) -> None:
    (out / "status.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def collect(args: argparse.Namespace) -> int:
    if not args.rights_confirmed:
        raise ValueError("Explicit rights confirmation required")
    if args.start != 1 or args.end != EXPECTED_CHAPTERS or args.delay < 1.0:
        raise ValueError("Scope must be chapters 1-229, and delay >= 1 second")
    out = Path(args.out)
    chapter_dir = out / "chapters"
    chapter_dir.mkdir(parents=True, exist_ok=True)
    status: dict = {
        "book_id": BOOK_ID, "title": BOOK_TITLE, "author": BOOK_AUTHOR,
        "source": SOURCE, "expected_chapters": EXPECTED_CHAPTERS,
        "status": "INCOMPLETE", "collected": 0, "chapters": [], "errors": [],
    }
    write_status(out, status)
    session = requests.Session()
    session.headers.update({
        "User-Agent": USER_AGENT,
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Accept": "text/html,application/xhtml+xml",
    })
    try:
        policy = robots_policy(session)
        catalog = parse_catalog(fetch_html(session, policy, SOURCE, args.delay))
        status["catalog_count"] = len(catalog)
        print("CATALOG", len(catalog), flush=True)
        seen_hashes = set()
        for entry in catalog:
            number = entry["number"]
            try:
                page = fetch_html(session, policy, entry["url"], args.delay, chapter=True)
                title, body, han_count = parse_chapter(page, entry)
                data = (title + "\n\n" + body + "\n").encode("utf-8")
                sha = hashlib.sha256(body.encode("utf-8")).hexdigest()
                if sha in seen_hashes:
                    raise ValueError(f"Duplicate chapter content at {number}")
                seen_hashes.add(sha)
                filename = f"chapters/{number:04d}.txt"
                (out / filename).write_bytes(data)
                status["chapters"].append({
                    "number": number, "title": title, "source_url": entry["url"],
                    "file": filename, "han_count": han_count, "body_sha256": sha,
                    "file_sha256": hashlib.sha256(data).hexdigest(),
                })
                status["collected"] = len(status["chapters"])
                print(f"OK {number:03d}/{EXPECTED_CHAPTERS} {han_count} Han", flush=True)
            except Exception as exc:
                status["errors"].append({
                    "number": number, "url": entry["url"],
                    "error": f"{type(exc).__name__}: {exc}",
                })
                print(f"FAIL chapter {number}: {type(exc).__name__}: {exc}", flush=True)
                break  # preserve truthful contiguous coverage
            finally:
                write_status(out, status)
        if status["collected"] == EXPECTED_CHAPTERS and not status["errors"]:
            joined = "\n\n".join(
                (out / row["file"]).read_text(encoding="utf-8")
                for row in status["chapters"]
            )
            (out / "combined.txt").write_text(joined + "\n", encoding="utf-8")
            archive = out / f"biquge-{BOOK_ID}-001-{EXPECTED_CHAPTERS}-zh.zip"
            with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
                for row in status["chapters"]:
                    z.write(out / row["file"], row["file"])
                z.write(out / "combined.txt", "combined.txt")
                z.writestr("manifest.json", json.dumps(status, ensure_ascii=False, indent=2))
            with zipfile.ZipFile(archive) as z:
                if z.testzip() is not None:
                    raise ValueError("ZIP CRC validation failed")
                names = [name for name in z.namelist() if name.startswith("chapters/")]
                if len(names) != EXPECTED_CHAPTERS:
                    raise ValueError("ZIP chapter count mismatch")
            status["status"] = "PASS"
            status["archive"] = archive.name
            status["archive_sha256"] = hashlib.sha256(archive.read_bytes()).hexdigest()
            print("COMPLETE", archive, status["archive_sha256"], flush=True)
    except Exception as exc:
        status["errors"].append({
            "stage": "setup_or_archive",
            "error": f"{type(exc).__name__}: {exc}",
        })
    finally:
        write_status(out, status)
        (out / "summary.md").write_text(
            f"# Biquge {BOOK_ID} collection\n\n"
            f"Status: **{status['status']}**\n\n"
            f"Chapters verified: **{status['collected']}/{EXPECTED_CHAPTERS}**\n\n"
            f"Errors: {len(status['errors'])}\n",
            encoding="utf-8",
        )
    print(json.dumps({
        "status": status["status"], "collected": status["collected"],
        "expected": EXPECTED_CHAPTERS, "errors": status["errors"][:3],
    }, ensure_ascii=False), flush=True)
    return 0 if status["status"] == "PASS" else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rights-confirmed", action="store_true")
    parser.add_argument("--start", type=int, default=1)
    parser.add_argument("--end", type=int, default=229)
    parser.add_argument("--delay", type=float, default=1.0)
    parser.add_argument("--out", default="out/biquge-5095363")
    return collect(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
