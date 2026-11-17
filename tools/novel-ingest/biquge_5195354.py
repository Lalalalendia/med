#!/usr/bin/env python3
"""Permission-scoped public Biquge collection, chapter 867 onward.
Stops on access restrictions, ambiguous content or missing chapter numbers.
"""
import argparse
import hashlib
import json
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser
from zipfile import ZipFile, ZIP_DEFLATED
import requests
from bs4 import BeautifulSoup

INDEX = "https://www.biquge.tw/book/5195354/"
UA = "MEDAuthorizedNovelCollector/1.0 (+https://github.com/Lalalalendia/med)"
CHAPTER = re.compile(r"第\s*(\d+)\s*章")
HAN = re.compile(r"[\u3400-\u9fff]")
BLOCK = ("captcha", "verify you are human", "just a moment", "access denied", "人机验证", "安全验证", "请先登录")
ROOTS = ("#chaptercontent", "#content", "#contentbox", "#txtcontent", ".content", ".chapter-content", ".read-content", "article")
REMOVE = "script,style,iframe,form,nav,header,footer,aside,button,.ad,.ads,.page,.pagination,.read-page"

def find_catalog(html):
    soup = BeautifulSoup(html, "html.parser")
    entries = {}
    for a in soup.select("a[href]"):
        title = a.get_text(" ", strip=True)
        m = CHAPTER.search(title)
        if not m: continue
        n = int(m.group(1))
        url = urljoin(INDEX, a["href"])
        p = urlsplit(url)
        if p.scheme=="https" and p.hostname in ("www.biquge.tw","biquge.tw") and p.path.startswith("/book/5195354/"):
            entries.setdefault(n, (title, url))
    return entries

def parse(html, expected):
    soup = BeautifulSoup(html, "html.parser")
    head = soup.select_one("h1")
    title = head.get_text(" ", strip=True) if head else ""
    m = CHAPTER.search(title)
    if not m or int(m.group(1)) != expected:
        raise ValueError(f"chapter heading mismatch at {expected}: {title[:100]}")
    nodes = [soup.select_one(s) for s in ROOTS]
    nodes = [n for n in nodes if n is not None]
    if not nodes: raise ValueError(f"missing content container: {expected}")
    root = max(nodes,key=lambda n:len(n.get_text(" ",strip=True)))
    for el in root.select(REMOVE): el.decompose()
    for el in root.select("br"): el.replace_with("\n")
    chunks = [re.sub(r"[ \t\xa0]+"," ",x).strip() for x in root.get_text("\n",strip=True).splitlines()]
    lines = [x for x in chunks if x and x!=title and not re.search(r"上一章|下一章|返回目录|加入书架", x)]
    body = "\n\n".join(lines)
    count = len(HAN.findall(body))
    if count < 200 or any(x in body[:500].lower() for x in BLOCK):
        raise ValueError(f"chapter {expected}: too short/blocked ({count} Han)")
    return title, body, count

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--rights-confirmed",action="store_true")
    ap.add_argument("--start",type=int,default=867)
    ap.add_argument("--end",type=int,default=0)
    ap.add_argument("--delay",type=float,default=1.5)
    ap.add_argument("--out",default="out/biquge-5195354")
    args=ap.parse_args()
    if not args.rights_confirmed: ap.error("explicit permission confirmation required")
    if args.start!=867 or args.delay<1.0: ap.error("scope start must be 867, delay >=1s")
    out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
    report={"source":INDEX,"start":args.start,"requested_end":args.end,"chapters":[],"status":"INCOMPLETE"}
    session=requests.Session()
    session.headers.update({"User-Agent":UA,"Accept-Language":"zh-CN,zh;q=0.9"})
    try:
        robots=session.get("https://www.biquge.tw/robots.txt",timeout=(10,30),allow_redirects=False)
        rp=RobotFileParser()
        if robots.status_code==200 and "<html" not in robots.text[:200].lower():
            rp.parse(robots.text.splitlines())
        elif robots.status_code in (404,410):
            rp.parse(["User-agent: *","Allow: /"])
        else: raise ValueError("unknown robots policy")
        if not rp.can_fetch(UA,INDEX):raise ValueError("robots forbids index")
        response=session.get(INDEX,timeout=(10,30),allow_redirects=False)
        if response.status_code!=200:raise ValueError(f"catalog HTTP {response.status_code}")
        response.encoding=response.apparent_encoding or "utf-8"
        entries=find_catalog(response.text)
        if not entries:raise ValueError("No numbered links in catalog")
        end=args.end or max(entries)
        report["catalog_max"]=max(entries);report["end"]=end
        missing=[n for n in range(args.start,end+1) if n not in entries]
        if missing:raise ValueError(f"catalog missing chapter ordinals: {missing[:20]} (total {len(missing)})")
        rows=[];seen=set()
        for number in range(args.start,end+1):
            _,url=entries[number]
            if not rp.can_fetch(UA,url):raise ValueError(f"robots forbids {number}")
            time.sleep(args.delay)
            page=session.get(url,timeout=(10,45),allow_redirects=False)
            if page.status_code!=200:raise ValueError(f"chapter {number}: HTTP {page.status_code}")
            if urlsplit(page.url).hostname not in ("www.biquge.tw","biquge.tw"):raise ValueError("untrusted page host")
            page.encoding=page.apparent_encoding or "utf-8"
            title,body,han=parse(page.text,number)
            digest=hashlib.sha256(body.encode("utf-8")).hexdigest()
            if digest in seen:raise ValueError(f"duplicate body at chapter {number}")
            seen.add(digest)
            rows.append((number,title,body))
            report["chapters"].append({"number":number,"title":title,"url":url,"han_chars":han,"sha256":digest})
            print(f"VERIFIED {number}: {han} Han",flush=True)
        archive=out/f"biquge-5195354-{args.start}-{end}-cn.zip"
        with ZipFile(archive,"w",compression=ZIP_DEFLATED) as z:
            for n,t,b in rows:z.writestr(f"chapters/{n:04d}.txt",f"{t}\n\n{b}\n")
            z.writestr("combined.txt","\n\n".join(f"{t}\n\n{b}" for _,t,b in rows))
            report["status"]="PASS"
            z.writestr("manifest.json",json.dumps(report,ensure_ascii=False,indent=2))
        with ZipFile(archive) as z:
            assert z.testzip() is None
            assert len([n for n in z.namelist() if n.startswith("chapters/")]) == end-args.start+1
        report["zip_sha256"]=hashlib.sha256(archive.read_bytes()).hexdigest()
    except Exception as exc:
        report["error"]=type(exc).__name__+": "+str(exc)
    (out/"status.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({k:v for k,v in report.items() if k!="chapters"},ensure_ascii=False),flush=True)
    if report["status"]!="PASS":raise SystemExit(1)

if __name__=="__main__":main()
