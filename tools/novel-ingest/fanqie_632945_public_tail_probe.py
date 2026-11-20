#!/usr/bin/env python3
"""Authorized 632945 tail pilot against an uncredentialed content endpoint.

Uses only publicly accessible endpoints. Never supplies account cookies, alters
auth, solves a challenge, or decrypts protected data. Stops at access limits.
Probe saves metadata only; prose is never committed.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
import requests
from bs4 import BeautifulSoup

BOOK_URL="https://fanqienovel.com/page/7519894716356250686"
PUBLIC_CONTENT="http://101.35.133.34:5000/api/content"
NUM=re.compile(r"第\s*(36[0-8])\s*章")
HAN=re.compile(r"[\u3400-\u9fff]")
BLOCKED=("login","captcha","verify you are human","access denied","svip","vip","登录","会员","验证")
UA="MedAuthorizedTailProbe/1.0 (+https://github.com/Lalalalendia/med)"

def chapter_links(session):
    r=session.get(BOOK_URL,timeout=(8,25),allow_redirects=False)
    if r.status_code!=200 or urlsplit(r.url).hostname!="fanqienovel.com":
        raise RuntimeError("Official Fanqie index unavailable")
    r.encoding="utf-8"
    soup=BeautifulSoup(r.text,"html.parser")
    ids={}
    for a in soup.select("a[href]"):
        title=a.get_text(" ",strip=True)
        m=NUM.search(title)
        if not m:
            continue
        n=int(m.group(1))
        path=urlsplit(a["href"]).path
        found=re.fullmatch(r"/reader/(\d{12,})",path)
        if not found:
            continue
        id=found.group(1)
        if n in ids and ids[n]["id"]!=id:
            raise ValueError(f"Conflicting chapter IDs at {n}")
        ids[n]={"id":id,"title":title}
    missing=sorted(set(range(361,369))-set(ids))
    if missing:
        raise RuntimeError(f"Official catalog missing chapters: {missing}")
    return ids

def pilot(session,number,item_id):
    r=session.get(PUBLIC_CONTENT,params={"tab":"小说","item_id":item_id},timeout=(8,40),allow_redirects=False)
    url=urlsplit(r.url)
    if url.hostname!="101.35.133.34" or url.port!=5000 or r.status_code in (301,302,307,308):
        raise RuntimeError("Unexpected source redirect")
    receipt={"ordinal":number,"item_id":item_id,"http":r.status_code,"bytes":len(r.content)}
    if r.status_code!=200:
        receipt["reason"]="not_available"
        return receipt
    try:
        obj=r.json()
    except ValueError:
        receipt["reason"]="not_json"
        return receipt
    data=obj.get("data") if isinstance(obj,dict) else None
    if not isinstance(data,dict):
        receipt["reason"]="no_data"
        receipt["root_code"]=str(obj.get("code",""))[:40] if isinstance(obj,dict) else ""
        return receipt
    raw=data.get("content") or ""
    if not isinstance(raw,str):
        receipt["reason"]="invalid_content"
        return receipt
    cleaned=BeautifulSoup(raw,"html.parser").get_text("\n",strip=True)
    receipt["chars"]=len(cleaned)
    receipt["han"]=len(HAN.findall(cleaned))
    receipt["sha256"]=hashlib.sha256(cleaned.encode("utf-8")).hexdigest()
    receipt["title"]=str(data.get("title") or "")[:100]
    receipt["blocked_markers"]=[s for s in BLOCKED if s in cleaned[:600].lower()]
    receipt["verified_public_body"]=receipt["han"]>=650 and not receipt["blocked_markers"]
    return receipt

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--out",type=Path,default=Path("out/fanqie-632945-public-pilot.json"))
    args=ap.parse_args()
    s=requests.Session()
    s.headers.update({"User-Agent":UA,"Accept-Language":"zh-CN,zh;q=0.8"})
    report={"utc":datetime.now(timezone.utc).isoformat(),"book_id":"7519894716356250686",
            "source":"public Fanqie catalog and uncredentialed api/content",
            "prose_saved":False,"items":[]}
    try:
        ids=chapter_links(s)
        report["index_count"]=len(ids)
        for n in (361,368):
            item=pilot(s,n,ids[n]["id"])
            item["catalog_title"]=ids[n]["title"][:130]
            report["items"].append(item)
            print("CHAPTER_PUBLIC_PILOT",json.dumps(item,ensure_ascii=False),flush=True)
    except Exception as e:
        report["error"]=type(e).__name__+": "+str(e)[:300]
        print("PILOT_STOPPED",report["error"],flush=True)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    if report.get("error"):
        raise SystemExit(1)

if __name__=="__main__":
    main()
