#!/usr/bin/env python3
"""Rights-confirmed collection of IXDZS 218645; no bypasses or prose commits.

Prefer the site's own TXT ZIP, with chapter-page fallback only when that file
is unavailable and robots.txt permits crawling. Outputs are temporary artifacts.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import io
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser
from zipfile import ZIP_DEFLATED, ZipFile

import requests
from bs4 import BeautifulSoup

BOOK = "218645"
TITLE = "某美漫的鳳凰之力"
AUTHOR = "難道我是超人"
INDEX = f"https://ixdzs.tw/read/{BOOK}/"
DOWNLOAD = f"https://down7.ixdzs8.tw/{BOOK}_tw.zip"
NUMBERED = 190
CATALOG_ENTRIES = 197
UA = "MEDAuthorizedIXDZS/1.0 (+https://github.com/Lalalalendia/med)"
CJK = re.compile(r"[\u3400-\u9fff]")
HEADING = re.compile(r"(?m)^[ \t\u3000\ufeff]*(第[ \t\u3000]*(\d{1,4})[ \t\u3000]*章[^\r\n]{0,110})[ \t\u3000]*$")
PAGE = re.compile(rf"^/read/{BOOK}/p(\d+)\.html$")
ROOTS = ("article", "#content", "#chaptercontent", "#txtcontent",
         "#chapter", ".chapter-content", ".read-content", "#read-content")
CHALLENGES = ("captcha", "verify you are human", "just a moment",
              "access denied", "正在验证", "安全驗證", "人機驗證")


class Unavailable(Exception):
    pass


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def request_bytes(session, url, hosts, *, cap=50 * 1024 * 1024):
    try:
        response = session.get(url, timeout=(10, 90), stream=True)
    except requests.RequestException as exc:
        raise Unavailable(f"Network failure at {url}: {type(exc).__name__}") from exc
    try:
        target = urlparse(response.url)
        if target.scheme != "https" or target.netloc.lower() not in hosts:
            raise ValueError(f"Untrusted redirect: {response.url}")
        if response.status_code in (403, 429, 503):
            raise RuntimeError(f"Access restriction HTTP {response.status_code} at {url}")
        if response.status_code != 200:
            raise Unavailable(f"HTTP {response.status_code} at {url}")
        out = io.BytesIO()
        for chunk in response.iter_content(chunk_size=131072):
            if chunk:
                out.write(chunk)
                if out.tell() > cap:
                    raise ValueError(f"Download size exceeds {cap} bytes")
        return out.getvalue(), response.url
    finally:
        response.close()


def decode_chinese(raw):
    for codec in ("utf-8-sig", "gb18030", "big5", "utf-16"):
        try:
            value = raw.decode(codec)
        except UnicodeError:
            continue
        if len(CJK.findall(value)) >= 100:
            return value.replace("\r\n", "\n").replace("\r", "\n")
    raise ValueError("Unknown or unreadable Chinese text encoding")


def validate(records, expected=NUMBERED, extras_expected=CATALOG_ENTRIES - NUMBERED):
    numbered = [r for r in records if r["number"] is not None]
    extras = [r for r in records if r["number"] is None]
    numbers = [r["number"] for r in numbered]
    if numbers != list(range(1, expected + 1)):
        raise ValueError(f"Numbered chapter sequence invalid: count={len(numbers)}, "
                         f"first={numbers[:10]}, last={numbers[-10:]}")
    if len(extras) != extras_expected or len(records) != expected + extras_expected:
        raise ValueError(f"Incomplete catalog: {len(numbered)} numbered, "
                         f"{len(extras)} extras, expected {expected}+{extras_expected}")
    if expected == NUMBERED and extras_expected == 7:
        wanted = Counter({"二戰風雲": 1, "變種人時代": 2, "復仇者聯盟": 1,
                          "回來了": 1, "最後還是說兩句": 1, "新書：開局一個女超人": 1})
        actual = Counter(r["title"] for r in extras)
        if actual != wanted:
            raise ValueError(f"Extras differ from source catalog: {actual}")
    fingerprints = [sha(r["text"].encode("utf-8")) for r in records]
    if len(fingerprints) != len(set(fingerprints)):
        raise ValueError("Duplicate entry bodies detected")
    for r in records:
        cjk = len(CJK.findall(r["text"]))
        minimum = 25 if r["number"] in (79, 110) or r["number"] is None else 100
        if cjk < minimum:
            raise ValueError(f"Short entry {r['number'] or r['title']}: {cjk} CJK")


EXTRA_TITLES = ("二戰風雲", "變種人時代", "復仇者聯盟", "回來了",
                "最後還是說兩句", "新書：開局一個女超人")
EXTRA_PATTERN = "|".join(re.escape(title) for title in EXTRA_TITLES)
ENTRY_LINE = re.compile(
    rf"(?m)^(?P<title>第(?P<number>\d{{1,4}})章[^\r\n]{{0,110}}|{EXTRA_PATTERN})[ \t\u3000]*\r?$"
)


def split_txt(content, expected=NUMBERED, extras_expected=CATALOG_ENTRIES - NUMBERED):
    # The official download has a front-matter metadata block and a closing
    # website footer. Keep only the entries represented in the book catalog.
    marker = "------章節內容開始-------"
    if marker in content:
        content = content.split(marker, 1)[1]
    content = re.split(r"(?m)^=已完結=[ \t]*$", content, maxsplit=1)[0]
    matches = list(ENTRY_LINE.finditer(content))
    records = []
    for index, match in enumerate(matches):
        number = int(match.group("number")) if match.group("number") else None
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
        body = content[start:end].strip()
        records.append({"number": number, "title": match.group("title").strip(),
                        "text": body, "source_url": DOWNLOAD})
    validate(records, expected, extras_expected)
    return records

def official_zip(session):
    raw, resolved_url = request_bytes(session, DOWNLOAD, {"down7.ixdzs8.tw"}, cap=60 * 1024 * 1024)
    if not raw.startswith(b"PK"):
        raise Unavailable("Official TXT download is not a ZIP")
    with ZipFile(io.BytesIO(raw)) as source:
        if source.testzip() is not None:
            raise ValueError("Official ZIP CRC failed")
        entries = [e for e in source.infolist() if not e.is_dir() and e.filename.lower().endswith(".txt")]
        if not entries:
            raise Unavailable("Official ZIP has no TXT")
        if sum(e.file_size for e in entries) > 90 * 1024 * 1024:
            raise ValueError("Official ZIP expands beyond 90 MiB")
        texts = [decode_chinese(source.read(e)) for e in entries]
    records = split_txt("\n\n".join(texts))
    combined = "\n\n".join(r["title"] + "\n\n" + r["text"] for r in records)
    return records, combined, raw, resolved_url

def robots_policy(session):
    raw, _ = request_bytes(session, "https://ixdzs.tw/robots.txt", {"ixdzs.tw"}, cap=150000)
    source = raw.decode("utf-8", errors="replace")
    if "user-agent:" not in source.lower():
        raise RuntimeError("Cannot verify robots.txt; no page crawling")
    parser = RobotFileParser()
    parser.parse(source.splitlines())
    if not parser.can_fetch(UA, INDEX):
        raise RuntimeError("Source catalog is disallowed by robots.txt")
    return parser, max(2.0, float(parser.crawl_delay(UA) or 0.0))


def chapter_body(html, title):
    soup = BeautifulSoup(html, "html.parser")
    heading = soup.select_one("h1")
    actual = heading.get_text(" ", strip=True) if heading else ""
    if not actual:
        raise ValueError("Chapter heading is absent")
    if any(marker in actual.lower() for marker in CHALLENGES):
        raise RuntimeError("Challenge page; stop")
    containers = [soup.select_one(sel) for sel in ROOTS]
    containers = [n for n in containers if n is not None]
    if not containers:
        raise ValueError(f"No chapter prose container for {title}")
    root = max(containers, key=lambda node: len(node.get_text(" ", strip=True)))
    for node in root.select("script,style,nav,footer,header,aside,iframe,form"):
        node.decompose()
    paragraphs = [part.strip() for part in root.stripped_strings if part.strip()]
    body = "\n\n".join(paragraphs)
    if len(CJK.findall(body)) < 25:
        raise ValueError(f"Missing body for {title}")
    return actual, body


def collect_pages(session, delay):
    robots, crawl_delay = robots_policy(session)
    delay = max(delay, crawl_delay)
    raw, final = request_bytes(session, INDEX, {"ixdzs.tw"}, cap=4 * 1024 * 1024)
    if urlparse(final).path.rstrip("/") != f"/read/{BOOK}":
        raise ValueError("Unexpected catalog destination")
    soup = BeautifulSoup(raw, "html.parser")
    pages = {}
    for anchor in soup.select("a[href]"):
        url = urljoin(INDEX, anchor["href"])
        bits = urlparse(url)
        if bits.scheme != "https" or bits.netloc != "ixdzs.tw":
            continue
        match = PAGE.fullmatch(bits.path)
        if match:
            pages[int(match.group(1))] = (url, anchor.get_text(" ", strip=True))
    if len(pages) != CATALOG_ENTRIES:
        raise ValueError(f"Index contains {len(pages)} distinct pages, expected {CATALOG_ENTRIES}")
    records = []
    for ordinal, (locator, (url, toc_heading)) in enumerate(sorted(pages.items()), 1):
        if not robots.can_fetch(UA, url):
            raise RuntimeError(f"robots.txt disallows {url}")
        time.sleep(delay)
        data, final = request_bytes(session, url, {"ixdzs.tw"}, cap=3 * 1024 * 1024)
        if urlparse(final).path != f"/read/{BOOK}/p{locator}.html":
            raise ValueError(f"Unexpected chapter redirect to {final}")
        html = data.decode("utf-8", errors="replace")
        if any(marker in html.lower()[:16000] for marker in CHALLENGES):
            raise RuntimeError(f"Anti-bot challenge at p{locator}")
        if re.search(rf'/read/{BOOK}/p{locator}[_-]\d+\.html', html):
            raise ValueError(f"Potential split chapter at p{locator}")
        title, body = chapter_body(html, toc_heading)
        match = HEADING.search(title)
        if not match:
            match = re.search(r"第[ \t\u3000]*(\d{1,4})[ \t\u3000]*章", title)
            number = int(match.group(1)) if match else None
        else:
            number = int(match.group(2))
        records.append({"number": number, "title": title, "text": body,
                        "source_url": final, "physical_locator": locator})
        print(f"PAGE {ordinal}/{len(pages)} p{locator}: chapter={number}, CJK={len(CJK.findall(body))}", flush=True)
    validate(records)
    return records, "\n\n".join(r["title"] + "\n\n" + r["text"] for r in records), None, None


def package(records, combined, original_zip, original_url, out, method):
    out.mkdir(parents=True, exist_ok=True)
    target = out / f"ixdzs-{BOOK}-authorized-cn.zip"
    chapter_meta = []
    with ZipFile(target, "w", ZIP_DEFLATED) as archive:
        for idx, row in enumerate(records, 1):
            suffix = f"{row['number']:04d}" if row["number"] is not None else f"{idx:04d}"
            name = ("chapters" if row["number"] is not None else "extras") + "/" + suffix + ".txt"
            raw = (row["title"] + "\n\n" + row["text"] + "\n").encode("utf-8")
            archive.writestr(name, raw)
            chapter_meta.append({"number": row["number"], "title": row["title"],
                                 "file": name, "sha256": sha(raw),
                                 "bytes": len(raw), "source_url": row["source_url"]})
        combined_raw = combined.encode("utf-8")
        archive.writestr("combined.txt", combined_raw)
        manifest = {"title": TITLE, "author": AUTHOR, "source_index": INDEX,
                    "source_method": method, "original_zip_sha256": sha(original_zip) if original_zip else None,
                    "original_download_url": original_url,
                    "catalog_entries_reported": CATALOG_ENTRIES,
                    "numbered_chapters_verified": NUMBERED,
                    "extras_individually_verified": True,
                    "extras_verified": sum(r["number"] is None for r in records),
                    "exported_records": len(records),
                    "combined_sha256": sha(combined_raw),
                    "rights_confirmed": True,
                    "verified_utc": datetime.now(timezone.utc).isoformat(),
                    "chapters": chapter_meta}
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    if original_zip is not None:
        (out / "original-official-download.zip").write_bytes(original_zip)
    with ZipFile(target) as archive:
        if archive.testzip() is not None or len(archive.namelist()) != len(records) + 2:
            raise ValueError("Output ZIP CRC or file count mismatch")
        if sha(archive.read("combined.txt")) != manifest["combined_sha256"]:
            raise ValueError("Combined TXT SHA256 mismatch")
        for row in chapter_meta:
            if sha(archive.read(row["file"])) != row["sha256"]:
                raise ValueError("Chapter TXT SHA256 mismatch")
    return target, manifest


def selftest():
    base = "".join("第%d章 測試%d\n%s\n" % (n, n, ("這是完整的測試正文%d。" % n) * 40)
                   for n in (1, 2, 3))
    fixture = ("------章節內容開始-------\n"
               + "二戰風雲\n" + "這是開場的獨立正文。" * 40 + "\n" + base
               + "變種人時代\n" + "這是另一段獨立正文。" * 40 + "\n=已完結=\n網站字樣")
    records = split_txt(fixture, 3, 2)
    assert [r["number"] for r in records] == [None, 1, 2, 3, None]
    assert [r["title"] for r in records if r["number"] is None] == ["二戰風雲", "變種人時代"]
    assert "網站字樣" not in records[-1]["text"]
    try:
        split_txt(fixture.replace("第2章", "第4章"), 3, 2)
    except ValueError:
        pass
    else:
        raise AssertionError("Missing chapter was accepted")
    try:
        split_txt(fixture.replace("變種人時代\n", ""), 3, 2)
    except ValueError:
        pass
    else:
        raise AssertionError("Missing extra entry was accepted")
    title, body = chapter_body("<h1>第1章 例子</h1><article><p>" + "測試正文" * 40 + "</p></article>", "第1章 例子")
    assert title == "第1章 例子" and len(CJK.findall(body)) >= 100
    with TemporaryDirectory() as d:
        combined = "\n\n".join(r["title"] + "\n\n" + r["text"] for r in records)
        output, manifest = package(records, combined, None, None, Path(d), "chapter_pages")
        with ZipFile(output) as z:
            assert z.testzip() is None and manifest["exported_records"] == 5
            assert "extras/0001.txt" in z.namelist()
            assert "extras/0005.txt" in z.namelist()
    print("IXDZS_218645_OFFLINE_SELFTEST_PASS")

def main():
    arg = argparse.ArgumentParser()
    arg.add_argument("--rights-confirmed", action="store_true")
    arg.add_argument("--out", type=Path, default=Path("out/authorized-ixdzs-218645"))
    arg.add_argument("--delay", type=float, default=2.0)
    arg.add_argument("--selftest", action="store_true")
    args = arg.parse_args()
    if args.selftest:
        selftest()
        return
    if not args.rights_confirmed:
        arg.error("Full-text reproduction permission must be explicitly confirmed")
    if args.delay < 2:
        arg.error("Delay must be at least 2 seconds")
    args.out.mkdir(parents=True, exist_ok=True)
    status = {"source": INDEX, "rights_confirmed": True, "complete": False,
              "timestamp_utc": datetime.now(timezone.utc).isoformat()}
    session = requests.Session()
    session.headers["User-Agent"] = UA
    try:
        try:
            records, text, raw_zip, original_url = official_zip(session)
            method = "official_zip"
        except Unavailable as exc:
            print(f"OFFICIAL_ZIP_UNAVAILABLE: {exc}; checking permitted page fallback", flush=True)
            records, text, raw_zip, original_url = collect_pages(session, args.delay)
            method = "chapter_pages"
        archive, manifest = package(records, text, raw_zip, original_url, args.out, method)
        status.update({"complete": True, "method": method, "verified_numbered": NUMBERED,
                       "entries": len(records), "archive": archive.name,
                       "archive_sha256": sha(archive.read_bytes()),
                       "archive_bytes": archive.stat().st_size,
                       "extras_individually_verified": manifest["extras_individually_verified"]})
        print("EXPORT_COMPLETE", json.dumps(status, ensure_ascii=False), flush=True)
    except Exception as exc:
        status.update({"error": str(exc)[:500], "error_type": type(exc).__name__})
        print("EXPORT_FAILED", json.dumps(status, ensure_ascii=False), flush=True)
        raise
    finally:
        (args.out / "status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", "utf-8")


if __name__ == "__main__":
    main()
