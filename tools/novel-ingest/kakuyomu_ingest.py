#!/usr/bin/env python3
"""Kakuyomu public-page acquisition for med. No auth or bypass."""
import argparse
import hashlib
import json
import re
import time
from pathlib import Path
import requests
from bs4 import BeautifulSoup, Tag

BASE = "https://kakuyomu.jp"
UA = "med-KakuyomuIngest/1.0 (public episode pages)"
class IngestError(Exception): pass

def parse_toc(html, work_id):
    soup = BeautifulSoup(html, "html.parser")
    script = soup.find(id="__NEXT_DATA__")
    if script is None: raise IngestError("Missing __NEXT_DATA__")
    try:
        state = json.loads(script.get_text())["props"]["pageProps"]["__APOLLO_STATE__"]
        work = state[f"Work:{work_id}"]
        nodes = work["tableOfContentsV2"]
    except (KeyError, TypeError, ValueError) as exc:
        raise IngestError("Invalid Apollo catalog") from exc
    rows, seen = [], set()
    for ref in nodes:
        toc = state.get(ref.get("__ref", ""), {})
        chapter = state.get((toc.get("chapter") or {}).get("__ref", ""), {})
        for ep_ref in toc.get("episodeUnions", []):
            ep = state.get(ep_ref.get("__ref", ""), {})
            eid = str(ep.get("id", ""))
            if not re.fullmatch(r"\d+", eid) or eid in seen: continue
            seen.add(eid)
            rows.append({"ordinal":len(rows)+1,"episode_id":eid,
                "title":ep.get("title", ""),"section":chapter.get("title", ""),
                "url":f"{BASE}/works/{work_id}/episodes/{eid}"})
    count = work.get("publicEpisodeCount")
    if not isinstance(count, int) or not rows or len(rows)!=count:
        raise IngestError(f"Catalog count mismatch: {len(rows)} vs {count}")
    return {"work_id":work_id,"title":work.get("title", ""),
            "published_episodes":count}, rows

def parse_body(html):
    soup=BeautifulSoup(html,"html.parser")
    body=soup.select_one(".widget-episodeBody, .js-episode-body")
    if body is None: raise IngestError("No public episode body")
    for ruby in body.find_all("ruby"):
        ruby.replace_with("".join(
            str(child) if isinstance(child,str) else child.get_text()
            for child in ruby.children
            if not isinstance(child,Tag) or child.name not in ("rt","rp")))
    paragraphs=[]
    for p in body.find_all("p"):
        for br in p.find_all("br"): br.replace_with("\n")
        paragraphs.append(p.get_text("",strip=False).rstrip())
    result="\n".join(paragraphs).strip()
    if not result: raise IngestError("Empty episode")
    return result

def html(session,url):
    try: r=session.get(url,timeout=30,allow_redirects=False)
    except requests.RequestException as exc: raise IngestError(f"Network: {type(exc).__name__}") from exc
    if r.status_code!=200: raise IngestError(f"HTTP {r.status_code}")
    if "html" not in r.headers.get("content-type","").lower(): raise IngestError("Non-HTML")
    return r.text

def collect(book,out,delay=2,min_chars=120,session=None):
    wid=str(book["work_id"]); slug=book["directory"]
    if not re.fullmatch(r"\d{10,22}",wid): raise ValueError("Bad work id")
    if not re.fullmatch(r"[a-z0-9_-]{1,64}",slug): raise ValueError("Bad path")
    if delay<1 or min_chars<1: raise ValueError("Invalid rate or length")
    session=session or requests.Session()
    session.headers.update({"User-Agent":UA,"Accept-Language":"ja,en;q=0.8"})
    root=out/slug; (root/"chapters").mkdir(parents=True,exist_ok=True)
    source=f"{BASE}/works/{wid}"
    meta,toc=parse_toc(html(session,source),wid)
    (root/"metadata.json").write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding="utf-8")
    (root/"toc.json").write_text(json.dumps(toc,ensure_ascii=False,indent=2),encoding="utf-8")
    records=[]; seen={}; blocked=False
    for item in toc:
        row=dict(item)
        if blocked:
            row.update(status="not_fetched",error="access restriction"); records.append(row); continue
        if records: time.sleep(delay)
        try:
            raw=parse_body(html(session,item["url"]))
            size=len(re.sub(r"\s+","",raw))
            if size<min_chars: raise IngestError(f"Too short: {size}")
            binary=(raw+"\n").encode("utf-8")
            sha=hashlib.sha256(binary).hexdigest()
            if sha in seen: raise IngestError(f"Duplicate body: {seen[sha]}")
            seen[sha]=item["ordinal"]
            name=f"chapters/{item['ordinal']:04d}_{item['episode_id']}.txt"
            (root/name).write_bytes(binary)
            row.update(status="ok",chars=size,sha256=sha,raw_file=name)
        except IngestError as exc:
            row.update(status="error",error=str(exc))
            if any(c in str(exc) for c in ("HTTP 401","HTTP 403","HTTP 429","HTTP 451")): blocked=True
        records.append(row)
    complete=len(toc)>=book["expected_episodes"] and all(r["status"]=="ok" for r in records)
    result={"work_id":wid,"status":"PASS" if complete else "PARTIAL",
       "indexed":len(toc),"downloaded":sum(r["status"]=="ok" for r in records),
       "failed":sum(r["status"]!="ok" for r in records),"complete":complete,"chapters":records}
    (root/"manifest.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    if complete:
        text="\n\n".join(f"===== {r['ordinal']:04d} {r['title']} =====\n{r['url']}\n\n"
            +(root/r["raw_file"]).read_text(encoding="utf-8") for r in records)
        (root/"full_book.txt").write_text(text,encoding="utf-8")
    else: (root/"full_book.txt").unlink(missing_ok=True)
    return result

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--books",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--book",type=int,action="append")
    p.add_argument("--delay",type=float,default=2)
    args=p.parse_args()
    books=json.loads(args.books.read_text(encoding="utf-8"))
    args.output.mkdir(parents=True,exist_ok=True)
    results=[]
    for b in books:
        if args.book and b["number"] not in args.book: continue
        try: result=collect(b,args.output,delay=args.delay)
        except (IngestError,ValueError,OSError) as exc:
            result={"work_id":b["work_id"],"status":"BLOCKED","complete":False,"error":str(exc)}
        print(result["work_id"],result["status"],flush=True)
        results.append(result)
    (args.output/"overall_status.json").write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding="utf-8")
    return 0 if results and all(r["complete"] for r in results) else 1

if __name__=="__main__": raise SystemExit(main())
