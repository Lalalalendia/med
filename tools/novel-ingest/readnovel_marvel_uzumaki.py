#!/usr/bin/env python3
"""Authorized public-chapter archive of ReadNovel/Qidian Marvel Uzumaki.
Never log in, decrypt, evade challenges, or present locked snippets as full text.
"""
from __future__ import annotations
import argparse,hashlib,json,re,time,zipfile
from pathlib import Path
from urllib.parse import urljoin,urlsplit
import requests
from bs4 import BeautifulSoup

BOOK_ID="1032797839"
INDEX="https://www.readnovel.com/bookquery/zfrhskhvdyjd"
BASE=f"https://m.qidian.com/chapter/{BOOK_ID}/"
UA="AuthorizedNovelPublicArchiver/1.0 (public pages only)"
SELECTORS=("#chapter-content",".chapter-content",".read-content",".reader-content",
           ".chapter-text",".chapterContent","#chapterContent",".content")
BLOCK=("登录后阅读","订阅本章","购买本章","付费阅读","请先登录","章节已锁定",
       "vip章节","需要登录","请登录","请输入验证码","人机验证","验证身份",
       "点击解锁","付费章节","not authorized","access denied","captcha")
def get(session,url):
    r=session.get(url,timeout=28,allow_redirects=False)
    if r.status_code!=200: raise ValueError(f"http_{r.status_code}")
    if "html" not in r.headers.get("content-type","").lower(): raise ValueError("not_html")
    return r.text
def catalog(session):
    soup=BeautifulSoup(get(session,INDEX),"html.parser")
    entries=[];seen=set()
    for a in soup.select("a[data-cid],a[href]"):
        href=a.get("data-cid") or a.get("href") or ""
        if "/chapter/"+BOOK_ID+"/" not in href: continue
        m=re.search(r"/chapter/"+BOOK_ID+r"/(\d{6,})/",href)
        if not m: continue
        cid=m.group(1)
        if cid in seen: continue
        name=a.get_text(" ",strip=True) or a.get("title","").strip()
        if not name or len(name)>160: continue
        seen.add(cid)
        entries.append({"ordinal":len(entries)+1,"cid":cid,"title":name,
                        "url":BASE+cid+"/"})
    if len(entries)<20:
        raise ValueError(f"Catalog too short ({len(entries)})")
    return entries
def body(html):
    soup=BeautifulSoup(html,"html.parser")
    visible=soup.get_text(" ",strip=True)
    for sel in SELECTORS:
        for el in soup.select(sel):
            for junk in el.select("script,style,header,footer,nav,button,.ads,.ad,.chapter-nav"):
                junk.decompose()
            lines=[re.sub(r"[\u00a0 \t]+"," ",x).strip() for x in el.get_text("\n",strip=True).splitlines()]
            lines=[x for x in lines if x]
            text="\n".join(lines)
            if any(marker in text[:1000].lower() for marker in BLOCK):
                return None,"locked"
            cjk=len(re.findall(r"[\u3400-\u9fff]",text))
            if cjk>=350 and len(lines)>=4:
                return text,"ok"
    if any(marker in visible[:3500].lower() for marker in BLOCK):
        return None,"locked_or_login"
    return None,"missing_text"
def run(args):
    out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
    s=requests.Session()
    s.headers.update({"User-Agent":UA,"Accept-Language":"zh-CN,zh;q=0.9"})
    catalog_rows=catalog(s)
    (out/"catalog.json").write_text(json.dumps(catalog_rows,ensure_ascii=False,indent=2),encoding="utf-8")
    selected=catalog_rows[max(args.start-1,0):args.end]
    if not selected: raise ValueError(f"No catalog positions {args.start}-{args.end} in {len(catalog_rows)}")
    records=[]
    for item in selected:
        row=dict(item)
        try:
            html=get(s,item["url"])
            content,status=body(html)
            row["status"]=status
            if content:
                filename=f"{item['ordinal']:04d}.txt"
                payload=f"{item['title']}\n\n{content}\n"
                (out/filename).write_text(payload,encoding="utf-8")
                row.update(file=filename,chars=len(content),
                           sha256=hashlib.sha256(payload.encode()).hexdigest())
        except Exception as exc:
            row.update(status="failed",error=str(exc)[:180])
        records.append(row)
        print(f"{row['ordinal']}/{len(catalog_rows)} {row['status']} {row.get('chars',0)} {row['title'][:40]}",flush=True)
        time.sleep(args.delay)
    summary={"source":INDEX,"source_book_id":BOOK_ID,"catalog_count":len(catalog_rows),
             "range":[args.start,args.end],"ok_count":sum(x["status"]=="ok" for x in records),
             "failed_count":sum(x["status"]!="ok" for x in records),"chapters":records}
    (out/"manifest.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    with zipfile.ZipFile(out/"chapters.zip","w",zipfile.ZIP_DEFLATED,compresslevel=7) as z:
        z.write(out/"manifest.json","manifest.json")
        z.write(out/"catalog.json","catalog.json")
        for p in sorted(out.glob("[0-9][0-9][0-9][0-9].txt")):z.write(p,p.name)
    print("SUMMARY",json.dumps({k:v for k,v in summary.items() if k!="chapters"},ensure_ascii=False))
    return 0 if summary["failed_count"]==0 else 1
if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--start",type=int,default=1)
    p.add_argument("--end",type=int,default=1)
    p.add_argument("--delay",type=float,default=0.8)
    p.add_argument("--out",default="out/readnovel-1032797839")
    a=p.parse_args()
    if a.start<1 or a.end<a.start or a.end-a.start>120 or a.delay<0.5:raise SystemExit("unsafe input")
    raise SystemExit(run(a))
