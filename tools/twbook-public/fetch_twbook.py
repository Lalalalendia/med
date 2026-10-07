#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

HERE = Path(__file__).resolve().parent
DEFAULT_MAPPING = HERE / "mapping.json"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0 Safari/537.36"
)
TIP_MARKERS = ("溫馨提示", "温馨提示", "VIP會員", "VIP会员")
MIN_BODY_CHARS = 300
MIN_BODY_CJK = 120


@dataclass
class ChapterResult:
    ordinal: int
    url: str
    status: str
    http_status: int | None = None
    title: str | None = None
    chars: int = 0
    cjk_chars: int = 0
    substitutions: int = 0
    unknown_total: int = 0
    unknown_unique: int = 0
    file: str | None = None
    note: str | None = None


def is_hangul(ch: str) -> bool:
    return len(ch) == 1 and "\uac00" <= ch <= "\ud7a3"


def is_cjk(ch: str) -> bool:
    return len(ch) == 1 and (
        "\u3400" <= ch <= "\u4dbf" or "\u4e00" <= ch <= "\u9fff"
    )


def load_mapping(path: Path) -> dict[str, str]:
    """Load the old bootstrap map for compatibility/diagnostics only.

    TWBook's substitutions are randomized across requests, so this map is not
    used to decode chapter bodies anymore.
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    for src, dst in raw.items():
        if len(src) != 1 or len(dst) != 1:
            raise ValueError(f"invalid mapping: {src!r} -> {dst!r}")
    return raw


def decode_text(text: str, mapping: dict[str, str]) -> tuple[str, int, Counter[str]]:
    """Legacy helper retained for tests/debugging, not used for chapter bodies."""
    substitutions = sum(text.count(ch) for ch in mapping)
    decoded = text.translate(str.maketrans(mapping))
    unknown = Counter(ch for ch in decoded if is_hangul(ch))
    return decoded, substitutions, unknown


def cjk_count(text: str) -> int:
    return len(re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]", text))


def hangul_count(text: str) -> int:
    return sum(1 for ch in text if is_hangul(ch))


def normalize_text(text: str) -> str:
    lines: list[str] = []
    previous_blank = False
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = re.sub(r"[\t\u00a0\u3000]+", " ", raw).strip()
        if not line:
            if lines and not previous_blank:
                lines.append("")
            previous_blank = True
            continue
        previous_blank = False
        if any(marker in line for marker in TIP_MARKERS):
            continue
        lines.append(line)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines).strip()


def soup_from_html(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def extract_catalog(html: str, base_url: str) -> list[tuple[str, str]]:
    soup = soup_from_html(html)
    base_path = urlparse(base_url).path.rstrip("/")
    book_id = base_path.split("/")[-2] if base_path.endswith("/dir") else base_path.split("/")[-1]
    out: list[tuple[str, str]] = []
    seen: set[str] = set()

    for a in soup.select("div.chaplist a[href], a[href]"):
        href = (a.get("href") or "").strip()
        if not href:
            continue
        url = urljoin(base_url, href)
        path = urlparse(url).path
        if not re.fullmatch(rf"/{re.escape(book_id)}/\d+(?:_\d+)*\.html", path):
            continue
        # Continuation pages have at least two underscore suffixes, e.g. 8096_1_2.
        if re.search(r"_\d+_\d+$", Path(path).stem):
            continue
        if url in seen:
            continue
        seen.add(url)
        out.append((url, normalize_text(a.get_text(" ", strip=True))))

    def chapter_number(item: tuple[str, str]) -> int:
        # URL numbering is more reliable than title text because titles can be
        # obfuscated or blank.
        stem = Path(urlparse(item[0]).path).stem
        match = re.match(r"(\d+)", stem)
        if match:
            return int(match.group(1))
        title_match = re.search(r"第\s*(\d+)\s*章", item[1])
        return int(title_match.group(1)) if title_match else 10**9

    out.sort(key=chapter_number)
    return out


def clean_content_node(node) -> str:
    clone = BeautifulSoup(str(node), "html.parser")
    for junk in clone.select(
        "script, style, noscript, iframe, svg, nav, header, footer, form, button, "
        ".adBlock, .gadBlock, ad"
    ):
        junk.decompose()
    for p in list(clone.select("p")):
        if any(marker in p.get_text(" ", strip=True) for marker in TIP_MARKERS):
            p.decompose()
    return normalize_text(clone.get_text("\n", strip=True))


def extract_title(soup: BeautifulSoup) -> str | None:
    for selector in ("div.chapter-content h1", "h1.title", "h1"):
        node = soup.select_one(selector)
        if node:
            title = normalize_text(node.get_text(" ", strip=True))
            title = re.sub(r"\s*\(\d+/\d+\)\s*$", "", title)
            if title:
                return title
    return None


def extract_content(soup: BeautifulSoup) -> str:
    node = soup.select_one("div.chapter-content div.content") or soup.select_one("div.chapter-content")
    if node is None:
        raise ValueError("chapter content node not found")
    return clean_content_node(node)


def next_part_url(soup: BeautifulSoup, current_url: str) -> str | None:
    stem = Path(urlparse(current_url).path).stem
    links = soup.select(".foot-nav a[href]")
    if not links:
        return None
    href = links[-1].get("href")
    if not href:
        return None
    nxt = urljoin(current_url, href)
    next_stem = Path(urlparse(nxt).path).stem
    if next_stem.startswith(stem + "_") and re.fullmatch(re.escape(stem) + r"_\d+", next_stem):
        return nxt
    return None


def fetch_html(
    session: requests.Session,
    url: str,
    timeout: float,
    *,
    max_attempts: int = 5,
) -> tuple[requests.Response, str]:
    """Fetch a public page, backing off on transient 429/5xx responses."""
    response: requests.Response | None = None
    for attempt in range(1, max_attempts + 1):
        response = session.get(url, timeout=timeout, allow_redirects=True)
        response.encoding = response.apparent_encoding or response.encoding or "utf-8"
        if response.status_code != 429 and response.status_code < 500:
            return response, response.text
        if attempt == max_attempts:
            return response, response.text
        retry_after = response.headers.get("Retry-After", "").strip()
        try:
            wait = float(retry_after)
        except ValueError:
            wait = min(30.0, 2.0 ** attempt)
        time.sleep(max(2.0, wait))
    assert response is not None
    return response, response.text


def body_is_plausible(text: str) -> bool:
    # Hangul substitutions are one code point each, so include them in the
    # language-character threshold before deobfuscation.
    language_chars = cjk_count(text) + hangul_count(text)
    return len(text) >= MIN_BODY_CHARS and language_chars >= MIN_BODY_CJK


def merge_renderings(renderings: list[str]) -> tuple[str, int, Counter[str]]:
    """Recover plaintext by comparing multiple randomized TWBook renderings.

    TWBook changes both *which* positions are obfuscated and which Hangul
    codepoint represents a character. Therefore a global Hangul->CJK dictionary
    is unsafe. For each position, take the non-Hangul character exposed by any
    rendering. If all renderings still contain Hangul there, leave it unresolved.
    """
    if not renderings:
        return "", 0, Counter()

    # Only compare the dominant exact length. A short anti-bot/placeholder body
    # must never be aligned against a real chapter.
    groups: dict[int, list[str]] = {}
    for text in renderings:
        groups.setdefault(len(text), []).append(text)
    best_len, variants = max(groups.items(), key=lambda kv: (len(kv[1]), kv[0]))

    out: list[str] = []
    resolved_positions = 0
    unresolved = Counter()

    for pos in range(best_len):
        chars = [text[pos] for text in variants]
        visible = {ch for ch in chars if not is_hangul(ch)}
        if len(visible) > 1:
            sample = "".join(chars)
            raise RuntimeError(
                f"rendering content conflict at position {pos}: {sample!r}"
            )
        if visible:
            chosen = next(iter(visible))
            if any(is_hangul(ch) for ch in chars):
                resolved_positions += 1
            out.append(chosen)
            continue

        # Every rendering still masks this position. Keep one sentinel Hangul so
        # fail-closed validation can request more renderings / report it.
        chosen = chars[0]
        out.append(chosen)
        unresolved[chosen] += 1

    merged = "".join(out)
    return merged, resolved_positions, unresolved


def merge_title_renderings(titles: list[str]) -> str | None:
    titles = [t for t in titles if t]
    if not titles:
        return None
    for title in titles:
        if not any(is_hangul(ch) for ch in title):
            return title
    try:
        merged, _, unresolved = merge_renderings(titles)
    except RuntimeError:
        return titles[0]
    return merged if not unresolved else titles[0]


def unknown_contexts(text: str, unknown: Counter[str], radius: int = 20) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for ch in unknown:
        snippets: list[str] = []
        start = 0
        while len(snippets) < 5:
            pos = text.find(ch, start)
            if pos < 0:
                break
            snippets.append(text[max(0, pos-radius):pos+radius+1].replace("\n", " "))
            start = pos + 1
        result[ch] = snippets
    return result


def fetch_rendering(
    session: requests.Session,
    url: str,
    timeout: float,
) -> tuple[int, str, str | None, str, str | None]:
    response, html = fetch_html(session, url, timeout)
    if response.status_code >= 400:
        return response.status_code, html, None, "", None
    soup = soup_from_html(html)
    return (
        response.status_code,
        html,
        extract_title(soup),
        extract_content(soup),
        next_part_url(soup, url),
    )


def fetch_twbook_chapter(
    session: requests.Session,
    url: str,
    ordinal: int,
    out_dir: Path,
    mapping: dict[str, str],
    timeout: float,
    save_html: bool,
    learn_attempts: int,
    max_parts: int = 8,
) -> ChapterResult:
    del mapping  # Static maps are intentionally not used for randomized bodies.

    result = ChapterResult(ordinal=ordinal, url=url, status="error")
    current = url
    visited: set[str] = set()
    parts: list[str] = []
    html_pages: list[str] = []
    all_titles: list[str] = []
    total_resolved = 0

    try:
        for _ in range(max_parts):
            if current in visited:
                raise RuntimeError(f"split-page loop at {current}")
            visited.add(current)

            renderings: list[str] = []
            raw_html_samples: list[str] = []
            next_url: str | None = None
            http_status: int | None = None

            # First obtain a plausible body. Some TWBook responses are 200 OK
            # placeholders only a few dozen characters long.
            max_fetches = max(2, learn_attempts + 3)
            for attempt in range(max_fetches):
                status, html, raw_title, raw_body, candidate_next = fetch_rendering(
                    session, current, timeout
                )
                http_status = status
                result.http_status = status

                if status >= 400:
                    result.status = "missing" if status == 404 else "error"
                    result.note = f"HTTP {status} at {current}"
                    return result

                raw_html_samples.append(html)
                if raw_title:
                    all_titles.append(raw_title)
                if candidate_next:
                    next_url = candidate_next

                if body_is_plausible(raw_body):
                    renderings.append(raw_body)
                elif attempt + 1 < max_fetches:
                    time.sleep(min(4.0, 0.75 * (attempt + 1)))

                if renderings:
                    merged, resolved, unresolved = merge_renderings(renderings)
                    if not unresolved:
                        break

                    # We have a real chapter, but still-masked positions remain.
                    # Fetch more independent renderings until every position is
                    # exposed at least once.
                    if len(renderings) < learn_attempts + 1:
                        time.sleep(0.5)
                        continue
            else:
                merged = ""

            if not renderings:
                diag = out_dir / "short" / f"{ordinal:03d}.json"
                diag.parent.mkdir(parents=True, exist_ok=True)
                diag.write_text(
                    json.dumps(
                        {
                            "chapter": ordinal,
                            "url": current,
                            "http_status": http_status,
                            "samples": [
                                {
                                    "chars": len(extract_content(soup_from_html(h)))
                                    if "chapter-content" in h
                                    else None,
                                    "text": (
                                        extract_content(soup_from_html(h))[:500]
                                        if "chapter-content" in h
                                        else ""
                                    ),
                                }
                                for h in raw_html_samples[-5:]
                            ],
                        },
                        ensure_ascii=False,
                        indent=2,
                    ) + "\n",
                    encoding="utf-8",
                )
                result.status = "needs_check"
                result.note = "no plausible chapter body after retries"
                return result

            merged, resolved, unresolved = merge_renderings(renderings)
            total_resolved += resolved
            if unresolved:
                diag = out_dir / "unresolved" / f"{ordinal:03d}.json"
                diag.parent.mkdir(parents=True, exist_ok=True)
                diag.write_text(
                    json.dumps(
                        {
                            "chapter": ordinal,
                            "url": current,
                            "renderings": len(renderings),
                            "counts": dict(unresolved),
                            "contexts": unknown_contexts(merged, unresolved),
                        },
                        ensure_ascii=False,
                        indent=2,
                    ) + "\n",
                    encoding="utf-8",
                )
                result.status = "mapping_incomplete"
                result.note = "unresolved after render consensus: " + ", ".join(
                    f"{ch}=U+{ord(ch):04X}x{count}"
                    for ch, count in unresolved.most_common()
                )
                return result

            parts.append(merged)
            if save_html:
                html_pages.extend(raw_html_samples)

            if not next_url:
                break
            current = next_url
        else:
            raise RuntimeError(f"more than {max_parts} split pages")
    except requests.RequestException as exc:
        result.note = f"network error: {exc}"
        return result
    except Exception as exc:
        result.note = f"parse error: {exc}"
        return result

    text = normalize_text("\n\n".join(parts))
    unresolved = Counter(ch for ch in text if is_hangul(ch))
    result.title = merge_title_renderings(all_titles)
    result.chars = len(text)
    result.cjk_chars = cjk_count(text)
    result.substitutions = total_resolved
    result.unknown_total = sum(unresolved.values())
    result.unknown_unique = len(unresolved)

    if save_html:
        p = out_dir / "html" / f"{ordinal:03d}.html"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("\n<!-- RENDER -->\n".join(html_pages), encoding="utf-8")

    if unresolved:
        result.status = "mapping_incomplete"
        result.note = "unexpected unresolved Hangul after merge"
        return result

    if result.cjk_chars < MIN_BODY_CJK or result.chars < MIN_BODY_CHARS:
        result.status = "needs_check"
        result.note = f"too little text chars={result.chars} cjk={result.cjk_chars}"
        return result

    p = out_dir / "chapters" / f"{ordinal:03d}.txt"
    p.parent.mkdir(parents=True, exist_ok=True)
    header = [f"Chapter: {ordinal}", f"Source: {url}"]
    if result.title:
        header.append(f"CN-Title: {result.title}")
    p.write_text("\n".join(header + ["", text, ""]), encoding="utf-8")
    result.file = str(p.relative_to(out_dir))
    result.status = "ok"
    result.note = f"parts={len(parts)}"
    return result



TWBOOK_FALLBACK_BOOK_ID = "0912500831"
ILWXS_BOOK_ID = "307344"
ILWXS_ROOT = f"https://m.ilwxs.com/shu/{ILWXS_BOOK_ID}/"
# Verified across repeated public requests: these TWBook chapter pages only
# return short placeholder bodies, while the fallback mirror has full text.
KNOWN_TWBOOK_PLACEHOLDERS = {232, 233, 234, 235, 356, 357}


def ilwxs_catalog_page_url(ordinal: int) -> str:
    page = (ordinal - 1) // 50 + 1
    return ILWXS_ROOT if page == 1 else f"https://m.ilwxs.com/shu/{ILWXS_BOOK_ID}_{page}/"


def resolve_ilwxs_chapter_url(
    session: requests.Session,
    ordinal: int,
    timeout: float,
) -> tuple[str, str] | None:
    """Resolve one chapter from the public ilwxs paginated catalog."""
    page_url = ilwxs_catalog_page_url(ordinal)
    response, html = fetch_html(session, page_url, timeout)
    if response.status_code >= 400:
        return None
    soup = soup_from_html(html)
    pattern = re.compile(rf"第\s*{ordinal}\s*章(?:\s|$)")
    for a in soup.select("a[href]"):
        title = normalize_text(a.get_text(" ", strip=True))
        if not pattern.search(title):
            continue
        url = urljoin(response.url, (a.get("href") or "").strip())
        if re.fullmatch(
            rf"https?://m\.ilwxs\.com/shu/{ILWXS_BOOK_ID}/\d+\.html",
            url,
        ):
            return url, title
    return None


def extract_ilwxs_content(soup: BeautifulSoup) -> str:
    """Extract the clean chapter body from a public ilwxs chapter page."""
    node = soup.select_one("div.content") or soup.select_one("div#content")
    if node is None:
        candidates = []
        for candidate in soup.select("[class*=content], article, main"):
            text = clean_content_node(candidate)
            if len(text) >= MIN_BODY_CHARS:
                candidates.append((len(text), text))
        if not candidates:
            raise ValueError("ilwxs chapter content node not found")
        return max(candidates)[1]
    return clean_content_node(node)


def fetch_ilwxs_chapter(
    session: requests.Session,
    ordinal: int,
    timeout: float,
) -> tuple[str, str, str] | None:
    resolved = resolve_ilwxs_chapter_url(session, ordinal, timeout)
    if resolved is None:
        return None
    url, title = resolved
    response, html = fetch_html(session, url, timeout)
    if response.status_code >= 400:
        return None
    text = extract_ilwxs_content(soup_from_html(html))
    if len(text) < MIN_BODY_CHARS or cjk_count(text) < MIN_BODY_CJK:
        return None
    if any(is_hangul(ch) for ch in text):
        return None
    return title, text, response.url


def write_fallback_chapter(
    result: ChapterResult,
    out_dir: Path,
    *,
    title: str,
    text: str,
    source_url: str,
    primary_url: str,
    primary_note: str | None,
) -> ChapterResult:
    p = out_dir / "chapters" / f"{result.ordinal:03d}.txt"
    p.parent.mkdir(parents=True, exist_ok=True)
    header = [
        f"Chapter: {result.ordinal}",
        f"Source: {source_url}",
        f"Primary: {primary_url}",
        f"CN-Title: {title}",
    ]
    p.write_text("\n".join(header + ["", text, ""]), encoding="utf-8")
    result.url = source_url
    result.http_status = 200
    result.title = title
    result.chars = len(text)
    result.cjk_chars = cjk_count(text)
    result.substitutions = 0
    result.unknown_total = 0
    result.unknown_unique = 0
    result.file = str(p.relative_to(out_dir))
    result.status = "ok"
    reason = primary_note or "TWBook primary unavailable"
    result.note = f"fallback=ilwxs; primary={reason}"
    return result


def fetch_chapter(
    session: requests.Session,
    url: str,
    ordinal: int,
    out_dir: Path,
    mapping: dict[str, str],
    timeout: float,
    save_html: bool,
    learn_attempts: int,
    max_parts: int = 8,
) -> ChapterResult:
    """Fetch TWBook first, then fail over to a clean public mirror if necessary."""
    primary_book_id = urlparse(url).path.strip("/").split("/", 1)[0]
    fallback_supported = primary_book_id == TWBOOK_FALLBACK_BOOK_ID

    if fallback_supported and ordinal in KNOWN_TWBOOK_PLACEHOLDERS:
        try:
            fallback = fetch_ilwxs_chapter(session, ordinal, timeout)
        except Exception:
            fallback = None
        if fallback is not None:
            title, text, source_url = fallback
            primary = ChapterResult(
                ordinal=ordinal,
                url=url,
                status="needs_check",
                http_status=200,
                note="known TWBook placeholder",
            )
            return write_fallback_chapter(
                primary,
                out_dir,
                title=title,
                text=text,
                source_url=source_url,
                primary_url=url,
                primary_note=primary.note,
            )

    primary = fetch_twbook_chapter(
        session,
        url,
        ordinal,
        out_dir,
        mapping,
        timeout,
        save_html,
        learn_attempts,
        max_parts,
    )
    if primary.status == "ok" or not fallback_supported:
        return primary

    primary_note = primary.note
    try:
        fallback = fetch_ilwxs_chapter(session, ordinal, timeout)
    except requests.RequestException:
        fallback = None
    except Exception:
        fallback = None
    if fallback is None:
        return primary

    title, text, source_url = fallback
    return write_fallback_chapter(
        primary,
        out_dir,
        title=title,
        text=text,
        source_url=source_url,
        primary_url=url,
        primary_note=primary_note,
    )

def write_reports(
    results: list[ChapterResult],
    catalog: list[tuple[str, str]],
    out_dir: Path,
    mapping: dict[str, str],
) -> None:
    (out_dir / "manifest.jsonl").write_text(
        "".join(json.dumps(asdict(x), ensure_ascii=False) + "\n" for x in results),
        encoding="utf-8",
    )
    (out_dir / "catalog.tsv").write_text(
        "".join(
            f"{i:03d}\t{title}\t{url}\n"
            for i, (url, title) in enumerate(catalog, 1)
        ),
        encoding="utf-8",
    )

    counts = Counter(x.status for x in results)
    unresolved = Counter()
    for p in (
        sorted((out_dir / "unresolved").glob("*.json"))
        if (out_dir / "unresolved").exists()
        else []
    ):
        data = json.loads(p.read_text(encoding="utf-8"))
        unresolved.update(data["counts"])

    lines = [
        "# TWBook public fetch",
        "",
        f"- catalog chapters: {len(catalog)}",
        f"- attempted: {len(results)}",
        f"- legacy mapping entries: {len(mapping)} (not used for chapter decoding)",
        "",
        "## Result counts",
        "",
    ]
    for status, count in sorted(counts.items()):
        lines.append(f"- {status}: {count}")
    lines.extend(["", "## Unresolved Hangul", ""])
    if unresolved:
        for ch, count in unresolved.most_common():
            lines.append(f"- `{ch}` U+{ord(ch):04X}: {count}")
    else:
        lines.append("- none")
    lines.extend(["", "## Chapters requiring attention", ""])
    bad = [x for x in results if x.status != "ok"]
    if bad:
        for x in bad:
            lines.append(f"- {x.ordinal:03d}: {x.status} — {x.note or ''}")
    else:
        lines.append("- none")
    (out_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_combined(results: list[ChapterResult], out_dir: Path) -> None:
    chunks: list[str] = []
    for item in results:
        if item.status == "ok" and item.file:
            chunks.append((out_dir / item.file).read_text(encoding="utf-8").rstrip())
    if chunks:
        (out_dir / "combined.txt").write_text(
            ("\n\n" + "=" * 72 + "\n\n").join(chunks) + "\n",
            encoding="utf-8",
        )


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--book-id", required=True)
    p.add_argument("--base-url", default="https://www.twbook.cc")
    p.add_argument("--out-dir", default="out/twbook")
    p.add_argument("--start", type=int, default=1)
    p.add_argument("--end", type=int)
    p.add_argument("--delay", type=float, default=0.8)
    p.add_argument("--timeout", type=float, default=20.0)
    p.add_argument("--mapping", type=Path, default=DEFAULT_MAPPING)
    p.add_argument("--save-html", action="store_true")
    p.add_argument(
        "--learn-attempts",
        type=int,
        default=4,
        help="extra public renderings used for per-position consensus",
    )
    p.add_argument("--allow-incomplete", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    if args.start < 1 or (args.end is not None and args.end < args.start):
        print("invalid range", file=sys.stderr)
        return 2
    if args.delay < 0.5:
        print("delay must be >= 0.5 seconds", file=sys.stderr)
        return 2
    if args.learn_attempts < 0 or args.learn_attempts > 10:
        print("learn-attempts must be between 0 and 10", file=sys.stderr)
        return 2

    mapping = load_mapping(args.mapping)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.5",
        }
    )

    dir_url = f"{args.base_url.rstrip('/')}/{args.book_id}/dir"
    try:
        response, html = fetch_html(session, dir_url, args.timeout)
    except requests.RequestException as exc:
        print(f"catalog network error: {exc}", file=sys.stderr)
        return 3
    if response.status_code >= 400:
        print(f"catalog HTTP {response.status_code}", file=sys.stderr)
        return 3

    catalog = extract_catalog(html, dir_url)
    if not catalog:
        print("no chapters found in catalog", file=sys.stderr)
        return 4

    end = min(args.end or len(catalog), len(catalog))
    selected = list(enumerate(catalog[args.start - 1:end], args.start))
    print(f"catalog: {len(catalog)} chapters; selected {args.start}-{end}")

    results: list[ChapterResult] = []
    for idx, (url, _) in selected:
        item = fetch_chapter(
            session,
            url,
            idx,
            out_dir,
            mapping,
            args.timeout,
            args.save_html,
            args.learn_attempts,
        )
        results.append(item)
        print(
            f"{idx:03d}: {item.status} http={item.http_status} "
            f"cjk={item.cjk_chars} resolved={item.substitutions} "
            f"unknown={item.unknown_total} note={item.note or ''}"
        )
        if idx != selected[-1][0]:
            time.sleep(args.delay)

    write_reports(results, catalog, out_dir, mapping)
    build_combined(results, out_dir)

    ok = sum(x.status == "ok" for x in results)
    print(f"done: {ok}/{len(results)} chapters clean")
    if any(x.status != "ok" for x in results) and not args.allow_incomplete:
        return 5
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
