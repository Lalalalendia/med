#!/usr/bin/env python3
import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

url="https://txl1.com/b/506686.html"
headers={"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/129.0 Safari/537.36"}
r=requests.get(url,headers=headers,timeout=30,allow_redirects=True)
print("status",r.status_code,"url",r.url,"chars",len(r.text),"ctype",r.headers.get("content-type"))
print("title", BeautifulSoup(r.text,"html.parser").title.get_text(" ",strip=True) if BeautifulSoup(r.text,"html.parser").title else "")
s=BeautifulSoup(r.text,"html.parser")
for a in s.find_all("a",href=True):
    text=re.sub(r"\s+"," ",a.get_text(" ",strip=True))
    href=urljoin(r.url,a["href"])
    if any(k in (text+" "+href).lower() for k in ["txt","下载","down","file","506686"]):
        print("LINK",repr(text),href)
