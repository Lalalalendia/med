#!/usr/bin/env python3
"""Fetch source book catalog metadata, not chapter text, via site's public reader API."""
import json, re, sys, time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser
import requests

HOST="jiuxiaozw.com"
BOOK="6af8d3227d54a8afba082141"
ROOT=f"https://{HOST}"
UA="MED-Authorized-Jiuxiao-Catalog/1.0"
OUT=Path("out/witcher-full-catalog.json")
s=requests.Session();s.headers.update({"User-Agent":UA,"Accept":"application/json","Accept-Language":"zh-CN,zh;q=0.9"})
robots=s.get(ROOT+"/robots.txt",timeout=25)
if robots.status_code!=200:raise RuntimeError("robots unavailable")
p=RobotFileParser();p.parse(robots.text.splitlines())
last=time.monotonic()
def fetch(path):
 global last
 u=ROOT+path
 if not p.can_fetch(UA,u):raise RuntimeError("robots blocks "+path)
 time.sleep(max(0,1.5-(time.monotonic()-last)))
 r=s.get(u,timeout=35,allow_redirects=False)
 last=time.monotonic()
 print("GET",path,"HTTP",r.status_code,"BYTES",len(r.content),"TYPE",r.headers.get("content-type"),flush=True)
 if r.status_code!=200:raise RuntimeError("HTTP "+str(r.status_code)+" for "+path)
 if "json" not in r.headers.get("content-type",""):
  raise RuntimeError("not JSON")
 return r.json()
info=fetch(f"/api/books/{BOOK}/catalog/version")
print("VERSION_RESPONSE",json.dumps(info,ensure_ascii=False)[:800])
rows=[]
total=None
version=info.get("version")
for offset in range(0,25000,128):
 params=f"?offset={offset}&limit=128"
 if version is not None:params+=f"&version={version}"
 data=fetch(f"/api/books/{BOOK}/catalog"+params)
 if total is None:
  total=data.get("total")
  if not isinstance(total,int) or not 1<=total<=20000:raise ValueError("invalid total")
  print("CATALOG_KEYS",list(data.keys()),"TOTAL",total)
 if data.get("total")!=total or data.get("offset")!=offset:
  raise ValueError("unstable or misaligned catalog")
 if version is not None and data.get("version")!=version:
  raise ValueError("catalog version changed")
 batch=data.get("rows")
 if not isinstance(batch,list) or not batch or len(batch)>128:
  raise ValueError("invalid batch")
 for row in batch:
  if not isinstance(row,dict) or not re.fullmatch(r"[0-9a-f]{24}",str(row.get("id",""))):
   raise ValueError("bad chapter id")
  if not isinstance(row.get("title"),str) or not isinstance(row.get("chapter_number"),(int,float)):
   raise ValueError("bad chapter row")
 rows.extend(batch)
 if len(rows)>=total:break
 if len(batch)<128:raise ValueError("unexpected short page")
if len(rows)!=total:raise ValueError(f"incomplete catalog: {len(rows)} / {total}")
if len({r["id"] for r in rows})!=total:raise ValueError("repeated chapter ids")
summary={"source":"Jiuxiao","source_book_url":ROOT+"/sim/book/"+BOOK,
 "book_id":BOOK,"version":version,"total":total,
 "retrieved_at":datetime.now(timezone.utc).isoformat(),
 "rows":[{"index":i+1,"id":r["id"],"title":r["title"],"chapter_number":r["chapter_number"]} for i,r in enumerate(rows)]}
OUT.parent.mkdir(exist_ok=True,parents=True)
OUT.write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
print("FIRST",json.dumps(summary["rows"][:3],ensure_ascii=False))
matches=[r for r in summary["rows"] if r["chapter_number"] in (598,599,600,601,602)]
print("NEAR_600",json.dumps(matches,ensure_ascii=False))
print("LAST",json.dumps(summary["rows"][-4:],ensure_ascii=False))
print("NUMERIC_RANGE",min(r["chapter_number"] for r in rows),max(r["chapter_number"] for r in rows))
print("SAVED",OUT)
