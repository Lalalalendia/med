#!/usr/bin/env python3
"""Six short Webnovel chapters: rights-confirmed source QA, not publication.

Fetch original public HTML through the current med parser, using a lower
*diagnostic* threshold, and retain short source bodies for human review.
Never classify short texts as valid novel prose without review.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import time
from pathlib import Path

import requests
from source_ingest import run_ingest

NUMBERS = (88, 89, 109, 115, 195, 315)
BOOK_URL = "https://www.webnovel.com/book/6831835502000105/catalog"
WARNING = re.compile(
    r"chapter is locked|purchase this chapter|unlock this chapter|"
    r"sign in|login to read|read more|subscribe|earn rewards|"
    r"download the app|enable javascript|captcha|access denied|"
    r"more free chapters|pay to read|next chapter|previous chapter", re.I)


def inspect(body: str) -> dict:
    clean = re.sub(r"\s+", " ", body).strip()
    return {
        "characters": len(re.sub(r"\s+", "", body)),
        "words": len(clean.split(" ")),
        "paragraphs": len([x for x in body.splitlines() if x.strip()]),
        "sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
        "access_or_ui_marker": bool(WARNING.search(body)),
    }


def run(out: Path):
    if out.exists() and any(out.iterdir()):
        raise ValueError("Output directory must be empty")
    out.mkdir(parents=True, exist_ok=True)
    sessions = requests.Session()
    rows = []
    try:
        for i, ordinal in enumerate(NUMBERS):
            tmp = out / f"tmp_{ordinal}"
            result = run_ingest(
                source="webnovel", book_url=BOOK_URL, start=ordinal,
                end=ordinal, out_dir=tmp, delay=2,
                min_chars=100, book_key="masked-knight",
                session=sessions)
            ch = result["chapters"][0] if result["chapters"] else {
                "ordinal": ordinal, "status": result["status"]}
            row = {"ordinal": ordinal, "status": ch["status"],
                   "url": ch.get("url"), "title": ch.get("title"),
                   "error": ch.get("error")}
            if ch.get("status") == "ok":
                raw = (tmp / ch["raw_file"]).read_text(encoding="utf-8")
                details = inspect(raw)
                row.update(details)
                dest = out / "review"
                dest.mkdir(exist_ok=True)
                (dest / f"{ordinal:04d}.txt").write_text(
                    raw, encoding="utf-8")
                row["verdict"] = ("SUSPICIOUS_REVIEW"
                                  if details["access_or_ui_marker"]
                                  else "SHORT_REQUIRES_MANUAL_REVIEW")
            rows.append(row)
            shutil.rmtree(tmp, ignore_errors=True)
            if i + 1 < len(NUMBERS):
                time.sleep(2)
    finally:
        sessions.close()
    manifest = {"status": "REVIEW_REQUIRED", "book":"Masked Knight",
                "source_url": BOOK_URL,
                "targeted_chapters": NUMBERS,
                "rights_confirmed": True,
                "chapters": rows}
    (out / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    return manifest


if __name__ == "__main__":
    run(Path("out/masked-knight-short-chapters"))
