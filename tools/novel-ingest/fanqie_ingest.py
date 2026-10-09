#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CATALOG_URL = "https://fanqienovel.com/api/reader/directory/detail?bookId={}"
CONTENT_URLS = (
    ("api-content", "http://101.35.133.34:5000/api/content?tab=%E5%B0%8F%E8%AF%B4&item_id={}"),
    ("api-raw-full", "http://101.35.133.34:5000/api/raw_full?item_id={}"),
)

AUTHOR_NO_RE = re.compile(r"^第\s*(\d+)\s*章")
TAG_RE = re.compile(r"<[^>]+>")
CJK_RE = re.compile(r"[\u3400-\u9fff]")


@dataclass
class Chapter:
    ordinal: int
    item_id: str
    title: str
    author_number: int | None


def decode_bytes(data: bytes) -> str:
    for enc in ("utf-8", "gb18030"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            pass
    return data.decode("utf-8", errors="replace")


def curl(url: str, timeout: int = 35) -> tuple[int, str, str]:
    p = subprocess.run(
        [
            "curl",
            "--compressed",
            "--location",
            "--silent",
            "--show-error",
            "--connect-timeout",
            "8",
            "--max-time",
            str(timeout),
            "--retry",
            "0",
            "--user-agent",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/140 Safari/537.36",
            "-w",
            "\n__HTTP__%{http_code}",
            url,
        ],
        capture_output=True,
    )
    marker = b"\n__HTTP__"
    body_b, sep, code_b = p.stdout.rpartition(marker)
    if sep:
        body = decode_bytes(body_b)
        code = code_b.decode("ascii", errors="replace")
    else:
        body = decode_bytes(p.stdout)
        code = ""
    err = decode_bytes(p.stderr)
    return p.returncode, code, body + ("" if not err else ""), err


def get_json(url: str, timeout: int = 35) -> dict[str, Any]:
    rc, code, body, err = curl(url, timeout=timeout)
    if rc != 0 and not body:
        raise RuntimeError(f"curl rc={rc} http={code}: {err[-300:]}")
    if code and code != "200":
        raise RuntimeError(f"http={code}: {body[:300]}")
    try:
        obj = json.loads(body)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"invalid/truncated JSON (rc={rc}, http={code}, chars={len(body)}): {e}"
        ) from e
    if not isinstance(obj, dict):
        raise RuntimeError("JSON root is not an object")
    return obj


def parse_catalog(root: dict[str, Any]) -> list[Chapter]:
    data = root.get("data") or {}
    volumes = data.get("chapterListWithVolume") or []
    entries: list[dict[str, Any]] = []
    for volume in volumes:
        if isinstance(volume, list):
            entries.extend(x for x in volume if isinstance(x, dict))
        elif isinstance(volume, dict):
            items = volume.get("items") or volume.get("chapterList") or []
            entries.extend(x for x in items if isinstance(x, dict))
    chapters: list[Chapter] = []
    for i, ent in enumerate(entries, 1):
        item_id = str(ent.get("itemId") or ent.get("item_id") or "")
        if not item_id:
            continue
        title = str(ent.get("title") or "")
        m = AUTHOR_NO_RE.match(title)
        chapters.append(
            Chapter(
                ordinal=len(chapters) + 1,
                item_id=item_id,
                title=title,
                author_number=int(m.group(1)) if m else None,
            )
        )
    if not chapters:
        raise RuntimeError("official Fanqie catalog returned no chapters")
    return chapters


def clean_content(raw: str) -> str:
    text = raw.replace("\\u003c", "<").replace("\\u003e", ">")
    text = TAG_RE.sub("\n", text)
    text = html.unescape(text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_content(root: dict[str, Any]) -> tuple[str, str | None]:
    data = root.get("data") or {}
    if not isinstance(data, dict):
        return "", None
    content = data.get("content") or ""
    title = data.get("title") or data.get("chapter_title") or data.get("name")
    return clean_content(str(content)), str(title) if title else None


def fetch_chapter(item_id: str, retries: int = 2) -> tuple[str, str, str | None]:
    errors: list[str] = []
    for attempt in range(retries + 1):
        for source, template in CONTENT_URLS:
            url = template.format(item_id)
            try:
                root = get_json(url, timeout=45 if source == "api-raw-full" else 30)
                content, api_title = extract_content(root)
                cjk = len(CJK_RE.findall(content))
                if len(content) < 500 or cjk < 250:
                    raise RuntimeError(
                        f"too short: chars={len(content)} cjk={cjk}"
                    )
                return source, content, api_title
            except Exception as e:
                errors.append(f"{source} attempt {attempt + 1}: {e}")
        if attempt < retries:
            time.sleep(2 + attempt * 2)
    raise RuntimeError(" | ".join(errors[-8:]))


def parse_ordinals(spec: str, total: int) -> list[int]:
    if not spec:
        return list(range(1, total + 1))
    out: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            out.update(range(int(a), int(b) + 1))
        else:
            out.add(int(part))
    bad = [n for n in out if n < 1 or n > total]
    if bad:
        raise SystemExit(f"ordinals out of range 1..{total}: {bad}")
    return sorted(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--book-id", required=True)
    ap.add_argument("--slug", required=True)
    ap.add_argument("--ordinals", default="")
    ap.add_argument("--out-root", type=Path, default=Path("out/fanqie"))
    args = ap.parse_args()

    catalog_root = get_json(CATALOG_URL.format(args.book_id), timeout=30)
    chapters = parse_catalog(catalog_root)
    selected = parse_ordinals(args.ordinals, len(chapters))

    out_dir = args.out_root / args.slug
    chapter_dir = out_dir / "chapters"
    chapter_dir.mkdir(parents=True, exist_ok=True)

    manifest: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    for n in selected:
        ch = chapters[n - 1]
        try:
            source, content, api_title = fetch_chapter(ch.item_id)
            title = ch.title or api_title or f"第{n}章"
            text = f"{title}\n\n{content.strip()}\n"
            sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
            author_tag = (
                f"author-{ch.author_number:03d}"
                if ch.author_number is not None
                else "author-none"
            )
            filename = f"{ch.ordinal:03d}_{author_tag}_{ch.item_id}.txt"
            (chapter_dir / filename).write_text(text, encoding="utf-8")
            row = {
                "ordinal": ch.ordinal,
                "author_number": ch.author_number,
                "item_id": ch.item_id,
                "title": title,
                "catalog_title": ch.title,
                "api_title": api_title,
                "source": source,
                "chars": len(content),
                "cjk": len(CJK_RE.findall(content)),
                "sha256": sha,
                "file": str(Path("chapters") / filename),
            }
            manifest.append(row)
            print(json.dumps({"ok": row}, ensure_ascii=False), flush=True)
        except Exception as e:
            row = {
                "ordinal": ch.ordinal,
                "author_number": ch.author_number,
                "item_id": ch.item_id,
                "title": ch.title,
                "error": str(e),
            }
            failures.append(row)
            print(json.dumps({"failure": row}, ensure_ascii=False), flush=True)

    (out_dir / "manifest.jsonl").write_text(
        "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in manifest),
        encoding="utf-8",
    )
    summary = {
        "book_id": args.book_id,
        "catalog_entries": len(chapters),
        "catalog_max_author_number": max(
            (c.author_number or 0) for c in chapters
        ),
        "selected": selected,
        "downloaded": len(manifest),
        "failures": failures,
        "duplicate_author_numbers": sorted(
            n
            for n in {c.author_number for c in chapters if c.author_number is not None}
            if sum(c.author_number == n for c in chapters) > 1
        ),
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    if failures:
        raise SystemExit(f"{len(failures)} chapter(s) failed")


if __name__ == "__main__":
    main()
