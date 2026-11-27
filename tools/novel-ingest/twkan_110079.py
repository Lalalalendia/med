#!/usr/bin/env python3
"""Authorized collection of book 110079 from public TWKAN pages.
No authentication, challenge solving, proxy rotation or access-control bypass.
"""
import hashlib
import json
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser
import requests
from bs4 import BeautifulSoup

BASE = "https://twkan.com"
BOOK = "110079"
AGENT = "MedNovelCollector/1.0"
INDEXES = (
    BASE + "/ajax_novels/chapterlist/" + BOOK + ".html",
    BASE + "/book/" + BOOK + ".html",
    BASE + "/book/" + BOOK + "/index.html",
)
EXPECTED = set(range(1, 292))
TITLE_RE = re.compile(r"^第\s*([0-9]+|[零〇一二三四五六七八九十百千兩两]+)\s*章\s*(.*)$")
HAN = dict(zip("零一二三四五六七八九", range(10)))
HAN.update({"〇": 0, "兩": 2, "两": 2})
UNITS = {"十": 10, "百": 100, "千": 1000}
CHAPTER_PATH = re.compile(r"/txt/" + BOOK + r"/\d+(?:\.html)?/?")
BLOCK = ("just a moment", "verify you are human", "checking your browser", "cf-chl-")
SELECTORS = ("#txtcontent0", "#txtcontent", "#chaptercontent", ".chapter-content",
             ".read-content", ".novel-content", "#content")
CHINESE = re.compile(r"[\u3400-\u9fff]")
OUT = Path("out/twkan-110079")

class Stop(Exception):
    pass

def number(s):
    if s.isdecimal():
        return int(s)
    total = digit = 0
    for ch in s:
        if ch in UNITS:
            total += (digit or 1) * UNITS[ch]
            digit = 0
        else:
            digit = HAN[ch]
    return total + digit

def title_number(s):
    match = TITLE_RE.match(s.strip())
    return number(match[1]) if match else None

def chapter_url(href):
    u = urljoin(BASE, href)
    p = urlsplit(u)
    if (p.scheme == "https" and p.netloc == "twkan.com" and
            CHAPTER_PATH.fullmatch(p.path) and not p.query):
        return BASE + p.path
    return None

def catalog(html):
    soup = BeautifulSoup(html, "html.parser")
    result = {}
    urls = {}
    for a in soup.select("a[href]"):
        u = chapter_url(a["href"])
        if not u:
            continue
        label = " ".join(a.get_text(" ", strip=True).split())
        n = title_number(label)
        if n not in EXPECTED:
            continue
        if n in result and result[n]["url"] != u:
            raise Stop(f"Conflicting URLs for chapter {n}")
        if u in urls and urls[u] != n:
            raise Stop(f"Same URL assigned to distinct chapters {urls[u]} and {n}")
        result[n] = {"number": n, "title": label, "url": u}
        urls[u] = n
    return result

def parse_body(html, expected):
    soup = BeautifulSoup(html, "html.parser")
    headers = [x.get_text(" ", strip=True) for x in soup.select("h1,h2,.chapter-title")]
    if soup.title:
        headers.append(soup.title.get_text(" ", strip=True))
    observed = [n for s in headers if (n := title_number(s)) is not None]
    if not observed or any(n != expected for n in observed):
        raise ValueError(f"chapter heading mismatch: expected {expected}, observed {observed}")
    numbered = [(int(m[1]), node) for node in soup.select("[id^=txtcontent]")
                if (m := re.fullmatch(r"txtcontent(\d+)", node.get("id","")))]
    if numbered:
        numbered.sort(key=lambda t: t[0])
        roots = [node for _,node in numbered if not any(other in node.parents for _,other in numbered)]
    else:
        roots = []
        for selector in SELECTORS:
            node = soup.select_one(selector)
            if node is not None:
                roots = [node]
                break
    if not roots:
        raise ValueError("no recognized chapter text container")
    for a in soup.select("a[href]"):
        if re.search(r"下一[頁页]|下[一]?頁|next page", a.get_text(" ", strip=True), re.I):
            raise ValueError("possible separate pagination; cannot certify complete chapter")
    blocks = []
    for root in roots:
        for junk in root.select("script,style,iframe,form,nav,footer,button,.ads,.advertisement,.ad"):
            junk.decompose()
        paragraphs = root.select("p")
        lines = [p.get_text(" ", strip=True) for p in paragraphs] if paragraphs else root.get_text("\n",strip=True).splitlines()
        for line in lines:
            line = re.sub(r"[\t \u00a0]+", " ", line).strip()
            if not line or re.fullmatch(r"(上一章|下一章|返回目[錄录]|加入書架|章節報錯)", line):
                continue
            blocks.append(line)
    body = "\n\n".join(blocks)
    han = len(CHINESE.findall(body))
    chars = len(re.sub(r"\s+", "", body))
    if han < 300 or chars < 400 or han / max(chars,1) < .35:
        raise ValueError(f"too short or not Chinese prose: {han} Han, {chars} characters")
    return body, chars, han

def self_test():
    sample = '<a href="/txt/110079/100">第1章 測試</a><a href="/txt/110079/200">第二章 測試</a><a href="/txt/110078/100">第3章 錯誤</a>'
    assert set(catalog(sample)) == {1,2}
    assert title_number("第二百九十一章 結局") == 291
    body = "<h1>第1章 測試</h1><div id='txtcontent0'><p>" + "這是合成測試資料。" * 100 + "</p></div>"
    assert parse_body(body,1)[2] >= 300
    try:
        parse_body(body,2)
    except ValueError:
        pass
    else:
        raise AssertionError("incorrect heading accepted")
    print("SELF_TEST_OK")

def run():
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT/"raw").mkdir(exist_ok=True)
    report = {"book_id":BOOK, "source":BASE, "expected":291, "catalog_requests":[],
              "catalog_count":0, "chapters":[], "status":"INCOMPLETE"}
    s = requests.Session()
    s.headers.update({"User-Agent":AGENT,"Accept-Language":"zh-TW,zh;q=0.8"})
    rp = RobotFileParser()
    delay = 2.0
    last = 0.0

    def request(url, robots=True):
        nonlocal last
        if robots and not rp.can_fetch(AGENT,url):
            raise Stop("robots.txt disallows " + url)
        time.sleep(max(0, delay - (time.monotonic()-last)))
        try:
            r = s.get(url, timeout=(10,25), allow_redirects=False)
        except requests.RequestException as e:
            raise Stop(f"network error: {e}") from e
        finally:
            last = time.monotonic()
        if r.status_code in (401,402,403,429,451,503):
            raise Stop(f"HTTP {r.status_code} at {url}; stopped without bypass")
        if r.status_code == 200 and any(x in r.text.lower() for x in BLOCK):
            raise Stop("challenge page; stopped without bypass")
        return r

    try:
        r = request(BASE+"/robots.txt",False)
        if r.status_code == 404:
            rp.parse([])
        elif r.status_code == 200 and "user-agent:" in r.text.lower():
            rp.parse(r.text.splitlines())
        else:
            raise Stop(f"robots.txt not verified: HTTP {r.status_code}")
        delay = max(delay, rp.crawl_delay(AGENT) or 0, rp.crawl_delay("*") or 0)
        rate = rp.request_rate(AGENT) or rp.request_rate("*")
        if rate and rate.requests:
            delay = max(delay, rate.seconds / rate.requests)
        entries = {}
        for u in INDEXES:
            if not rp.can_fetch(AGENT,u):
                report["catalog_requests"].append({"url":u,"status":"robots_disallowed"})
                continue
            r = request(u)
            report["catalog_requests"].append({"url":u,"http_status":r.status_code})
            if r.status_code != 200:
                continue
            found = catalog(r.text)
            report["catalog_requests"][-1]["count"] = len(found)
            if len(found)>len(entries):
                entries=found
            if set(entries)==EXPECTED:
                break
        report["catalog_count"]=len(entries)
        report["catalog_missing"]=sorted(EXPECTED-set(entries))
        report["catalog"]=list(entries.values())
        print("CATALOG", len(entries), "/ 291", flush=True)
        if set(entries)!=EXPECTED:
            raise Stop("catalog incomplete; chapter export withheld")
        body_hashes={}
        for n in sorted(entries):
            row=dict(entries[n])
            try:
                r=request(row["url"])
                if r.status_code!=200:
                    raise ValueError(f"HTTP {r.status_code}")
                body,chars,han=parse_body(r.text,n)
                bh=hashlib.sha256(body.encode()).hexdigest()
                if bh in body_hashes:
                    raise ValueError(f"duplicate body of chapter {body_hashes[bh]}")
                body_hashes[bh]=n
                payload=(row["title"]+"\n\n"+body+"\n").encode()
                dest=OUT/"raw"/f"{n:04d}.txt"
                dest.write_bytes(payload)
                row.update(status="ok",file=f"raw/{n:04d}.txt",chars=chars,han=han,
                           sha256=hashlib.sha256(payload).hexdigest())
            except Stop as e:
                row.update(status="stopped",error=str(e))
                report["chapters"].append(row)
                raise
            except ValueError as e:
                row.update(status="failed",error=str(e))
            report["chapters"].append(row)
            if n<=5 or n%10==0 or n==291 or row["status"]!="ok":
                print("CHAPTER",n,row["status"],row.get("han",0),flush=True)
    except Stop as e:
        report["stop_reason"]=str(e)
        print("STOP",e,flush=True)
    finally:
        rows={r["number"]:r for r in report["chapters"]}
        report["chapters"]=[rows.get(n,{"number":n,"status":"not_attempted"}) for n in sorted(EXPECTED)]
        ok=[r for r in report["chapters"] if r["status"]=="ok"]
        report["ok_count"]=len(ok)
        report["total_han"]=sum(r["han"] for r in ok)
        report["total_chars"]=sum(r["chars"] for r in ok)
        report["missing_numbers"]=[r["number"] for r in report["chapters"] if r["status"]!="ok"]
        for r in ok:
            p=OUT/r["file"]
            if hashlib.sha256(p.read_bytes()).hexdigest()!=r["sha256"]:
                raise RuntimeError(f"hash mismatch {r['number']}")
        report["status"]="PASS" if len(ok)==291 else "INCOMPLETE"
        name="combined.txt" if len(ok)==291 else "partial.txt"
        if ok:
            (OUT/name).write_bytes(b"\n\n".join((OUT/r["file"]).read_bytes() for r in ok))
        (OUT/"manifest.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        files=sorted(p for p in OUT.rglob("*") if p.is_file() and p.name!="SHA256SUMS")
        (OUT/"SHA256SUMS").write_text("".join(hashlib.sha256(p.read_bytes()).hexdigest()+"  "+p.relative_to(OUT).as_posix()+"\n" for p in files),encoding="utf-8")
        print("RESULT",report["status"],len(ok),"/ 291; HAN",report["total_han"],flush=True)
    return 0 if report["status"]=="PASS" else 1

if __name__=="__main__":
    self_test()
    raise SystemExit(run())
