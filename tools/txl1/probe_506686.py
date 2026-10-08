#!/usr/bin/env python3
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

headers={"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/129.0 Safari/537.36"}
page="https://txl1.com/b/506686.html"
s=requests.Session()
s.headers.update(headers)
r=s.get(page,timeout=30,allow_redirects=True)
r.encoding=r.apparent_encoding or r.encoding
print("PAGE",r.status_code,r.url,len(r.content),r.headers.get("content-type"),"cookies",s.cookies.get_dict())
soup=BeautifulSoup(r.text,"html.parser")
for a in soup.find_all("a",href=True):
    href=urljoin(r.url,a["href"])
    if "GetDown" in href:
        print("DL_ANCHOR",a.get_text(" ",strip=True),href,"PARENT",str(a.parent)[:1200])

for pathid in (0,1):
    u=f"https://txl1.com/e/DownSys/GetDown/?classid=7&id=506686&pathid={pathid}"
    d=s.get(u,headers={"Referer":page},timeout=40,allow_redirects=True)
    d.encoding=d.apparent_encoding or d.encoding
    print("TRY",pathid,"status",d.status_code,"url",d.url,"bytes",len(d.content),"ctype",d.headers.get("content-type"),"disp",d.headers.get("content-disposition"))
    print("HEADBYTES",repr(d.content[:200]))
    if "text/html" in (d.headers.get("content-type") or "").lower():
        print("HTML",d.text[:1800])
