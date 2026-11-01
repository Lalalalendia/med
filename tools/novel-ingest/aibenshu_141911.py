#!/usr/bin/env python3
"""Collect public Aibenshu 141911 chapters with fail-closed page completeness."""
import argparse
import base64
import hashlib
import json
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

BOOK = "https://www.aibenshu.com/book/141911/"
CHAPTER_RE = re.compile(r"^/read/141911/(\d+)(?:_(\d+))?\.html$")
TITLE_RE = re.compile(r"第\s*(\d+)\s*章")
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/129 Safari/537.36"


def get(session, url):
    last = None
    for attempt in range(4):
        try:
            r = session.get(url, timeout=35)
            if r.status_code in (429, 500, 502, 503, 504):
                last = f"HTTP {r.status_code}"
                time.sleep(2 ** attempt + 1)
                continue
            r.raise_for_status()
            r.encoding = r.apparent_encoding or "utf-8"
            return BeautifulSoup(r.text, "html.parser"), r.url, r.text
        except requests.RequestException as exc:
            last = str(exc)
            time.sleep(2 ** attempt + 1)
    raise RuntimeError(last)


def catalog(session):
    soup, resolved, _ = get(session, BOOK)
    result = {}
    for a in soup.select(".chapterlist a[href], dd a[href]"):
        title = a.get_text(" ", strip=True)
        match = TITLE_RE.search(title)
        if not match:
            continue
        href = urljoin(resolved, a["href"])
        if not CHAPTER_RE.fullmatch(urlsplit(href).path):
            continue
        ordinal = int(match.group(1))
        if ordinal in result and result[ordinal][0] != href:
            # Some catalog titles duplicate chapter numbers; prefer the expected
            # sequential URL ID, keeping the anomaly visible in the manifest.
            old_url = result[ordinal][0]
            expected_id = 96882 + ordinal - 1
            old_id = int(CHAPTER_RE.fullmatch(urlsplit(old_url).path).group(1))
            new_id = int(CHAPTER_RE.fullmatch(urlsplit(href).path).group(1))
            if abs(new_id - expected_id) < abs(old_id - expected_id):
                result[ordinal] = (href, title)
        else:
            result[ordinal] = (href, title)
    return result


def normalize(value):
    return "\n".join(line.strip() for line in value.splitlines() if line.strip())


def page(session, url, expected_ordinal):
    soup, final, html = get(session, url)
    h = soup.select_one("h1")
    heading = h.get_text(" ", strip=True) if h else ""
    m = TITLE_RE.search(heading)
    if not m or int(m.group(1)) != expected_ordinal:
        raise RuntimeError(f"wrong chapter header at {final}: {heading}")

    current = CHAPTER_RE.fullmatch(urlsplit(final).path)
    if not current:
        raise RuntimeError(f"unexpected page url {final}")
    page_no = int(current.group(2) or 1)
    count = re.search(r"[（(]\s*(\d+)\s*/\s*(\d+)\s*[）)]", heading)
    total = int(count.group(2)) if count else page_no
    if count and int(count.group(1)) != page_no:
        raise RuntimeError(f"wrong page index at {final}: {heading}")

    # The server-side #rtext node includes only an incomplete preview and
    # "Loading..." placeholder. The full public content is in an inline
    # CryptoJS AES-CBC payload, inserted into #rtext by the website itself.
    script_call = re.search(
        r"""\$\(\s*['"]#rtext['"]\s*\)\s*\.html\(\s*z\(\s*['"]([A-Za-z0-9+/=]+)['"]\s*,\s*['"]([A-Za-z0-9]{16})['"]\s*,\s*['"]([A-Za-z0-9]{16})['"]\s*\)\s*\)""",
        html,
        re.S,
    )
    if not script_call:
        raise RuntimeError(f"missing encrypted full chapter at {final}")

    ciphertext64, key, iv = script_call.groups()
    ciphertext = base64.b64decode(ciphertext64, validate=True)
    if len(ciphertext) < 1000 or len(ciphertext) % 16:
        raise RuntimeError(f"invalid ciphertext length at {final}: {len(ciphertext)}")
    decryptor = Cipher(algorithms.AES(key.encode("ascii")), modes.CBC(iv.encode("ascii"))).decryptor()
    decrypted = decryptor.update(ciphertext) + decryptor.finalize()
    pad_len = decrypted[-1]
    if not 1 <= pad_len <= 16 or decrypted[-pad_len:] != bytes([pad_len]) * pad_len:
        raise RuntimeError(f"invalid PKCS7 padding at {final}")
    chapter_html = decrypted[:-pad_len].decode("utf-8")
    chapter_soup = BeautifulSoup(chapter_html, "html.parser")
    for tag in chapter_soup.select("script,style,iframe,nav,header,footer,form,button"):
        tag.decompose()
    body = normalize(chapter_soup.get_text("\n", strip=True))

    preview_node = soup.select_one("#rtext")
    if preview_node is None:
        raise RuntimeError(f"missing preview node at {final}")
    visible_prefix = normalize(
        preview_node.get_text("\n", strip=True).split("Loading...", 1)[0]
    )
    if len(visible_prefix) < 50 or not body.startswith(visible_prefix):
        raise RuntimeError(f"decrypted body does not match visible preview at {final}")
    if "Loading..." in body or "内容未加载完成" in body:
        raise RuntimeError(f"unloaded placeholder in decrypted body at {final}")
    cjk_chars = len(re.findall(r"[\u3400-\u9fff]", body))
    if len(body) < 700 or cjk_chars < 450 or len(body) <= len(visible_prefix) + 200:
        raise RuntimeError(f"too little verified chapter at {final}: chars={len(body)}, cjk={cjk_chars}")
    return body, page_no, total


def run(args):
    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"})
    chapters = catalog(session)
    if not chapters:
        raise RuntimeError("catalog empty")
    end = max(chapters) if args.end == 0 else args.end
    if not 1 <= args.start <= end:
        raise RuntimeError(f"bad range {args.start}-{end}")
    root = Path(args.output)
    (root / "chapters").mkdir(parents=True, exist_ok=True)
    manifest = {"book_url": BOOK, "catalog_count": len(chapters), "catalog_max": max(chapters), "requested_start": args.start, "requested_end": end, "chapters": [], "failures": []}
    combined = []
    for n in range(args.start, end + 1):
        if n not in chapters:
            manifest["failures"].append({"number": n, "error": "missing catalog entry"})
            print(f"{n}: missing catalog entry", flush=True)
            continue
        url, title = chapters[n]
        try:
            first, page_no, total = page(session, url, n)
            if page_no != 1 or total > 12:
                raise RuntimeError(f"invalid pagination: {page_no}/{total}")
            text = [first]
            base = CHAPTER_RE.fullmatch(urlsplit(url).path).group(1)
            for p in range(2, total + 1):
                next_url = f"https://www.aibenshu.com/read/141911/{base}_{p}.html"
                time.sleep(max(args.delay, .5))
                part, actual, declared = page(session, next_url, n)
                if actual != p or declared != total:
                    raise RuntimeError(f"bad pagination page {p}/{total}: got {actual}/{declared}")
                text.append(part)
            content = "\n\n".join(text)
            if any(x == y for x,y in zip(text,text[1:])):
                raise RuntimeError("duplicate consecutive pages")
            chapter_text = f"{title}\nSource: {url}\n\n{content}\n"
            path = root / "chapters" / f"{n:04}.txt"
            path.write_text(chapter_text, encoding="utf-8")
            combined.append(chapter_text)
            manifest["chapters"].append({"number":n,"title":title,"source":url,"pages":total,"chars":len(content),"cjk_chars":len(re.findall(r"[\u3400-\u9fff]", content)),"sha256":hashlib.sha256(content.encode("utf-8")).hexdigest(),"file":str(path.relative_to(root))})
            print(f"{n}: OK {len(content)} chars, {total} pages", flush=True)
        except Exception as exc:
            manifest["failures"].append({"number":n,"url":url,"error":str(exc)})
            print(f"{n}: FAILED {exc}", flush=True)
        time.sleep(max(args.delay, .5))
    if combined:
        (root / "combined.txt").write_text("\n\n" + ("\n\n" + "="*60 + "\n\n").join(combined),encoding="utf-8")
    manifest["status"] = "PASS" if not manifest["failures"] and len(manifest["chapters"]) == end-args.start+1 else "INCOMPLETE"
    (root/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (root/"summary.md").write_text(f"# Aibenshu 141911\n\nRange: {args.start}-{end}\n\nStatus: {manifest['status']}\n\nVerified chapters: {len(manifest['chapters'])}\n\nFailures: {len(manifest['failures'])}\n",encoding="utf-8")
    print("STATUS",manifest["status"],"OK",len(manifest["chapters"]),"FAILURES",len(manifest["failures"]))
    return 0 if manifest["status"]=="PASS" else 1


if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--start",type=int,default=237)
    ap.add_argument("--end",type=int,default=0)
    ap.add_argument("--delay",type=float,default=0.7)
    ap.add_argument("--output",default="out/aibenshu-141911")
    raise SystemExit(run(ap.parse_args()))
