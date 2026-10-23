#!/usr/bin/env python3
"""Reconstruct authorized CN 330-chapter Notion source artifact, no prose in Git."""
from __future__ import annotations
import argparse, hashlib, json, re, statistics
from pathlib import Path

ORIGINAL_SHA = "da745ca09bb35b35e168eaf74d888133fe0d7e22c2a486ef4dd8f2cd0a5c371e"
COMBINED_SHA = "ce71af7527675e400b4fb09de0778c2485e439d0ba5fe1f53f4f8f1c852f1d1a"
CJK = re.compile(r"[\u3400-\u9fff]")
HEAD = re.compile(r"^\s*(?:(?:第?[一二三四五六七八九十百千两兩零〇0-9]{1,6}卷|卷[一二三四五六七八九十百千两兩零〇0-9]{1,6}|天界之卷|[\u4e00-\u9fff]{2,7}卷)\s*)?第\s*([零〇一二三四五六七八九十百千两兩0-9]{1,15})\s*章(?:\s|[【〖（(]|$).{0,90}$")
DIGITS = dict(zip("零〇一二三四五六七八九", (0,0,1,2,3,4,5,6,7,8,9)))
DIGITS.update({"两":2, "兩":2})
UNITS = {"十":10,"百":100,"千":1000}

def number(raw):
    if raw.isdecimal(): return int(raw)
    total=part=0
    for ch in raw:
        if ch in DIGITS: part=DIGITS[ch]
        elif ch in UNITS: total+=max(1,part)*UNITS[ch];part=0
        else: return None
    return total+part

def package(src:Path,out:Path):
    original=src.read_bytes()
    if hashlib.sha256(original).hexdigest()!=ORIGINAL_SHA or len(original)!=4875554:
        raise ValueError("Source does not match previously verified original")
    text=original.decode("utf-8-sig")
    starts=[];pos=0
    for line in text.splitlines(keepends=True):
        v=line.strip().lstrip("\ufeff").split("\u3000\u3000",1)[0].strip()
        match=HEAD.match(v) if len(v)<140 else None
        if match:
            n=number(match.group(1))
            if n is not None and 1<=n<=330: starts.append((n,v,pos))
        pos+=len(line)
    if [n for n,_,_ in starts]!=list(range(1,331)):
        raise ValueError("Chapter numbering is incomplete, nonmonotonic or duplicated")
    (out/"source").mkdir(parents=True,exist_ok=True)
    (out/"chapters").mkdir(exist_ok=True)
    (out/"qa").mkdir(exist_ok=True)
    (out/"source"/"original_full.txt").write_bytes(original)
    combined=[]; chapters=[]; flags=[];removed_total=0
    for i,(n,title,begin) in enumerate(starts):
        end=starts[i+1][2] if i+1<len(starts) else len(text)
        raw=text[begin:end]
        first=raw.splitlines()[0].lstrip(" \t\u3000\ufeff")
        if not first.startswith(title): raise ValueError(f"Wrong header at {n}")
        spill=first[len(title):].lstrip(" \t\u3000")
        rest="\n".join(([spill] if spill else [])+raw.splitlines()[1:])
        lines=[];removed=0
        for line in rest.splitlines():
            s=line.strip()
            if s=="}":removed+=1;continue
            if not s:
                if lines and lines[-1]!="": lines.append("")
            else: lines.append(s)
        while lines and not lines[-1]:lines.pop()
        prose="\n".join(lines).strip()+"\n"
        cjk=len(CJK.findall(prose))
        if cjk<1500:raise ValueError(f"Short story chapter {n}")
        chapter=title+"\n\n"+prose
        data=chapter.encode("utf-8")
        (out/"chapters"/f"{n:03d}.txt").write_bytes(data)
        combined.append(chapter+"\n\n")
        chapters.append({"ordinal":n,"title":title,"cjk":cjk,
            "bytes":len(data),"sha256":hashlib.sha256(data).hexdigest(),
            "removed_exact_boilerplate_lines":removed})
        removed_total+=removed
        count=chapter.count("\ufffd")
        if count:flags.append({"ordinal":n,"flag":"U+FFFD","count":count,
            "action":"Source verification needed, no automatic substitution"})
    joined="".join(combined)
    if hashlib.sha256(joined.encode()).hexdigest()!=COMBINED_SHA:
        raise ValueError("Cleaned text differs from audited 330-chapter combined TXT")
    if removed_total!=2 or len(flags)!=11 or sum(x["count"] for x in flags)!=22:
        raise ValueError("Known QA exceptions differ from previous review")
    (out/"combined_cn.txt").write_text(joined,encoding="utf-8")
    meta={
        "book":"变脸武士","author":"跳舞","other_titles":"Masked Knight / Рыцарь в Маске",
        "chapter_count":330,"missing_ordinals":[],"original_sha256":ORIGINAL_SHA,
        "original_bytes":len(original),"combined_sha256":COMBINED_SHA,
        "cleaned_cjk_total":len(CJK.findall(joined)),
        "median_chapter_cjk":statistics.median(x["cjk"] for x in chapters),
        "status":"RAW_FULL_BY_NUMBERING_EDITORIAL_QA_PENDING",
        "source":"https://huggingface.co/datasets/lainka0o0/chinese-novel-nonH-collect/blob/main/D/096.%E5%8F%98%E8%84%B8%E6%AD%A6%E5%A3%AB.txt",
        "quality_flags":flags,"chapters":chapters}
    (out/"manifest.json").write_text(json.dumps(meta,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (out/"qa"/"quality_flags.json").write_text(json.dumps(flags,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (out/"README.md").write_text(
        "# 变脸武士 / Рыцарь в Маске — китайский оригинал (RAW)\n\n"
        "330 отдельных TXT, единый combined_cn.txt, исходный неперезаписанный текст, SHA-256 и QA.\n"
        "Глава 241 есть. У 11 глав 22 испорченных символа U+FFFD: требуется ручная вычитка.\n"
        "Полный исходник не публиковался в репозитории — только во временном приватном артефакте CI.\n",
        encoding="utf-8")
    print(json.dumps({"status":meta["status"],"chapters":len(chapters),
        "sha256":COMBINED_SHA,"cjk":meta["cleaned_cjk_total"]},ensure_ascii=False))

if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("source",type=Path)
    ap.add_argument("output",type=Path)
    opts=ap.parse_args()
    package(opts.source,opts.output)
