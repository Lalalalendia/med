#!/usr/bin/env python3
"""Collect verifiable public RAW, preserving chapter numbers and provenance."""
import argparse
import hashlib
import json
import re
import sys
import time
import zipfile
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BOOK = "巫師：我有一棵技能樹"
INDEX = "https://sto55.com/book/62763/ajax_index.html"
NUMS = {c:i for i,c in enumerate("零一二三四五六七八九")}
NUMS.update({"〇":0,"两":2,"兩":2})
UNITS = {"十":10,"百":100,"千":1000,"萬":10000,"万":10000}

def parse_number(value):
    value = value.strip()
    if value.isdecimal():
        return int(value)
    total, subtotal, digit = 0, 0, 0
    for ch in value:
        if ch in NUMS:
            digit = NUMS[ch]
        elif ch in UNITS:
            unit = UNITS[ch]
            if unit >= 10000:
                total += (subtotal+digit)*unit
                subtotal = digit = 0
            else:
                subtotal += (digit or (1 if unit == 10 else 0))*unit
                digit = 0
        else:
            return None
    return total+subtotal+digit

def chapter_heading(value):
    match = re.match(r"^\s*第\s*([零〇一二三四五六七八九十百千萬万两兩\d]+)\s*章\s*(.*)", value)
    if not match:
        return None
    number = parse_number(match.group(1))
    return (number, match.group(2).strip()) if number else None

def request(session,url):
    for attempt in range(4):
        try:
            response=session.get(url,timeout=25)
            response.raise_for_status()
            return BeautifulSoup(response.content,"html.parser",from_encoding=response.apparent_encoding)
        except (requests.RequestException, ValueError):
            if attempt==3:raise
            time.sleep(2**attempt)
    raise RuntimeError("request failed")

def catalog(session):
    soup=request(session,INDEX)
    chapters={}
    conflicts={}
    for link in soup.select("a[href]"):
        heading=chapter_heading(link.get_text(" ",strip=True))
        if not heading:continue
        n,title=heading
        url=urljoin(INDEX,link["href"])
        if not url.startswith("https://sto55.com/book/62763/"):continue
        if n in chapters and chapters[n]["url"]!=url:
            conflicts.setdefault(n,[]).append(url)
            continue
        chapters[n]={"number":n,"title":title,"url":url}
    return chapters,conflicts

BAD_EXACT={"首頁","玄幻奇幻",BOOK,"關燈","字體-","字體+","目錄","書籤","報錯","上一章","下一章","返回目錄","本章完"}
AD_TOKENS=("想知道後續發展，請訪問","思兔（閱讀）最新最快","sto55.com","Sto55.com","𝑺𝒕𝒐𝟓𝟓")

def content(soup,n,title):
    page_title=soup.title.get_text(" ",strip=True) if soup.title else ""
    if "巫師：我有一棵技能樹" not in page_title:
        raise ValueError("wrong book in page title: "+page_title[:120])
    main=soup.select_one(".content")
    if main is None:
        raise ValueError("missing .content")
    clone=BeautifulSoup(str(main),"html.parser")
    for bad in clone.select("script,style,noscript,iframe,svg,nav,header,footer,form,button,aside"):
        bad.decompose()
    raw=clone.get_text("\n",strip=True)
    lines=[re.sub(r"[\u00a0\t ]+"," ",line).strip() for line in raw.splitlines()]
    lines=[line for line in lines if line]
    marker = -1
    for i,line in enumerate(lines):
        h=chapter_heading(line)
        if h and h[0]==n:
            marker=i
    if marker<0:
        raise ValueError("expected chapter heading absent")
    body=lines[marker+1:]
    while body and body[0] in BAD_EXACT:
        body.pop(0)
    for idx,line in enumerate(body):
        if line in ("上一章","下一章","返回目錄","目錄") or re.fullmatch(r"上一章\s+下一章.*",line):
            body=body[:idx]
            break
    body=[line for line in body if line not in BAD_EXACT and not any(ad.lower() in line.lower() for ad in AD_TOKENS)]
    text="\n\n".join(body).strip()
    if len(text)<600:
        raise ValueError("too short: "+str(len(text)))
    if "加載中" in text[:30] or "加载中" in text[:30]:
        raise ValueError("loading placeholder")
    return text

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--start",type=int,default=500)
    parser.add_argument("--end",type=int,default=0)
    parser.add_argument("--delay",type=float,default=.7)
    parser.add_argument("--out",default="out/witch-skill-tree")
    args=parser.parse_args()
    out=Path(args.out)
    raw=out/"raw";raw.mkdir(parents=True,exist_ok=True)
    session=requests.Session()
    session.headers.update({"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36","Accept-Language":"zh-TW,zh;q=0.9"})
    books,conflicts=catalog(session)
    if not books:
        raise SystemExit("No chapter entries parsed")
    last=min(args.end,max(books)) if args.end else max(books)
    if args.start>last:raise SystemExit("Start beyond catalog end")
    rows=[]
    errors=[]
    for number in range(args.start,last+1):
        entry=books.get(number)
        if not entry:
            errors.append({"chapter":number,"reason":"missing catalog entry"})
            print("MISSING",number,flush=True)
            continue
        try:
            soup=request(session,entry["url"])
            text=content(soup,number,entry["title"])
            filename=f"{number:04d}.txt"
            raw_bytes=(f"第{number}章 {entry['title']}\n\n"+text+"\n").encode("utf-8")
            (raw/filename).write_bytes(raw_bytes)
            digest=hashlib.sha256(raw_bytes).hexdigest()
            row={**entry,"chars":len(text),"sha256":digest,"file":"raw/"+filename}
            rows.append(row)
            print("OK",number,len(text),digest[:12],flush=True)
        except Exception as exc:
            errors.append({"chapter":number,"url":entry["url"],"reason":str(exc)})
            print("FAILED",number,str(exc),flush=True)
        time.sleep(max(.5,args.delay))
    chunks=[(out/row["file"]).read_text(encoding="utf-8").rstrip() for row in rows]
    if chunks:
        (out/"combined.txt").write_text("\n\n"+("\n\n"+"="*50+"\n\n").join(chunks)+"\n",encoding="utf-8")
    report={"book":BOOK,"catalog_url":INDEX,"requested_start":args.start,"requested_end":last,"catalog_max":max(books),"catalog_entries":len(books),"ok":len(rows),"failures":errors,"catalog_conflicts":conflicts,"chapters":rows}
    (out/"manifest.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (out/"summary.md").write_text(f"# Wizard skill tree RAW collection\n\nRange: {args.start}-{last}\n\nOK: {len(rows)}\n\nFailed: {len(errors)}\n\nCatalog max: {max(books)}\n\nConflicts: {len(conflicts)}\n",encoding="utf-8")
    with zipfile.ZipFile(out/"witch-skill-tree-raw.zip","w",compression=zipfile.ZIP_DEFLATED) as z:
        for path in sorted(raw.glob("*.txt")):z.write(path,arcname="raw/"+path.name)
        for filename in ("combined.txt","manifest.json","summary.md"):
            if (out/filename).exists():z.write(out/filename,arcname=filename)
    if errors:
        print("INCOMPLETE: "+str(len(errors))+" chapter failures",file=sys.stderr)
        return 1
    print("COMPLETE: "+str(len(rows))+" chapters")
    return 0

if __name__=="__main__":
    sys.exit(main())
