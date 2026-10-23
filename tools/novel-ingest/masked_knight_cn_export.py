#!/usr/bin/env python3
"""Rights-confirmed Chinese source collection for Masked Knight (变脸武士).

Uses only ordinary public pages and obeys robots.txt. No authentication,
paid-content bypass, CAPTCHA solving or browser impersonation. A full
combined TXT is produced only for 330/330 verified story chapter numbers.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import sys
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup
from chapter_coverage_census import PoliteClient, parse_han_number

TITLE = "变脸武士"
EXPECTED = 330
SOURCES = (
    ("piaotia", "https://www.piaotia.com/html/0/387/index.html",
     r"^/html/0/387/\d+\.html$"),
    ("69shuba", "https://www.69shuba.com/book/15103/",
     r"^/txt/15103/[0-9]+(?:\.html)?$"),
)
NUM_RE = re.compile(r"第\s*([零〇一二三四五六七八九十百千两兩0-9]{1,15})\s*章")
BLOCK_RE = re.compile(
    r"verify you are human|checking your browser|captcha|just a moment|"
    r"access denied|正在验证浏览器|正在驗證瀏覽器|请输入验证码|请先登录|"
    r"需要购买本章|请充值阅读", re.I)
BODY_SELECTORS = (
    "#content", "#chaptercontent", "#chapter-content", "#article",
    "#txt", "#TextContent", ".read-content", ".chapter-content",
    ".novel-content", ".article-content", "article", ".content",
)


def chapter_number(label: str) -> int | None:
    match = NUM_RE.search(label)
    if not match:
        return None
    value = match.group(1).replace("兩", "二").replace("两", "二")
    return int(value) if value.isdecimal() else parse_han_number(value)


def index_rows(index_url: str, chapter_pattern: str, html: str,
               expected: int = EXPECTED) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    home = urlsplit(index_url)
    found: dict[int, dict] = {}
    collisions = []
    for anchor in soup.select("a[href]"):
        label = re.sub(r"\s+", " ", anchor.get_text(" ", strip=True))
        number = chapter_number(label)
        if number is None or not 1 <= number <= expected:
            continue
        target_url = urljoin(index_url, anchor["href"]).split("#", 1)[0]
        parsed = urlsplit(target_url)
        if (parsed.scheme != "https" or parsed.hostname != home.hostname
                or parsed.port not in (None, 443) or parsed.query
                or not re.fullmatch(chapter_pattern, parsed.path)):
            continue
        row = {"ordinal": number, "title": label, "url": target_url}
        if number in found and found[number]["url"] != target_url:
            collisions.append({"ordinal": number,
                               "urls": [found[number]["url"], target_url]})
        else:
            found[number] = row
    missing = sorted(set(range(1, expected + 1)) - set(found))
    return {"chapters": [found[n] for n in sorted(found)],
            "catalog_count": len(found), "missing": missing,
            "collisions": collisions,
            "complete": len(found) == expected and not collisions}


def chapter_body(html: str, ordinal: int) -> tuple[str, int]:
    if BLOCK_RE.search(html[:16000]):
        raise ValueError("access_or_challenge_page")
    soup = BeautifulSoup(html, "html.parser")
    title_text = soup.title.get_text(" ", strip=True) if soup.title else ""
    if TITLE not in title_text and "變臉武士" not in title_text:
        raise ValueError("book_identity_not_confirmed")
    for heading in soup.select("h1,.bookname h1"):
        number = chapter_number(heading.get_text(" ", strip=True))
        if number is not None and number != ordinal:
            raise ValueError("chapter_number_mismatch")
    for selector in BODY_SELECTORS:
        node = soup.select_one(selector)
        if not node:
            continue
        for bad in node.select(
                "script,style,noscript,iframe,svg,nav,header,footer,aside,"
                ".chapter-nav,.advertisement,.ads,.comment,form,button"):
            bad.decompose()
        lines = [re.sub(r"[ \t\u00a0]+", " ", line).strip()
                 for line in node.get_text("\n", strip=True).splitlines()]
        text = "\n".join(line for line in lines if line).strip()
        chars = len(re.findall(r"[\u3400-\u9fff]", text))
        if chars < 180:
            continue
        if BLOCK_RE.search(text[:1500]):
            raise ValueError("blocked_story_body")
        return text + "\n", chars
    raise ValueError("no_valid_story_body_container")


def run(out: Path, delay: float, expected: int = EXPECTED) -> dict:
    if delay < 1.5:
        raise ValueError("delay must be >= 1.5")
    if out.exists() and any(out.iterdir()):
        raise ValueError("output folder must be empty")
    out.mkdir(parents=True, exist_ok=True)
    client = PoliteClient(delay)
    source_checks = []
    choice = None
    for name, index, pattern in SOURCES:
        source = {"name": name, "index": index, "status": "unverified"}
        source_checks.append(source)
        try:
            html = client.get(index)
            if TITLE not in html and "變臉武士" not in html:
                source["status"] = "identity_unverified"
                continue
            parsed = index_rows(index, pattern, html, expected)
            source.update(status="complete" if parsed["complete"] else "partial",
                          count=parsed["catalog_count"],
                          missing=parsed["missing"],
                          conflicts=parsed["collisions"])
            if parsed["complete"]:
                choice = (name, parsed["chapters"])
                break
        except Exception as exc:
            source.update(status="blocked_or_unavailable", reason=str(exc)[:220])
    rows: list[dict] = []
    verified: set[int] = set()
    seen_sha: dict[str, int] = {}
    if choice:
        name, chapters = choice
        raw = out / "raw"
        raw.mkdir()
        for ch in chapters:
            ordinal = ch["ordinal"]
            row = {"ordinal": ordinal, "title": ch["title"],
                   "url": ch["url"], "source": name, "status": "unverified"}
            try:
                html = client.get(ch["url"])
                body, cjk_chars = chapter_body(html, ordinal)
                data = body.encode("utf-8")
                digest = hashlib.sha256(data).hexdigest()
                if digest in seen_sha:
                    raise ValueError(
                        "duplicate_story_body_of_" + str(seen_sha[digest]))
                seen_sha[digest] = ordinal
                filename = f"raw/{ordinal:04d}.txt"
                (out / filename).write_bytes(data)
                row.update(status="ok", cjk=cjk_chars,
                           sha256=digest, raw_file=filename)
                verified.add(ordinal)
            except Exception as exc:
                row.update(status="unverified", reason=str(exc)[:220])
                rows.append(row)
                if isinstance(exc, RuntimeError):
                    # Robots, challenge, 403, 429 and network failures stop the source.
                    break
                continue
            rows.append(row)
    missing = sorted(set(range(1, expected + 1)) - verified)
    status = "PASS" if len(verified) == expected and not missing else "PARTIAL"
    if choice is None:
        status = "NO_COMPLETE_PUBLIC_CATALOG"
    result = {
        "book": TITLE, "source_language": "zh",
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "rights_confirmed": True, "expected": expected,
        "verified": len(verified), "missing": missing,
        "status": status, "source_checks": source_checks,
        "chapters": rows,
    }
    (out / "manifest.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    if status == "PASS":
        with (out / "combined_cn.txt").open("w", encoding="utf-8") as combined:
            by_number = {row["ordinal"]: row for row in rows}
            for i in range(1, expected + 1):
                entry = by_number[i]
                text = (out / entry["raw_file"]).read_text(encoding="utf-8")
                combined.write(f"第{i}章 {entry['title']}\n\n{text}\n")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rights-confirmed", action="store_true")
    parser.add_argument("--out", type=Path,
                        default=Path("out/masked-knight-cn-authorized"))
    parser.add_argument("--delay", type=float, default=2.5)
    args = parser.parse_args()
    if not args.rights_confirmed:
        print("Book-specific rights confirmation required", file=sys.stderr)
        return 2
    try:
        result = run(args.out, args.delay)
    except Exception as exc:
        print(f"CN export failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({
        "status": result["status"], "verified": result["verified"],
        "expected": result["expected"], "source_checks": result["source_checks"],
        "missing_count": len(result["missing"]),
    }, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
