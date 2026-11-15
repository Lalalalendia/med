#!/usr/bin/env python3
"""Authorized ENGSHU 4748 chapter-tail collector; full prose stays in Actions artifacts."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import zipfile
from pathlib import Path
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

BASE = "https://engshu.com"
BOOK = "让你开维修店，你掀起机战风暴？"
AUTHOR = "咸鱼翻身路"
INDEX = BASE + "/list5/4748/"
FIRST = 2600
MIN_CJK = 350
HEAD_RE = re.compile(r"第\s*(\d+)\s*章")
CHAPTER_PATH = re.compile(r"^/list5/4748/(\d+)\.html$")
CJK = re.compile(r"[\u3400-\u9fff]")
CHALLENGE = ("人机验证", "安全验证", "请输入验证码", "Cloudflare", "Access Denied")
PLACEHOLDERS = ("本章正在手打", "本章节需要付费", "请登录后阅读", "内容加载中")
SELECTORS = (
    "#content", "#chaptercontent", "#chapter-content", "#readContent",
    ".read-content", ".chapter-content", ".reading-content",
    ".content", ".txtnav", ".book-content", "article",
)


class CollectionError(RuntimeError):
    pass


def checked_url(url: str) -> None:
    p = urlparse(url)
    if p.scheme != "https" or p.hostname != "engshu.com" or not (
        p.path == "/robots.txt" or p.path == "/list5/4748/" or CHAPTER_PATH.fullmatch(p.path)
    ):
        raise CollectionError(f"Unexpected source URL: {url}")


def session_factory() -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (compatible; authorized-research-collector/1.0)",
        "Accept-Language": "zh-CN,zh;q=0.9",
    })
    return session


def get_html(session: requests.Session, url: str) -> BeautifulSoup:
    checked_url(url)
    for attempt in range(3):
        try:
            response = session.get(url, timeout=30, allow_redirects=True)
        except requests.RequestException as exc:
            if attempt == 2:
                raise CollectionError(f"Network failure at {url}: {exc}") from exc
            time.sleep(2 * (attempt + 1))
            continue
        checked_url(response.url)
        if response.status_code in (401, 403, 429):
            raise CollectionError(f"Access restricted: HTTP {response.status_code} at {url}")
        if response.status_code >= 500:
            if attempt == 2:
                raise CollectionError(f"Server HTTP {response.status_code}: {url}")
            time.sleep(2 * (attempt + 1))
            continue
        if response.status_code != 200:
            raise CollectionError(f"HTTP {response.status_code}: {url}")
        response.encoding = response.apparent_encoding if response.encoding in (None, "ISO-8859-1") else response.encoding
        if any(t in response.text[:3500] for t in CHALLENGE):
            raise CollectionError(f"Access challenge encountered at {url}")
        return BeautifulSoup(response.text, "html.parser")
    raise CollectionError(f"Unreachable: {url}")


def assert_robots(session: requests.Session) -> None:
    url = BASE + "/robots.txt"
    try:
        response = session.get(url, timeout=20, allow_redirects=True)
    except requests.RequestException as exc:
        raise CollectionError(f"Could not check robots.txt: {exc}") from exc
    checked_url(response.url)
    if response.status_code == 404:
        return
    if response.status_code != 200:
        raise CollectionError(f"robots.txt unavailable: HTTP {response.status_code}")
    robots = RobotFileParser()
    robots.parse(response.text.splitlines())
    if not robots.can_fetch(session.headers["User-Agent"], INDEX):
        raise CollectionError("Robots disallow catalog collection")
    if not robots.can_fetch(session.headers["User-Agent"], INDEX + "2600.html"):
        raise CollectionError("Robots disallow chapter collection")


def discover_latest(html: BeautifulSoup) -> int:
    page = html.get_text(" ", strip=True)
    if BOOK not in page or AUTHOR not in page:
        raise CollectionError("Index title or author does not match the requested novel")
    numbers = []
    for a in html.select("a[href]"):
        link = urlparse(a.get("href", ""))
        match = CHAPTER_PATH.fullmatch(link.path)
        if match and (not link.hostname or link.hostname == "engshu.com"):
            title_match = HEAD_RE.search(a.get_text(" ", strip=True))
            if title_match and int(title_match.group(1)) == int(match.group(1)):
                numbers.append(int(match.group(1)))
    if not numbers:
        raise CollectionError("No validated numbered chapters in catalog")
    latest = max(numbers)
    if latest < FIRST:
        raise CollectionError(f"Catalog latest {latest} is below chapter {FIRST}")
    if latest > 100000:
        raise CollectionError("Catalog ordinal is implausible")
    return latest


def count_cjk(text: str) -> int:
    return len(CJK.findall(text))


def clean_body(node) -> str:
    copy = BeautifulSoup(str(node), "html.parser")
    for element in copy.select("script, style, nav, noscript, iframe, form, .ads, .advertisement"):
        element.decompose()
    lines = []
    for original in copy.get_text("\n", strip=True).splitlines():
        line = re.sub(r"\s+", " ", original).strip()
        if not line:
            continue
        if re.fullmatch(r"(上一页|下一页|返回目录|章节目录|书页/目录|目录|加入书架|字:[大小中]+)", line):
            continue
        if re.match(r"^(请收藏|最新网址|喜欢.*请收藏|本章未完|手机用户请浏览)", line):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def extract_chapter(html: BeautifulSoup, number: int) -> tuple[str, str]:
    page_text = html.get_text(" ", strip=True)
    if BOOK not in page_text or AUTHOR not in page_text:
        raise CollectionError(f"Book or author mismatch for {number}")
    headings = [h.get_text(" ", strip=True) for h in html.select("h1")]
    candidates = [title for title in headings if (m := HEAD_RE.search(title)) and int(m.group(1)) == number]
    if not candidates:
        raise CollectionError(f"Chapter {number} missing correct numbered H1: {headings[:3]}")
    title = candidates[-1]
    # Prefer the reader's dedicated text element. Never silently take a whole index.
    bodies = []
    for selector in SELECTORS:
        for node in html.select(selector):
            text = clean_body(node)
            if count_cjk(text) >= MIN_CJK:
                bodies.append((count_cjk(text), text, selector))
        if bodies:
            break
    if not bodies:
        # Some mirrors use unlabelled wrappers: choose a large div without an H1
        # rather than a page-level container with navigation and metadata.
        for node in html.select("div"):
            if node.select_one("h1"):
                continue
            text = clean_body(node)
            cjk = count_cjk(text)
            if cjk >= MIN_CJK:
                bodies.append((cjk, text, "div-fallback"))
    if not bodies:
        raise CollectionError(f"Chapter {number} has no substantial text container")
    _, body, used_selector = max(bodies, key=lambda item: item[0])
    body = body.strip()
    if HEAD_RE.search(body[:80]) and body.startswith(title):
        body = body[len(title):].lstrip()
    if count_cjk(body) < MIN_CJK:
        raise CollectionError(f"Chapter {number} too short after cleaning")
    if any(marker in body[:400] for marker in PLACEHOLDERS):
        raise CollectionError(f"Chapter {number} is placeholder text")
    if len(body.splitlines()) < 3:
        raise CollectionError(f"Chapter {number} appears truncated (few paragraphs)")
    return title, body


def digest(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def chapter_url(n: int) -> str:
    return f"{INDEX}{n}.html"


def write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def collect(start: int, end: int, out: Path, delay: float) -> int:
    if start < FIRST or end < start or delay < 0.8:
        raise CollectionError("Invalid range or request delay")
    out.mkdir(parents=True, exist_ok=True)
    (out / "chapters").mkdir(exist_ok=True)
    session = session_factory()
    assert_robots(session)
    manifest = []
    seen = set()
    consecutive_errors = 0
    for n in range(start, end + 1):
        url = chapter_url(n)
        record = {"number": n, "url": url, "status": "error"}
        try:
            html = get_html(session, url)
            title, body = extract_chapter(html, n)
            hash_ = digest(body)
            if hash_ in seen:
                raise CollectionError("Repeated chapter body hash")
            seen.add(hash_)
            record.update(
                status="ok", title=title, cjk=count_cjk(body),
                sha256=hash_, bytes=len(body.encode("utf-8")),
            )
            (out / "chapters" / f"{n:04d}.txt").write_text(
                f"{title}\n\n{body}\n", encoding="utf-8",
            )
            consecutive_errors = 0
        except (CollectionError, requests.RequestException) as exc:
            record["error"] = str(exc)
            consecutive_errors += 1
            print(f"ERROR {n}: {exc}", flush=True)
        manifest.append(record)
        write_json(out / "manifest.json", manifest)
        print(f"{n}: {record['status']} ({record.get('cjk', 0)} CJK)", flush=True)
        if record.get("error", "").startswith(("Access restricted", "Access challenge")) or consecutive_errors >= 3:
            print("Stopping to avoid continuing against an access barrier.", flush=True)
            break
        if n < end:
            time.sleep(delay)
    (out / "summary.json").write_text(
        json.dumps({"start": start, "end": end, "ok": sum(r["status"] == "ok" for r in manifest),
                    "requested": end - start + 1}, indent=2) + "\n", encoding="utf-8"
    )
    return 0 if len(manifest) == end - start + 1 and all(r["status"] == "ok" for r in manifest) else 1


def verify(root: Path, out: Path, first: int, last: int) -> int:
    expected = set(range(first, last + 1))
    rows = []
    files = {}
    for path in root.rglob("manifest.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        for row in data:
            rows.append(row)
            file = path.parent / "chapters" / f"{int(row['number']):04d}.txt"
            if file.exists():
                files.setdefault(row["number"], []).append(file)
    counts = {}
    for row in rows:
        counts[row["number"]] = counts.get(row["number"], 0) + 1
    by_no = {row["number"]: row for row in rows}
    missing = sorted(expected - set(by_no))
    duplicate_ordinals = sorted(n for n, occurrences in counts.items() if occurrences != 1)
    errors = {n: r.get("error", "bad status") for n, r in by_no.items() if r["status"] != "ok"}
    mismatch = []
    hashes = set()
    for n in sorted(expected & set(by_no)):
        row = by_no[n]
        paths = files.get(n, [])
        if row["status"] != "ok" or len(paths) != 1:
            mismatch.append(n)
            continue
        text = paths[0].read_text(encoding="utf-8")
        title, separator, body = text.partition("\n\n")
        body = body.rstrip("\n")
        if not separator or row.get("title") != title or digest(body) != row.get("sha256") or count_cjk(body) < MIN_CJK:
            mismatch.append(n)
            continue
        if row["sha256"] in hashes:
            mismatch.append(n)
        hashes.add(row["sha256"])
    out.mkdir(parents=True, exist_ok=True)
    report = {
        "book": BOOK, "author": AUTHOR, "source": INDEX,
        "first": first, "last": last, "expected": len(expected),
        "collected_records": len(rows), "verified": len(expected) - len(set(missing + mismatch)),
        "missing": missing, "duplicate_ordinals": duplicate_ordinals,
        "mismatched": sorted(set(mismatch)), "errors": errors,
    }
    passed = (len(rows) == len(expected) and not missing and not duplicate_ordinals and not mismatch and not errors)
    report["completed"] = passed
    write_json(out / "verified.json", report)
    if not passed:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1
    write_json(out / "manifest.json", [by_no[n] for n in sorted(expected)])
    combined = "\n\n".join(files[n][0].read_text(encoding="utf-8").rstrip() for n in sorted(expected)) + "\n"
    (out / "combined.txt").write_text(combined, encoding="utf-8")
    (out / "summary.md").write_text(
        f"# Engshu 4748 collection\n\n- Range: {first}-{last}\n"
        f"- Verified: {len(expected)}/{len(expected)}\n"
        "- No missing chapters or repeated bodies\n- Authorized copying asserted by requester\n",
        encoding="utf-8",
    )
    archive = out / f"engshu-4748-{first}-{last}.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for n in sorted(expected):
            zf.write(files[n][0], arcname=f"chapters/{n:04d}.txt")
        for name in ("combined.txt", "manifest.json", "verified.json", "summary.md"):
            zf.write(out / name, arcname=name)
    print(f"PASS {len(expected)}/{len(expected)} chapters; zip={archive}", flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="action", required=True)
    d = sub.add_parser("discover")
    d.add_argument("--first", type=int, default=FIRST)
    d.add_argument("--shard-size", type=int, default=40)
    c = sub.add_parser("collect")
    c.add_argument("--start", type=int, required=True)
    c.add_argument("--end", type=int, required=True)
    c.add_argument("--delay", type=float, default=1.6)
    c.add_argument("--out", type=Path, required=True)
    v = sub.add_parser("verify")
    v.add_argument("--root", type=Path, required=True)
    v.add_argument("--out", type=Path, required=True)
    v.add_argument("--first", type=int, default=FIRST)
    v.add_argument("--last", type=int, required=True)
    args = parser.parse_args()
    if args.action == "verify":
        return verify(args.root, args.out, args.first, args.last)
    if args.action == "collect":
        return collect(args.start, args.end, args.out, args.delay)
    session = session_factory()
    assert_robots(session)
    latest = discover_latest(get_html(session, INDEX))
    matrix = {"include": [
        {"shard": f"{(n - args.first) // args.shard_size + 1:02d}", "start": n,
         "end": min(latest, n + args.shard_size - 1)}
        for n in range(args.first, latest + 1, args.shard_size)
    ]}
    print(json.dumps({"first": args.first, "last": latest, "matrix": matrix}, ensure_ascii=False))
    if "GITHUB_OUTPUT" in os.environ:
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as file:
            file.write(f"last={latest}\n")
            file.write("matrix=" + json.dumps(matrix, separators=(",", ":")) + "\n")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (CollectionError, requests.RequestException) as exc:
        print(f"COLLECTION BLOCKED: {exc}", file=sys.stderr)
        sys.exit(2)
