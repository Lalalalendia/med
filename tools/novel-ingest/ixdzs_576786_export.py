#!/usr/bin/env python3
"""Authorized, checked export of all 242 chapters of IXDZS book 576786.

Prefer the site's own ZIP download; fall back to individual public chapter
pages only when the archive is unavailable and robots policy permits it.
Do not bypass authentication, CAPTCHA, anti-bot checks or rate limits.
Novel prose is written only to ignored out/ and a temporary Actions artifact.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser
from zipfile import ZIP_DEFLATED, ZipFile

import requests
from bs4 import BeautifulSoup

BOOK = "576786"
TOTAL = 242
INDEX = f"https://ixdzs8.com/read/{BOOK}/"
DOWNLOAD = f"https://down7.ixdzs8.com/{BOOK}.zip"
USER_AGENT = "MedAuthorizedBookExport/1.0 (+https://github.com/Lalalalendia/med)"
HEAD = re.compile(r"^\ufeff?\s*第\s*(\d{1,3})\s*章[^\r\n]{0,100}\s*$", re.M)
PAGE = re.compile(rf"^/read/{BOOK}/p(\d+)\.html$")
CHINESE = re.compile(r"[\u3400-\u9fff]")
CHALLENGE = ("captcha", "cloudflare", "verify you are human", "just a moment",
             "access denied", "正在验证", "安全驗證", "人機驗證")
ROOTS = ("article", "#content", "#chaptercontent", "#txtcontent",
         ".chapter-content", ".read-content", "#chapter", "#read-content")


class NotAvailable(Exception):
    pass


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def valid_host(response: requests.Response, hosts: set[str], path: str | None = None):
    parsed = urlparse(response.url)
    if parsed.scheme != "https" or parsed.netloc.lower() not in hosts:
        raise ValueError(f"Untrusted download redirect: {response.url}")
    if path and parsed.path != path:
        raise ValueError(f"Unexpected source path: {response.url}")


def get(session: requests.Session, url: str, hosts: set[str], *, timeout=30):
    try:
        response = session.get(url, timeout=(10, timeout), stream=True)
    except requests.RequestException as exc:
        raise NotAvailable(f"Unable to fetch {url}: {type(exc).__name__}") from exc
    if response.status_code in (403, 429, 503):
        response.close()
        raise RuntimeError(f"Access restricted at {url} (HTTP {response.status_code}); stopping")
    if response.status_code != 200:
        code = response.status_code
        response.close()
        raise NotAvailable(f"HTTP {code} at {url}")
    valid_host(response, hosts)
    return response


def archive_source(session: requests.Session) -> tuple[bytes, list[dict]]:
    response = get(session, DOWNLOAD, {"down7.ixdzs8.com"}, timeout=100)
    buf = io.BytesIO()
    try:
        for chunk in response.iter_content(chunk_size=131072):
            if chunk:
                buf.write(chunk)
                if buf.tell() > 50 * 1024 * 1024:
                    raise ValueError("Official ZIP exceeded 50 MiB")
    finally:
        response.close()
    raw = buf.getvalue()
    if not raw.startswith(b"PK"):
        raise NotAvailable("Official download is not a ZIP file")
    with ZipFile(io.BytesIO(raw)) as archive:
        if archive.testzip() is not None:
            raise ValueError("Official ZIP failed its CRC check")
        entries = [x for x in archive.infolist()
                   if not x.is_dir() and x.filename.lower().endswith((".txt", ".text"))]
        if not entries:
            raise NotAvailable("Official ZIP contains no TXT entries")
        if sum(item.file_size for item in entries) > 80 * 1024 * 1024:
            raise ValueError("Official ZIP expands beyond 80 MiB")
        parts = [decode_text(archive.read(entry)) for entry in entries]
    # Most downloads contain one combined text. Multiple TXT entries are also
    # supported, but no chapter is silently accepted unless numbered 1..242.
    combined = "\n\n".join(parts)
    records = split_text(combined, TOTAL)
    return raw, records


def decode_text(value: bytes) -> str:
    for codec in ("utf-8-sig", "gb18030", "big5"):
        try:
            decoded = value.decode(codec)
        except UnicodeDecodeError:
            continue
        if len(CHINESE.findall(decoded)) > 200:
            return decoded.replace("\r\n", "\n").replace("\r", "\n")
    raise ValueError("TXT is unreadable Chinese text (UTF-8/GB18030/Big5)")


def split_text(content: str, expected: int = TOTAL) -> list[dict]:
    matches = list(HEAD.finditer(content))
    records = []
    for index, match in enumerate(matches):
        number = int(match.group(1))
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
        body = content[start:end].strip()
        title = match.group(0).strip()
        if len(CHINESE.findall(body)) < 200:
            raise ValueError(f"Empty or truncated chapter {number}: only {len(CHINESE.findall(body))} CJK")
        records.append({"number": number, "title": title, "text": body})
    validate(records, expected)
    return records


def validate(records: list[dict], expected: int = TOTAL):
    observed = [r["number"] for r in records]
    wanted = list(range(1, expected + 1))
    if observed != wanted:
        missing = sorted(set(wanted) - set(observed))
        duplicated = sorted({x for x in observed if observed.count(x) > 1})
        raise ValueError(
            f"Expected chapters 1-{expected} in order, got {len(observed)}; "
            f"missing={missing[:30]}, repeated={duplicated[:30]}, first={observed[:8]}, last={observed[-8:]}"
        )
    hashes = [digest(r["text"].encode("utf-8")) for r in records]
    if len(hashes) != len(set(hashes)):
        raise ValueError("Duplicate chapter bodies found")


def robots_permit(session: requests.Session) -> RobotFileParser:
    response = get(session, "https://ixdzs8.com/robots.txt", {"ixdzs8.com"})
    try:
        content = response.text
    finally:
        response.close()
    if "user-agent:" not in content.lower():
        raise RuntimeError("Cannot verify source robots.txt: refusing chapter scrape")
    robots = RobotFileParser()
    robots.parse(content.splitlines())
    if not robots.can_fetch(USER_AGENT, INDEX):
        raise RuntimeError("robots.txt disallows book index: refusing chapter scrape")
    return robots


def chapter_source(session: requests.Session, delay: float) -> list[dict]:
    robots = robots_permit(session)
    # Check chapter count from index before requesting individual chapters.
    index_resp = get(session, INDEX, {"ixdzs8.com"})
    try:
        valid_host(index_resp, {"ixdzs8.com"}, f"/read/{BOOK}/")
        index_html = index_resp.text
    finally:
        index_resp.close()
    soup = BeautifulSoup(index_html, "html.parser")
    index_headings = [int(m.group(1)) for a in soup.select("a[href]")
                      if (m := HEAD.search(a.get_text(" ", strip=True)))]
    if TOTAL not in index_headings or 1 not in index_headings:
        raise RuntimeError("Cannot verify first and last chapters in catalog")
    chapters = []
    for number in range(1, TOTAL + 1):
        url = f"{INDEX}p{number}.html"
        if not robots.can_fetch(USER_AGENT, url):
            raise RuntimeError(f"robots.txt disallows chapter {number}")
        time.sleep(delay)
        response = get(session, url, {"ixdzs8.com"})
        try:
            valid_host(response, {"ixdzs8.com"}, f"/read/{BOOK}/p{number}.html")
            title, body = parse_page(response.text, number)
        finally:
            response.close()
        chapters.append({"number": number, "title": title, "text": body})
        print(f"CHAPTER {number}/{TOTAL}: {len(CHINESE.findall(body))} CJK", flush=True)
    validate(chapters)
    return chapters


def parse_page(html: str, number: int) -> tuple[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    title_el = soup.select_one("h1") or soup.title
    title = title_el.get_text(" ", strip=True) if title_el else ""
    if any(token in title.lower() for token in CHALLENGE):
        raise ValueError(f"Challenge at chapter {number}")
    chapter_match = re.search(r"第\s*(\d{1,3})\s*章", title)
    if not chapter_match or int(chapter_match.group(1)) != number:
        raise ValueError(f"Chapter title mismatch at p{number}: {title[:90]}")
    candidates = [soup.select_one(selector) for selector in ROOTS]
    candidates = [node for node in candidates if node]
    if not candidates:
        raise ValueError(f"No prose container at p{number}")
    root = max(candidates, key=lambda node: len(node.get_text(" ", strip=True)))
    for unwanted in root.select("script,style,nav,form,iframe,footer,header,aside"):
        unwanted.decompose()
    body = "\n\n".join(s for s in root.stripped_strings if s.strip())
    cjk_count = len(CHINESE.findall(body))
    if cjk_count < 200:
        raise ValueError(f"Truncated chapter p{number}, only {cjk_count} CJK")
    return title, body


def write_archive(records: list[dict], outdir: Path, source: str, source_sha: str | None):
    validate(records)
    outdir.mkdir(parents=True, exist_ok=True)
    path = outdir / f"ixdzs-{BOOK}-1-{TOTAL}-cn.zip"
    chapter_info = []
    combined = []
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        for chapter in records:
            number = chapter["number"]
            content = f'{chapter["title"]}\n\n{chapter["text"]}\n'
            chapter_bytes = content.encode("utf-8")
            filename = f"chapters/{number:04d}.txt"
            archive.writestr(filename, chapter_bytes)
            combined.append(content)
            chapter_info.append({
                "number": number, "title": chapter["title"],
                "file": filename, "bytes": len(chapter_bytes),
                "cjk_chars": len(CHINESE.findall(chapter["text"])),
                "sha256": digest(chapter_bytes),
                "source_url": f"{INDEX}p{number}.html",
            })
        complete = "\n\n".join(combined).encode("utf-8")
        archive.writestr("combined.txt", complete)
        manifest = {
            "title": "一个老父亲在漫威的悠闲生活",
            "author": "暮沉", "source_index": INDEX,
            "source_method": source, "source_zip_sha256": source_sha,
            "first": 1, "last": TOTAL, "chapters_count": len(records),
            "combined_sha256": digest(complete),
            "verified_utc": datetime.now(timezone.utc).isoformat(),
            "rights_confirmed": True, "chapters": chapter_info,
        }
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    with ZipFile(path) as archive:
        if archive.testzip() is not None:
            raise ValueError("Generated ZIP CRC validation failed")
        if len(archive.namelist()) != TOTAL + 2:
            raise ValueError("Generated ZIP file count mismatch")
        if digest(archive.read("combined.txt")) != manifest["combined_sha256"]:
            raise ValueError("combined.txt checksum mismatch")
        for item in chapter_info:
            if digest(archive.read(item["file"])) != item["sha256"]:
                raise ValueError("Chapter checksum mismatch")
    return path, manifest


def selftest():
    fixture = "".join(f"第{n}章 标题{n}\n" + ("这是完整的测试文字。" * 38) + "\n" for n in range(1, 4))
    records = split_text(fixture, expected=3)
    assert [r["number"] for r in records] == [1, 2, 3]
    try:
        split_text(fixture.replace("第2章", "第4章"), expected=3)
    except ValueError:
        pass
    else:
        raise AssertionError("Missing chapter went undetected")
    page = "<h1>第1章 治病</h1><article><p>" + "这是测试内容" * 60 + "</p></article>"
    t, body = parse_page(page, 1)
    assert "第1章" in t and "测试内容" in body
    try:
        parse_page(page, 2)
    except ValueError:
        pass
    else:
        raise AssertionError("Heading mismatch went undetected")
    with TemporaryDirectory() as folder:
        old_total = globals()["TOTAL"]
        globals()["TOTAL"] = 3
        try:
            result, metadata = write_archive(records, Path(folder), "test", None)
            assert metadata["chapters_count"] == 3
            with ZipFile(result) as z:
                assert "combined.txt" in z.namelist() and z.testzip() is None
        finally:
            globals()["TOTAL"] = old_total
    print("OFFLINE_SELFTEST_PASS")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rights-confirmed", action="store_true")
    parser.add_argument("--out", type=Path, default=Path("out/authorized-ixdzs-576786"))
    parser.add_argument("--delay", type=float, default=2.0)
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        selftest()
        return
    if not args.rights_confirmed:
        parser.error("Explicit permission is required before copying full text")
    if args.delay < 2:
        parser.error("Delay must be at least 2 seconds")
    args.out.mkdir(parents=True, exist_ok=True)
    status = {"source": INDEX, "expected_chapters": TOTAL, "rights_confirmed": True,
              "completed": False, "utc": datetime.now(timezone.utc).isoformat()}
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    try:
        try:
            source_raw, records = archive_source(session)
            method = "official_zip"
            source_hash = digest(source_raw)
            print("OFFICIAL_ZIP_PARSED", len(records), "chapters", flush=True)
        except (NotAvailable, ValueError) as error:
            print("OFFICIAL_ZIP_NOT_USABLE", type(error).__name__, str(error)[:250], flush=True)
            records = chapter_source(session, args.delay)
            method = "public_chapter_pages"
            source_hash = None
        archive, manifest = write_archive(records, args.out, method, source_hash)
        status.update({"completed": True, "verified": True, "chapters": len(records),
                       "archive": archive.name, "archive_bytes": archive.stat().st_size,
                       "archive_sha256": digest(archive.read_bytes()),
                       "combined_sha256": manifest["combined_sha256"],
                       "source_method": method})
        print("COMPLETE_VERIFIED", json.dumps(status, ensure_ascii=False), flush=True)
    except Exception as error:
        status.update({"error_type": type(error).__name__, "error": str(error)[:500]})
        raise
    finally:
        (args.out / "status.json").write_text(
            json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
