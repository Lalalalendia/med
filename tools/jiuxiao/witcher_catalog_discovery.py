#!/usr/bin/env python3
"""Determine Jiuxiao's public full-catalog mechanism without downloading novel text.

Only HTML/JS metadata and limited non-content API response descriptors logged.
"""
import json, re, time
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser
import requests
from bs4 import BeautifulSoup

ROOT="https://jiuxiaozw.com"
BOOK="6af8d3227d54a8afba082141"
UA="MED-Authorized-Source-Discovery/1.0"
sess=requests.Session()
sess.headers.update({"User-Agent":UA,"Accept-Language":"zh-CN,zh;q=0.9"})
rp=RobotFileParser()
rr=sess.get(ROOT+"/robots.txt",timeout=25); print("ROBOTS",rr.status_code)
if rr.status_code!=200:raise RuntimeError("robots unavailable")
rp.parse(rr.text.splitlines())
last=time.monotonic()
def get(url):
    global last
    if not rp.can_fetch(UA,url):raise RuntimeError("robots blocks "+url)
    wait=max(0,1.75-(time.monotonic()-last))
    if wait:time.sleep(wait)
    r=sess.get(url,timeout=35)
    last=time.monotonic()
    print("FETCH",urlparse(url).path[:130],"HTTP",r.status_code,"BYTES",len(r.content),"TYPE",r.headers.get("content-type","")[:65])
    r.raise_for_status()
    return r.text

html=get(ROOT+"/sim/book/"+BOOK)
soup=BeautifulSoup(html,"html.parser")
scripts=[urljoin(ROOT,x.get("src")) for x in soup.select("script[src]")]
print("SCRIPT_COUNT",len(scripts))
print("HTML chapter 600 string?",bool(re.search(r'第(?:六百|600)章',html)))
print("HTML possible catalog URLs",sorted(set(re.findall(r'["\x27](/(?:api/)?[^"\x27\s]{0,170}(?:catalog|chapter|catalogue|directory)[^"\x27\s]{0,100})',html,re.I)))[:35])
print("HTML HEAD",str(soup.head)[:500] if soup.head else "")
keywords=[r'catalog',r'chapter',r'目录',r'章節',r'chapters',r'/api/',r'book/']
summary=[]
for i,script in enumerate(scripts[:55]):
    try: js=get(script)
    except Exception as ex:
        summary.append({"i":i,"src":urlparse(script).path,"error":type(ex).__name__})
        continue
    score={k:len(re.findall(k,js,re.I)) for k in keywords}
    matches=[]
    for rx in [
        r'(?i)(?:/api/)[^"\x27\s]{0,170}',
        r'(?i)[a-z][a-z0-9._/-]{0,55}(?:chapter|catalog)[a-z0-9._/?=&-]{0,160}',
        r'(?i)[a-z][a-z0-9._/-]{0,55}(?:cursor|pageSize|limit|loadMore)[a-z0-9._/?=&-]{0,60}'
    ]:
        for m in re.finditer(rx,js):
            part=m.group(0)[:170]
            if part not in matches:matches.append(part)
            if len(matches)>=18:break
        if len(matches)>=18:break
    summary.append({"i":i,"src":urlparse(script).path,"bytes":len(js),"score":score,"strings":matches})
print("JS_SUMMARY",json.dumps([x for x in summary if x.get('score',{}).get('catalog',0) or x.get('score',{}).get('chapter',0) or x.get('score',{}).get('目录',0)],ensure_ascii=False,indent=2)[:24000])
# Read source implementation of the public catalog interface; no novel text.
for source in scripts:
    if "1ei8qzrisx2k" not in source:
        continue
    js=get(source)
    for needle in ("catalog/version", "catalog?"):
        pos=js.find(needle)
        print("CATALOG_API_CODE",needle,"at",pos,js[max(0,pos-2300):pos+1200] if pos>=0 else "")

