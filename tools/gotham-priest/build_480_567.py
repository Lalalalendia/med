#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

ROOT = Path("novels/gotham-priest")
SOURCE = ROOT / "source" / "tail-516-567.txt"
RAW = ROOT / "raw"
SUDUGUU_RAW = Path("novels/suduguu/2322/raw")

START = 480
BRIDGE_START = 516
END = 567

def parse_tail(text: str) -> dict[int, tuple[str, str]]:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    rx = re.compile(r"(?m)^\s*第\s*(\d{1,4})\s*章\s*([^\n]*)\s*$")
    matches = list(rx.finditer(text))
    out: dict[int, tuple[str, str]] = {}
    for i, m in enumerate(matches):
        n = int(m.group(1))
        title = m.group(2).strip(" ：:　")
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        if BRIDGE_START <= n <= END:
            out[n] = (title, body)
    return out

def main() -> int:
    if not SOURCE.exists():
        raise SystemExit(f"Missing source: {SOURCE}")

    RAW.mkdir(parents=True, exist_ok=True)

    # Canonicalize the already-collected Suduguu segment into the project folder.
    missing_old = []
    for n in range(START, BRIDGE_START):
        src = SUDUGUU_RAW / f"{n:03d}.txt"
        if not src.exists():
            missing_old.append(n)
            continue
        shutil.copyfile(src, RAW / src.name)
    if missing_old:
        raise SystemExit(f"Missing Suduguu chapters: {missing_old}")

    tail = parse_tail(SOURCE.read_text(encoding="utf-8"))
    missing_tail = [n for n in range(BRIDGE_START, END + 1) if n not in tail]
    if missing_tail:
        raise SystemExit(f"Missing uploaded-tail chapters: {missing_tail}")

    for n in range(BRIDGE_START, END + 1):
        title, body = tail[n]
        if len(body) < 200:
            raise SystemExit(f"Chapter {n} unexpectedly short: {len(body)} chars")
        (RAW / f"{n:03d}.txt").write_text(
            f"Chapter: {n}\n"
            f"Source: user-supplied complete TXT\n"
            f"Source file: 人在哥谭当神父，开局捡到小男孩 完本.txt\n"
            f"CN-Title: 第{n}章 {title}\n\n"
            f"{body}\n",
            encoding="utf-8",
        )

    expected = list(range(START, END + 1))
    present = [n for n in expected if (RAW / f"{n:03d}.txt").exists()]
    if present != expected:
        missing = sorted(set(expected) - set(present))
        raise SystemExit(f"Canonical RAW gap: {missing}")

    manifest = []
    combined = []
    for n in expected:
        path = RAW / f"{n:03d}.txt"
        text = path.read_text(encoding="utf-8")
        title_match = re.search(r"(?m)^CN-Title:\s*(.+)$", text)
        manifest.append({
            "chapter": n,
            "title": title_match.group(1).strip() if title_match else "",
            "source": "suduguu" if n < BRIDGE_START else "user-supplied-complete-txt",
            "file": str(path.relative_to(ROOT)),
            "chars": len(text),
        })
        combined.append(text.rstrip())

    (ROOT / "manifest-480-567.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (ROOT / "combined-480-567.txt").write_text(
        ("\n\n" + "=" * 72 + "\n\n").join(combined) + "\n",
        encoding="utf-8",
    )
    (ROOT / "summary.md").write_text(
        "# 人在哥谭当神父，开局捡到小男孩 — RAW 480–567\n\n"
        "- Canonical range: 480–567\n"
        "- Chapters: 88/88\n"
        "- 480–515: Suduguu\n"
        "- 516–567: user-supplied complete TXT\n"
        "- Final chapter: 第567章 大结局：三位一体\n",
        encoding="utf-8",
    )

    print("canonical chapters", len(expected))
    print("tail chapters", len(tail))
    print("first tail", tail[BRIDGE_START][0])
    print("final", tail[END][0])
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
