#!/usr/bin/env python3
"""Collect a publicly accessible Tongren 3233353 RAW shard with explicit failure receipts.

Never bypass robots, account gates or anti-bot challenges. A successful exit
requires every requested catalog ordinal and all discovered split pages.
"""
import argparse
import hashlib
import json
import re
import time
import zipfile
from pathlib import Path
from urllib.parse import urljoin, urlsplit, parse_qs
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

HOST = "m.tongrenxiaoshuo.com"
BOOK_ID = "3233353"
ROOT = "https://" + HOST + "/b/" + BOOK_ID
UA = "MedNovelRawCollector/1.0 (public HTML only)"
CHAPTER_RE = re.compile(r"^/b/3233353/c/(\d+)(?:/)?$")
INDEX_RE = re.compile(r"^/b/3233353(?:/cs(?:/\d+)?)?/?$")
CHALLENGES = ("just a moment", "captcha", "访问频繁", "验证码", "登录后阅读",
              "請登入", "access denied", "verify you are human", "购买本章", "付费阅读")
CONTAINERS = ("#chaptercontent", "#content", "#chapterContent",
              ".chapter-content", ".read-content", ".content", "article", "main")
JUNK = "script,style,noscript,iframe,form,nav,header,footer,aside,button,.ad,.ads,.advertisement,.copyright,.page,.pagination"


def checked(url, kind=None):
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname != HOST or parsed.username or parsed.password or parsed.port not in (None, 443) or parsed.fragment:
        raise ValueError("Unsafe external URL: " + url)
    is_chapter = bool(CHAPTER_RE.fullmatch(parsed.path))
    is_index = bool(INDEX_RE.fullmatch(parsed.path))
    if kind == "chapter" and not is_chapter:
        raise ValueError("Not a chapter URL: " + url)
    if kind == "index" and not is_index:
        raise ValueError("Not a catalog URL: " + url)
    if not (is_chapter or is_index):
        raise ValueError("Unrecognized book path: " + url)
    q = parse_qs(parsed.query)
    if q and (set(q) != {"page"} or len(q["page"]) != 1 or not re.fullmatch(r"[1-9]\d{0,2}",q["page"][0])):
        raise ValueError("Unexpected query: " + url)
    return parsed


def read(session, policy, url, delay):
    checked(url)
    if not policy.can_fetch(UA, url):
        raise ValueError("robots.txt disallows " + url)
    time.sleep(delay)
    r = session.get(url, timeout=35, allow_redirects=False)
    if r.status_code in (301,302,303,307,308,401,402,403,429,451):
        raise ValueError("Blocked or redirected: HTTP " + str(r.status_code))
    if r.status_code != 200:
        raise ValueError("HTTP " + str(r.status_code))
    if "html" not in r.headers.get("Content-Type","").lower():
        raise ValueError("Not an HTML page")
    r.encoding = r.apparent_encoding or "utf-8"
    source = r.text
    if any(x.lower() in source[:15000].lower() for x in CHALLENGES):
        raise ValueError("Potential access challenge")
    return BeautifulSoup(source, "html.parser")


def robots(session):
    r=session.get("https://" + HOST + "/robots.txt",timeout=25,allow_redirects=False)
    policy=RobotFileParser()
    if r.status_code in (404,410):
        policy.parse(["User-agent: *","Allow: /"])
    elif r.status_code==200 and "<html" not in r.text[:500].lower():
        policy.parse(r.text.splitlines())
    else:
        raise ValueError("Cannot determine robots policy: HTTP "+str(r.status_code))
    return policy


def catalog(session,policy,delay):
    pending=[ROOT+"/cs/1"]
    visited=set()
    chapters={}
    while pending:
        url=pending.pop(0)
        if url in visited:
            continue
        if len(visited)>=50:
            raise ValueError("Catalog pagination overflow")
        visited.add(url)
        page=read(session,policy,url,delay)
        for a in page.select("a[href]"):
            href=urljoin(url,a["href"])
            try:
                p=checked(href)
            except ValueError:
                continue
            if INDEX_RE.fullmatch(p.path) and href not in visited and href not in pending:
                pending.append(href)
            match=CHAPTER_RE.fullmatch(p.path)
            if not match or p.query:
                continue
            title=re.sub(r"\s+"," ",a.get_text(" ",strip=True)).strip()
            if not title:
                continue
            # Chapter source IDs are not guaranteed to be contiguous.
            chapters.setdefault(href,title)
    if len(chapters)<1:
        raise ValueError("No chapter links discovered")
    result=[]
    for n,(url,title) in enumerate(chapters.items(),1):
        m=re.search(r"第\s*(\d+)\s*章",title)
        if not m or int(m.group(1))!=n:
            raise ValueError("Catalog order mismatch at %s: %s" % (n,title))
        result.append({"ordinal":n,"url":url,"title":title})
    return result


def split_page(soup,url):
    candidate=[]
    for selector in CONTAINERS:
        for node in soup.select(selector):
            candidate.append((len(node.get_text(" ",strip=True)),node))
        if candidate:
            break
    if not candidate:
        raise ValueError("Chapter content container missing")
    _,node=max(candidate,key=lambda x:x[0])
    for bad in node.select(JUNK):
        bad.decompose()
    paragraphs=[re.sub(r"[ \t\u00a0]+"," ",line).strip() for line in node.get_text("\n",strip=True).splitlines()]
    paragraphs=[p for p in paragraphs if p]
    content="\n".join(paragraphs)
    han=len(re.findall(r"[\u3400-\u9fff]",content))
    # Split pages can contain a short final paragraph. Full-chapter minimum
    # length is checked only after every declared page has been assembled.
    if han<10 or len(content)<25:
        raise ValueError("Split page appears empty or truncated")
    if any(x.lower() in content.lower() for x in CHALLENGES):
        raise ValueError("Access gate embedded in chapter")
    next_pages=[]
    current=int(parse_qs(urlsplit(url).query).get("page",["1"])[0])
    for a in soup.select("a[href]"):
        candidate_url=urljoin(url,a["href"])
        try:
            p=checked(candidate_url,"chapter")
        except ValueError:
            continue
        if p.path!=urlsplit(url).path:
            continue
        next_no=int(parse_qs(p.query).get("page",["1"])[0])
        if next_no==current+1:
            next_pages.append(candidate_url)
    if len(set(next_pages))>1:
        raise ValueError("Ambiguous next page URL")
    title=soup.title.get_text(" ",strip=True) if soup.title else ""
    page_match=re.search(r"\((\d+)\s*/\s*(\d+)\)",title)
    if not page_match:
        raise ValueError("Missing multipart page count: " + title[:100])
    shown,total=map(int,page_match.groups())
    if shown!=current or not 1<=total<=30:
        raise ValueError("Invalid multipart page number")
    if current<total and not next_pages:
        raise ValueError("Missing continuation for page %s/%s" % (current,total))
    if current==total and next_pages:
        raise ValueError("Continuation beyond declared total")
    return content, (next_pages[0] if next_pages else None)


def chapter(session,policy,entry,delay):
    url=entry["url"]
    pages=[]
    texts=[]
    seen=set()
    while url:
        if url in seen or len(seen)>30:
            raise ValueError("Repeated page or page count overflow")
        seen.add(url)
        page=read(session,policy,url,delay)
        heading=page.title.get_text(" ",strip=True) if page.title else ""
        m=re.search(r"第\s*(\d+)\s*章",heading)
        if not m or int(m.group(1))!=entry["ordinal"]:
            raise ValueError("Wrong chapter number in page title: "+heading[:100])
        body,next_url=split_page(page,url)
        if body in texts:
            raise ValueError("Duplicate split-page text")
        texts.append(body)
        pages.append(url)
        url=next_url
    full="\n\n".join(texts)
    if len(full)<1000 or len(re.findall(r"[\u3400-\u9fff]",full))<500:
        raise ValueError("Assembled chapter is incomplete")
    return full,pages


def run(args):
    if not 0.5<=args.delay<=60 or args.start<1 or args.end<0 or (args.end and args.end<args.start):
        raise ValueError("Invalid options")
    out=Path(args.output)
    out.mkdir(parents=True,exist_ok=True)
    receipt={"source":ROOT,"status":"INCOMPLETE","catalog_count":0,"range":[args.start,args.end],
             "chapters":[],"errors":[]}
    try:
        session=requests.Session()
        session.headers.update({"User-Agent":UA,"Accept-Language":"zh-CN,zh;q=0.9"})
        policy=robots(session)
        entries=catalog(session,policy,args.delay)
        receipt["catalog_count"]=len(entries)
        receipt["catalog"]=[{"ordinal":x["ordinal"],"url":x["url"],"title":x["title"]} for x in entries]
        end=args.end or len(entries)
        if end>len(entries):
            raise ValueError("Requested end exceeds discovered catalog")
        selected=entries[args.start-1:end]
        if not selected:
            raise ValueError("Empty selection")
        if not args.catalog_only:
            (out/"chapters").mkdir(exist_ok=True)
            existing={}
            if args.resume and (out/"manifest.json").exists():
                old=json.loads((out/"manifest.json").read_text(encoding="utf-8"))
                if old.get("source")!=ROOT or old.get("catalog")!=receipt["catalog"]:
                    raise ValueError("Catalog changed; refusing unsafe resume")
                for row in old.get("chapters",[]):
                    ordinal=row.get("ordinal")
                    if not isinstance(ordinal,int) or ordinal not in range(args.start,end+1):
                        continue
                    entry=entries[ordinal-1]
                    if row.get("url")!=entry["url"] or row.get("title")!=entry["title"]:
                        raise ValueError("Prior chapter source mismatch at "+str(ordinal))
                    expected="chapters/%04d.txt" % ordinal
                    if row.get("file")!=expected:
                        raise ValueError("Prior chapter path mismatch at "+str(ordinal))
                    content_path=out/expected
                    if not content_path.is_file():
                        raise ValueError("Prior chapter file missing at "+str(ordinal))
                    data=content_path.read_bytes()
                    if hashlib.sha256(data).hexdigest()!=row.get("sha256"):
                        raise ValueError("Prior chapter hash mismatch at "+str(ordinal))
                    if ordinal in existing:
                        raise ValueError("Duplicate prior chapter "+str(ordinal))
                    existing[ordinal]=row
                print("RESUME",len(existing),"verified existing chapters",flush=True)
            for entry in selected:
                n=entry["ordinal"]
                if n in existing:
                    receipt["chapters"].append(existing[n])
                    continue
                try:
                    content,pages=chapter(session,policy,entry,args.delay)
                    value=entry["title"]+"\nSource: "+entry["url"]+"\n\n"+content+"\n"
                    data=value.encode("utf-8")
                    filename="chapters/%04d.txt" % n
                    (out/filename).write_bytes(data)
                    receipt["chapters"].append({"ordinal":n,"url":entry["url"],"title":entry["title"],
                        "pages":pages,"chars":len(content),"bytes":len(data),
                        "sha256":hashlib.sha256(data).hexdigest(),"file":filename})
                    print("OK",n,"pages",len(pages),"chars",len(content),flush=True)
                except Exception as exc:
                    receipt["errors"].append({"ordinal":n,"url":entry["url"],"error":str(exc)})
                    print("FAIL",n,str(exc),flush=True)
            if len(receipt["chapters"])==len(selected) and not receipt["errors"]:
                receipt["chapters"].sort(key=lambda row:row["ordinal"])
                combined="\n\n".join((out/x["file"]).read_text(encoding="utf-8") for x in receipt["chapters"])
                (out/"combined.txt").write_text(combined,encoding="utf-8")
                with zipfile.ZipFile(out/"chapters.zip","w",compression=zipfile.ZIP_DEFLATED) as archive:
                    for entry in receipt["chapters"]:
                        archive.write(out/entry["file"],entry["file"])
                    archive.write(out/"combined.txt","combined.txt")
                receipt["status"]="PASS"
        else:
            receipt["status"]="CATALOG_ONLY"
    except Exception as exc:
        receipt["errors"].append({"error":str(exc)})
        print("FATAL",str(exc),flush=True)
    (out/"manifest.json").write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (out/"summary.md").write_text("# Tongren 3233353\n\nCatalog: %s\n\nStatus: %s\n\nVerified: %s\n\nFailures: %s\n"%
          (receipt["catalog_count"],receipt["status"],len(receipt["chapters"]),len(receipt["errors"])),encoding="utf-8")
    return 0 if receipt["status"] in ("PASS","CATALOG_ONLY") else 1


if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--start",type=int,default=1)
    ap.add_argument("--end",type=int,default=0,help="0 means catalog end")
    ap.add_argument("--delay",type=float,default=1.0)
    ap.add_argument("--output",default="out/tongren-3233353")
    ap.add_argument("--catalog-only",action="store_true")
    ap.add_argument("--resume",action="store_true",help="Verify and reuse existing chapter files and manifest")
    raise SystemExit(run(ap.parse_args()))
