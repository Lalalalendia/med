#!/usr/bin/env python3
"""Join independently verified ZHYS chapter artifacts into one complete corpus."""
from __future__ import annotations
import argparse
import hashlib
import json
import re
from pathlib import Path


def sha(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def merge(input_dir: Path, output_dir: Path, expected: int = 318) -> dict:
    manifests = sorted(input_dir.glob("*/manifest.json"))
    if len(manifests) != 4:
        raise ValueError(f"Expected four shard manifests, found {len(manifests)}")
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError("Output not empty")
    rows, catalog_proof = {}, None
    seen_hashes = {}
    for path in manifests:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if manifest.get("status") != "PASS":
            raise ValueError(f"{path}: shard not PASS: {manifest.get('status')}")
        if manifest.get("book_id") != 2268838 or manifest.get("source") != "zhys":
            raise ValueError(f"{path}: wrong book/source")
        if manifest.get("catalog_count") != expected:
            raise ValueError(f"{path}: catalog count mismatch")
        fingerprint = sha(json.dumps(
            [(x["ordinal"], x["source_id"], x["url"]) for x in manifest["catalog"]],
            ensure_ascii=False, separators=(",", ":")))
        if catalog_proof and fingerprint != catalog_proof:
            raise ValueError(f"{path}: catalog differs between shards")
        catalog_proof = fingerprint
        requested = manifest["requested"]
        local = set()
        for row in manifest["chapters"]:
            n = row["ordinal"]
            if n in rows or n in local:
                raise ValueError(f"{path}: duplicate ordinal {n}")
            local.add(n)
            if row["status"] != "ok":
                raise ValueError(f"{path}: chapter {n} not ok")
            if n < requested["start"] or n > requested["end"]:
                raise ValueError(f"{path}: chapter outside shard range: {n}")
            relative = Path(row["file"])
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError(f"{path}: unsafe relative path")
            f = path.parent / relative
            if not f.is_file():
                raise ValueError(f"{path}: chapter file missing: {n}")
            content = f.read_text(encoding="utf-8")
            if sha(content) != row["sha256"]:
                raise ValueError(f"{path}: chapter checksum mismatch: {n}")
            if row["body_sha256"] in seen_hashes:
                raise ValueError(f"{path}: duplicated body with chapter {seen_hashes[row['body_sha256']]}")
            seen_hashes[row["body_sha256"]] = n
            rows[n] = (row, f)
        if local != set(range(requested["start"], requested["end"] + 1)):
            raise ValueError(f"{path}: incomplete requested shard")
    if set(rows) != set(range(1, expected + 1)):
        missing = sorted(set(range(1, expected + 1)) - set(rows))
        extra = sorted(set(rows) - set(range(1, expected + 1)))
        raise ValueError(f"Missing {missing}; extra {extra}")
    output_dir.mkdir(parents=True, exist_ok=True)
    raw = output_dir / "raw"
    raw.mkdir()
    collected, clean_rows = [], []
    clean_signatures = set()
    book_title = "漫威，谁把他救出来的？！"
    for n in range(1, expected+1):
        row, source = rows[n]
        original = source.read_text(encoding="utf-8")
        original_title, separator, original_body = original.partition("\n\n")
        if not separator:
            raise ValueError(f"Chapter {n}: no body separator")
        content_lines = original_body.strip().splitlines()
        if (len(content_lines) < 3 or not content_lines[0].startswith("第")
                or content_lines[1] != book_title):
            raise ValueError(f"Chapter {n}: unexpected chapter heading or book label")
        chapter_title = content_lines[0].strip()
        prose_lines = content_lines[2:]
        site_footer = {
            "分享", "猜你喜欢", "🎉", "本书已读至最新章节",
            "新章节更新后将第一时间为您推送", "追到这儿，说两句读后感？",
        }
        if not prose_lines or prose_lines[-1] != "猜你喜欢":
            raise ValueError(f"Chapter {n}: missing expected site-footer boundary")
        while prose_lines and prose_lines[-1] in site_footer:
            prose_lines.pop()
        if n == 1:
            if prose_lines and prose_lines[0] == "无":
                prose_lines.pop(0)
            if prose_lines and prose_lines[-1] == "无":
                prose_lines.pop()
        story = "\n".join(prose_lines).strip()
        if not story or any(x in site_footer for x in prose_lines[-4:]):
            raise ValueError(f"Chapter {n}: site footer not fully removed")
        if len(re.findall(r"[\u3400-\u9fff]", story)) < 180:
            raise ValueError(f"Chapter {n}: too little story text")
        if re.search(r"[\uac00-\ud7a3]", story):
            raise ValueError(f"Chapter {n}: obfuscated Hangul in Chinese body")
        normalized = chapter_title + "\n\n" + story + "\n"
        story_hash = sha(re.sub(r"\s+", "", story))
        if story_hash in clean_signatures:
            raise ValueError(f"Chapter {n}: duplicated normalized story text")
        clean_signatures.add(story_hash)
        dst = raw / f"{n:04d}.txt"
        dst.write_text(normalized, encoding="utf-8")
        collected.append(normalized.rstrip())
        label = re.match(r"^第\s*(\d+)\s*章", chapter_title)
        clean_rows.append({
            **row, "file": str(dst.relative_to(output_dir)),
            "title": chapter_title,
            "author_number": int(label.group(1)) if label else None,
            "original_catalog_title": original_title,
            "original_raw_sha256": row["sha256"],
            "original_body_sha256": row["body_sha256"],
            "sha256": sha(normalized),
            "body_sha256": story_hash,
            "chars": len(story),
            "han": len(re.findall(r"[\u3400-\u9fff]", story)),
            "title_source": "chapter_body",
        })
    combined = "\n\n" + "=" * 72 + "\n\n"
    full = combined.join(collected) + "\n"
    (output_dir / "combined.txt").write_text(full, encoding="utf-8")
    manifest = {"schema_version": 2, "book_key": "marvel-who-rescued-him",
                "source": "zhys", "source_book_url": "https://cn.zhys.tw/book/2268838.html",
                "expected": expected, "verified": len(clean_rows), "status": "PASS",
                "catalog_sha256": catalog_proof,
                "title_fixes": sum(x["original_catalog_title"] != x["title"] for x in clean_rows),
                "combined_sha256": sha(full), "chapters": clean_rows,
                "notion_sync": "not_performed"}
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    (output_dir / "summary.md").write_text(
        "# Marvel Taylor Chinese RAW\n\n"
        f"- Verified **{len(clean_rows)} / {expected}** distinct chapter files\n"
        f"- Total text characters: {len(full)}\n"
        f"- Combined SHA-256: {manifest['combined_sha256']}\n"
        "- Source: ZHYS, metadata/identity matches in all four shards\n"
        f"- Titles repaired from chapter body: {manifest['title_fixes']}\n"
        "- Printed chapter numbers preserved separately (duplicates may be intentional)\n"
        "- Notion sync and Russian translation: not performed\n",
        encoding="utf-8")
    return manifest


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--input-dir", type=Path, required=True)
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--expected", type=int, default=318)
    args = p.parse_args()
    m = merge(args.input_dir,args.out_dir,args.expected)
    print(json.dumps({"status":m["status"],"verified":m["verified"],
                      "combined_sha256":m["combined_sha256"]}))


if __name__=="__main__":
    main()
