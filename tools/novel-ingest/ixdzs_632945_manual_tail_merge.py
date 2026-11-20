#!/usr/bin/env python3
"""Verify authorized local tail TXT (361-368) and join with IXDZS 1-360.

No network requests or paywall bypass. Stop on missing, conflicting or duplicate
chapters. The original 360 files are copied byte-for-byte from the verified ZIP.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from zipfile import ZipFile, ZIP_DEFLATED

BASE_SHA = "1cd0015641727e81a369fdce984ac67ce00d78be2615069e0e572bca0e109c91"
TAIL_TITLES = {
  361:"替名碑？放心我会多给你烧点纸钱的",
  362:"灵异节点？欢迎收听午夜故事",
  363:"电台惊魂",
  364:"尖叫就会被拔舌",
  365:"咒乐园剧情开启",
  366:"一起前往咒乐园",
  367:"小丑阿特的杀戮时刻",
  368:"这里居然还有活人？",
}
HAN=re.compile(r"[\u3400-\u9fff]")
HEAD=re.compile(r"^\ufeff?\s*第\s*(\d{3})\s*章\s*([^\r\n]+)")
JUNK=("上一章","下一章","返回目录","扫码阅读","付费解锁","请登录后阅读","正在验证")
def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()
def cleaned_title(v: str) -> str:
    return re.sub(r"[\s\u3000?!？！，,。.·・：:]+","",v)

def tail_file(root:Path,n:int)->Path:
    choices=[root/f"{n:04d}.txt",root/"chapters"/f"{n:04d}.txt"]
    found=[p for p in choices if p.is_file()]
    if len(found)!=1:
        raise ValueError(f"Chapter {n} must exist exactly once as four-digit TXT in tail/ or tail/chapters/")
    return found[0]

def validate_tail(n:int,content:str)->str:
    text=content.replace("\r\n","\n").replace("\r","\n").lstrip("\ufeff").strip()+"\n"
    match=HEAD.match(text)
    if not match or int(match.group(1))!=n:
        raise ValueError(f"Title/number mismatch at chapter {n}")
    title=match.group(2).strip()
    if cleaned_title(title)!=cleaned_title(TAIL_TITLES[n]):
        raise ValueError(f"Unexpected title at chapter {n}: {title[:100]!r}")
    body=text[match.end():].strip()
    count=len(HAN.findall(body))
    if count<500:
        raise ValueError(f"Chapter {n} contains only {count} Chinese body characters")
    for marker in JUNK:
        if marker in body[:500]:
            raise ValueError(f"Possible non-prose or restricted page at chapter {n}: {marker}")
    return text

def open_base(path: Path):
    raw=path.read_bytes()
    base_sha=sha(raw)
    if base_sha!=BASE_SHA:
        raise ValueError(f"Unexpected base archive SHA-256: {base_sha}")
    with ZipFile(path) as z:
        if z.testzip() is not None:
            raise ValueError("IXDZS base archive CRC failed")
        names=set(z.namelist())
        want={f"chapters/{n:04d}.txt" for n in range(1,361)}|{"combined.txt","manifest.json"}
        if names!=want:
            raise ValueError(f"Base archive entries differ: missing={sorted(want-names)[:10]}, extra={sorted(names-want)[:10]}")
        old=json.loads(z.read("manifest.json"))
        if old.get("chapters_count")!=360 or old.get("last")!=360 or old.get("first")!=1:
            raise ValueError("Base archive metadata is not 1-360")
        items=old.get("chapters",[])
        if len(items)!=360 or [a.get("number") for a in items]!=list(range(1,361)):
            raise ValueError("Base chapter manifest is not 1-360")
        chapters=[]
        for n,row in enumerate(items,1):
            data=z.read(f"chapters/{n:04d}.txt")
            if sha(data)!=row.get("sha256"):
                raise ValueError(f"Base chapter SHA-256 mismatch: {n}")
            chapters.append(data)
        if sha(z.read("combined.txt"))!=old.get("combined_sha256"):
            raise ValueError("Base combined text SHA-256 mismatch")
    return chapters,old,base_sha

def join(base:Path, tail:Path, out:Path,source_label:str):
    if not source_label.strip() or len(source_label)>500:
        raise ValueError("Provide a nonempty concise tail source label")
    chapters,old,base_sha=open_base(base)
    rows=list(old["chapters"])
    text_hashes=set()
    for n,data in enumerate(chapters,1):
        text=data.decode("utf-8")
        body="\n".join(text.splitlines()[1:]).strip()
        body_hash=sha(body.encode("utf-8"))
        if body_hash in text_hashes:
            raise ValueError(f"Duplicate original body in chapter {n}")
        text_hashes.add(body_hash)
    for n in range(361,369):
        p=tail_file(tail,n)
        text=validate_tail(n,p.read_text(encoding="utf-8-sig"))
        data=text.encode("utf-8")
        body="\n".join(text.splitlines()[1:]).strip()
        body_hash=sha(body.encode("utf-8"))
        if body_hash in text_hashes:
            raise ValueError(f"Repeated body at appended chapter {n}")
        text_hashes.add(body_hash)
        chapters.append(data)
        rows.append({
            "number":n,"title":text.splitlines()[0],"file":f"chapters/{n:04d}.txt",
            "bytes":len(data),"cjk_chars":len(HAN.findall(body)),
            "sha256":sha(data),"source_label":source_label
        })
    if len(chapters)!=368:
        raise ValueError("Incomplete final chapter sequence")
    merged=b"\n\n".join(item.rstrip(b"\n") for item in chapters)+b"\n"
    manifest={
        "title":"美恐：用恐怖打败恐怖",
        "source_base":old.get("source_index"),
        "source_base_sha256":base_sha,
        "source_tail":source_label,
        "source_tail_chapters":"361-368",
        "rights_confirmed":True,
        "first":1,"last":368,"chapters_count":368,
        "verified_utc":datetime.now(timezone.utc).isoformat(),
        "combined_sha256":sha(merged),"chapters":rows
    }
    out.parent.mkdir(parents=True,exist_ok=True)
    with ZipFile(out,"w",ZIP_DEFLATED) as z:
        for n,data in enumerate(chapters,1):
            z.writestr(f"chapters/{n:04d}.txt",data)
        z.writestr("combined.txt",merged)
        z.writestr("manifest.json",json.dumps(manifest,ensure_ascii=False,indent=2)+"\n")
    with ZipFile(out) as z:
        if z.testzip() is not None or len(z.namelist())!=370:
            raise ValueError("Final ZIP CRC or file count failed")
        if sha(z.read("combined.txt"))!=manifest["combined_sha256"]:
            raise ValueError("Final combined SHA mismatch")
        for row in rows:
            if sha(z.read(row["file"]))!=row["sha256"]:
                raise ValueError(f"Final file SHA mismatch: {row['number']}")
    result={"status":"VERIFIED","chapters":368,"archive":str(out),
            "bytes":out.stat().st_size,"sha256":sha(out.read_bytes()),
            "combined_sha256":manifest["combined_sha256"]}
    print(json.dumps(result,ensure_ascii=False))
    return result

def selftest():
    for n,title in TAIL_TITLES.items():
        fixture=f"第{n}章 {title}\n\n"+("这是原创示例测试文本。"*90)
        assert validate_tail(n,fixture).startswith(f"第{n}章")
    try:
        validate_tail(361,"第362章 Wrong\n\n"+"这是测试文字"*180)
        raise AssertionError("Misnumbered chapter accepted")
    except ValueError:
        pass
    try:
        validate_tail(368,"第368章 这里居然还有活人？\n\n短篇")
        raise AssertionError("Short chapter accepted")
    except ValueError:
        pass
    print("OFFLINE_SELFTEST_PASS")

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base",type=Path)
    p.add_argument("--tail-dir",type=Path)
    p.add_argument("--out",type=Path,default=Path("out/ixdzs-632945-1-368-cn.zip"))
    p.add_argument("--tail-source",type=str)
    p.add_argument("--rights-confirmed",action="store_true")
    p.add_argument("--selftest",action="store_true")
    args=p.parse_args()
    if args.selftest:
        selftest()
        return
    if not args.rights_confirmed:
        p.error("Permission must be explicitly confirmed")
    if args.base is None or args.tail_dir is None or not args.tail_source:
        p.error("--base, --tail-dir and --tail-source are required")
    join(args.base,args.tail_dir,args.out,args.tail_source)

if __name__=="__main__":
    main()
