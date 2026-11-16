#!/usr/bin/env python3
"""Inspect first 5 chapter transitions of a large Jiuxiao book.

No text or article excerpts are persisted, only metadata/statistics.
"""
import json
import re
import time
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

BASE="https://jiuxiaozw.com"
BOOK="6aa28737ebce31446c4d1253"
UA="MED-Jiuxiao-Linked-Chapter-Pilot/1.0"
s=requests.Session()
s.headers.update({"User-Agent":UA,"Accept-Language":"zh-CN,zh;q=0.9"})
rp=RobotFileParser()
rr=s.get(BASE+"/robots.txt",timeout=20)
if rr.status_code!=200: raise RuntimeError("robots unavailable")
rp.parse(rr.text.splitlines())
last=0.0

def get(path):
    global last
    u=urljoin(BASE,path)
    if urlparse(u).hostname!="jiuxiaozw.com" or not rp.can_fetch(UA,u):
        raise RuntimeError("robots or host disallowed "+path)
    time.sleep(max(0,2.0-(time.monotonic()-last)))
    r=s.get(u,timeout=35)
    last=time.monotonic()
    r.raise_for_status()
    return BeautifulSoup(r.text,"html.parser")

soup=get("/sim/book/"+BOOK)
button=soup.select_one("button.book-latest-catalog")
announced=re.search(r"([0-9,]+)\s*章",button.get_text(" ",strip=True)).group(1)
links=[]
start=None
for a in soup.select("a[href]"):
    u=urlparse(urljoin(BASE,a.get("href"))).path
    match=re.fullmatch(r"/book/("+BOOK+r")/([a-f0-9]{24})",u)
    if match:
        links.append(u)
        if "开始阅读" in a.get_text(" ",strip=True):
            start=u
if start is None:
    raise RuntimeError("first chapter link missing")
item={"announced_catalog":int(announced.replace(",","")),"visible_chapter_links":len(set(links)),"first_url":start,"steps":[]}
seen=set()
current=start
for i in range(5):
    if current in seen: raise RuntimeError("cycle")
    seen.add(current)
    chapter=get(current)
    h1=chapter.select_one("h1")
    root=chapter.select_one("div.reader-columns")
    if h1 is None or root is None:
        raise RuntimeError("chapter body unavailable")
    pp=root.select("p.reader-paragraph")
    cjk=sum(len(re.findall(r"[\u3400-\u9fff]",p.get_text("",strip=True))) for p in pp)
    nextlink=next((a for a in chapter.select("a[href]") if a.get_text(" ",strip=True)=="下一章"),None)
    nextpath=urlparse(urljoin(BASE,nextlink.get("href"))).path if nextlink else None
    if nextpath is not None and not re.fullmatch(r"/book/"+BOOK+r"/[a-f0-9]{24}",nextpath):
        raise RuntimeError("invalid next chapter route")
    item["steps"].append({"step":i+1,"heading":h1.get_text(" ",strip=True)[:80],"paragraphs":len(pp),"cjk_chars":cjk,"next_path":nextpath})
    if cjk<200: raise RuntimeError("unexpectedly short body")
    if nextpath is None:break
    current=nextpath
print(json.dumps(item,ensure_ascii=False,indent=2))
assert len(item["steps"])==5,"short chain"
assert item["announced_catalog"]>item["visible_chapter_links"],"big book actually has complete catalog"
