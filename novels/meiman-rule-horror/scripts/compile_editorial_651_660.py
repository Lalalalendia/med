#!/usr/bin/env python3
"""Package an independently rewritten 651-660 batch, without altering 607-650 or 661-756."""
from __future__ import annotations

from pathlib import Path
import hashlib
import json
import re
import zipfile

ROOT = Path("novels/meiman-rule-horror/ru/literary-edit")
OUT = Path("marvel-literary-bundle")
BEFORE = ROOT / "combined-ru-607-756-EDITORIAL-PASS2-044.txt"
LAST_NEW = 660
FIRST = 607
LAST = 756
HEAD = re.compile(r"(?m)^Глава (\d{3})\.[^\n]*$")
ZH = re.compile(r"[\u3400-\u9fff]")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_chapters(data: str, first: int, last: int) -> dict[int, str]:
    matches = list(HEAD.finditer(data))
    if len(matches) != last - first + 1:
        raise RuntimeError(f"Wrong chapter count: {len(matches)}")
    result = {}
    for i, m in enumerate(matches):
        n = int(m.group(1))
        end = matches[i + 1].start() if i + 1 < len(matches) else len(data)
        if n in result:
            raise RuntimeError(f"Duplicate chapter {n}")
        result[n] = data[m.start():end].strip()
    if sorted(result) != list(range(first, last + 1)):
        raise RuntimeError(f"Gapped or reordered chapters: {list(result)}")
    return result


def main():
    old_text = BEFORE.read_text("utf-8")
    old = parse_chapters(old_text, FIRST, LAST)
    edited = {}
    for n in range(FIRST, LAST_NEW + 1):
        path = ROOT / f"ru-{n:03d}.txt"
        if not path.is_file():
            raise RuntimeError(f"Missing edited chapter {n}: {path}")
        txt = path.read_text("utf-8").strip()
        if not txt.startswith(f"Глава {n}."):
            raise RuntimeError(f"Wrong heading in {path}")
        if len(txt) < 1500 or ZH.search(txt):
            raise RuntimeError(f"Missing text or untranslated Chinese: {path}")
        if n <= 650 and txt != old[n]:
            raise RuntimeError(f"Accepted chapter {n} changed from PASS2")
        edited[n] = txt

    full = {n: edited[n] if n <= LAST_NEW else old[n] for n in range(FIRST, LAST + 1)}
    if any(full[n] != old[n] for n in range(661, LAST + 1)):
        raise RuntimeError("Unreviewed 661-756 changed")
    literary = "\n\n\n".join(edited[n] for n in range(FIRST, LAST_NEW + 1)) + "\n"
    fulltxt = "\n\n\n".join(full[n] for n in range(FIRST, LAST + 1)) + "\n"
    assert len(parse_chapters(literary, FIRST, LAST_NEW)) == 54
    assert len(parse_chapters(fulltxt, FIRST, LAST)) == 150
    for n, txt in full.items():
        if ZH.search(txt):
            raise RuntimeError(f"CJK characters remain in chapter {n}")

    OUT.mkdir(exist_ok=True)
    litname = "Marvel-literary-607-660.txt"
    fullname = "Marvel-ru-607-756-EDITORIAL-PASS3-054.txt"
    zipname = "Marvel-ru-607-756-EDITORIAL-PASS3-054.zip"
    (OUT / litname).write_text(literary, encoding="utf-8")
    (OUT / fullname).write_text(fulltxt, encoding="utf-8")
    (ROOT / "combined-ru-607-660-LITERARY.txt").write_text(literary, encoding="utf-8")
    (ROOT / "combined-ru-607-756-EDITORIAL-PASS3-054.txt").write_text(fulltxt, encoding="utf-8")
    with zipfile.ZipFile(OUT / zipname, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for n in range(FIRST, LAST + 1):
            z.writestr(f"ru-{n:03d}.txt", full[n] + "\n")
    with zipfile.ZipFile(OUT / zipname) as z:
        if z.testzip():
            raise RuntimeError("Bad ZIP CRC")
        expected = [f"ru-{n:03d}.txt" for n in range(FIRST, LAST + 1)]
        if sorted(z.namelist()) != sorted(expected):
            raise RuntimeError("Incorrect ZIP chapter inventory")
        for n in (607, 650, 651, 660, 661, 756):
            body = z.read(f"ru-{n:03d}.txt").decode("utf-8").strip()
            if body != full[n]:
                raise RuntimeError(f"ZIP chapter {n} mismatches TXT")
    metadata = {
        "status": "partially-literary-edited",
        "range": [FIRST, LAST],
        "source_checked_and_literary_rewritten": list(range(607, 661)),
        "literary_count": 54,
        "newly_rewritten": list(range(651, 661)),
        "machine_draft_with_selected_technical_fixes": list(range(661, 757)),
        "machine_draft_count": 96,
        "accepted_607_650_unchanged": True,
        "unreviewed_661_756_unchanged": True,
        "combined_literary_sha256": digest(literary.encode("utf-8")),
        "combined_full_sha256": digest(fulltxt.encode("utf-8")),
        "literary_bytes": len(literary.encode("utf-8")),
        "full_bytes": len(fulltxt.encode("utf-8")),
        "zip_bytes": (OUT / zipname).stat().st_size,
        "warning": "The 661-756 part is machine-translated and not semantically proofread. Source chapter 756 does not conclude the novel."
    }
    report = json.dumps(metadata, ensure_ascii=False, indent=2) + "\n"
    (ROOT / "editorial-report-pass3-054.json").write_text(report, encoding="utf-8")
    (OUT / "Marvel-editorial-report-PASS3-054.json").write_text(report, encoding="utf-8")
    print(json.dumps({k: v for k, v in metadata.items() if k in
         ("status", "literary_count", "machine_draft_count", "literary_bytes", "full_bytes", "zip_bytes", "accepted_607_650_unchanged", "unreviewed_661_756_unchanged")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
