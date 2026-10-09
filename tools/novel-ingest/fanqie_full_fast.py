#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import fanqie_ingest as fq

FAST_URL = "http://101.35.133.34:5000/api/content?tab=%E5%B0%8F%E8%AF%B4&item_id={}"
FALLBACK_URL = "http://101.35.133.34:5000/api/raw_full?item_id={}"

def request_json(url: str, timeout: int) -> dict[str, Any]:
    p = subprocess.run(
        [
            "curl","--compressed","--location","--silent","--show-error",
            "--connect-timeout","5","--max-time",str(timeout),"--retry","0",
            "--user-agent","Mozilla/5.0",
            "-w","\n__HTTP__%{http_code}",url,
        ],
        capture_output=True,
    )
    marker=b"\n__HTTP__"
    body_b,sep,code_b=p.stdout.rpartition(marker)
    body_b = body_b if sep else p.stdout
    code = code_b.decode("ascii","replace") if sep else ""
    body=None
    for enc in ("utf-8","gb18030"):
        try:
            body=body_b.decode(enc)
            break
        except UnicodeDecodeError:
            pass
    if body is None:
        body=body_b.decode("utf-8","replace")
    if code and code!="200":
        raise RuntimeError(f"http={code}")
    try:
        obj=json.loads(body)
    except Exception as e:
        raise RuntimeError(f"bad json chars={len(body)}: {e}") from e
    if not isinstance(obj,dict):
        raise RuntimeError("root not object")
    return obj

def extract(root: dict[str,Any]) -> tuple[str,str|None]:
    data=root.get("data") or {}
    if not isinstance(data,dict):
        return "",None
    content=fq.clean_content(str(data.get("content") or ""))
    title=data.get("title") or data.get("chapter_title") or data.get("name")
    return content,str(title) if title else None

def fetch_one(ch: fq.Chapter, source: str, timeout: int) -> tuple[str,str,str|None]:
    url=(FAST_URL if source=="api-content" else FALLBACK_URL).format(ch.item_id)
    root=request_json(url,timeout)
    content,title=extract(root)
    cjk=len(fq.CJK_RE.findall(content))
    if len(content)<500 or cjk<250:
        raise RuntimeError(f"too short chars={len(content)} cjk={cjk}")
    return source,content,title

def save(ch: fq.Chapter, source: str, content: str, api_title: str|None, chapter_dir: Path) -> dict[str,Any]:
    title=ch.title or api_title or f"第{ch.ordinal}章"
    body=content.strip()
    text=f"{title}\n\n{body}\n"
    body_sha=hashlib.sha256(body.encode("utf-8")).hexdigest()
    text_sha=hashlib.sha256(text.encode("utf-8")).hexdigest()
    author_tag=f"author-{ch.author_number:03d}" if ch.author_number is not None else "author-none"
    filename=f"{ch.ordinal:03d}_{author_tag}_{ch.item_id}.txt"
    (chapter_dir/filename).write_text(text,encoding="utf-8")
    return {
        "ordinal":ch.ordinal,
        "author_number":ch.author_number,
        "item_id":ch.item_id,
        "title":title,
        "catalog_title":ch.title,
        "api_title":api_title,
        "source":source,
        "chars":len(body),
        "cjk":len(fq.CJK_RE.findall(body)),
        "body_sha256":body_sha,
        "sha256":text_sha,
        "file":str(Path("chapters")/filename),
    }

def run_pass(chapters: list[fq.Chapter], source: str, timeout: int, workers: int, chapter_dir: Path):
    ok={}
    fail=[]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs={pool.submit(fetch_one,ch,source,timeout):ch for ch in chapters}
        done=0
        for fut in as_completed(futs):
            ch=futs[fut]
            done+=1
            try:
                src,content,api_title=fut.result()
                row=save(ch,src,content,api_title,chapter_dir)
                ok[ch.ordinal]=row
                print(json.dumps({"pass":source,"ok":ch.ordinal,"chars":row["chars"],"done":done,"total":len(chapters)},ensure_ascii=False),flush=True)
            except Exception as e:
                fail.append({"chapter":ch,"error":str(e)})
                print(json.dumps({"pass":source,"fail":ch.ordinal,"error":str(e),"done":done,"total":len(chapters)},ensure_ascii=False),flush=True)
    return ok,fail

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--book-id",required=True)
    ap.add_argument("--slug",required=True)
    ap.add_argument("--out-root",type=Path,default=Path("out/fanqie-fast"))
    args=ap.parse_args()

    catalog=fq.parse_catalog(fq.get_json(fq.CATALOG_URL.format(args.book_id),timeout=30))
    out_dir=args.out_root/args.slug
    chapter_dir=out_dir/"chapters"
    chapter_dir.mkdir(parents=True,exist_ok=True)

    all_ok={}
    pass_stats=[]

    ok1,fail1=run_pass(catalog,"api-content",10,12,chapter_dir)
    all_ok.update(ok1)
    pass_stats.append({"pass":"api-content-10s","attempted":len(catalog),"ok":len(ok1),"fail":len(fail1)})

    remaining=[x["chapter"] for x in fail1]
    if remaining:
        ok2,fail2=run_pass(remaining,"api-content",20,6,chapter_dir)
        all_ok.update(ok2)
        pass_stats.append({"pass":"api-content-20s","attempted":len(remaining),"ok":len(ok2),"fail":len(fail2)})
        remaining=[x["chapter"] for x in fail2]

    if remaining:
        ok3,fail3=run_pass(remaining,"api-raw-full",45,3,chapter_dir)
        all_ok.update(ok3)
        pass_stats.append({"pass":"api-raw-full-45s","attempted":len(remaining),"ok":len(ok3),"fail":len(fail3)})
        final_fail=fail3
    else:
        final_fail=[]

    manifest=[all_ok[n] for n in sorted(all_ok)]
    (out_dir/"manifest.jsonl").write_text(
        "".join(json.dumps(x,ensure_ascii=False)+"\n" for x in manifest),encoding="utf-8"
    )
    combined=[]
    for row in manifest:
        combined.append((out_dir/row["file"]).read_text(encoding="utf-8").rstrip())
    (out_dir/"combined.txt").write_text("\n\n".join(combined)+("\n" if combined else ""),encoding="utf-8")

    author_numbers=[c.author_number for c in catalog if c.author_number is not None]
    counts=Counter(author_numbers)
    max_author=max(author_numbers,default=0)
    sha_map=defaultdict(list)
    for row in manifest:
        sha_map[row["body_sha256"]].append(row["ordinal"])
    summary={
        "book_id":args.book_id,
        "catalog_entries":len(catalog),
        "catalog_max_author_number":max_author,
        "downloaded":len(manifest),
        "missing_ordinals":[n for n in range(1,len(catalog)+1) if n not in all_ok],
        "missing_author_numbers":[n for n in range(1,max_author+1) if n not in counts],
        "duplicate_author_numbers":sorted(n for n,v in counts.items() if v>1),
        "duplicate_bodies":[{"sha256":s,"ordinals":o} for s,o in sha_map.items() if len(o)>1],
        "unique_item_ids":len({c.item_id for c in catalog}),
        "source_counts":dict(Counter(x["source"] for x in manifest)),
        "pass_stats":pass_stats,
        "failures":[
            {"ordinal":x["chapter"].ordinal,"author_number":x["chapter"].author_number,"item_id":x["chapter"].item_id,"title":x["chapter"].title,"error":x["error"]}
            for x in final_fail
        ],
    }
    (out_dir/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"summary":summary},ensure_ascii=False),flush=True)

    if summary["downloaded"]!=summary["catalog_entries"] or summary["failures"]:
        raise SystemExit(2)

if __name__=="__main__":
    main()
