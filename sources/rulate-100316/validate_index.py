#!/usr/bin/env python3
"""Validate Rulate 100316 continuation link metadata. No remote fetching."""
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

MANIFEST = Path(__file__).with_name("continuation-370-450.json")


def validate(data: dict) -> None:
    assert data["schema_version"] == 1
    assert data["book"]["rulate_id"] == 100316
    chapters = data["chapters"]
    assert len(chapters) == 81
    assert data["coverage"]["chapters"] == len(chapters)
    assert data["coverage"]["total_part_urls"] == 243
    identities = set()
    for expected_ordinal, row in zip(range(370, 451), chapters, strict=True):
        assert row["catalog_ordinal"] == expected_ordinal
        chapter_id = row["site_chapter_id"]
        assert re.fullmatch(r"[0-9]+", chapter_id)
        assert chapter_id not in identities
        identities.add(chapter_id)
        assert len(row["part_urls"]) == 3
        for part, url in enumerate(row["part_urls"], 1):
            parsed = urlsplit(url)
            assert parsed.scheme == "https" and parsed.hostname == "xszj.org"
            assert parsed.path == f"/b/352919/c/{chapter_id}"
            assert parse_qs(parsed.query) == ({} if part == 1 else {"page": [str(part)]})


if __name__ == "__main__":
    validate(json.loads(MANIFEST.read_text(encoding="utf-8")))
    print("PASS: 81 unique ordered chapters / 243 structurally valid links (not live page validation)")
