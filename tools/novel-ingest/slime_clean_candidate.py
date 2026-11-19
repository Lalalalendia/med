#!/usr/bin/env python3
"""Make a reversible, conservative CLEAN_CANDIDATE copy from STRICT_229.

Removes only chapter-final '>' markers and standalone 101看书 promos.
Never alters source ZIP or overwrites it. Numeric lines and suspect truncations
are left untouched for source comparison. No network operations.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from slime_archive_quality import inspect

PROMO = re.compile(r"101\s*看\s*书|更新不易，记得分享\s*101")


def standalone_site_promo(line: str) -> bool:
    """Remove an advertisement only when its entire line matches a known template.

    The mere presence of a URL, brand name, or the literal 101看书 inside dialogue
    is NOT enough to discard the containing prose line.
    """
    line = line.strip()
    if not PROMO.search(line):
        return False
    return (
        (line.startswith("本书首发")
         and "提供给你无错章节，无乱序章节的阅读体验" in line)
        or (line.startswith("101看书") and "全手打无错站" in line)
        or (line == "更新不易，记得分享101看书网")
        or (line.startswith("【写到这里我希望读者记一下我们域名")
            and line.endswith("】"))
    )


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def transform(data: bytes, number: int) -> tuple[bytes, list[dict]]:
    lines = data.decode("utf-8", errors="strict").splitlines(keepends=True)
    kept = []
    changes = []
    for line_number, line in enumerate(lines, 1):
        if standalone_site_promo(line):
            changes.append({"operation": "remove_site_ad", "line": line_number})
        else:
            kept.append((line_number, line))
    tail = next((i for i in range(len(kept) - 1, -1, -1)
                 if kept[i][1].strip()), None)
    if tail is not None and kept[tail][1].strip() == ">":
        changes.append({"operation": "remove_trailing_html_marker",
                        "line": kept[tail][0]})
        del kept[tail]
    cleaned = "".join(line for _, line in kept)
    # Leave unchanged files byte-for-byte unchanged.
    if not changes:
        return data, []
    cleaned = cleaned.rstrip() + "\n"
    result = cleaned.encode("utf-8")
    if result == data:
        raise ValueError(f"chapter {number} marked changed but bytes identical")
    return result, changes


def derive(seed_zip: Path, seed_manifest: Path,
           output: Path) -> dict:
    audit = inspect(seed_zip, seed_manifest, min_cjk=0)
    if audit["integrity"] != "PASS":
        raise ValueError("integrity audit failed")
    manifest = json.loads(seed_manifest.read_text("utf-8"))
    output.mkdir(parents=True, exist_ok=True)
    docs = {}
    new_hashes = {}
    edits = []
    for number in sorted(int(n) for n in manifest["sha256"]):
        with ZipFile(seed_zip) as z:
            original = z.read(f"chapters/{number:04d}.txt")
        derived, changes = transform(original, number)
        docs[number] = derived
        new_hashes[str(number)] = digest(derived)
        if changes:
            edits.append({
                "chapter": number,
                "source_sha256": digest(original),
                "derived_sha256": digest(derived),
                "operations": changes,
            })

    result_zip = output / "slime_220-449_cn_CLEAN_CANDIDATE_229.zip"
    with ZipFile(result_zip, "w", ZIP_DEFLATED) as archive:
        for number in sorted(docs):
            archive.writestr(f"chapters/{number:04d}.txt", docs[number])
        archive.writestr("combined.txt",
                         b"\n\n".join(docs[n].rstrip() for n in sorted(docs))
                         + b"\n")
    with ZipFile(result_zip) as archive:
        if archive.testzip() is not None:
            raise ValueError("derived ZIP CRC failure")
        for number, original in docs.items():
            if archive.read(f"chapters/{number:04d}.txt") != original:
                raise ValueError(f"derived ZIP mismatch {number}")

    count_by_action = {
        action: sum(ch["operation"] == action
                    for entry in edits for ch in entry["operations"])
        for action in ("remove_site_ad", "remove_trailing_html_marker")
    }
    payload = {
        "book": "史莱姆真仙",
        "variant": "CLEAN_CANDIDATE_NOT_EDITORIALLY_VERIFIED",
        "source_archive": seed_zip.name,
        "source_manifest": seed_manifest.name,
        "range": manifest["range"],
        "verified_full_chapters": len(docs),
        "sha256": new_hashes,
        "changed_chapters": len(edits),
        "operations": count_by_action,
        "remaining_qa_required": True,
        "caveat": ("Only obvious HTML suffixes and site promotions removed. "
                   "Numeric artifacts and suspicious endings not repaired."),
    }
    (output / "slime_220-449_cn_CLEAN_CANDIDATE_manifest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", "utf-8")
    (output / "slime_clean_candidate_change_log.json").write_text(
        json.dumps({"book": "史莱姆真仙", "changes": edits},
                   ensure_ascii=False, indent=2) + "\n", "utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zip", dest="seed_zip", required=True, type=Path)
    parser.add_argument("--manifest", dest="seed_manifest", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    payload = derive(args.seed_zip, args.seed_manifest, args.out)
    print("CLEAN_CANDIDATE", payload["verified_full_chapters"],
          "changed", payload["changed_chapters"],
          payload["operations"], "QA_REQUIRED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
