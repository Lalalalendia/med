#!/usr/bin/env python3
"""Recover only six missing Chinese chapter bodies from a title-matched public copy."""
import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from zipfile import ZipFile, ZIP_DEFLATED

import requests
from bs4 import BeautifulSoup

BOOK = "https://www.diyibanzi.com/read/25731/"
TARGETS = {
    159: (157, "人形无限手套"),
    214: (212, "被打击的斯特兰奇"),
    215: (213, "黄铭对刘战"),
    233: (231, "蜘蛛侠入队"),
    234: (232, "机场‘偶遇’"),
    252: (250, "比赛"),
}
PAGES = re.compile(r"[（(]\s*(\d+)\s*/\s*(\d+)\s*[）)]")
HAN = re.compile(r"[\u3400-\u9fff]")
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/130.0.0.0 Safari/537.36"

def read(session, url):
    p = urlsplit(url)
    if p.scheme != "https" or p.netloc != "www.diyibanzi.com" or not re.fullmatch(r"/read/25731/\d+(?:_\d+)?\.html", p.path):
        raise ValueError("Unsafe URL: " + url)
    r = session.get(url, timeout=(10, 30), allow_redirects=False)
    if r.status_code in (401,403,429):
        raise ValueError("Access/rate restriction, stop: HTTP %d" % r.status_code)
    if r.status_code != 200:
        raise ValueError("Chapter unavailable: HTTP %d at %s" % (r.status_code, url))
    r.encoding = r.apparent_encoding or "utf-8"
    soup = BeautifulSoup(r.text, "html.parser")
    title = soup.title.get_text(" ",strip=True) if soup.title else ""
    article = soup.select_one("#content") or soup.select_one(".content") or soup.select_one("article")
    if not article:
        raise ValueError("Missing chapter content at " + url)
    clone = BeautifulSoup(str(article), "html.parser")
    for node in clone.select("script,style,iframe,nav,footer,header,form,button,.ad,.ads,.pagination"):
        node.decompose()
    for node in clone.find_all("br"):
        node.replace_with("\n")
    body = clone.get_text("\n", strip=True)
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in body.splitlines()]
    body = "\n".join(x for x in lines if x and not PAGES.fullmatch(x))
    body = body.replace("\u3000", " ").strip()
    markers = PAGES.findall(title)
    if len(markers) != 1:
        raise ValueError("No declared title page count at " + url + " title=" + title)
    page, total = map(int, markers[0])
    if not 1 <= page <= total <= 12:
        raise ValueError("Invalid page count at " + url)
    han = len(HAN.findall(body))
    if han < 200:
        raise ValueError("Short, placeholder or restricted text at " + url + ": " + str(han))
    return {"title":title,"body":body,"page":page,"total":total,"han":han,"url":url}

def normalized(t):
    return re.sub(r"[^\u3400-\u9fffA-Za-z0-9]", "", t)

def main():
    root=Path("out/xiaoshuoren-marvel-recovered")
    (root/"chapters").mkdir(parents=True,exist_ok=True)
    s=requests.Session()
    s.headers.update({"User-Agent":UA,"Accept-Language":"zh-CN,zh;q=0.9"})
    manifest={"status":"INCOMPLETE","source":BOOK,"rights_attested":True,"requested":len(TARGETS),
        "chapters":[],"failures":[],"created_utc":datetime.now(timezone.utc).isoformat()}
    for ordinal,(alt,title) in TARGETS.items():
        url=BOOK+str(1003320+alt)+".html"
        try:
            first=read(s,url)
            if first["page"] != 1:
                raise ValueError("First page not 1 at " + url)
            if normalized(title) not in normalized(first["title"]):
                raise ValueError("TITLE_MISMATCH expected %r actual %r" % (title,first["title"]))
            pages=[first]
            for n in range(2,first["total"]+1):
                time.sleep(.7)
                url2=BOOK+str(1003320+alt)+"_"+str(n)+".html"
                part=read(s,url2)
                if part["page"]!=n or part["total"]!=first["total"] or normalized(title) not in normalized(part["title"]):
                    raise ValueError("Wrong page, title or count at " + url2)
                pages.append(part)
            all_text=[p["body"] for p in pages]
            if len(set(all_text))!=len(all_text):
                raise ValueError("Duplicate page text")
            body="\n\n".join(all_text)
            sha=hashlib.sha256(body.encode("utf-8")).hexdigest()
            file="chapters/%04d.txt" % ordinal
            (root/file).write_text("%s\nSource: %s\n\n%s\n" % (title,pages[0]["url"],body),encoding="utf-8")
            row={"ordinal":ordinal,"alternate_ordinal":alt,"title":title,"source":pages[0]["url"],"file":file,
                "pages":len(pages),"page_urls":[p["url"] for p in pages],"chars":len(body),
                "cjk_chars":len(HAN.findall(body)),"sha256":sha}
            manifest["chapters"].append(row)
            print("RECOVER",ordinal,"OK",row["pages"],row["chars"],row["cjk_chars"],flush=True)
        except Exception as exc:
            manifest["failures"].append({"ordinal":ordinal,"error":str(exc)})
            print("RECOVER",ordinal,"FAILED",str(exc),flush=True)
        time.sleep(.7)
    manifest["status"]="PASS" if len(manifest["chapters"])==len(TARGETS) and not manifest["failures"] else "INCOMPLETE"
    (root/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (root/"summary.md").write_text("# Recovered missing chapters\nStatus: %s\nFound: %d/%d\n" % (manifest["status"],len(manifest["chapters"]),len(TARGETS)),encoding="utf-8")
    archive=Path("out/xiaoshuoren-marvel-recovered.zip")
    with ZipFile(archive,"w",ZIP_DEFLATED,compresslevel=8) as z:
        for path in sorted(root.rglob("*")):
            if path.is_file():
                z.write(path,path.relative_to(root.parent))
    with ZipFile(archive) as z:
        if z.testzip():
            raise RuntimeError("ZIP damaged")
    print("RECOVER_RESULT",manifest["status"],len(manifest["chapters"]),"/",len(TARGETS),"ZIP",archive,flush=True)
    return 0 if manifest["status"]=="PASS" else 2

if __name__=="__main__":
    sys.exit(main())
