#!/usr/bin/env python3
"""Fetch publicly accessible Faloo chapter pages without authentication or paywall bypass.

The script intentionally:
- uses only normal HTTP GET requests;
- sends no cookies, credentials, tokens, or browser automation;
- does not attempt to defeat anti-bot challenges;
- marks inaccessible/login/VIP/paywalled pages as blocked;
- writes only chapters that are visible in the returned public HTML.

Example:
    python tools/faloo-public/fetch_public_chapters.py \
        --book-id 1046066 --start 1 --end 77 --out-dir out/faloo
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

import requests
from bs4 import BeautifulSoup


DEFAULT_URL_TEMPLATE = "https://wap.faloo.com/{book_id}_{chapter}.html"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/129.0 Safari/537.36"
)

CONTENT_SELECTORS = (
    "#content",
    "#chapter-content",
    ".chapter-content",
    ".read-content",
    ".novel-content",
    ".noveContent",
    ".novel_content",
    ".content_detail",
    "article",
)

TITLE_SELECTORS = (
    "h1",
    ".chapter-title",
    ".chapter_title",
    ".novel-title",
    ".title",
)

BLOCK_MARKERS = (
    "VIP章节",
    "VIP章節",
    "请登录",
    "請登錄",
    "登录后",
    "登錄後",
    "订阅本章",
    "訂閱本章",
    "购买本章",
    "購買本章",
    "充值",
    "付费",
    "付費",
    "权限不足",
    "權限不足",
    "访问过于频繁",
    "訪問過於頻繁",
    "安全验证",
    "安全驗證",
    "验证码",
    "驗證碼",
)

NOISE_LINE_PATTERNS = (
    r"^上一章$",
    r"^下一章$",
    r"^返回目录$",
    r"^返回目錄$",
    r"^章节目录$",
    r"^章節目錄$",
    r"^加入书架$",
    r"^加入書架$",
    r"^推荐本书$",
    r"^推薦本書$",
    r"^手机阅读$",
    r"^手機閱讀$",
    r"^下载APP$",
    r"^下載APP$",
)
NOISE_RE = re.compile("|".join(f"(?:{p})" for p in NOISE_LINE_PATTERNS), re.I)


@dataclass
class ChapterResult:
    chapter: int
    url: str
    status: str
    http_status: int | None = None
    title: str | None = None
    chars: int = 0
    cjk_chars: int = 0
    file: str | None = None
    html_file: str | None = None
    note: str | None = None


def cjk_count(text: str) -> int:
    return len(re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]", text))


def normalize_text(text: str) -> str:
    lines: list[str] = []
    previous_blank = False

    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = re.sub(r"[\t\u00a0\u3000]+", " ", raw).strip()
        if not line:
            if not previous_blank and lines:
                lines.append("")
            previous_blank = True
            continue

        previous_blank = False
        if NOISE_RE.match(line):
            continue
        lines.append(line)

    while lines and not lines[-1]:
        lines.pop()

    return "\n".join(lines).strip()


def visible_text(node) -> str:
    for tag in node.select(
        "script, style, noscript, iframe, svg, nav, header, footer, form, button"
    ):
        tag.decompose()
    return normalize_text(node.get_text("\n", strip=True))


def extract_title(soup: BeautifulSoup) -> str | None:
    for selector in TITLE_SELECTORS:
        node = soup.select_one(selector)
        if node:
            text = normalize_text(node.get_text(" ", strip=True))
            if text:
                return text[:300]

    if soup.title:
        text = normalize_text(soup.title.get_text(" ", strip=True))
        if text:
            return text[:300]
    return None


def extract_content(soup: BeautifulSoup) -> tuple[str, str]:
    candidates: list[tuple[int, int, str, str]] = []

    for selector in CONTENT_SELECTORS:
        for node in soup.select(selector):
            text = visible_text(node)
            candidates.append((cjk_count(text), len(text), selector, text))

    if candidates:
        candidates.sort(reverse=True, key=lambda item: (item[0], item[1]))
        best = candidates[0]
        if best[0] >= 120:
            return best[3], best[2]

    body = soup.body or soup
    body_text = visible_text(body)
    return body_text, "body-fallback"


def looks_blocked(text: str, response_url: str, status_code: int) -> str | None:
    if status_code in {401, 402, 403, 407, 429}:
        return f"HTTP {status_code}"

    lowered_url = response_url.lower()
    if any(token in lowered_url for token in ("login", "signin", "passport", "captcha")):
        return f"redirected to access page: {response_url}"

    hits = [marker for marker in BLOCK_MARKERS if marker in text]
    if hits and cjk_count(text) < 500:
        return "access marker(s): " + ", ".join(hits[:4])

    return None


def fetch_one(
    session: requests.Session,
    *,
    book_id: str,
    chapter: int,
    url_template: str,
    out_dir: Path,
    save_html: bool,
    timeout: float,
) -> ChapterResult:
    url = url_template.format(book_id=book_id, chapter=chapter)
    result = ChapterResult(chapter=chapter, url=url, status="error")

    try:
        response = session.get(url, timeout=timeout, allow_redirects=True)
    except requests.RequestException as exc:
        result.note = f"network error: {exc}"
        return result

    result.http_status = response.status_code

    if response.status_code >= 500:
        result.note = f"server error HTTP {response.status_code}"
        return result

    response.encoding = response.apparent_encoding or response.encoding or "utf-8"
    html = response.text

    html_path: Path | None = None
    if save_html:
        html_path = out_dir / "html" / f"{chapter:03d}.html"
        html_path.parent.mkdir(parents=True, exist_ok=True)
        html_path.write_text(html, encoding="utf-8")
        result.html_file = str(html_path.relative_to(out_dir))

    soup = BeautifulSoup(html, "html.parser")
    title = extract_title(soup)
    text, selector = extract_content(soup)

    result.title = title
    result.chars = len(text)
    result.cjk_chars = cjk_count(text)

    blocked = looks_blocked(text, response.url, response.status_code)
    if blocked:
        result.status = "blocked"
        result.note = blocked
        return result

    if response.status_code >= 400:
        result.status = "missing"
        result.note = f"HTTP {response.status_code}"
        return result

    if result.cjk_chars < 120 or len(text) < 300:
        result.status = "needs_check"
        result.note = (
            f"too little extracted text; selector={selector}; "
            f"chars={len(text)} cjk={result.cjk_chars}"
        )
        return result

    chapter_path = out_dir / "chapters" / f"{chapter:03d}.txt"
    chapter_path.parent.mkdir(parents=True, exist_ok=True)

    header = [
        f"Chapter: {chapter}",
        f"Source: {url}",
    ]
    if title:
        header.append(f"Title: {title}")
    header.extend(["", text, ""])

    chapter_path.write_text("\n".join(header), encoding="utf-8")
    result.file = str(chapter_path.relative_to(out_dir))
    result.status = "ok"
    result.note = f"selector={selector}"
    return result


def build_combined(results: Iterable[ChapterResult], out_dir: Path) -> None:
    chunks: list[str] = []
    for item in results:
        if item.status != "ok" or not item.file:
            continue
        path = out_dir / item.file
        chunks.append(path.read_text(encoding="utf-8").rstrip())

    if chunks:
        (out_dir / "combined.txt").write_text(
            "\n\n" + ("\n\n" + "=" * 72 + "\n\n").join(chunks) + "\n",
            encoding="utf-8",
        )


def write_reports(results: list[ChapterResult], out_dir: Path) -> None:
    manifest = out_dir / "manifest.jsonl"
    manifest.write_text(
        "".join(json.dumps(asdict(item), ensure_ascii=False) + "\n" for item in results),
        encoding="utf-8",
    )

    counts: dict[str, int] = {}
    for item in results:
        counts[item.status] = counts.get(item.status, 0) + 1

    lines = [
        "# Faloo public chapter fetch",
        "",
        "This run used public HTTP GET requests only. No authentication, cookies,",
        "paywall bypass, CAPTCHA solving, or anti-bot circumvention was attempted.",
        "",
        "## Result counts",
        "",
    ]
    for key in sorted(counts):
        lines.append(f"- {key}: {counts[key]}")

    lines.extend(["", "## Chapters requiring attention", ""])
    attention = [r for r in results if r.status != "ok"]
    if not attention:
        lines.append("- none")
    else:
        for item in attention:
            note = item.note or ""
            lines.append(
                f"- {item.chapter:03d}: {item.status}"
                f" (HTTP {item.http_status if item.http_status is not None else 'n/a'})"
                f" — {note}"
            )

    (out_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--book-id", required=True)
    parser.add_argument("--start", type=int, default=1)
    parser.add_argument("--end", type=int, default=77)
    parser.add_argument("--out-dir", default="out/faloo")
    parser.add_argument("--url-template", default=DEFAULT_URL_TEMPLATE)
    parser.add_argument("--delay", type=float, default=2.0)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--save-html", action="store_true")
    parser.add_argument("--user-agent", default=DEFAULT_USER_AGENT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.start < 1 or args.end < args.start:
        print("invalid chapter range", file=sys.stderr)
        return 2
    if args.end - args.start + 1 > 300:
        print("refusing ranges larger than 300 chapters", file=sys.stderr)
        return 2
    if args.delay < 0.5:
        print("delay must be at least 0.5 seconds", file=sys.stderr)
        return 2

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": args.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6",
            "Connection": "keep-alive",
        }
    )

    results: list[ChapterResult] = []
    for chapter in range(args.start, args.end + 1):
        item = fetch_one(
            session,
            book_id=args.book_id,
            chapter=chapter,
            url_template=args.url_template,
            out_dir=out_dir,
            save_html=args.save_html,
            timeout=args.timeout,
        )
        results.append(item)
        print(
            f"{chapter:03d}: {item.status} "
            f"http={item.http_status} cjk={item.cjk_chars} note={item.note or ''}"
        )

        if chapter != args.end:
            time.sleep(args.delay)

    build_combined(results, out_dir)
    write_reports(results, out_dir)

    ok = sum(1 for item in results if item.status == "ok")
    print(f"done: {ok}/{len(results)} chapters extracted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
