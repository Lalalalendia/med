#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html as html_lib
import json
import re
import time
import urllib.parse
import subprocess
from html.parser import HTMLParser
from pathlib import Path

MISSING_RESOURCE_TEXT = "本章暂无阅读资源"
DMCA_PREFIX = "如果此书侵犯了您的权益"
NEXT_TEASER_PREFIX = "小主子，这个章节后面还有哦"
SITE_PROMO_PREFIX = "喜欢魔女大人，请按剧本黑化！请大家收藏"


class ChapterPageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_content = False
        self.content_depth = 0
        self.parts: list[str] = []
        self.next_href: str | None = None

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        data = dict(attrs)
        if tag == "div" and data.get("id") == "content":
            self.in_content = True
            self.content_depth = 1
            return
        if tag == "a" and data.get("id") == "pager_next":
            self.next_href = data.get("href")
        if self.in_content:
            if tag == "div":
                self.content_depth += 1
            if tag in {"p", "br"}:
                self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self.in_content:
            self.parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if not self.in_content:
            return
        if tag == "p":
            self.parts.append("\n")
        if tag == "div":
            self.content_depth -= 1
            if self.content_depth == 0:
                self.in_content = False


def normalize_body(parts: list[str]) -> str:
    lines: list[str] = []
    for raw in "".join(parts).splitlines():
        text = html_lib.unescape(raw).strip()
        if not text:
            continue
        if text.startswith(DMCA_PREFIX):
            continue
        if text.startswith(NEXT_TEASER_PREFIX):
            continue
        if text.startswith(SITE_PROMO_PREFIX):
            continue
        lines.append(text)
    return "\n".join(lines).strip()


def fetch(url: str, retries: int = 4) -> str:
    error = None
    for attempt in range(1, retries + 1):
        proc = subprocess.run(
            [
                "curl",
                "--compressed",
                "--fail",
                "--location",
                "--silent",
                "--show-error",
                "--connect-timeout",
                "10",
                "--max-time",
                "40",
                "--user-agent",
                "Mozilla/5.0",
                url,
            ],
            capture_output=True,
        )
        if proc.returncode == 0 and len(proc.stdout) > 1000:
            return proc.stdout.decode("utf-8", errors="replace")
        error = proc.stderr.decode("utf-8", errors="replace").strip()
        if attempt < retries:
            time.sleep(attempt)
    raise RuntimeError(f"Failed to fetch {url}: {error}")


def same_chapter_page(first_url: str, next_url: str) -> bool:
    first = urllib.parse.urlsplit(first_url)
    nxt = urllib.parse.urlsplit(next_url)
    first_name = Path(first.path).stem
    next_name = Path(nxt.path).stem
    return next_name == first_name or next_name.startswith(first_name + "_")


def crawl_entry(first_url: str, max_pages: int = 20) -> dict:
    pages: list[str] = []
    bodies: list[str] = []
    current = first_url
    seen: set[str] = set()
    missing_resource = False

    while current and current not in seen:
        if len(pages) >= max_pages:
            raise RuntimeError(f"Exceeded {max_pages} pages for {first_url}")
        seen.add(current)
        source = fetch(current)
        parser = ChapterPageParser()
        parser.feed(source)
        body = normalize_body(parser.parts)
        if MISSING_RESOURCE_TEXT in body:
            missing_resource = True
        if body:
            bodies.append(body)
        pages.append(current)

        if not parser.next_href:
            break
        candidate = urllib.parse.urljoin(current, parser.next_href)
        if not same_chapter_page(first_url, candidate):
            break
        current = candidate

    return {
        "first_url": first_url,
        "pages": pages,
        "page_count": len(pages),
        "body": "\n".join(bodies).strip(),
        "missing_resource": missing_resource,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", type=Path, required=True)
    ap.add_argument("--chunk", type=int, required=True)
    ap.add_argument("--chunks", type=int, default=8)
    ap.add_argument("--out-dir", type=Path, required=True)
    args = ap.parse_args()

    rows = json.loads(args.manifest.read_text(encoding="utf-8"))
    selected = [r for r in rows if (r["ordinal"] - 1) % args.chunks == args.chunk]
    args.out_dir.mkdir(parents=True, exist_ok=True)

    summary = []
    for idx, row in enumerate(selected, 1):
        result = crawl_entry(row["url"])
        result.update({"ordinal": row["ordinal"], "heading": row["heading"]})
        (args.out_dir / f"{row['ordinal']:03d}.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        summary.append(
            {
                "ordinal": row["ordinal"],
                "page_count": result["page_count"],
                "chars": len(result["body"]),
                "missing_resource": result["missing_resource"],
            }
        )
        if idx % 10 == 0 or idx == len(selected):
            print(
                json.dumps(
                    {
                        "chunk": args.chunk,
                        "done": idx,
                        "total": len(selected),
                        "last_ordinal": row["ordinal"],
                    },
                    ensure_ascii=False,
                )
            )

    print(json.dumps({"chunk": args.chunk, "entries": summary}, ensure_ascii=False))


if __name__ == "__main__":
    main()
