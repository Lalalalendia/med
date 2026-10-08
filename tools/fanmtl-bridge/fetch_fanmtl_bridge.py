#!/usr/bin/env python3
"""Fetch bounded English MTL bridge chapters for explicitly identified books.

The historical 'witch' profile keeps its strict 66..77 / +1 mapping and
78-position boundary. The independent 'oa' profile covers story chapters
221..290 with exact source-number mapping and a book-identity check.

Public HTTP GET only: never bypass logins, CAPTCHAs, paywalls or rate limits.
Outputs are EN machine-translation evidence, never verified Chinese RAW.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path

import requests
from bs4 import BeautifulSoup


BOOK_SLUG = "american-comics-chinese-restaurant-employee-scarlet-witch"
MAX_VALID_POSITION = 78
SOURCE_TEMPLATES = {
    "wuxiaspot": "https://www.wuxiaspot.com/novel/{slug}_{position}.html",
    "fanmtl": "https://www.fanmtl.com/novel/{slug}_{position}.html",
    "wuxiabox": "https://www.wuxiabox.com/novel/{slug}_{position}.html",
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
    sha256: str | None = None
    file: str | None = None
    note: str | None = None


@dataclass(frozen=True)
class BookProfile:
    key: str
    cn_title: str
    slug: str
    first_chapter: int
    last_chapter: int
    offset: int
    last_source_position: int
    sources: tuple[str, ...]
    expected_series: str | None = None


BOOKS = {
    "witch": BookProfile(
        "witch", "美漫中餐馆：员工绯红女巫", BOOK_SLUG,
        66, 77, 1, MAX_VALID_POSITION, ("wuxiaspot", "fanmtl"),
    ),
    "oa": BookProfile(
        "oa", "美漫：悟性逆天，我创造OA神力",
        "american-comics-my-understanding-is-incredible-i-create-oa-magical-power",
        221, 290, 0, 290, ("wuxiabox", "fanmtl"),
        "american comics: my understanding is incredible, i create oa magical power",
    ),
}


def has_expected_series(soup: BeautifulSoup, expected: str) -> bool:
    """Require the OA book's name, not merely a plausible chapter number."""
    candidates = [
        node.get_text(" ", strip=True)
        for node in soup.select("h1, .book-title, .novel-title, .book_name")
    ]
    if soup.title:
        candidates.append(soup.title.get_text(" ", strip=True))
    for meta in soup.select('meta[property="og:title"]'):
        candidates.append(meta.get("content", ""))
    return any(
        expected in re.sub(r"\s+", " ", name).casefold()
        for name in candidates
    )


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
    max_valid_position: int = MAX_VALID_POSITION,
    expected_series: str | None = None,
) -> Result:
    if source_position > max_valid_position:
        return Result(
            story_chapter=story_chapter,
            source_position=source_position,
            source_name=source_name,
            url="",
            status="refused",
            note=f"position {source_position} exceeds safe boundary {max_valid_position}",
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

    if expected_series and not has_expected_series(soup, expected_series):
        result.status = "needs_check"
        result.note = "book identity missing or mismatched; chapter not saved"
        return result

    if expected_series and not title:
        result.status = "needs_check"
        result.note = "chapter title missing; chapter not saved"
        return result

    if not title_matches_story_chapter(title, story_chapter):
        result.status = "needs_check"
        result.note = f"title does not match story chapter {story_chapter}: {title!r}"
        return result

    if len(text) < 800 or result.words < 150 or (expected_series and selector == "body-fallback"):
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
    result.sha256 = sha256(text.encode("utf-8")).hexdigest()
    result.file = str(path.relative_to(out_dir))
    result.status = "ok"
    result.note = f"selector={selector}"
    return result


def write_outputs(results: list[Result], out_dir: Path, source_name: str, book: BookProfile) -> None:
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
        f"Book: {book.cn_title}",
        f"Mirror: {source_name}",
        "",
        "This output is English machine translation only and must not be treated as Chinese RAW.",
        "",
        "## Mapping",
        "",
        f"- mapping: source_position = story_chapter + ({book.offset})",
        f"- allowed story chapters: {book.first_chapter}..{book.last_chapter}",
        f"- highest safe source position: {book.last_source_position}",
        f"- expected series: {book.expected_series or 'historical profile'}",
        "",
        "## Counts",
        "",
    ]
    for key in sorted(counts):
        lines.append(f"- {key}: {counts[key]}")

    lines.extend(["", "## Extracted chapter proofs", ""])
    for r in results:
        if r.status == "ok":
            lines.append(
                f"- chapter {r.story_chapter}: words={r.words}, "
                f"sha256={r.sha256}, url={r.url}"
            )

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
    p.add_argument("--book", choices=sorted(BOOKS), default="witch")
    p.add_argument("--source", choices=sorted(SOURCE_TEMPLATES), default=None)
    p.add_argument("--slug", default=None)
    p.add_argument("--story-start", type=int, default=None)
    p.add_argument("--story-end", type=int, default=None)
    p.add_argument("--offset", type=int, default=None)
    p.add_argument("--delay", type=float, default=1.5)
    p.add_argument("--timeout", type=float, default=20.0)
    p.add_argument("--out-dir", default="out/mtl-bridge")
    p.add_argument("--user-agent", default=DEFAULT_USER_AGENT)
    p.add_argument(
        "--strict", action="store_true",
        help="Fail unless every requested chapter has passed all checks",
    )
    return p.parse_args()


def resolve_request(args: argparse.Namespace) -> tuple[BookProfile, str, int, int]:
    book = BOOKS[args.book]
    source = args.source or book.sources[0]
    start = args.story_start if args.story_start is not None else book.first_chapter
    default_end = min(start + 4, book.last_chapter) if book.key == "oa" else book.last_chapter
    end = args.story_end if args.story_end is not None else default_end
    offset = args.offset if args.offset is not None else book.offset
    slug = args.slug or book.slug

    if source not in book.sources:
        raise ValueError(f"source {source} is not permitted for {book.key}")
    if slug != book.slug:
        raise ValueError("slug differs from the registered book identity")
    if offset != book.offset:
        raise ValueError(
            f"unsafe chapter offset {offset}: {book.key} requires {book.offset}"
        )
    if not (book.first_chapter <= start <= end <= book.last_chapter):
        raise ValueError(
            f"invalid story range {start}..{end}; "
            f"{book.key} permits {book.first_chapter}..{book.last_chapter}"
        )
    if end + offset > book.last_source_position:
        raise ValueError("requested source position exceeds verified book boundary")
    if book.key == "oa" and end - start + 1 > 10:
        raise ValueError("OA bridge accepts at most 10 chapters per run")
    return book, source, start, end


def main() -> int:
    args = parse_args()
    try:
        book, source, start, end = resolve_request(args)
    except ValueError as exc:
        print(f"refusing request: {exc}", file=sys.stderr)
        return 2

    if args.delay < 0.5:
        print("delay must be at least 0.5 seconds", file=sys.stderr)
        return 2
    if args.timeout <= 0:
        print("timeout must be positive", file=sys.stderr)
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
    for story_chapter in range(start, end + 1):
        source_position = story_chapter + book.offset
        item = fetch_one(
            session,
            source_name=source,
            slug=book.slug,
            story_chapter=story_chapter,
            source_position=source_position,
            out_dir=out_dir,
            timeout=args.timeout,
            max_valid_position=book.last_source_position,
            expected_series=book.expected_series,
        )
        results.append(item)

        print(
            f"book={book.key} source={source} story={story_chapter:03d} "
            f"position={source_position} status={item.status} "
            f"http={item.http_status} words={item.words} note={item.note or ''}"
        )

        if story_chapter != end:
            time.sleep(args.delay)

    write_outputs(results, out_dir, source, book)

    ok = sum(1 for r in results if r.status == "ok")
    print(f"done: {ok}/{len(results)} EN/MTL chapters extracted from {source}")
    if args.strict and ok != len(results):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
