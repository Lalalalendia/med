#!/usr/bin/env python3
"""Collect authorized Jiuxiao novel text from an exact author chapter number.

Reads a versioned full index produced by witcher_full_catalog.py.
Preserves <p class="reader-paragraph"> boundaries. Maintains verified
per-chapter progress.json so interrupted GitHub Actions can export partial
data. Does not bypass robots, paywalls, challenges or site rate limits.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from collector import Entry, HOST, RespectfulClient, parse_chapter, sha256

BOOK_ID = "6af8d3227d54a8afba082141"
BOOK_NAME = "猎魔人：狼学派的狩魔手记"
CN_DIGITS = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2,
             "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
CN_UNITS = {"十": 10, "百": 100, "千": 1000}
CHAPTER_RE = re.compile(r"^第([0-9]+|[零〇一二两三四五六七八九十百千]+)章")


def chapter_number(title: str) -> int | None:
    match = CHAPTER_RE.match(title)
    if not match:
        return None
    raw = match.group(1)
    if raw.isdecimal():
        return int(raw)
    result = 0
    pending = 0
    for char in raw:
        if char in CN_DIGITS:
            pending = CN_DIGITS[char]
        elif char in CN_UNITS:
            result += (pending or 1) * CN_UNITS[char]
            pending = 0
        else:
            raise ValueError("Unknown Chinese numeral character")
    return result + pending


def read_catalog(path: Path, first: int, last: int | None) -> tuple[dict, list[dict], list[dict]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("book_id") != BOOK_ID or not data.get("version"):
        raise ValueError("Wrong book or missing catalog version")
    rows = data.get("rows")
    if not isinstance(rows, list) or len(rows) != data.get("total"):
        raise ValueError("Incomplete index snapshot")
    for pos, row in enumerate(rows):
        if row.get("index") != pos + 1 or not re.fullmatch(r"[a-f0-9]{24}", str(row.get("id", ""))):
            raise ValueError("Invalid index or chapter ID")
    if len({r["id"] for r in rows}) != len(rows):
        raise ValueError("Duplicate chapter IDs in catalog")
    named = [(chapter_number(r["title"]), pos, r) for pos, r in enumerate(rows)]
    anchors = [(pos, row) for number, pos, row in named if number == first]
    if len(anchors) != 1:
        raise ValueError(f"Could not resolve unique author chapter {first}")
    startpos = anchors[0][0]
    if last is None:
        last = max(n for n, _, _ in named if n is not None)
    if last < first:
        raise ValueError("Range end smaller than start")
    targets = rows[startpos:]
    finalpos = next((i for i, r in enumerate(targets) if chapter_number(r["title"]) == last), None)
    if finalpos is None:
        raise ValueError("Requested final chapter not found")
    targets = targets[:finalpos+1]
    # For this book, all chapters in 600+ have an author number and it must be contiguous.
    chapter_nums = [chapter_number(r["title"]) for r in targets]
    required = list(range(first, last+1))
    if chapter_nums != required:
        raise ValueError(f"Source author numbering is missing, duplicated or re-ordered: {chapter_nums[:15]} vs {required[:15]}")
    return data, rows, targets


def atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def load_progress(path: Path, *, version: str, first: int, last: int) -> dict:
    if not path.exists():
        return {
            "status": "PARTIAL", "book_id": BOOK_ID,
            "title": BOOK_NAME, "source": "Jiuxiao",
            "catalog_version": version, "start_author_chapter": first,
            "end_author_chapter": last, "chapters": []
        }
    saved = json.loads(path.read_text(encoding="utf-8"))
    if (saved.get("book_id"), saved.get("catalog_version"),
        saved.get("start_author_chapter"), saved.get("end_author_chapter")) != (BOOK_ID, version, first, last):
        raise ValueError("Cannot resume with a different book, catalog version or chapter range")
    if not isinstance(saved.get("chapters"), list):
        raise ValueError("Invalid progress file")
    return saved


def collect(catalog_path: Path, output: Path, first: int, last: int | None,
            max_new: int | None, delay: float) -> dict:
    data, all_rows, selection = read_catalog(catalog_path, first, last)
    last = chapter_number(selection[-1]["title"])
    assert last is not None
    output.mkdir(parents=True, exist_ok=True)
    folder = output / "chapters"
    folder.mkdir(exist_ok=True)
    state_path = output / "progress.json"
    state = load_progress(state_path, version=str(data["version"]), first=first, last=last)
    cached = state["chapters"]
    if len(cached) > len(selection):
        raise ValueError("Checkpoint has more chapters than catalog")
    seen_hashes = set()
    for i, row in enumerate(cached):
        expected = selection[i]
        number = first+i
        if (row.get("number") != number or row.get("id") != expected["id"]
            or row.get("title") != expected["title"]):
            raise ValueError("Checkpoint chapter order/title/id mismatch")
        fn = row.get("filename")
        if fn != f"{number:04d}.txt":
            raise ValueError("Unsafe or invalid checkpoint filename")
        path = folder / fn
        if not path.is_file():
            raise ValueError(f"Checkpoint text file missing for chapter {number}")
        text = path.read_text(encoding="utf-8")
        if sha256(text) != row.get("sha256") or row.get("paragraphs", 0) < 2:
            raise ValueError(f"Checkpoint digest or paragraph validation failed at {number}")
        if row["sha256"] in seen_hashes:
            raise ValueError("Duplicate chapter text digest in checkpoint")
        seen_hashes.add(row["sha256"])
    to_fetch = len(selection)-len(cached)
    if max_new is not None:
        if max_new < 1:
            raise ValueError("max-new must be positive")
        to_fetch = min(to_fetch, max_new)
    client = RespectfulClient(wait=delay) if to_fetch else None
    # Requests to chapter pages are strictly sequential and spaced by >=2 sec.
    base_pos = all_rows.index(selection[0])
    for idx in range(len(cached),len(cached)+to_fetch):
        row = selection[idx]
        number = first+idx
        chapter_id = row["id"]
        url = f"https://{HOST}/book/{BOOK_ID}/{chapter_id}"
        entry = Entry(number,row["title"],url,chapter_id)
        html = client.get(url)
        title, paragraphs, nxt = parse_chapter(html, entry)
        global_pos = base_pos+idx
        expected_next = all_rows[global_pos+1]["id"] if global_pos+1 < len(all_rows) else None
        if expected_next:
            if not nxt or urlparse(nxt).path.rsplit("/",1)[-1] != expected_next:
                raise ValueError(f"Navigation mismatch after author chapter {number}")
        elif nxt:
            raise ValueError("Unexpected next link after the catalog's final chapter")
        text = "\n\n".join(paragraphs).rstrip()+"\n"
        digest = sha256(text)
        if digest in seen_hashes:
            raise ValueError(f"Duplicate contents in author chapter {number}")
        seen_hashes.add(digest)
        filename = f"{number:04d}.txt"
        atomic_write(folder / filename,text)
        cached.append({
            "number":number, "catalog_index":row["index"],
            "id":chapter_id, "title":title, "source_url":url,
            "filename":filename, "paragraphs":len(paragraphs),
            "characters":len(text), "sha256":digest,
        })
        state["status"]="PARTIAL"
        atomic_write(state_path,json.dumps(state,ensure_ascii=False,indent=2)+"\n")
        print("SAVED",number,f"{len(cached)}/{len(selection)}",
              "chars",len(text),"paragraphs",len(paragraphs),"sha256",digest[:12],flush=True)

    if len(cached)==len(selection):
        text="\n\n\n".join(
            row["title"]+"\n\n"+(folder/row["filename"]).read_text(encoding="utf-8").rstrip()
            for row in cached
        ).rstrip()+"\n"
        atomic_write(output/"book-600-plus.txt",text)
        result={
            "status":"RANGE_COMPLETE",
            "book_id":BOOK_ID,
            "title":BOOK_NAME,
            "source_url":f"https://{HOST}/sim/book/{BOOK_ID}",
            "catalog_version":data["version"],
            "catalog_total":data["total"],
            "source_snapshot_at":data.get("retrieved_at"),
            "start_author_chapter":first,
            "end_author_chapter":last,
            "expected_chapters":len(selection),
            "chapters_collected":len(cached),
            "missing_author_numbers":[],
            "text_characters":len(text),
            "sha256_book_txt":sha256(text),
            "completed_at_utc":datetime.now(timezone.utc).isoformat(),
            "chapters":cached
        }
        atomic_write(output/"manifest.json",json.dumps(result,ensure_ascii=False,indent=2)+"\n")
        state["status"]="RANGE_COMPLETE"
        atomic_write(state_path,json.dumps(state,ensure_ascii=False,indent=2)+"\n")
        print("RANGE_COMPLETE",json.dumps({
            "start":first,"end":last,"chapters":len(cached),"characters":len(text),
            "sha256":sha256(text)
        },ensure_ascii=False),flush=True)
        return result
    print("PARTIAL",json.dumps({"chapters":len(cached),"total":len(selection),
                                "next_author_number":first+len(cached)},ensure_ascii=False),flush=True)
    return state


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--catalog",type=Path,required=True)
    p.add_argument("--out-dir",type=Path,default=Path("out/witcher-600-plus"))
    p.add_argument("--start",type=int,default=600)
    p.add_argument("--end",type=int)
    p.add_argument("--max-new",type=int)
    p.add_argument("--delay",type=float,default=2.0)
    a=p.parse_args()
    collect(a.catalog,a.out_dir,a.start,a.end,a.max_new,a.delay)

if __name__=="__main__":
    try:
        main()
    except Exception as exc:
        print("COLLECT_FAILED",type(exc).__name__,str(exc),file=sys.stderr,flush=True)
        sys.exit(1)
