#!/usr/bin/env python3
"""Fetch an English MTL bridge for story chapters 66..77.

Known numbering for this book:
- source position 67 = story chapter 66
- ...
- source position 78 = story chapter 77
- position 79+ belongs to another novel and must never be used

Supported public mirrors:
- wuxiaspot (preferred)
- fanmtl (fallback; currently returns 403 from GitHub Actions)

The script uses public HTTP GET only and does not bypass authentication,
CAPTCHAs, paywalls, anti-bot challenges, or other access controls.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import requests
from bs4 import BeautifulSoup


BOOK_SLUG = "american-comics-chinese-restaurant-employee-scarlet-witch"
MAX_VALID_POSITION = 78
SOURCE_TEMPLATES = {
    "wuxiaspot": "https://www.wuxiaspot.com/novel/{slug}_{position}.html",
    "fanmtl": "https://www.fanmtl.com/novel/{slug}_{position}.html",
}
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/129.0 Safari/537.36"
)

CONTENT_SELECTORS = (
    "#chapter-content",
    "#content",
    ".chapter-content",
    ".chapter_content",
    ".read-content",
    ".reading-content",
    ".content",
    ".entry-content",
    ".novel-content",
    "article",
    "main",
)

TITLE_SELECTORS = (
    ".chapter-title",
    ".chapter_title",
    "h2",
    "h1",
    ".title",
)

BLOCK_MARKERS = (
    "captcha",
    "cloudflare",
    "access denied",
    "forbidden",
    "verify you are human",
    "too many requests",
)


@dataclass
class Result:
    story_chapter: int
    source_position: int
    source_name: str
    url: str
    status: str
    http_status: int | None = None
    title: str | None = None
    chars: int = 0
    words: int = 0
    file: str | None = None
    note: str | None = None


def normalize(text: str) -> str:
    lines: list[str] = []
    previous_blank = False
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = re.sub(r"[\t\u00a0]+", " ", raw).strip()
        if not line:
            if lines and not previous_blank:
                lines.append("")
            previous_blank = True
            continue
        previous_blank = False
        lines.append(line)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines).strip()


def visible_text(node) -> str:
    for tag in node.select(
        "script, style, noscript, iframe, svg, nav, header, footer, form, button, aside"
    ):
        tag.decompose()
    return normalize(node.get_text("\n", strip=True))


def extract_title(soup: BeautifulSoup) -> str | None:
    for selector in TITLE_SELECTORS:
        node = soup.select_one(selector)
        if node:
            text = normalize(node.get_text(" ", strip=True))
            if text:
                return text[:300]
    if soup.title:
        text = normalize(soup.title.get_text(" ", strip=True))
        if text:
            return text[:300]
    return None


def extract_content(soup: BeautifulSoup) -> tuple[str, str]:
    candidates: list[tuple[int, str, str]] = []
    for selector in CONTENT_SELECTORS:
        for node in soup.select(selector):
            text = visible_text(node)
            candidates.append((len(text), selector, text))

    if candidates:
        candidates.sort(reverse=True, key=lambda x: x[0])
        length, selector, text = candidates[0]
        if length >= 500:
            return text, selector

    body = soup.body or soup
    return visible_text(body), "body-fallback"


def looks_blocked(text: str, status_code: int, final_url: str) -> str | None:
    if status_code in {401, 402, 403, 407, 429}:
        return f"HTTP {status_code}"
    lowered = text.lower()
    for marker in BLOCK_MARKERS:
        if marker in lowered and len(text) < 4000:
            return f"access marker: {marker}"
    if any(token in final_url.lower() for token in ("captcha", "login", "signin")):
        return f"redirected to access page: {final_url}"
    return None


def title_matches_story_chapter(title: str | None, story_chapter: int) -> bool:
    if not title:
        return True
    normalized = re.sub(r"\s+", " ", title).lower()
    patterns = (
        rf"\bchapter\s+{story_chapter}\b",
        rf"\b{story_chapter}\s+chapter\b",
    )
    return any(re.search(p, normalized) for p in patterns)


def fetch_one(
    session: requests.Session,
    *,
    source_name: str,
    slug: str,
    story_chapter: int,
    source_position: int,
    out_dir: Path,
    timeout: float,
) -> Result:
    if source_position > MAX_VALID_POSITION:
        return Result(
            story_chapter=story_chapter,
            source_position=source_position,
            source_name=source_name,
            url="",
            status="refused",
            note=f"position {source_position} exceeds safe boundary {MAX_VALID_POSITION}",
        )

    template = SOURCE_TEMPLATES[source_name]
    url = template.format(slug=slug, position=source_position)
    result = Result(
        story_chapter=story_chapter,
        source_position=source_position,
        source_name=source_name,
        url=url,
        status="error",
    )

    try:
        response = session.get(url, timeout=timeout, allow_redirects=True)
    except requests.RequestException as exc:
        result.note = f"network error: {exc}"
        return result

    result.http_status = response.status_code
    response.encoding = response.apparent_encoding or response.encoding or "utf-8"

    soup = BeautifulSoup(response.text, "html.parser")
    title = extract_title(soup)
    text, selector = extract_content(soup)

    result.title = title
    result.chars = len(text)
    result.words = len(re.findall(r"\b\w+\b", text))

    blocked = looks_blocked(text, response.status_code, response.url)
    if blocked:
        result.status = "blocked"
        result.note = blocked
        return result

    if response.status_code >= 400:
        result.status = "missing"
        result.note = f"HTTP {response.status_code}"
        return result

    if not title_matches_story_chapter(title, story_chapter):
        result.status = "needs_check"
        result.note = f"title does not match story chapter {story_chapter}: {title!r}"
        return result

    if len(text) < 800 or result.words < 150:
        result.status = "needs_check"
        result.note = (
            f"too little extracted text; selector={selector}; "
            f"chars={result.chars}; words={result.words}"
        )
        return result

    path = out_dir / "chapters" / f"{story_chapter:03d}.txt"
    path.parent.mkdir(parents=True, exist_ok=True)

    header = [
        f"Story chapter: {story_chapter}",
        f"Source mirror: {source_name}",
        f"Source position: {source_position}",
        f"Source: {url}",
        "Source type: English machine translation bridge; NOT Chinese RAW",
    ]
    if title:
        header.append(f"Source title: {title}")
    header.extend(["", text, ""])

    path.write_text("\n".join(header), encoding="utf-8")
    result.file = str(path.relative_to(out_dir))
    result.status = "ok"
    result.note = f"selector={selector}"
    return result


def write_outputs(results: list[Result], out_dir: Path, source_name: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    (out_dir / "manifest.jsonl").write_text(
        "".join(json.dumps(asdict(r), ensure_ascii=False) + "\n" for r in results),
        encoding="utf-8",
    )

    chunks: list[str] = []
    for r in results:
        if r.status == "ok" and r.file:
            chunks.append((out_dir / r.file).read_text(encoding="utf-8").rstrip())

    if chunks:
        (out_dir / "combined.txt").write_text(
            ("\n\n" + "=" * 72 + "\n\n").join(chunks) + "\n",
            encoding="utf-8",
        )

    counts: dict[str, int] = {}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1

    lines = [
        "# MTL bridge fetch",
        "",
        "Book: 美漫中餐馆：员工绯红女巫",
        f"Mirror: {source_name}",
        "",
        "This output is English machine translation only and must not be treated as Chinese RAW.",
        "",
        "## Mapping",
        "",
        "- source position 67 -> story chapter 66",
        "- ...",
        "- source position 78 -> story chapter 77",
        "- source position 79+ -> different novel; intentionally refused",
        "",
        "## Counts",
        "",
    ]
    for key in sorted(counts):
        lines.append(f"- {key}: {counts[key]}")

    lines.extend(["", "## Attention", ""])
    attention = [r for r in results if r.status != "ok"]
    if not attention:
        lines.append("- none")
    else:
        for r in attention:
            lines.append(
                f"- story {r.story_chapter:03d} / source {r.source_position}: "
                f"{r.status} — {r.note or ''}"
            )

    (out_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--source", choices=sorted(SOURCE_TEMPLATES), default="wuxiaspot")
    p.add_argument("--slug", default=BOOK_SLUG)
    p.add_argument("--story-start", type=int, default=66)
    p.add_argument("--story-end", type=int, default=77)
    p.add_argument("--offset", type=int, default=1)
    p.add_argument("--delay", type=float, default=1.5)
    p.add_argument("--timeout", type=float, default=20.0)
    p.add_argument("--out-dir", default="out/mtl-bridge")
    p.add_argument("--user-agent", default=DEFAULT_USER_AGENT)
    return p.parse_args()


def main() -> int:
    args = parse_args()

    if args.story_start < 1 or args.story_end < args.story_start:
        print("invalid story chapter range", file=sys.stderr)
        return 2
    if args.delay < 0.5:
        print("delay must be at least 0.5 seconds", file=sys.stderr)
        return 2

    last_position = args.story_end + args.offset
    if last_position > MAX_VALID_POSITION:
        print(
            f"refusing request: source position {last_position} exceeds "
            f"safe boundary {MAX_VALID_POSITION}",
            file=sys.stderr,
        )
        return 2

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": args.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Connection": "keep-alive",
        }
    )

    results: list[Result] = []
    for story_chapter in range(args.story_start, args.story_end + 1):
        source_position = story_chapter + args.offset
        item = fetch_one(
            session,
            source_name=args.source,
            slug=args.slug,
            story_chapter=story_chapter,
            source_position=source_position,
            out_dir=out_dir,
            timeout=args.timeout,
        )
        results.append(item)

        print(
            f"source={args.source} story={story_chapter:03d} "
            f"position={source_position} status={item.status} "
            f"http={item.http_status} words={item.words} note={item.note or ''}"
        )

        if story_chapter != args.story_end:
            time.sleep(args.delay)

    write_outputs(results, out_dir, args.source)

    ok = sum(1 for r in results if r.status == "ok")
    print(f"done: {ok}/{len(results)} bridge chapters extracted from {args.source}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
