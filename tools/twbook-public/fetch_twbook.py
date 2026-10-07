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


def load_mapping(path: Path) -> dict[str, str]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    for src, dst in raw.items():
        if len(src) != 1 or len(dst) != 1:
            raise ValueError(f"invalid mapping: {src!r} -> {dst!r}")
    return raw


def decode_text(text: str, mapping: dict[str, str]) -> tuple[str, int, Counter[str]]:
    substitutions = sum(text.count(ch) for ch in mapping)
    decoded = text.translate(str.maketrans(mapping))
    unknown = Counter(ch for ch in decoded if is_hangul(ch))
    return decoded, substitutions, unknown


def cjk_count(text: str) -> int:
    return len(re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]", text))


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


def fetch_html(session: requests.Session, url: str, timeout: float) -> tuple[requests.Response, str]:
    response = session.get(url, timeout=timeout, allow_redirects=True)
    response.encoding = response.apparent_encoding or response.encoding or "utf-8"
    return response, response.text


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


def fetch_chapter(
    session: requests.Session,
    url: str,
    ordinal: int,
    out_dir: Path,
    mapping: dict[str, str],
    timeout: float,
    save_html: bool,
    max_parts: int = 8,
) -> ChapterResult:
    result = ChapterResult(ordinal=ordinal, url=url, status="error")
    current = url
    visited: set[str] = set()
    parts: list[str] = []
    decoded_pages: list[str] = []
    title: str | None = None
    total_subs = 0

    try:
        for _ in range(max_parts):
            if current in visited:
                raise RuntimeError(f"split-page loop at {current}")
            visited.add(current)
            response, html = fetch_html(session, current, timeout)
            result.http_status = response.status_code
            if response.status_code >= 400:
                result.status = "missing" if response.status_code == 404 else "error"
                result.note = f"HTTP {response.status_code} at {current}"
                return result

            decoded_html, subs, _ = decode_text(html, mapping)
            total_subs += subs
            decoded_pages.append(decoded_html)
            soup = soup_from_html(decoded_html)
            if title is None:
                title = extract_title(soup)
            parts.append(extract_content(soup))
            nxt = next_part_url(soup, current)
            if not nxt:
                break
            current = nxt
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
    result.title = title
    result.chars = len(text)
    result.cjk_chars = cjk_count(text)
    result.substitutions = total_subs
    result.unknown_total = sum(unresolved.values())
    result.unknown_unique = len(unresolved)

    if save_html:
        p = out_dir / "html" / f"{ordinal:03d}.html"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("\n<!-- SPLIT -->\n".join(decoded_pages), encoding="utf-8")

    if unresolved:
        diag = out_dir / "unresolved" / f"{ordinal:03d}.json"
        diag.parent.mkdir(parents=True, exist_ok=True)
        diag.write_text(
            json.dumps(
                {
                    "chapter": ordinal,
                    "url": url,
                    "counts": dict(unresolved),
                    "contexts": unknown_contexts(text, unresolved),
                },
                ensure_ascii=False,
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )
        result.status = "mapping_incomplete"
        result.note = "unresolved: " + ", ".join(
            f"{ch}=U+{ord(ch):04X}x{count}" for ch, count in unresolved.most_common()
        )
        return result

    if result.cjk_chars < 120 or result.chars < 300:
        result.status = "needs_check"
        result.note = f"too little text chars={result.chars} cjk={result.cjk_chars}"
        return result

    p = out_dir / "chapters" / f"{ordinal:03d}.txt"
    p.parent.mkdir(parents=True, exist_ok=True)
    header = [f"Chapter: {ordinal}", f"Source: {url}"]
    if title:
        header.append(f"CN-Title: {title}")
    p.write_text("\n".join(header + ["", text, ""]), encoding="utf-8")
    result.file = str(p.relative_to(out_dir))
    result.status = "ok"
    result.note = f"parts={len(parts)}"
    return result


def write_reports(results: list[ChapterResult], catalog: list[tuple[str, str]], out_dir: Path, mapping: dict[str, str]) -> None:
    (out_dir / "manifest.jsonl").write_text(
        "".join(json.dumps(asdict(x), ensure_ascii=False) + "\n" for x in results),
        encoding="utf-8",
    )
    (out_dir / "catalog.tsv").write_text(
        "".join(f"{i:03d}\t{title}\t{url}\n" for i, (url, title) in enumerate(catalog, 1)),
        encoding="utf-8",
    )

    counts = Counter(x.status for x in results)
    unresolved = Counter()
    for p in sorted((out_dir / "unresolved").glob("*.json")) if (out_dir / "unresolved").exists() else []:
        data = json.loads(p.read_text(encoding="utf-8"))
        unresolved.update(data["counts"])

    lines = [
        "# TWBook public fetch",
        "",
        f"- catalog chapters: {len(catalog)}",
        f"- attempted: {len(results)}",
        f"- mapping entries: {len(mapping)}",
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

    decoded_dir, _, _ = decode_text(html, mapping)
    catalog = extract_catalog(decoded_dir, dir_url)
    if not catalog:
        print("no chapters found in catalog", file=sys.stderr)
        return 4

    end = min(args.end or len(catalog), len(catalog))
    selected = list(enumerate(catalog[args.start - 1:end], args.start))
    print(f"catalog: {len(catalog)} chapters; selected {args.start}-{end}")

    results: list[ChapterResult] = []
    for idx, (url, _) in selected:
        item = fetch_chapter(
            session, url, idx, out_dir, mapping, args.timeout, args.save_html
        )
        results.append(item)
        print(
            f"{idx:03d}: {item.status} http={item.http_status} "
            f"cjk={item.cjk_chars} subs={item.substitutions} "
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
