#!/usr/bin/env python3
"""Audit candidate mirror availability and HTML layout without saving text."""
from __future__ import annotations
import json
import re
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser
import requests
from bs4 import BeautifulSoup

SOURCES = {
    "novel543": "https://www.novel543.com/0511558316/dir",
    "zhys": "https://cn.zhys.tw/book/2268838.html",
    "abbshu": "https://m.abbshu.net/book/309042/",
    "twbook": "https://www.twbook.cc/1901458316/dir",
}
UA = "MedNovelMirrorProbe/1.0 (public HTML metadata only)"
CHAPTER = re.compile(r"第\s*[\d一二三四五六七八九十百千]{1,5}\s*[章节節回]")
SELECTORS = ("#content", "#chaptercontent", "#txt", "#BookText",
             ".chapter-content", ".read-content", ".article-content",
             ".txtnav", ".content", "article")


def same_host(base, target):
    a, b = urlsplit(base), urlsplit(target)
    return (b.scheme == "https" and b.hostname == a.hostname
            and b.username is None and b.password is None
            and b.port in (None, 443))


def get_robots(session, url):
    p = urlsplit(url)
    robots_url = p.scheme + "://" + p.netloc + "/robots.txt"
    try:
        r = session.get(robots_url, timeout=20, allow_redirects=False)
    except requests.RequestException as exc:
        return None, "robots_error:" + type(exc).__name__
    policy = RobotFileParser()
    if r.status_code in (404, 410):
        policy.parse(["User-agent: *", "Allow: /"])
    elif r.status_code == 200 and "<html" not in r.text[:500].lower():
        policy.parse(r.text.splitlines())
    else:
        return None, "robots_http:" + str(r.status_code)
    return policy, "ok"


def get_html(session, url, policy, original):
    if not same_host(original, url):
        return None, "external_host"
    if not policy.can_fetch(UA, url):
        return None, "robots_disallow"
    try:
        r = session.get(url, timeout=30, allow_redirects=False)
    except requests.RequestException as exc:
        return None, "network_error:" + type(exc).__name__
    if r.status_code != 200:
        return None, "http:" + str(r.status_code)
    if "html" not in r.headers.get("Content-Type", "").lower():
        return None, "not_html"
    if not r.encoding or r.encoding.lower() == "iso-8859-1":
        r.encoding = r.apparent_encoding or "utf-8"
    return BeautifulSoup(r.text, "html.parser"), "ok"


def node_stats(doc):
    output = []
    for sel in SELECTORS:
        for el in doc.select(sel)[:2]:
            raw = el.get_text(" ", strip=True)
            output.append({"selector": sel, "chars": len(raw),
                           "han": len(re.findall(r"[\u3400-\u9fff]", raw)),
                           "links": len(el.select("a[href]"))})
    return output


def chapter_links(doc, base):
    out, seen = [], set()
    for a in doc.select("a[href]"):
        title = re.sub(r"\s+", " ", a.get_text(" ", strip=True))
        if not CHAPTER.search(title) or len(title) > 120:
            continue
        url = urljoin(base, a["href"])
        if not same_host(base, url) or url in seen:
            continue
        seen.add(url)
        out.append({"label": title[:70], "url": url})
    return out


def probe(session, name, url):
    row = {"name": name, "url": url}
    policy, robots_state = get_robots(session, url)
    row["robots"] = robots_state
    if policy is None:
        row["status"] = "robots_unavailable"
        return row
    page, status = get_html(session, url, policy, url)
    row["status"] = status
    if page is None:
        return row
    row["title"] = page.title.get_text(" ", strip=True)[:150] if page.title else ""
    row["page_han"] = len(re.findall(r"[\u3400-\u9fff]", page.get_text(" ", strip=True)))
    row["containers"] = node_stats(page)
    navigation = []
    for a in page.select("a[href]"):
        label = re.sub(r"\s+", " ", a.get_text(" ", strip=True))
        if any(key in label.lower() for key in ("目录", "目錄", "章节", "章節", "more", "全部")):
            href = urljoin(url, a["href"])
            if same_host(url, href) and len(navigation) < 20:
                navigation.append({"label": label[:55], "url": href})
    row["navigation"] = navigation
    row["article_children"] = []
    for el in page.select("article > *, main > *")[:30]:
        text = el.get_text(" ", strip=True)
        row["article_children"].append({"tag": el.name, "class": el.get("class", []),
                                        "id": el.get("id"), "han": len(re.findall(r"[\u3400-\u9fff]", text)),
                                        "links": len(el.select("a[href]"))})
    links = chapter_links(page, url)
    row["chapter_link_count"] = len(links)
    row["first_links"] = links[:3]
    row["last_links"] = links[-3:]
    if links:
        first = links[0]["url"]
        sub, result = get_html(session, first, policy, url)
        row["sample"] = {"url": first, "status": result}
        if sub is not None:
            row["sample"]["containers"] = node_stats(sub)
            row["sample"]["title"] = sub.title.get_text(" ", strip=True)[:150] if sub.title else ""
    return row


def run(output, session=None):
    session = session or requests.Session()
    session.headers.update({"User-Agent": UA, "Accept-Language": "zh,zh-TW;q=0.9"})
    rows = [probe(session, name, url) for name, url in SOURCES.items()]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"sources": rows}, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    for row in rows:
        print(json.dumps({"name": row["name"], "status": row["status"],
                          "robots": row["robots"], "links": row.get("chapter_link_count", 0),
                          "sample_status": row.get("sample", {}).get("status")},
                         ensure_ascii=False))
    return rows


if __name__ == "__main__":
    run(Path("out/marvel-taylor/mirror-probe.json"))
