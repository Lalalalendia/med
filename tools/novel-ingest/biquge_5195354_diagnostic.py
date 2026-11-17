#!/usr/bin/env python3
"""Catalog structure diagnostics for Biquge 5195354; metadata only, no novel prose saved."""
import json
import re
from urllib.parse import urljoin, urlsplit
from bs4 import BeautifulSoup
import requests

INDEX = "https://www.biquge.tw/book/5195354/"
S = requests.Session()
S.headers.update({"User-Agent":"MEDAuthorizedNovelProbe/1.0 (+https://github.com/Lalalalendia/med)", "Accept-Language":"zh-CN,zh;q=0.9"})
han = re.compile(r"[\u3400-\u9fff]")
pat = re.compile(r"第\s*(\d+)\s*章")
def get(url):
    r=S.get(url,timeout=(10,35),allow_redirects=False)
    r.raise_for_status()
    r.encoding = r.apparent_encoding or "utf-8"
    return BeautifulSoup(r.text,"html.parser")

soup=get(INDEX)
hits={}
for a in soup.select("a[href]"):
    title=a.get_text(" ",strip=True)
    m=pat.search(title)
    if not m: continue
    p=urlsplit(urljoin(INDEX,a.get("href")))
    if p.hostname not in ("www.biquge.tw","biquge.tw") or not p.path.startswith("/book/5195354/"):continue
    n=int(m.group(1))
    hits.setdefault(n,[]).append({"title":title[:100],"url":p.geturl(),"parent":a.parent.get("class",[]),"parent_id":a.parent.get("id","")})
print("CATALOG",json.dumps({"total_unique":len(hits),"max":max(hits),"outliers":[(n,hits[n][0]) for n in sorted(hits) if n>1150][:8],"missing_850_1150":[n for n in range(850,1151) if n not in hits][:30]},ensure_ascii=False))
for n in list(range(1032,1040)) + list(range(1128,1135)):
    print("ENTRY",n,json.dumps(hits.get(n,[]),ensure_ascii=False))
def probe(number,url):
    try:
        d=get(url)
        h=d.select_one("h1")
        title=h.get_text(" ",strip=True) if h else ""
        nav=[]
        for a in d.select("a[href]"):
            tx=a.get_text(" ",strip=True)
            if any(x in tx for x in ("上一章","下一章","目录","1036")):
                nav.append({"text":tx[:90],"href":urljoin(url,a["href"])})
        root_counts={}
        for sel in ("#chaptercontent","#content","#contentbox","#txtcontent",".content",".chapter-content",".read-content","article"):
            p=d.select_one(sel)
            if p:root_counts[sel]=len(han.findall(p.get_text(" ",strip=True)))
        print("CHAPTER",number,json.dumps({"url":url,"heading":title[:120],"nav":nav[-10:],"content_nodes_han":root_counts},ensure_ascii=False))
    except Exception as e:print("CHAPTER_ERROR",number,type(e).__name__,str(e)[:200])
for n in (867,1035,1037,1133):
    if n in hits:probe(n,hits[n][0]["url"])
# Check strictly the adjacent numeric ID only if 1035 and 1037 have the same URL pattern and IDs differ by 2.
if 1035 in hits and 1037 in hits:
    a,b=[hits[n][0]["url"] for n in (1035,1037)]
    ma=re.fullmatch(r"(https://www\.biquge\.tw/book/5195354/)(\d+)(\.html)",a)
    mb=re.fullmatch(r"(https://www\.biquge\.tw/book/5195354/)(\d+)(\.html)",b)
    if ma and mb and int(mb.group(2))-int(ma.group(2))==2:
        probe(1036,ma.group(1)+str(int(ma.group(2))+1)+ma.group(3))
    else:
        print("CANDIDATE_1036","cannot infer adjacent ID safely")
