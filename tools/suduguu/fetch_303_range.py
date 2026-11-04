#!/usr/bin/env python3
"""Collect and verify numbered chapters 650-855 of Suduguu book 303.

Suduguu labels the last chapter as 853, although its canonical ordinal is 855.
It also divides many chapters into multiple HTML pages (-2.html, -3.html, ...).
This collector corrects the final label and downloads every page of each chapter.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BOOK_URL = "https://www.suduguu.com/303/"
BOOK_NAME = "百世修仙：我能固定天赋"
AUTHOR = "牛顿不秃顶"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/129.0 Safari/537.36"
CHAPTER_LINK = re.compile(r"^https://www\.suduguu\.com/303/(\d+)\.html$")
LABEL = re.compile(r"^第\s*(\d+)\s*章\s*(.*)$")
STOP = {"上一章", "下一章", "上一页", "下一页", "上一頁", "下一頁",
        "目录", "目錄", "相关小说", "全部", "返回书页", "设置"}
BAD = {"首页", "速读谷", "菜单", "收起", "网站换肤", "阅读记录"}


def make_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(total=4, connect=4, read=3, backoff_factor=1.0,
                  status_forcelist=[429, 500, 502, 503, 504],
                  allowed_methods=frozenset(["GET"]))
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.headers.update({
        "User-Agent": UA,
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
    })
    return session


def get_soup(session: requests.Session, url: str) -> BeautifulSoup:
    response = session.get(url, timeout=(15, 45))
    response.raise_for_status()
    soup = BeautifulSoup(response.content, "html.parser")
    if not soup.title or BOOK_NAME not in soup.title.get_text(" ", strip=True):
        raise ValueError(f"Unexpected page/title at {url}: " +
                         (soup.title.get_text(" ", strip=True) if soup.title else "no title"))
    return soup


def build_catalog(session: requests.Session) -> dict[int, dict]:
    soup = get_soup(session, BOOK_URL)
    catalog: dict[int, dict] = {}
    for a in soup.find_all("a", href=True):
        label = re.sub(r"\s+", " ", a.get_text(" ", strip=True)).strip()
        match = LABEL.fullmatch(label)
        if not match:
            continue
        source_no = int(match.group(1))
        title = match.group(2).strip()
        link = urljoin(BOOK_URL, a["href"]).split("?", 1)[0]
        if not CHAPTER_LINK.fullmatch(link):
            continue
        ordinal = source_no
        if source_no == 853 and "大天尊" in title and "大结局" in title:
            ordinal = 855  # Suduguu's misnumbered finale; official original is #855.
        item = {"chapter": ordinal, "source_number": source_no,
                "title": title, "url": link}
        if ordinal in catalog and catalog[ordinal]["url"] != link:
            raise ValueError(f"Conflicting links for chapter {ordinal}: " +
                             f"{catalog[ordinal]['url']} vs {link}")
        catalog[ordinal] = item
    return catalog


def normalize_text(text: str) -> list[str]:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = []
    for raw in text.split("\n"):
        line = re.sub(r"[\t\u00a0 ]+", " ", raw).strip()
        if line and line not in BAD:
            lines.append(line)
    return lines


def extract_page(soup: BeautifulSoup, source_number: int, title: str) -> str:
    """Use the confirmed story container, never the body or related-books sidebar."""
    containers = soup.select("div.container > div.con")
    if len(containers) != 1:
        raise ValueError(f"Expected 1 story container, found {len(containers)}")
    paragraphs = containers[0].find_all("p", recursive=False)
    if len(paragraphs) < 3:
        raise ValueError(f"Expected multiple story paragraphs, found {len(paragraphs)}")
    lines = []
    for paragraph in paragraphs:
        item = paragraph.get_text(" ", strip=True)
        item = re.sub(r"[\t\u00a0 ]+", " ", item).strip()
        if item:
            lines.append(item)
    body = "\n\n".join(lines)
    cjk_count = len(re.findall(r"[\u3400-\u9fff]", body))
    if len(body) < 100 or cjk_count < 65:
        raise ValueError(f"Suspiciously short page, total={len(body)}, CJK={cjk_count}")
    if "第" + str(source_number) + "章" in body[:100] and title in body[:100]:
        raise ValueError("Chapter heading leaked into extracted body")
    return body


def next_part(soup: BeautifulSoup, first_url: str, part_number: int) -> str | None:
    base = first_url[:-5]  # Strip .html
    for a in soup.find_all("a", href=True):
        label = a.get_text(" ", strip=True)
        if label not in {"下一页", "下一頁", "下页", "下頁"}:
            continue
        link = urljoin(first_url, a["href"]).split("?", 1)[0]
        match = re.fullmatch(re.escape(base) + r"-(\d+)\.html", link)
        if match:
            dest = int(match.group(1))
            if dest != part_number + 1:
                raise ValueError(f"Pagination gap: expected part {part_number + 1}, got {dest}")
            return link
    return None


def fetch_chapter(session: requests.Session, item: dict, delay: float) -> tuple[str, list[str]]:
    url = item["url"]
    visited: set[str] = set()
    parts = []
    links = []
    page_hashes: set[str] = set()
    for part_number in range(1, 41):
        if url in visited:
            raise ValueError("Pagination loop")
        visited.add(url)
        soup = get_soup(session, url)
        body = extract_page(soup, item["source_number"], item["title"])
        if len(body) < 100:
            raise ValueError(f"Unexpected short page {len(body)} chars: {url}")
        body_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
        if body_hash in page_hashes:
            raise ValueError(f"Repeated page content at {url}")
        page_hashes.add(body_hash)
        parts.append(body)
        links.append(url)
        next_url = next_part(soup, item["url"], part_number)
        if not next_url:
            break
        url = next_url
        time.sleep(max(delay, 0.25))
    else:
        raise ValueError("Exceeded 40 pages for a single chapter")
    full = "\n\n".join(parts)
    if len(full) < 550:
        raise ValueError(f"Unexpected short chapter {len(full)} chars: {item['chapter']}")
    return full, links


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=int, default=650)
    parser.add_argument("--end", type=int, default=855)
    parser.add_argument("--out-dir", default="novels/suduguu/303")
    parser.add_argument("--delay", type=float, default=0.45)
    args = parser.parse_args()
    if not (1 <= args.start <= args.end <= 855):
        parser.error("Expected range within 1..855")
    folder = Path(args.out_dir)
    raw = folder / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    session = make_session()
    catalog = build_catalog(session)
    required = set(range(args.start, args.end + 1))
    absent = required - catalog.keys()
    manifest = []
    failures = []
    for ordinal in sorted(absent):
        failures.append({"chapter": ordinal, "error": "missing_from_catalog"})
    if absent:
        print("Missing from catalog:", sorted(absent), flush=True)

    for ordinal in range(args.start, args.end + 1):
        if ordinal not in catalog:
            continue
        item = catalog[ordinal]
        try:
            body, pages = fetch_chapter(session, item, args.delay)
            filename = raw / f"{ordinal:03d}.txt"
            source_heading = f"第{item['source_number']}章 {item['title']}"
            filename.write_text(
                f"Chapter: {ordinal}\n"
                f"CN-Title: {source_heading}\n"
                f"Source: {item['url']}\n"
                f"Page count: {len(pages)}\n\n"
                f"{body}\n", encoding="utf-8")
            manifest.append({
                "chapter": ordinal,
                "source_number": item["source_number"],
                "title": item["title"],
                "url": item["url"],
                "pages": pages,
                "page_count": len(pages),
                "chars": len(body),
                "sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
                "file": str(filename.relative_to(folder)),
            })
            print(f"{ordinal}: OK chars={len(body)} pages={len(pages)}", flush=True)
        except Exception as error:
            failure = {"chapter": ordinal, "url": item["url"],
                       "error": f"{type(error).__name__}: {error}"}
            failures.append(failure)
            print(f"{ordinal}: FAIL {failure['error']}", flush=True)
        time.sleep(max(args.delay, 0.25))

    hashes = [item["sha256"] for item in manifest]
    if len(hashes) != len(set(hashes)):
        failures.append({"chapter": None, "error": "identical_contents_for_multiple_chapters"})
    manifest.sort(key=lambda item: item["chapter"])
    failures.sort(key=lambda item: item["chapter"] or 0)
    (folder / "manifest.json").write_text(
        json.dumps({"book": BOOK_NAME, "author": AUTHOR, "source": BOOK_URL,
                    "start": args.start, "end": args.end,
                    "chapters": manifest}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    (folder / "failures.json").write_text(
        json.dumps(failures, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    parts = [(folder / item["file"]).read_text(encoding="utf-8").rstrip()
             for item in manifest]
    combined = folder / ("combined.txt" if not failures and len(manifest) == len(required)
                         else "combined.partial.txt")
    if parts:
        combined.write_text(("\n\n" + "=" * 72 + "\n\n").join(parts) + "\n", encoding="utf-8")

    summary = [
        f"# {BOOK_NAME} — RAW {args.start}–{args.end}",
        f"Source: {BOOK_URL}",
        f"Requested: {len(required)} numbered chapters",
        f"Collected: {len(manifest)}",
        f"Failures: {len(failures)}",
        f"Total source pages: {sum(item['page_count'] for item in manifest)}",
        f"Complete: {'YES' if not failures and len(manifest) == len(required) else 'NO'}",
        "",
        "Chapter 855 on Suduguu is mislabelled '第853章 大天尊（大结局）';",
        "the verified original numbering is 855. All paginated chapter parts are included.",
        "",
    ]
    if failures:
        summary += ["## Failures"] + [
            f"- {item['chapter']}: {item['error']}" for item in failures
        ]
    (folder / "summary.md").write_text("\n".join(summary) + "\n", encoding="utf-8")
    print("\n".join(summary), flush=True)
    return 0 if not failures and len(manifest) == len(required) else 2


if __name__ == "__main__":
    raise SystemExit(main())
