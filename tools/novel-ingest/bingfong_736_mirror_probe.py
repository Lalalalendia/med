#!/usr/bin/env python3
"""Safe metadata-only availability probe for authorized alternate novel sources."""
import json
import re
import time
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser
import requests
from bs4 import BeautifulSoup

SOURCES = [
    ("czbooks", "https://czbooks.net/n/uk0ff", "/n/uk0ff/"),
    ("8book", "https://8book.com/novelbooks/140659/", "/novelbooks/140659/"),
    ("biquge", "https://m.biquge.com.tw/gzzeg/", "/gzzeg/"),
]
UA = "MedNovelAvailabilityAudit/1.0 (+https://github.com/Lalalalendia/med)"
TARGET = {
    1: (r"第(?:一|1)章",),
    300: (r"第(?:三百|300)章",),
    587: (r"第(?:五百八十七|587)章",),
}

def fetch(session, robot, url, host):
    if urlsplit(url).hostname != host or not robot.can_fetch(UA, url):
        raise ValueError("host or robots disallowed")
    time.sleep(1.2)
    r = session.get(url, timeout=(8, 22), allow_redirects=False)
    if r.status_code != 200:
        raise ValueError("HTTP " + str(r.status_code))
    if "html" not in r.headers.get("Content-Type", "").lower():
        raise ValueError("unexpected content type")
    if r.url != url:
        raise ValueError("redirect")
    r.encoding = r.apparent_encoding or "utf-8"
    return r.text

def inspect(label, index, prefix):
    s = requests.Session()
    s.headers["User-Agent"] = UA
    host = urlsplit(index).hostname
    result = {"source": label, "index": index, "status": "unverified", "samples": []}
    try:
        rr = s.get(f"https://{host}/robots.txt", timeout=(8, 18), allow_redirects=False)
        policy = RobotFileParser()
        if rr.status_code == 200 and "<html" not in rr.text[:400].lower():
            policy.parse(rr.text.splitlines())
        elif rr.status_code in (404, 410):
            policy.parse(["User-agent: *", "Allow: /"])
        else:
            raise ValueError(f"robots unavailable (HTTP {rr.status_code})")
        html = fetch(s, policy, index, host)
        doc = BeautifulSoup(html, "html.parser")
        anchors = {}
        for a in doc.select("a[href]"):
            title = a.get_text(" ", strip=True)
            url = urljoin(index, a["href"])
            p = urlsplit(url)
            if p.scheme == "https" and p.hostname == host and p.path.startswith(prefix) and not p.query:
                if re.search(r"第.{1,12}章", title):
                    anchors[url] = title[:120]
        result["catalog_links"] = len(anchors)
        if len(anchors) < 500:
            raise ValueError("incomplete catalog / fewer than 500 chapter links")
        for n, patterns in TARGET.items():
            choices = [(u, t) for u, t in anchors.items()
                       if any(re.search(pattern, t) for pattern in patterns)]
            if len(choices) != 1:
                raise ValueError(f"chapter {n} link count: {len(choices)}")
            url, title = choices[0]
            body = fetch(s, policy, url, host)
            soup = BeautifulSoup(body, "html.parser")
            if any(x in soup.get_text(" ", strip=True).lower()[:2000]
                   for x in ("captcha", "verify you are human", "access denied", "請先登入")):
                raise ValueError("access challenge")
            roots = [soup.select_one(sel) for sel in
                     ("#content", "#chaptercontent", ".chapter-content", ".read-content",
                      ".content", "article", "main")]
            roots = [x for x in roots if x is not None]
            if not roots:
                raise ValueError("chapter content selector missing")
            best = max(roots, key=lambda x: len(x.get_text(" ", strip=True)))
            han = len(re.findall(r"[\u3400-\u9fff]", best.get_text(" ", strip=True)))
            result["samples"].append({"chapter": n, "url": url, "han_chars": han, "title": title})
            if han < 500:
                raise ValueError(f"short chapter {n} ({han} Han)")
        result["status"] = "3_samples_readable"
    except Exception as err:
        result["status"] = "failed"
        result["error"] = str(err)[:250]
    return result

def main():
    rows = [inspect(*s) for s in SOURCES]
    for row in rows:
        print(json.dumps(row, ensure_ascii=False), flush=True)
    from pathlib import Path
    out = Path("out/bingfong-736-mirrors")
    out.mkdir(parents=True, exist_ok=True)
    (out / "probe.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "summary.md").write_text(
        "# Alternate original sources (metadata only)\n\n" +
        "\n".join(f"- {r['source']}: {r['status']}; {r.get('catalog_links',0)} links; {r.get('error','')}"
                  for r in rows) + "\n", encoding="utf-8")
    return 0 if any(r["status"] == "3_samples_readable" for r in rows) else 2

if __name__ == "__main__":
    raise SystemExit(main())
