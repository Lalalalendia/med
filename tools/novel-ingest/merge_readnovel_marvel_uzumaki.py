#!/usr/bin/env python3
"""Merge previously downloaded ReadNovel archive job artifacts.
No fetching, no paywall access, exact byte/hash/sequence validation.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import zipfile
from pathlib import Path

def main(input_root: Path, output_root: Path) -> int:
    manifests = []
    file_roots = []
    for p in sorted(input_root.rglob("manifest.json")):
        if not p.parent.name.startswith("readnovel-marvel-uzumaki-"):
            continue
        doc = json.loads(p.read_text(encoding="utf-8"))
        if doc.get("source_book_id") != "1032797839":
            raise ValueError(f"Wrong book id: {p}")
        manifests.append(doc)
        file_roots.append(p.parent)
    if len(manifests) != 3:
        raise ValueError(f"Expected 3 independent acquisition batch artifacts, got {len(manifests)}")
    catalog = json.loads((file_roots[0] / "catalog.json").read_text(encoding="utf-8"))
    if len(catalog) != 290:
        raise ValueError(f"Unexpected catalog cardinality: {len(catalog)}")
    for root in file_roots[1:]:
        c = json.loads((root / "catalog.json").read_text(encoding="utf-8"))
        if [(x["ordinal"], x["cid"]) for x in c] != [(x["ordinal"], x["cid"]) for x in catalog]:
            raise ValueError(f"Conflicting catalog: {root}")
    if [x["ordinal"] for x in catalog] != list(range(1, 291)):
        raise ValueError("Catalog numbering has duplicates or gaps")
    output_root.mkdir(parents=True, exist_ok=True)
    raw_dir = output_root / "raw"
    raw_dir.mkdir(exist_ok=True)
    results = {}
    all_hashes = {}
    verified = 0
    for root, manifest in zip(file_roots, manifests):
        for row in manifest["chapters"]:
            n = row["ordinal"]
            if n in results:
                raise ValueError(f"Overlapping batches: {n}")
            if row.get("cid") != catalog[n - 1]["cid"]:
                raise ValueError(f"Source chapter ID mismatch: {n}")
            if row["status"] == "ok":
                source_path = root / row["file"]
                if source_path.name != f"{n:04d}.txt":
                    raise ValueError(f"File naming mismatch: {n}")
                b = source_path.read_bytes()
                digest = hashlib.sha256(b).hexdigest()
                if digest != row.get("sha256"):
                    raise ValueError(f"Incorrect SHA256 for position {n}")
                if len(b) < 400 or len(b.decode("utf-8")) < 300:
                    raise ValueError(f"Unexpectedly short successful chapter: {n}")
                if digest in all_hashes:
                    raise ValueError(f"Identical text at {n} and {all_hashes[digest]}")
                all_hashes[digest] = n
                (raw_dir / source_path.name).write_bytes(b)
                verified += 1
                row = {**row, "verification": "sha256_pass", "raw_file": "raw/" + source_path.name}
            results[n] = row
    if sorted(results) != list(range(1, 291)):
        raise ValueError(f"Missing receipt entries: {set(range(1, 291)) - results.keys()}")
    ordered = [results[n] for n in range(1, 291)]
    fail = len(ordered) - verified
    manifest = {
        "schema_version": 2,
        "book_title": "漫威里的旋涡一族",
        "source_id": "1032797839",
        "readnovel_query": "https://www.readnovel.com/bookquery/zfrhskhvdyjd",
        "catalog_count": 290,
        "verified_raw_count": verified,
        "unavailable_count": fail,
        "is_complete": not bool(fail),
        "source_run": "https://github.com/Lalalalendia/med/actions/runs/45218896040",
        "catalog": catalog,
        "receipts": ordered,
    }
    (output_root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    text_parts = []
    for row in ordered:
        n = row["ordinal"]
        title = row.get("title", catalog[n - 1]["title"])
        if row["status"] == "ok":
            payload = (raw_dir / f"{n:04d}.txt").read_text(encoding="utf-8")
            text_parts.append(f"===== {n:04d} / {title} =====\n{payload.strip()}")
        else:
            text_parts.append(f"===== {n:04d} / {title} =====\n[NOT EXPORTED: {row['status']}]")
    (output_root / "combined_available.txt").write_text(
        "\n\n".join(text_parts) + "\n", encoding="utf-8")
    missing = [{"ordinal": r["ordinal"], "title": r.get("title", ""), "status": r["status"]}
               for r in ordered if r["status"] != "ok"]
    (output_root / "missing.json").write_text(
        json.dumps(missing, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    readme = (
        "# ReadNovel - 漫威里的旋涡一族\n\n"
        f"Сохранено текстов из оглавления: **{verified}/{len(ordered)}**.\n"
        f"Не удалось получить: **{fail}**.\n"
        "Это НЕ полная книга. Позиции оглавления включают сюжетные главы и служебные сообщения автора.\n"
        "В combined_available.txt для отсутствующих позиций оставлены явные маркеры, а не придуманный текст.\n"
        "Исходные тексты находятся в raw/, а контрольные суммы и состояние каждой позиции - в manifest.json.\n"
        "Ссылка на источник: https://www.readnovel.com/bookquery/zfrhskhvdyjd\n"
        "Источник выгрузки: https://github.com/Lalalalendia/med/actions/runs/45218896040\n")
    (output_root / "README_ru.md").write_text(readme, encoding="utf-8")
    zip_path = output_root.parent / "readnovel-1032797839-verified-available.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=7) as archive:
        for file in sorted(output_root.rglob("*")):
            if file.is_file():
                archive.write(file, file.relative_to(output_root).as_posix())
    with zipfile.ZipFile(zip_path) as archive:
        assert archive.testzip() is None
        assert len([x for x in archive.namelist() if x.startswith("raw/")]) == verified
    print(json.dumps({"verified": verified, "missing": fail,
                      "catalog": len(ordered), "output_archive": str(zip_path)}, ensure_ascii=False))
    return 0

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--input-root", type=Path, required=True)
    ap.add_argument("--output-root", type=Path, default=Path("out/consolidated"))
    a = ap.parse_args()
    raise SystemExit(main(a.input_root, a.output_root))
