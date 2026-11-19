#!/usr/bin/env python3
"""Offline integrity and editorial-noise audit for archived 史莱姆真仙 text.

Never transmits, prints, or changes chapter prose. Reports chapter numbers
and issue categories only. SHA and CRC attest local integrity, not fidelity
to an author-controlled source.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from zipfile import ZipFile

FIRST, LAST = 220, 544
CHAPTER_PATH = re.compile(r"^chapters/(\d{4})\.txt$")
HEAD = re.compile(r"^=== 第(\d{1,4})章 .+ ===$")
NUMBER = re.compile(r"^\d{1,3}$")
BRAND = re.compile(r"101\s*看\s*书|更新不易，记得分享\s*101")
PUNCT_ONLY = frozenset(("：", ":", ".", "。", "?", "？"))
TERMINAL = ("。", "！", "？", "!", "?", "」", "”", "）", ")", "】", "…", ".", '"')
SHA = re.compile(r"^[a-f0-9]{64}$")


def inspect(archive: Path, manifest: Path, min_cjk: int = 2500) -> dict:
    """Audit the known STRICT manifest and ZIP; fail closed on damaged inputs."""
    report = json.loads(manifest.read_text(encoding="utf-8"))
    if report.get("range") != [FIRST, LAST]:
        raise ValueError("unexpected range in seed manifest")
    checksum_map = report.get("sha256")
    if not isinstance(checksum_map, dict) or not checksum_map:
        raise ValueError("manifest must include per-chapter SHA-256")
    numbers = set()
    for label, value in checksum_map.items():
        if not re.fullmatch(r"\d{3}", label):
            raise ValueError(f"invalid number key {label!r}")
        number = int(label)
        if not FIRST <= number <= LAST or str(number) != label:
            raise ValueError(f"unexpected number key {label!r}")
        if not isinstance(value, str) or not SHA.fullmatch(value):
            raise ValueError(f"invalid SHA-256 for {number}")
        numbers.add(number)
    if report.get("verified_full_chapters") != len(numbers):
        raise ValueError("count disagreement between manifest and checksums")
    if min_cjk < 0:
        raise ValueError("min_cjk cannot be negative")

    findings = []
    paragraphs = {}
    with ZipFile(archive) as z:
        member_names = z.namelist()
        if len(member_names) != len(set(member_names)):
            raise ValueError("duplicate ZIP member names")
        actual = {name for name in member_names if CHAPTER_PATH.fullmatch(name)}
        expected = {f"chapters/{n:04d}.txt" for n in numbers}
        if actual != expected:
            raise ValueError("chapter file set differs from manifest")
        if z.testzip() is not None:
            raise ValueError("ZIP CRC failure")

        combined = []
        for number in sorted(numbers):
            payload = z.read(f"chapters/{number:04d}.txt")
            if hashlib.sha256(payload).hexdigest() != checksum_map[str(number)]:
                raise ValueError(f"SHA-256 mismatch in chapter {number}")
            text = payload.decode("utf-8", errors="strict")
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            if not lines or not HEAD.fullmatch(lines[0]):
                raise ValueError(f"invalid title in chapter {number}")
            if int(HEAD.fullmatch(lines[0]).group(1)) != number:
                raise ValueError(f"wrong chapter number in heading {number}")
            combined.append(text.rstrip())

            flags = []
            if lines[-1] == ">":
                flags.append("trailing_html_marker")
            tail = lines[-2] if lines[-1] == ">" and len(lines) > 1 else lines[-1]
            if not tail.endswith(TERMINAL):
                flags.append("suspicious_ending")
            if any(NUMBER.fullmatch(line) for line in lines[1:]):
                flags.append("isolated_number")
            if any(BRAND.search(line) for line in lines[1:]):
                flags.append("site_watermark")
            if any(line in PUNCT_ONLY for line in lines[1:]):
                flags.append("isolated_punctuation")
            cjk = sum("\u3400" <= char <= "\u9fff"
                      for char in "\n".join(lines[1:]))
            if cjk < min_cjk:
                flags.append("low_cjk_volume")

            prose_hash = hashlib.sha256("\n".join(lines[1:]).encode("utf-8")).hexdigest()
            if prose_hash in paragraphs:
                flags.append("duplicate_chapter_body")
                for prior in findings:
                    if prior["chapter"] == paragraphs[prose_hash] and \
                            "duplicate_chapter_body" not in prior["flags"]:
                        prior["flags"].append("duplicate_chapter_body")
                        break
            else:
                paragraphs[prose_hash] = number
            if flags:
                findings.append({"chapter": number, "flags": flags})
        if "combined.txt" in member_names:
            expected_combined = ("\n\n".join(combined) + "\n").encode("utf-8")
            if z.read("combined.txt") != expected_combined:
                raise ValueError("combined.txt does not match original chapter files")

    types = sorted({flag for row in findings for flag in row["flags"]})
    counts = {flag: sum(flag in row["flags"] for row in findings)
              for flag in types}
    return {
        "book": "史莱姆真仙",
        "range": [FIRST, LAST],
        "chapter_files": len(numbers),
        "sha256_verified": len(numbers),
        "zip_crc": "PASS",
        "integrity": "PASS",
        "editorial_quality": "REVIEW_REQUIRED" if findings else "NO_WARNINGS",
        "chapters_with_findings": len(findings),
        "flag_counts": counts,
        "findings": findings,
        "limitations": [
            "SHA-256 and ZIP CRC validate local integrity, not source fidelity.",
            "A length threshold does not prove a chapter is complete.",
            "Suspicious endings are review candidates, not automatic proof of truncation.",
            "Original ZIP files are not changed.",
        ],
    }


def write_report(report: dict, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "quality.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    lines = [
        "# 史莱姆真仙 — аудит архива", "",
        f"SHA-256: {report['sha256_verified']}/{report['chapter_files']} "
        f"(PASS). ZIP CRC: {report['zip_crc']}.", "",
        f"Глав с замечаниями: {report['chapters_with_findings']}.", "",
        "| Класс замечания | Число глав |", "| --- | ---: |",
    ]
    lines.extend(f"| {label} | {count} |"
                 for label, count in report["flag_counts"].items())
    lines += ["", "## Детализация", "",
              "| Глава | Замечания |", "| ---: | --- |"]
    lines.extend(f"| {row['chapter']} | {', '.join(row['flags'])} |"
                 for row in report["findings"])
    lines += ["", "Сохранённые тексты не исправлялись и не выводились в отчёт.",
              "Хеши не доказывают полноту текста по авторскому оригиналу."]
    (destination / "quality.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zip", dest="archive", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--min-cjk", type=int, default=2500)
    args = parser.parse_args()
    quality = inspect(args.archive, args.manifest, args.min_cjk)
    write_report(quality, args.out)
    print("ARCHIVE", quality["integrity"], "chapters",
          quality["chapter_files"], "editorial", quality["editorial_quality"],
          "findings", quality["chapters_with_findings"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
