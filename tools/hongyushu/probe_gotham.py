#!/usr/bin/env python3
from __future__ import annotations
import re
from urllib.parse import quote, urljoin
import requests
from bs4 import BeautifulSoup

TITLE="人在哥谭当神父，开局捡到小男孩"
BASE="https://www.hongyushu.org/"
UA="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/129.0 Safari/537.36"

s=requests.Session()
s.headers.update({"User-Agent":UA,"Accept-Language":"zh-CN,zh;q=0.9,en;q=0.7"})
u=BASE+"search/?searchkey="+quote(TITLE)
r=s.get(u,timeout=30,allow_redirects=True)
r.encoding=r.apparent_encoding or r.encoding or "utf-8"
print("SEARCH",r.status_code,r.url,len(r.content))
soup=BeautifulSoup(r.text,"html.parser")
cands=[]
for a in soup.find_all("a",href=True):
    t=re.sub(r"\s+"," ",a.get_text(" ",strip=True))
    if TITLE in t or ("哥谭" in t and "神父" in t and "小男孩" in t):
        cands.append((t,urljoin(r.url,a["href"])))
print("CANDS",cands[:20])
if not cands:
    raise SystemExit("no exact book link")
book=cands[0][1]
r=s.get(book,timeout=30,allow_redirects=True)
r.encoding=r.apparent_encoding or r.encoding or "utf-8"
print("BOOK",r.status_code,r.url,len(r.content))
soup=BeautifulSoup(r.text,"html.parser")
chap=[]
for a in soup.find_all("a",href=True):
    t=re.sub(r"\s+"," ",a.get_text(" ",strip=True))
    m=re.search(r"第\s*(\d+)\s*章\s*(.*)",t)
    if m:
        chap.append((int(m.group(1)),t,urljoin(r.url,a["href"])))
print("COUNT",len(chap),"MAX",max((x[0] for x in chap),default=None))
for x in sorted(chap,key=lambda x:x[0])[-20:]:
    print("CH",x[0],x[1],x[2])
