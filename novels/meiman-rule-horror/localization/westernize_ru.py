#!/usr/bin/env python3
"""Conservative literary Westernization of the Russian Meiman translation.

Run only on an isolated branch. The source commit is retained in Git history.
Replaces a reviewed glossary, not arbitrary Chinese-looking strings.
"""
from __future__ import annotations

import collections
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
ROOT = BASE / "ru"
LOCAL = BASE / "localization"
OUT = Path("marvel-ru-westernized-artifacts")
GLOSSARY = LOCAL / "westernization-ru.json"
CHAPTER_RE = re.compile(r"^(?:\d{3}|396b)\.txt$")
LETTER = r"[^\W\d_]"  # Unicode letters; avoid replacing inside other words.


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def replacements():
    spec = json.loads(GLOSSARY.read_text(encoding="utf-8"))
    seen = {}
    for old, new in list(spec["names"]) + list(spec["terms"]):
        if old in seen and seen[old] != new:
            raise ValueError(f"Contradictory mapping for {old!r}")
        seen[old] = new
    ordered = sorted((key for key in seen if key != seen[key]), key=lambda x: (-len(x), x))
    pattern = re.compile(r"(?<!" + LETTER + r")(?:"
                         + "|".join(re.escape(old) for old in ordered) + r")(?!" + LETTER + r")")
    return pattern, seen


def westernize(body: str, rules, counters: collections.Counter) -> str:
    pattern, mapping = rules

    def swap(match):
        original = match.group(0)
        counters[original] += 1
        return mapping[original]

    return pattern.sub(swap, body)


def build_zip(path: Path, sources: dict[str, bytes], identifiers: list[str]):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as output:
        for key in identifiers:
            info = zipfile.ZipInfo(f"ru-{key}.txt", date_time=(2026, 11, 14, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            output.writestr(info, sources[key])
    with zipfile.ZipFile(path) as verify:
        assert verify.testzip() is None
        assert sorted(verify.namelist()) == sorted(f"ru-{k}.txt" for k in identifiers)


def main():
    dry_run = "--check" in sys.argv
    rules = replacements()
    chapters = sorted(p for p in ROOT.iterdir() if p.is_file() and CHAPTER_RE.fullmatch(p.name))
    ids = [f"{n:03d}" for n in range(1, 607) if n != 226]
    ids.insert(ids.index("396") + 1, "396b")
    available = {p.stem for p in chapters}
    if available != set(ids):
        raise RuntimeError(f"Missing or unexpected chapter files: {sorted(available ^ set(ids))}")
    if len(ids) != 606:
        raise RuntimeError(f"Expected 605 numbered chapters + 396-bis, got {len(ids)}")

    counts = collections.Counter()
    changed = []
    latest = {}
    manifest = []
    for chapter in chapters:
        original = chapter.read_bytes()
        source = original.decode("utf-8")
        local_count = collections.Counter()
        translated = westernize(source, rules, local_count)
        if chapter.stem != "396b" and not translated.startswith(f"Глава {int(chapter.stem)}."):
            raise RuntimeError(f"Wrong heading: {chapter}")
        if re.search(r"[\u3400-\u9fff]", translated):
            raise RuntimeError(f"Untranslated CJK characters: {chapter}")
        new_data = translated.encode("utf-8")
        latest[chapter.stem] = new_data
        counts.update(local_count)
        if new_data != original:
            changed.append(chapter.name)
            if not dry_run:
                chapter.write_bytes(new_data)
        manifest.append({"chapter": chapter.stem, "before": sha(original), "after": sha(new_data),
                         "changes": sum(local_count.values())})

    combined_files = []
    for path in sorted(ROOT.glob("combined-ru-*.txt")):
        original = path.read_bytes()
        local_count = collections.Counter()
        transformed = westernize(original.decode("utf-8"), rules, local_count).encode("utf-8")
        counts.update(local_count)
        if transformed != original:
            combined_files.append(path.name)
            if not dry_run:
                path.write_bytes(transformed)

    if dry_run:
        if changed or combined_files:
            raise RuntimeError(f"Westernization not idempotent; {len(changed)} chapters "
                               f"and {len(combined_files)} combined files would change")
        print(json.dumps({"status": "PASS", "chapters": len(ids), "remaining_changes": 0}))
        return

    OUT.mkdir(parents=True, exist_ok=True)
    def assemble(selected):
        return b"\n\n\n".join(latest[key].rstrip(b"\n") for key in selected) + b"\n"

    all_text = assemble(ids)
    recent = [f"{n:03d}" for n in range(597, 607)]
    last_twenty = [f"{n:03d}" for n in range(587, 607)]
    cumulative_name = "combined-ru-001-606-gap-226.txt"
    (ROOT / cumulative_name).write_bytes(all_text)
    (OUT / cumulative_name).write_bytes(all_text)
    (OUT / "combined-ru-597-606.txt").write_bytes(assemble(recent))
    (OUT / "combined-ru-587-606.txt").write_bytes(assemble(last_twenty))
    build_zip(OUT / "reader-ru-597-606.zip", latest, recent)
    build_zip(OUT / "reader-ru-001-606-gap-226.zip", latest, ids)
    report = {
        "chapters": len(ids), "missing": [226], "extra": ["396b"],
        "numbered_last": 606, "changed_chapter_files": len(changed),
        "changed_combined_files": len(combined_files),
        "replacement_count": sum(counts.values()),
        "counts": dict(counts.most_common()),
        "files": manifest,
        "cumulative_sha256": sha(all_text),
        "cumulative_bytes": len(all_text),
        "artifacts": [p.name for p in sorted(OUT.iterdir())]
    }
    (OUT / "westernization-audit.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (LOCAL / "westernization-report.md").write_text(
        "# RU literary Westernization, through chapter 606\n\n"
        f"- Source chapters: {len(ids)} (226 absent, 396-bis retained).\n"
        f"- Individual chapter files modified: {len(changed)}.\n"
        f"- Existing combined files modified: {len(combined_files)}.\n"
        f"- Exact glossary substitutions: {sum(counts.values())}.\n"
        f"- Complete westernized TXT sha256: \`{sha(all_text)}\`.\n\n"
        "Originals are preserved on the parent branch. Named canonical works, "
        "Marvel characters and historical figures were intentionally not automatically renamed.\n",
        encoding="utf-8"
    )
    print(json.dumps({
        "chapters": len(ids), "changed": len(changed),
        "combined_changed": len(combined_files), "replacements": sum(counts.values()),
        "cumulative_bytes": len(all_text), "top_replacements": counts.most_common(15)
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
