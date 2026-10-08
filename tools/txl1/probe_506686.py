#!/usr/bin/env python3
import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

headers={"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/129.0 Safari/537.36"}

page="https://txl1.com/b/506686.html"
r=requests.get(page,headers=headers,timeout=30,allow_redirects=True)
r.encoding = r.apparent_encoding or r.encoding
print("PAGE",r.status_code,r.url,len(r.content),r.headers.get("content-type"))
s=BeautifulSoup(r.text,"html.parser")
for a in s.find_all("a",href=True):
    text=re.sub(r"\s+"," ",a.get_text(" ",strip=True))
    href=urljoin(r.url,a["href"])
    if any(k in (text+" "+href).lower() for k in ["txt","下载","down","file","506686"]):
        print("LINK",repr(text),href)

down="https://txl1.com/e/DownSys/GetDown/?classid=7&id=506686&pathid=0"
d=requests.get(down,headers={**headers,"Referer":page},timeout=30,allow_redirects=True)
d.encoding = d.apparent_encoding or d.encoding
print("DOWN",d.status_code,d.url,len(d.content),d.headers.get("content-type"),"enc",d.encoding)
print("DOWN_TEXT_BEGIN")
print(d.text[:4000])
print("DOWN_TEXT_END")
ds=BeautifulSoup(d.text,"html.parser")
for a in ds.find_all("a",href=True):
    print("DOWN_LINK",repr(a.get_text(" ",strip=True)),urljoin(d.url,a["href"]))
