#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

NUMBERED_HEADING_RE = re.compile(r"^第\s*(\d+)\s*章(?:\s*[。.]?)\s*(.*?)\s*$")
EXTRA_HEADING_RE = re.compile(r"^番外\s*[:：]?\s*(.*?)\s*$")


@dataclass
class Chapter:
    ordinal: int
    author_number: Optional[int]
    title: str
    heading: str
    start_line: int
    end_line: int
    body: str

    @property
    def text(self) -> str:
        return f"{self.heading}\n\n{self.body.strip()}\n"

    @property
    def chars(self) -> int:
        return len(self.body.strip())

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()


def discover_headings(lines: list[str]):
    found = []
    for i, raw in enumerate(lines):
        line = raw.strip()
        m = NUMBERED_HEADING_RE.match(line)
        if m:
            num = int(m.group(1))
            title = m.group(2).strip()
            normalized = f"第{num}章" + (f" {title}" if title else "")
            found.append((i, num, title, normalized))
            continue
        m = EXTRA_HEADING_RE.match(line)
        if m:
            title = m.group(1).strip()
            normalized = "番外" + (f"：{title}" if title else "")
            found.append((i, None, title, normalized))
    return found


def parse_book(text: str) -> list[Chapter]:
    lines = text.splitlines()
    heads = discover_headings(lines)
    chapters = []
    for idx, (start_i, author_no, title, heading) in enumerate(heads):
        end_i = heads[idx + 1][0] if idx + 1 < len(heads) else len(lines)
        body = "\n".join(lines[start_i + 1:end_i]).strip()
        chapters.append(
            Chapter(
                ordinal=idx + 1,
                author_number=author_no,
                title=title,
                heading=heading,
                start_line=start_i + 1,
                end_line=end_i,
                body=body,
            )
        )
    return chapters


def metadata(chapter: Chapter, chapters: list[Chapter]) -> dict:
    numbered = [c.author_number for c in chapters if c.author_number is not None]
    max_author = max(numbered) if numbered else 0
    present = set(numbered)
    return {
        "ordinal": chapter.ordinal,
        "author_number": chapter.author_number,
        "title": chapter.title,
        "heading": chapter.heading,
        "start_line": chapter.start_line,
        "end_line": chapter.end_line,
        "chars": chapter.chars,
        "sha256": chapter.sha256,
        "total_actual_chapters": len(chapters),
        "numbered_chapters": len(numbered),
        "extras": len(chapters) - len(numbered),
        "max_author_number": max_author,
        "missing_author_numbers": [
            n for n in range(1, max_author + 1) if n not in present
        ],
    }


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Extract one actual chapter from a full Chinese novel TXT."
    )
    ap.add_argument("source", type=Path)
    selector = ap.add_mutually_exclusive_group(required=True)
    selector.add_argument(
        "--ordinal",
        type=int,
        help="Actual chapter order in the file (includes extras).",
    )
    selector.add_argument(
        "--author-number",
        type=int,
        help="Author's numbered chapter label. Extras have no author number.",
    )
    ap.add_argument("--out-dir", type=Path, default=Path("out/novel"))
    args = ap.parse_args()

    text = args.source.read_text(encoding="utf-8-sig")
    chapters = parse_book(text)
    if not chapters:
        raise SystemExit("No chapter headings found.")

    if args.ordinal is not None:
        selected = [c for c in chapters if c.ordinal == args.ordinal]
    else:
        selected = [c for c in chapters if c.author_number == args.author_number]

    if not selected:
        raise SystemExit("Chapter not found.")

    chapter = selected[0]
    meta = metadata(chapter, chapters)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    author_tag = (
        f"author-{chapter.author_number:03d}"
        if chapter.author_number is not None
        else "extra"
    )
    stem = f"{chapter.ordinal:03d}_{author_tag}"
    (args.out_dir / f"{stem}.txt").write_text(chapter.text, encoding="utf-8")
    (args.out_dir / f"{stem}.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(meta, ensure_ascii=False))


if __name__ == "__main__":
    main()
