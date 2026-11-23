#!/usr/bin/env python3
"""Public archive for authorized Marvel Uzumaki source on xbiqiuge.

HTTP-only legacy origin; no login or anticaptcha. Validates robots.txt,
catalog IDs, every pagination page, chapter identity, body length and SHA256.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser
import requests
from bs4 import BeautifulSoup

ROOT="http://www.xbiqiuge.net"
CATALOG_URL=ROOT+"/biquge_143731/"
UA="AuthorizedNovelPublicArchiver/1.0 (authorized archive of public texts)"
DIGIT={c:i for i,c in enumerate("零一二三四五六七八九")}
DIGIT["〇"]=0
UNITS={"十":10,"百":100,"千":1000}
HEADING_RE=re.compile(r"第\s*([零〇一二三四五六七八九十百千\d]+)\s*章")
PAGE_RE=re.compile(r"[（(]\s*(\d+)\s*/\s*(\d+)\s*[）)]")
CJK_RE=re.compile(r"[\u3400-\u9fff]")

def chinese_number(s:str)->int:
    if s.isdecimal(): return int(s)
    result, current=0,0
    for ch in s:
        if ch in DIGIT:current=DIGIT[ch]
        elif ch in UNITS:
            result+=(current or 1)*UNITS[ch]
            current=0
        else:raise ValueError(f"Bad Chinese numeral {s}")
    return result+current

def same_book(url:str)->bool:
    u=urlsplit(url)
    return (u.scheme=="http" and u.hostname=="www.xbiqiuge.net"
            and re.fullmatch(r"/biquge_143731/\d+(?:_[2-9])?\.html",u.path) is not None)

def fetch(session:requests.Session,url:str,robot:RobotFileParser)->BeautifulSoup:
    if url != CATALOG_URL and not same_book(url):
        raise ValueError(f"Unsafe URL: {url}")
    if not robot.can_fetch(UA,url):raise ValueError("robots disallows "+url)
    r=session.get(url,timeout=28,allow_redirects=False)
    if r.status_code!=200:raise ValueError(f"HTTP {r.status_code} {url}")
    if "html" not in r.headers.get("Content-Type","").lower():
        raise ValueError("Non HTML chapter")
    r.encoding=r.apparent_encoding or "utf-8"
    soup=BeautifulSoup(r.text,"html.parser")
    title=soup.title.get_text(" ",strip=True) if soup.title else ""
    if "漫威里的旋涡一族" not in title:
        raise ValueError(f"Wrong book title: {title}")
    return soup

def catalog(session,robot)->dict[int,dict]:
    soup=fetch(session,CATALOG_URL,robot)
    rows={}
    for a in soup.select("a[href]"):
        url=urljoin(CATALOG_URL,a["href"])
        if not same_book(url):continue
        title=a.get_text(" ",strip=True)
        if not title or title.startswith("最新章节"):continue
        ordinal=None
        match=HEADING_RE.search(title)
        if match:ordinal=chinese_number(match.group(1))
        elif title=="序":ordinal=0
        elif title.startswith("尾声") or title.startswith("尾聲"):ordinal=284
        if ordinal is None or not 0<=ordinal<=284:continue
        if ordinal in rows and rows[ordinal]["url"]!=url:
            raise ValueError(f"Ambiguous chapter {ordinal}: {rows[ordinal]['url']} and {url}")
        rows[ordinal]={"ordinal":ordinal,"title":title,"url":url}
    missing=set(range(285))-set(rows)
    if missing:raise ValueError(f"Catalog missing story chapter ordinals: {sorted(missing)}; discovered={len(rows)}")
    return rows

def body(soup, ordinal:int, requested_page:int)->tuple[str,int]:
    title=soup.select_one("h1")
    heading=title.get_text(" ",strip=True) if title else ""
    if ordinal==0:
        if not heading.startswith("序"):raise ValueError(f"Wrong prologue heading: {heading}")
    elif ordinal==284:
        if not heading.startswith(("尾声","尾聲")):raise ValueError(f"Wrong epilogue heading: {heading}")
    else:
        m=HEADING_RE.search(heading)
        if not m or chinese_number(m.group(1))!=ordinal:
            raise ValueError(f"Wrong chapter heading {ordinal}: {heading}")
    pm=PAGE_RE.search(heading)
    current,total=(int(pm.group(1)),int(pm.group(2))) if pm else (1,1)
    if current!=requested_page or total>6:raise ValueError(f"Unexpected pagination heading: {heading}")
    node=soup.select_one("article.content, article, .content")
    if node is None: raise ValueError("No content article")
    for el in node.select("script,style,nav,aside,button,.ad,.advertisement"):
        el.decompose()
    text="\n".join(x.strip() for x in node.get_text("\n",strip=True).splitlines() if x.strip())
    chinese=len(CJK_RE.findall(text))
    if chinese<250:raise ValueError(f"Too short page: CJK={chinese} n={ordinal} p={current}")
    if re.search(r"登录阅读|订阅本章|章节已锁定|正在验证浏览器",text[:500]):
        raise ValueError("Locked or challenge")
    return text,total

def run(nums:list[int],out:Path,delay:float)->dict:
    if delay<0.5:raise ValueError("Delay below 0.5")
    out.mkdir(parents=True,exist_ok=True)
    raw=out/"raw";raw.mkdir(exist_ok=True)
    session=requests.Session()
    session.headers.update({"User-Agent":UA,"Accept-Language":"zh-CN,zh;q=0.9"})
    r=session.get(ROOT+"/robots.txt",timeout=20,allow_redirects=False)
    if r.status_code!=200 or "<html" in r.text[:200].lower():
        raise ValueError(f"robots.txt unavailable: {r.status_code}")
    robot=RobotFileParser();robot.parse(r.text.splitlines())
    entries=catalog(session,robot)
    (out/"catalog.json").write_text(json.dumps(list(entries.values()),ensure_ascii=False,indent=2),encoding="utf-8")
    rows=[]
    for n in nums:
        row=dict(entries[n]);parts=[];total=1
        try:
            for page in range(1,7):
                url=row["url"] if page==1 else row["url"].removesuffix(".html")+f"_{page}.html"
                soup=fetch(session,url,robot)
                text,total=body(soup,n,page)
                parts.append(text)
                if page>=total:break
                time.sleep(delay)
            if len(parts)!=total: raise ValueError(f"Missing page: got {len(parts)}/{total}")
            full="\n\n".join(parts).strip()+"\n"
            chars=len(CJK_RE.findall(full))
            if chars<500:raise ValueError(f"Too short chapter after join: {chars}")
            filename=f"raw/{n:04d}.txt"
            (out/filename).write_text(row["title"]+"\n\n"+full,encoding="utf-8")
            digest=hashlib.sha256((row["title"]+"\n\n"+full).encode("utf-8")).hexdigest()
            row.update(status="ok",pages=total,cjk_chars=chars,sha256=digest,raw_file=filename)
        except Exception as exc:
            row.update(status="failed",error=str(exc)[:300])
        rows.append(row)
        print(f"{n:04d} {row['status']} pages={row.get('pages')} chars={row.get('cjk_chars')} {row.get('error','')}",flush=True)
        time.sleep(delay)
    good=sum(1 for r in rows if r["status"]=="ok")
    manifest={"source":CATALOG_URL,"source_book_id":"1032797839","catalog_story_units":len(entries),
              "requested":nums,"ok_count":good,"failed_count":len(rows)-good,"chapters":rows}
    (out/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
    print("SUMMARY",json.dumps({"requested":len(nums),"ok":good,"failed":len(rows)-good},ensure_ascii=False))
    return manifest

if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--start",type=int,default=0)
    ap.add_argument("--end",type=int,default=284)
    ap.add_argument("--numbers",default="")
    ap.add_argument("--out",type=Path,required=True)
    ap.add_argument("--delay",type=float,default=0.75)
    args=ap.parse_args()
    if args.numbers:
        nums=[int(x) for x in args.numbers.split(",")]
    else:
        if args.end<args.start or args.end-args.start>85:raise SystemExit("range must contain <=86 units")
        nums=list(range(args.start,args.end+1))
    if not nums or min(nums)<0 or max(nums)>284 or len(nums)>86 or len(set(nums))!=len(nums):
        raise SystemExit("Invalid list of source chapter numbers")
    try:
        result=run(nums,args.out,args.delay)
        sys.exit(0 if result["failed_count"]==0 else 1)
    except Exception as exc:
        print("FATAL:",repr(exc),file=sys.stderr)
        sys.exit(2)
