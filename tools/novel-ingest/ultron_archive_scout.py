#!/usr/bin/env python3
"""Archive and syndicated-search discovery for the 2021 Faloo novel.

Read-only URL discovery. No authenticated sessions or attempts to access locked text.
"""
from __future__ import annotations
import json
import re
import time
from pathlib import Path
from urllib.parse import urlencode, urlsplit, unquote, parse_qs
import requests
from bs4 import BeautifulSoup

OUT=Path("out/ultron-archive-search")
OUT.mkdir(parents=True,exist_ok=True)
S=requests.Session()
S.headers.update({
    "User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36",
    "Accept-Language":"zh-CN,zh;q=0.8,en;q=0.6"
})
BOOK="我在漫威当奥创"
QUERIES=[
    '"我在漫威当奥创" "老司机开车了"',
    '"我在漫威当奥创" txt 完本',
    '"变形元素，旺达失控" "奥创"',
    '"轰杀灭霸！打出响指！大结局！"',
]
PROVIDERS={
    "bing_rss":("https://www.bing.com/search",{"format":"rss"}, "q"),
    "yandex":("https://yandex.com/search/",{},"text"),
    "360":("https://www.so.com/s",{},"q"),
    "google":("https://www.google.com/search",{},"q"),
}
ROWS=[]
def get(url, params):
    r=S.get(url,params=params,timeout=18,allow_redirects=False)
    if r.status_code==200 and len(r.content)<2_000_000:
        r.encoding=r.apparent_encoding
    return r

def tidy_url(u):
    parts=urlsplit(u)
    if parts.scheme not in ("http","https") or not parts.hostname:
        return None
    if parts.hostname.endswith(("google.com","bing.com","yandex.com","so.com")):
        q=parse_qs(parts.query)
        for k in ("url","u","uddg"):
            val=(q.get(k) or [""])[0]
            if val.startswith(("http://","https://")):return val
        return None
    return u

for provider,(url,static,key) in PROVIDERS.items():
    for q in QUERIES:
        row={"provider":provider,"q":q,"status":"pending","candidates":[]}
        try:
            r=get(url,dict(static,**{key:q}))
            row["http"]=r.status_code
            row["final_url"]=r.url[:180]
            row["bytes"]=len(r.content)
            if r.status_code!=200:
                row["status"]="http_"+str(r.status_code)
            else:
                soup=BeautifulSoup(r.text,"xml" if provider=="bing_rss" else "html.parser")
                records=[]
                if provider=="bing_rss":
                    for item in soup.select("item"):
                        title=item.title.get_text(" ",strip=True) if item.title else ""
                        href=item.link.get_text(strip=True) if item.link else ""
                        desc=item.description.get_text(" ",strip=True) if item.description else ""
                        records.append((title,href,desc))
                else:
                    for a in soup.select("a[href]"):
                        title=a.get_text(" ",strip=True)
                        if len(title)<7 or len(title)>220:continue
                        records.append((title,a.get("href",""),""))
                for title,href,desc in records:
                    candidate=tidy_url(href)
                    if not candidate:continue
                    host=urlsplit(candidate).hostname or ""
                    if host.endswith(("faloo.com","ixdzs8.com","zongcaiwenxue.org")):
                        classification="known_source"
                    elif BOOK in title or BOOK in desc or
                         ("奥创" in title and ("漫威" in title or "老司机" in title)):
                        classification="new_match"
                    else:
                        continue
                    if candidate not in [x["url"] for x in row["candidates"]]:
                        row["candidates"].append({"title":title[:100],"url":candidate[:400],"class":classification})
                    if len(row["candidates"])>=35:break
                row["status"]="parsed"
        except Exception as e:
            row["status"]="error"
            row["error"]=f"{type(e).__name__}: {str(e)[:150]}"
        ROWS.append(row)
        print(json.dumps({"provider":provider,"status":row["status"],"q":q,
             "matches":row["candidates"][:12]},ensure_ascii=False),flush=True)
        time.sleep(.6)

archive_rows=[]
for label,url,params in [
    ("IA_exact","https://archive.org/advancedsearch.php",
      {"q":f'title:"{BOOK}"',"fl[]":"identifier","rows":"20","output":"json"}),
    ("IA_full","https://archive.org/advancedsearch.php",
      {"q":f'"{BOOK}"',"fl[]":"identifier","rows":"20","output":"json"}),
    ("wayback_faloo_64","https://web.archive.org/cdx/search/cdx",
      {"url":"wap.faloo.com/567548_64.html","output":"json","filter":"statuscode:200","collapse":"timestamp:4"}),
    ("wayback_zong_120","https://web.archive.org/cdx/search/cdx",
      {"url":"m.zongcaiwenxue.org/38603/9579074.html","output":"json","filter":"statuscode:200","collapse":"timestamp:4"}),
]:
    row={"provider":label}
    try:
        r=get(url,params)
        row["http"]=r.status_code
        row["bytes"]=len(r.content)
        if r.status_code==200:
            obj=r.json()
            row["status"]="parsed"
            row["data"]=obj.get("response",{}).get("docs",[])[:20] if isinstance(obj,dict) else obj[:20]
        else:
            row["status"]="http_"+str(r.status_code)
    except Exception as e:
        row.update(status="error",error=f"{type(e).__name__}: {str(e)[:150]}")
    archive_rows.append(row)
    print(json.dumps(row,ensure_ascii=False)[:3000],flush=True)
report={"title":BOOK,"searches":ROWS,"archives":archive_rows}
new=[]
seen=set()
for r in ROWS:
    for c in r["candidates"]:
        if c["class"]=="new_match" and c["url"] not in seen:
            new.append(c)
            seen.add(c["url"])
report["new_url_candidates"]=new
(OUT/"manifest.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
print("SUMMARY",json.dumps({"attempts":len(ROWS),"engines":list(PROVIDERS),
      "new_urls":len(new),"new_hosts":sorted(set(urlsplit(x["url"]).hostname for x in new))},ensure_ascii=False))
