#!/usr/bin/env python3
"""Offline assembly of author-supplied Japanese novel exports.

NO NETWORK ACCESS. Narou's terms prohibit automatic chapter scraping.
This tool reads only local files supplied by an authorized rights holder.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
import sys
import zipfile
from pathlib import Path

MAX_MEMBER_BYTES = 4_000_000
MAX_TOTAL_BYTES = 100_000_000
KAKUYOMU_RE = re.compile(r"(?:^|/)episode_(\d{1,6})\.txt$", re.I)
LOCAL_RE = re.compile(r"^(?:episode_|chapter_)?(\d{1,6})\.txt$", re.I)
NAROU_RE = re.compile(r"(?:^|/)(n[0-9a-z]{5,8})\.txt$", re.I)


class ImportFailure(Exception):
    pass


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def decode_text(data: bytes, encoding: str, source: str) -> str:
    if len(data) > MAX_MEMBER_BYTES and source != "narou-author":
        raise ImportFailure(f"Too large: {source}")
    if b"\x00" in data:
        raise ImportFailure(f"NUL byte in {source}")
    try:
        result = data.decode("utf-8-sig" if encoding == "utf-8" else encoding)
    except UnicodeError as exc:
        raise ImportFailure(f"Cannot decode {source} as {encoding}") from exc
    result = result.replace("\r\n", "\n").replace("\r", "\n")
    if not result.strip():
        raise ImportFailure(f"Empty text: {source}")
    return result


def members_from_zip(path: Path) -> list[tuple[str, bytes]]:
    try:
        with zipfile.ZipFile(path) as archive:
            if archive.testzip() is not None:
                raise ImportFailure("ZIP CRC check failed")
            rows = []
            total = 0
            for info in archive.infolist():
                if info.is_dir():
                    continue
                if info.flag_bits & 1:
                    raise ImportFailure("Encrypted archive not supported")
                if ((info.external_attr >> 16) & 0o170000) == stat.S_IFLNK:
                    raise ImportFailure("Symlink in ZIP not allowed")
                if info.file_size > MAX_MEMBER_BYTES:
                    raise ImportFailure(f"Oversized ZIP entry: {info.filename}")
                total += info.file_size
                if total > MAX_TOTAL_BYTES:
                    raise ImportFailure("ZIP uncompressed size is too large")
                name = info.filename.replace("\\", "/")
                if name.startswith("/") or ".." in name.split("/"):
                    raise ImportFailure(f"Unsafe ZIP member path: {name}")
                data = archive.read(info)
                rows.append((name, data))
            return rows
    except zipfile.BadZipFile as exc:
        raise ImportFailure("Invalid ZIP") from exc


def load_episodes(path: Path, mode: str, encoding: str) -> dict[int, tuple[str, bytes]]:
    if mode == "kakuyomu-zip":
        if not path.is_file() or path.suffix.lower() != ".zip":
            raise ImportFailure("kakuyomu-zip expects a .zip file")
        candidates = members_from_zip(path)
        regex = KAKUYOMU_RE
    elif mode == "episode-directory":
        if not path.is_dir():
            raise ImportFailure("episode-directory expects a folder")
        candidates = [(p.name, p.read_bytes()) for p in path.iterdir() if p.is_file()]
        regex = LOCAL_RE
    else:
        raise ImportFailure("Unknown episode source mode")
    seen: dict[int, tuple[str, bytes]] = {}
    for name, raw in candidates:
        match = regex.search(name)
        if not match:
            continue
        ordinal = int(match.group(1))
        if not 1 <= ordinal <= 100_000:
            raise ImportFailure(f"Invalid ordinal {ordinal}")
        if ordinal in seen:
            raise ImportFailure(f"Duplicate episode number {ordinal}: {seen[ordinal][0]} and {name}")
        if len(raw) > MAX_MEMBER_BYTES:
            raise ImportFailure(f"Oversized episode: {name}")
        # Reject empty/malformed file before claiming the episode exists.
        decode_text(raw, encoding, name)
        seen[ordinal] = (name, raw)
    if not seen:
        raise ImportFailure("No numbered episode files found")
    return seen


def load_narou_author_export(path: Path, encoding: str, ncode: str) -> tuple[str, bytes]:
    if path.suffix.lower() == ".zip":
        rows = members_from_zip(path)
        matching = [(n, b) for n, b in rows if (m := NAROU_RE.search(n)) and m.group(1).lower() == ncode.lower()]
        if len(matching) != 1:
            raise ImportFailure(f"Expected exactly one {ncode}.txt in author ZIP; got {len(matching)}")
        name, raw = matching[0]
    elif path.suffix.lower() == ".txt":
        name, raw = path.name, path.read_bytes()
    else:
        raise ImportFailure("Narou author export must be a .txt or .zip")
    if len(raw) > MAX_TOTAL_BYTES:
        raise ImportFailure("Oversized author backup")
    decode_text(raw, encoding, name)
    return name, raw


def run(path: Path, output: Path, *, mode: str, expected: int, ncode: str, encoding: str) -> dict:
    if not re.fullmatch(r"n[0-9a-z]{5,8}", ncode, re.I):
        raise ImportFailure("Invalid N-code")
    if expected < 1 or expected > 100_000:
        raise ImportFailure("Expected count must be positive")
    if output.exists() and any(output.iterdir()):
        raise ImportFailure("Output folder must be empty; refusing to overwrite previous work")
    if mode == "narou-author":
        # Narou's author backup contains prose AND work/episode metadata in one TXT.
        # It is deliberately kept intact; we cannot infer episode boundaries safely.
        name, raw = load_narou_author_export(path, encoding, ncode)
        output.mkdir(parents=True, exist_ok=True)
        body = decode_text(raw, encoding, name)
        target = output / "narou_author_export.txt"
        target.write_text(body, encoding="utf-8")
        result = {
            "schema": 1, "ncode": ncode.upper(), "mode": mode, "expected_episodes": expected,
            "source_name": name, "source_sha256": sha256(raw),
            "normalized_sha256": sha256(target.read_bytes()),
            "status": "UNSEGMENTED_AUTHOR_BACKUP", "confirmed_episodes": 0,
            "ready_for_translation": False,
            "note": "Author TXT contains work metadata; episode delimiters need verification before splitting.",
        }
        (output / "manifest.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return result

    rows = load_episodes(path, mode, encoding)
    actual = sorted(rows)
    expected_ordinals = list(range(1, expected + 1))
    missing = sorted(set(expected_ordinals) - set(actual))
    extra = sorted(set(actual) - set(expected_ordinals))
    result = {
        "schema": 1, "ncode": ncode.upper(), "mode": mode,
        "expected_episodes": expected, "found_episodes": len(rows),
        "missing": missing, "extra": extra,
        "status": "COMPLETE" if actual == expected_ordinals else "PARTIAL",
        "ready_for_translation": actual == expected_ordinals,
        "episodes": [],
    }
    output.mkdir(parents=True, exist_ok=True)
    if missing or extra:
        (output / "manifest.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return result
    chapter_dir = output / "episodes"
    chapter_dir.mkdir()
    combined = []
    for number in actual:
        filename, raw = rows[number]
        value = decode_text(raw, encoding, filename)
        # Preserve original ruby notation and Japanese punctuation. Normalize line endings only.
        value = value.rstrip("\n") + "\n"
        data = value.encode("utf-8")
        relative = f"episodes/{number:04d}.txt"
        (output / relative).write_bytes(data)
        result["episodes"].append({"index": number, "source_filename": filename,
                                  "file": relative, "characters": len(value),
                                  "source_sha256": sha256(raw), "sha256": sha256(data)})
        combined.append(f"=== EPISODE {number:04d} ===\n\n{value}\n")
    compiled = output / "combined_ja.txt"
    compiled.write_text("\n".join(combined), encoding="utf-8")
    result["combined_sha256"] = sha256(compiled.read_bytes())
    manifest = output / "manifest.json"
    manifest.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with zipfile.ZipFile(output / "complete_ja.zip", "w", compression=zipfile.ZIP_DEFLATED, compresslevel=8) as z:
        for item in result["episodes"]:
            z.write(output / item["file"], arcname=item["file"])
        z.write(compiled, arcname=compiled.name)
        z.write(manifest, arcname=manifest.name)
    with zipfile.ZipFile(output / "complete_ja.zip") as z:
        assert z.testzip() is None
    return result


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", type=Path, required=True, help="Authorized local TXT/ZIP or episode folder")
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--mode", choices=("narou-author", "kakuyomu-zip", "episode-directory"), required=True)
    p.add_argument("--expected", type=int, default=217)
    p.add_argument("--ncode", default="N9107EE")
    p.add_argument("--encoding", choices=("utf-8", "shift_jis", "euc_jp"), default="utf-8")
    args = p.parse_args()
    try:
        report = run(args.input, args.output, mode=args.mode, expected=args.expected,
                     ncode=args.ncode, encoding=args.encoding)
    except (ImportFailure, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({k: v for k, v in report.items() if k != "episodes"}, ensure_ascii=False, indent=2))
    return 0 if report["ready_for_translation"] or report["status"] == "UNSEGMENTED_AUTHOR_BACKUP" else 3


if __name__ == "__main__":
    raise SystemExit(main())
