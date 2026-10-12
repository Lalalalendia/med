#!/usr/bin/env python3
"""Gather publicly readable xszj 3-part chapters with fail-closed receipts.

Use only with rights appropriate for the intended use. Never commits story
content to Git. In CI, --metadata-only hashes parsed bodies without persisting
them. --emit-text explicitly writes chapter TXT files in the job workspace.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from xszj_probe import HOST, USER_AGENT, request_public, robots_allow

CJK = re.compile(r"[\u3400-\u9fff]")
PART_MARKER = re.compile(r"[（(]\s*(\d+)\s*/\s*(\d+)\s*[)）]")
WATERMARK_MARKERS = ("M.Ι.", "请收藏本站", "小说之家提醒", "手机用户请浏览")


class ChapterError(Exception):
    pass


@dataclass(frozen=True)
class Part:
    part: int
    title: str
    display_number: int | None
    text: str
    cjk_chars: int
    sha256: str
    warnings: tuple[str, ...]


def normalize_text(value: str) -> str:
    lines = [re.sub(r"[\t\u00a0\u3000 ]+", " ", line).strip()
             for line in value.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    normalized = []
    blank = False
    for line in lines:
        if line:
            normalized.append(line)
            blank = False
        elif normalized and not blank:
            normalized.append("")
            blank = True
    return "\n".join(normalized).strip()


def parse_part(html: str, expected_part: int, *, min_chars: int = 120) -> Part:
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.select_one("h1")
    if h1 is None:
        raise ChapterError("missing chapter h1")
    heading = re.sub(r"\s+", " ", h1.get_text(" ", strip=True))
    markers = PART_MARKER.findall(heading)
    if len(markers) != 1:
        raise ChapterError("missing or ambiguous (part/total) heading marker")
    actual_part, total = map(int, markers[0])
    if actual_part != expected_part or total != 3:
        raise ChapterError(f"wrong page marker: {actual_part}/{total}, expected {expected_part}/3")
    title = PART_MARKER.sub("", heading).strip()
    chapter_match = re.search(r"第\s*(\d{1,5})", title)
    display_number = int(chapter_match.group(1)) if chapter_match else None

    candidates = soup.select("#content")
    if len(candidates) != 1:
        raise ChapterError(f"expected exactly one #content, found {len(candidates)}")
    container = candidates[0]
    for element in list(container.select("script,style,iframe,noscript,nav,footer,aside,.advert,.ads,.pagination")):
        element.decompose()
    text = normalize_text(container.get_text("\n", strip=True))
    if not text:
        raise ChapterError("empty body after extracting #content")
    chinese = len(CJK.findall(text))
    if chinese < min_chars:
        raise ChapterError(f"body too short: {chinese} Han characters")
    if chinese < 0.35 * len(text):
        raise ChapterError("body does not resemble Chinese chapter prose")
    warnings = tuple("possible_watermark:" + marker for marker in WATERMARK_MARKERS if marker in text)
    return Part(expected_part, title, display_number, text, chinese,
                hashlib.sha256(text.encode("utf-8")).hexdigest(), warnings)


def merge_parts(parts: list[Part]) -> tuple[str, list[str]]:
    if len(parts) != 3 or [p.part for p in parts] != [1, 2, 3]:
        raise ChapterError("exactly ordered parts 1/3, 2/3, 3/3 required")
    if len({p.title for p in parts}) != 1:
        raise ChapterError("page chapter titles disagree")
    if len({p.sha256 for p in parts}) != 3:
        raise ChapterError("duplicate page body across the three parts")
    text = parts[0].text
    for part in parts[1:]:
        # xszj splits inside a word, e.g. 周 | 年纪念. Do NOT always inject a
        # newline. Existing section boundary punctuation may start a paragraph.
        boundary = "\n" if text.endswith(tuple("。！？；…\"”」』")) else ""
        text += boundary + part.text
    warnings = list(dict.fromkeys(w for p in parts for w in p.warnings))
    if any(p.cjk_chars < 300 for p in parts):
        warnings.append("short_page_requires_review")
    return text, warnings


def validate_manifest(data: dict, start: int, end: int) -> list[dict]:
    if data.get("schema_version") != 1 or data.get("book", {}).get("rulate_id") != 100316:
        raise ValueError("unsupported index schema/book")
    if not (370 <= start <= end <= 450) or end - start + 1 > 10:
        raise ValueError("only contiguous batches up to 10 chapters, 370..450")
    index = data.get("chapters")
    if not isinstance(index, list) or len(index) != 81:
        raise ValueError("chapter index incomplete")
    for i, row in enumerate(index):
        ordinal = i + 370
        chapter_id = row["site_chapter_id"]
        if row["catalog_ordinal"] != ordinal or not re.fullmatch(r"\d+", chapter_id):
            raise ValueError("malformed catalog ordinal or chapter id")
        expected = [
            f"https://{HOST}/b/352919/c/{chapter_id}" + (f"?page={part}" if part > 1 else "")
            for part in (1, 2, 3)
        ]
        if row["part_urls"] != expected:
            raise ValueError("chapter URL mismatch")
    return index[start - 370:end - 369]


def gather(manifest: Path, *, start: int, end: int,
           out_dir: Path, emit_text: bool = False, delay: float = 1.5) -> dict:
    if delay < 1.0:
        raise ValueError("delay must be at least one second")
    rows = validate_manifest(json.loads(manifest.read_text(encoding="utf-8")), start, end)
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "text/html"})
    urls = [url for row in rows for url in row["part_urls"]]
    allowed, robots_reason = robots_allow(session, urls)
    out_dir.mkdir(parents=True, exist_ok=True)
    receipts = []
    if allowed:
        for row in rows:
            ordinal = row["catalog_ordinal"]
            record = {"catalog_ordinal": ordinal,
                      "source_id": row["site_chapter_id"],
                      "part_urls": row["part_urls"],
                      "status": "error"}
            try:
                parts = []
                for p, url in enumerate(row["part_urls"], 1):
                    response = request_public(session, url)
                    if response.status_code != 200:
                        raise ChapterError(f"part {p}: HTTP {response.status_code}")
                    if "html" not in response.headers.get("Content-Type", "").lower():
                        raise ChapterError(f"part {p}: response is not HTML")
                    parts.append(parse_part(response.text, p))
                    time.sleep(delay)
                merged, warnings = merge_parts(parts)
                number = parts[0].display_number
                if number is None:
                    warnings.append("missing_original_heading_number")
                elif number != ordinal:
                    warnings.append(f"display_number_{number}_differs_from_ordinal_{ordinal}")
                digest = hashlib.sha256(merged.encode("utf-8")).hexdigest()
                record.update({
                    "status": "collected" if not warnings else "needs_review",
                    "title_original": parts[0].title, "displayed_number": number,
                    "part_cjk_chars": [part.cjk_chars for part in parts],
                    "part_sha256": [part.sha256 for part in parts],
                    "joined_cjk_chars": len(CJK.findall(merged)),
                    "joined_sha256": digest,
                    "warnings": warnings,
                    "official_text_collated": False,
                })
                if emit_text:
                    target = out_dir / "chapters" / f"{ordinal:03d}.txt"
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(merged + "\n", encoding="utf-8")
                    record["raw_path"] = str(target.relative_to(out_dir))
            except (ChapterError, requests.RequestException, ValueError) as error:
                record["status"] = "error"
                record["error_type"] = type(error).__name__
                record["error"] = str(error)
            receipts.append(record)
    report = {
        "schema_version": 1, "book_id": 100316, "first": start, "last": end,
        "robots_allowed": allowed, "robots_reason": robots_reason,
        "raw_txt_emitted": emit_text and allowed,
        "chapters_expected": end - start + 1,
        "chapters_collected_or_review": sum(r["status"] in ("collected", "needs_review") for r in receipts),
        "chapters_error": sum(r["status"] == "error" for r in receipts),
        "status": "complete" if allowed and len(receipts) == end - start + 1
                  and all(r["status"] in ("collected", "needs_review") for r in receipts)
                  else "incomplete",
        "chapters": receipts,
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--start", type=int, required=True)
    parser.add_argument("--end", type=int, required=True)
    parser.add_argument("--out-dir", type=Path, default=Path("out/rulate-100316"))
    parser.add_argument("--emit-text", action="store_true",
                        help="Explicitly write TXT to the run artifact workspace")
    parser.add_argument("--delay", type=float, default=1.5)
    opts = parser.parse_args()
    result = gather(opts.manifest, start=opts.start, end=opts.end,
                    out_dir=opts.out_dir, emit_text=opts.emit_text, delay=opts.delay)
    # Receipts only. The workflow log must never contain Chinese chapter bodies.
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["status"] != "complete":
        raise SystemExit("Not all requested public chapters passed source validation")


if __name__ == "__main__":
    main()
