#!/usr/bin/env python3
"""Build an audited complete story archive from four xbiqiuge shards.

The official verified ReadNovel partial ZIP is used only for independent
cross-checks, not as a substitute for missing content or editorial notes.
"""
from __future__ import annotations
import argparse,difflib,hashlib,json,re,zipfile
from pathlib import Path

CJK=re.compile(r"[\u3400-\u9fff]")

def fingerprint(b:bytes)->str:
    return hashlib.sha256(b).hexdigest()

def run(mirror_input:Path,official_input:Path,out:Path)->None:
    paths=sorted(mirror_input.glob("*/manifest.json"))
    if len(paths)!=4:raise ValueError(f"Expected 4 batches: {paths}")
    rows={}
    catalog=None
    for p in paths:
        base=p.parent
        manifest=json.loads(p.read_text(encoding="utf-8"))
        if manifest.get("source_book_id")!="1032797839" or manifest.get("failed_count")!=0:
            raise ValueError(f"Unverified batch {p}")
        cat=json.loads((base/"catalog.json").read_text(encoding="utf-8"))
        current={r["ordinal"]:r["url"] for r in cat}
        if len(current)!=285 or set(current)!=set(range(285)):raise ValueError(f"Invalid catalog {p}")
        if catalog is not None and current!=catalog:raise ValueError("Conflicting catalogs")
        catalog=current
        for row in manifest["chapters"]:
            n=row["ordinal"]
            if n in rows:raise ValueError(f"Overlapping ordinal {n}")
            if row["status"]!="ok" or row["pages"]<1 or row["pages"]>6:
                raise ValueError(f"Bad status {n}")
            if row["cjk_chars"]<500:raise ValueError(f"Suspiciously short unit {n}")
            b=(base/row["raw_file"]).read_bytes()
            if fingerprint(b)!=row["sha256"]:raise ValueError(f"SHA mismatch {n}")
            if len(CJK.findall(b.decode("utf-8")))<row["cjk_chars"]:
                raise ValueError(f"Length mismatch {n}")
            rows[n]=(dict(row),b)
    if set(rows)!=set(range(285)):raise ValueError(f"Missing positions: {sorted(set(range(285))-set(rows))}")

    # Independently compare selected formerly-free chapters with original HTTPS ReadNovel raw.
    prior=list(official_input.rglob("readnovel-1032797839-verified-available.zip"))
    if len(prior)!=1:raise ValueError(f"Prior official sample ZIP not found: {prior}")
    checks={}
    with zipfile.ZipFile(prior[0]) as old:
        if old.testzip() is not None:raise ValueError("Original partial ZIP corrupt")
        for n in [0,1,10,30,60,90,117,118]:
            old_num=1 if n==0 else n+2
            older=old.read(f"raw/{old_num:04d}.txt").decode("utf-8")
            newer=rows[n][1].decode("utf-8")
            a="".join(CJK.findall(older))
            b="".join(CJK.findall(newer))
            ratio=difflib.SequenceMatcher(None,a[:1300],b[:1300],autojunk=False).ratio()
            checks[str(n)]=round(ratio,4)
            if ratio<0.7:raise ValueError(f"Original versus mirror text mismatch at {n}: {ratio:.3f}")
    print("Independent comparisons:",json.dumps(checks,ensure_ascii=False),flush=True)

    out.mkdir(parents=True,exist_ok=True)
    raw=out/"raw";raw.mkdir(exist_ok=True)
    chapter_rows=[]
    pieces=[]
    seen={}
    for n in range(285):
        row,b=rows[n]
        digest=fingerprint(b)
        if digest in seen:raise ValueError(f"Duplicate body: {n}, {seen[digest]}")
        seen[digest]=n
        (raw/f"{n:04d}.txt").write_bytes(b)
        chapter_rows.append(row)
        pieces.append(f"===== {'ПРОЛОГ' if n==0 else 'ЭПИЛОГ' if n==284 else f'ГЛАВА {n}'} =====\n"+
                      b.decode("utf-8").strip())
    (out/"combined_zh.txt").write_text("\n\n".join(pieces)+"\n",encoding="utf-8")
    (out/"catalog.json").write_text(
        json.dumps([{"ordinal":n,"url":catalog[n]} for n in range(285)],ensure_ascii=False,indent=2),
        encoding="utf-8")
    manifest={
        "book_id":"1032797839","title":"漫威里的旋涡一族",
        "source_book_url":"http://www.xbiqiuge.net/biquge_143731/",
        "original_book_url":"https://www.readnovel.com/bookquery/zfrhskhvdyjd",
        "story_count":285,"numbered_chapters":283,"prologue":1,"epilogue":1,
        "verified_count":len(rows),"missing_story_count":0,"original_catalog_count":290,
        "editorial_notes_included":False,
        "independent_original_excerpt_checks":checks,
        "warning":"Source is HTTP: no transport-level authenticity. Selected texts cross-checked against official HTTPS copy.",
        "chapters":chapter_rows
    }
    (out/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    readme=(
        "# 漫威里的旋涡一族 - собранный китайский оригинал\n\n"
        "Готовность сюжетного текста: 283/283 главы, пролог и эпилог.\n"
        "Это 285 сюжетных позиций. Официальное оглавление содержит 290 позиций,\n"
        "включая служебные сообщения автора, которые сюда не включены.\n\n"
        "Источник текста: http://www.xbiqiuge.net/biquge_143731/\n"
        "Официальная карточка: https://www.readnovel.com/bookquery/zfrhskhvdyjd\n"
        "Особенность: источник работает по HTTP без TLS, поэтому возможна подмена\n"
        "данных на пути. Несколько ранних глав независимо сверены с официальным\n"
        "ранее сохраненным ReadNovel-архивом; поздние главы проверить по оригиналу\n"
        "пока не удалось. Проверьте их перед публикацией.\n\n"
        "raw/: отдельные китайские тексты.\n"
        "combined_zh.txt: весь сюжетный текст.\n"
        "manifest.json: размеры, страницы, URL и SHA256.\n"
        "catalog.json: карта источников.\n")
    (out/"README_ru.md").write_text(readme,encoding="utf-8")
    destination=out.parent/"readnovel-1032797839-complete-story-zh.zip"
    with zipfile.ZipFile(destination,"w",zipfile.ZIP_DEFLATED,compresslevel=7) as z:
        for p in sorted(out.rglob("*")):
            if p.is_file():z.write(p,p.relative_to(out).as_posix())
    with zipfile.ZipFile(destination) as z:
        if z.testzip() is not None:raise ValueError("ZIP validation failed")
        if sum(name.startswith("raw/") for name in z.namelist())!=285:raise ValueError("Wrong ZIP entry count")
    print("COMPLETE",json.dumps({"story_units":285,"chapters":283,"archive_bytes":destination.stat().st_size,
        "crosschecks":checks},ensure_ascii=False))

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--mirror-input",type=Path,required=True)
    p.add_argument("--official-input",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True)
    a=p.parse_args()
    run(a.mirror_input,a.official_input,a.out)
