#!/usr/bin/env python3
"""Authorized collection of the public Chinese Masked Knight source.

Download every distinct chapter page linked in the Tianyabooks catalog.
Keep all conflicting URLs, retain partial results, and NEVER claim the entire
book is complete without ordinals 1..330 and an editorial continuity review.
No login, paywall, CAPTCHA or robots.txt bypass.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup
from chapter_coverage_census import PoliteClient
from masked_knight_cn_catalog_audit import number_from_title

INDEX = "https://www.tianyabooks.com/net/bianlianwushi/"
CHAPTER_RE = re.compile(r"^/net/bianlianwushi/([0-9]+)\.html$")
EXPECTED = 330
CJK = re.compile(r"[\u3400-\u9fff]")
ACCESS = re.compile(r"captcha|just a moment|verify you are human|"
                    r"access denied|login to read|请先登录|请输入验证码|付费阅读|"
                    r"购买本章|本站不提供", re.I)
NAV = re.compile(r"^(上一章|下一章|返回目录|回目录|目录|首页|"
                 r"上一篇|下一篇|返回书页|变脸武士在线阅读|"
                 r"天涯书库|Copyright|加入书签)(?:\s|$)")
STORY_SELECTORS = ("#main", "#content", ".content", "article", "main")


def catalog(html: str) -> dict:
    found = []
    seen = set()
    for a in BeautifulSoup(html, "html.parser").select("a[href]"):
        title = re.sub(r"\s+", " ", a.get_text(" ", strip=True))
        number = number_from_title(title)
        if number is None or not 1 <= number <= EXPECTED:
            continue
        url = urljoin(INDEX, a.get("href", "")).split("#", 1)[0]
        p = urlsplit(url)
        if (p.scheme != "https" or p.netloc != "www.tianyabooks.com"
                or p.query or not CHAPTER_RE.fullmatch(p.path)):
            continue
        if url in seen:
            continue
        seen.add(url)
        found.append({"ordinal": number, "title": title,
                      "url": url, "source_id": CHAPTER_RE.fullmatch(p.path).group(1)})
    groups = defaultdict(list)
    for row in found:
        groups[row["ordinal"]].append(row)
    return {
        "links": found,
        "indexed_ordinals": len(groups),
        "index_unique_pages": len(found),
        "missing_ordinals": sorted(set(range(1, EXPECTED + 1)) - set(groups)),
        "multiple_pages": {str(n): v for n, v in groups.items() if len(v) > 1},
    }


def parse_story(html: str, ordinal: int) -> dict:
    if ACCESS.search(html[:14000]):
        return {"status": "access_page", "cjk": 0, "text": ""}
    doc = BeautifulSoup(html, "html.parser")
    heading = doc.select_one("h1,h2")
    heading_text = heading.get_text(" ", strip=True) if heading else ""
    heading_number = number_from_title(heading_text)
    if heading_number is not None and heading_number != ordinal:
        return {"status": "wrong_heading", "cjk": 0, "text": "",
                "heading": heading_text[:100]}
    original_cjk = len(CJK.findall(doc.get_text(" ", strip=True)))
    for selector in STORY_SELECTORS:
        container = doc.select_one(selector)
        if container is None:
            continue
        # Selectors are site-specific candidates, never entire HTML.
        for bad in container.select(
                "script,style,noscript,iframe,svg,nav,footer,header,aside,"
                "form,button,textarea,.advertisement,.ads,.navigation,"
                ".breadcrumb,.breadcrumbs,.comment,.comments"):
            bad.decompose()
        raw_lines = container.get_text("\n", strip=True).splitlines()
        lines = []
        for line in raw_lines:
            normalized = re.sub(r"[\u00a0 \t]+", " ", line).strip()
            if not normalized or NAV.search(normalized):
                continue
            if len(normalized) < 70 and (normalized.startswith("上一") or normalized.startswith("下一")):
                continue
            if (normalized.startswith("变脸武士") or normalized.startswith("第")
                    ) and number_from_title(normalized) == ordinal and len(normalized) < 120:
                continue
            lines.append(normalized)
        text = "\n".join(lines).strip()
        chars = len(CJK.findall(text))
        if chars < 200:
            continue
        proportion = round(chars / max(original_cjk, 1), 3)
        status = "long_candidate" if chars >= 1200 and proportion >= 0.65 else "needs_review"
        if ACCESS.search(text[:3000]):
            status = "access_page"
        return {"status": status, "text": text+"\n",
                "cjk": chars, "document_cjk": original_cjk,
                "relative_cjk": proportion, "selector": selector,
                "heading": heading_text[:100]}
    return {"status": "no_valid_body", "text": "", "cjk": 0,
            "document_cjk": original_cjk, "heading": heading_text[:100]}


def save_status(out: Path, state: dict) -> None:
    out.mkdir(parents=True, exist_ok=True)
    verified = {x["ordinal"] for x in state["pages"]
                if x["status"] == "long_candidate"}
    recovered = {x["ordinal"] for x in state["pages"]
                 if x["status"] in ("long_candidate", "needs_review")}
    state["cjk_long_candidate_ordinals"] = len(verified)
    state["recovered_text_ordinals"] = len(recovered)
    state["missing_verified_ordinals"] = sorted(set(range(1, EXPECTED+1)) - verified)
    state["missing_any_text_ordinals"] = sorted(set(range(1, EXPECTED+1)) - recovered)
    state["status"] = "PARTIAL_COLLECTION"
    if (len(verified) == EXPECTED and
            not state["index"]["missing_ordinals"] and
            not state["failed_pages"] and
            not state["index"]["multiple_pages"]):
        state["status"] = "AUTOMATED_330_CANDIDATES_PENDING_EDITORIAL_REVIEW"
    (out/"manifest.json").write_text(
        json.dumps(state,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    lines = [
        "# Masked Knight — Tianyabooks Chinese collection", "",
        "Status: **"+state["status"]+"**",
        f"Catalog: {state['index']['indexed_ordinals']}/330 ordinals, "
        f"{state['index']['index_unique_pages']} distinct chapter page URLs.",
        "Missing catalog ordinals: "+str(state["index"]["missing_ordinals"]),
        f"Collected candidate full texts: {sum(r['status']=='long_candidate' for r in state['pages'])}",
        f"Collected shorter/review texts: {sum(r['status']=='needs_review' for r in state['pages'])}",
        f"Downloaded pages: {len(state['pages'])}; failures: {len(state['failed_pages'])}",
        f"Recovered ordinals: {len(recovered)}/330; long-text candidates: {len(verified)}/330.",
        "Duplicate chapter numbers: "+str(sorted(state["index"]["multiple_pages"].keys())),
        "Remaining ordinals with no text: "+str(state["missing_any_text_ordinals"]),
        "",
        "This is not a certified complete book. Content continuity and split chapter review are required.",
    ]
    (out/"summary.md").write_text("\n".join(lines)+"\n",encoding="utf-8")


def collect(out: Path, delay: float = 2.0, *, sample_only: bool = False) -> dict:
    if not 1.5 <= delay <= 10:
        raise ValueError("delay must be between 1.5 and 10 seconds")
    if out.exists() and any(out.iterdir()):
        raise ValueError("Output directory must be empty")
    out.mkdir(parents=True, exist_ok=True)
    client = PoliteClient(delay)
    try:
        html = client.get(INDEX)
        if "变脸武士" not in html and "變臉武士" not in html:
            raise RuntimeError("Book identity not found in catalog")
        index = catalog(html)
        if index["indexed_ordinals"] < 300:
            raise RuntimeError("Catalog unexpectedly too short")
        rows = index.pop("links")
        state = {
            "book":"变脸武士", "author":"跳舞", "site":"tianyabooks",
            "book_url":INDEX, "started_utc":dt.datetime.now(dt.timezone.utc).isoformat(),
            "expected_ordinals":EXPECTED, "rights_confirmed":True,
            "mode":"smoke" if sample_only else "full",
            "index":index, "pages":[], "failed_pages":[],
            "source_priority":"main_recovery",
        }
        save_status(out,state)
        if sample_only:
            positions=(1,159,164,200,240,242,330)
            rows=[r for r in rows if r["ordinal"] in positions]
        (out/"raw").mkdir()
        # Preserve same-ordinal alternative links separately. Never silently
        # merge these split/duplicate entries into one chapter.
        for i, row in enumerate(rows, 1):
            num=row["ordinal"]
            try:
                page=client.get(row["url"])
                quality=parse_story(page, num)
                record={**row, **{k:v for k,v in quality.items() if k!="text"}}
                if quality["status"] in ("long_candidate","needs_review"):
                    body=quality["text"].encode("utf-8")
                    fingerprint=hashlib.sha256(body).hexdigest()
                    filename=f"raw/{num:03d}_{row['source_id']}.txt"
                    (out/filename).write_bytes(body)
                    record["sha256"]=fingerprint
                    record["raw_file"]=filename
                state["pages"].append(record)
                if quality["status"] not in ("long_candidate","needs_review"):
                    state["failed_pages"].append({
                        "url":row["url"],"ordinal":num,
                        "reason":quality["status"]})
            except Exception as exc:
                state["failed_pages"].append({
                    "url":row["url"],"ordinal":num,
                    "reason":type(exc).__name__+": "+str(exc)[:230]})
                if isinstance(exc, RuntimeError):
                    # Robots/403/429 and other runtime transport blocks halt requests.
                    break
            if i % 20 == 0 or i == len(rows):
                save_status(out,state)
                print(f"progress {i}/{len(rows)}; recovered="
                      f"{len(state['pages'])}; failed={len(state['failed_pages'])}",flush=True)
        save_status(out,state)
        return state
    finally:
        client.session.close()


def main() -> int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--rights-confirmed",action="store_true")
    p.add_argument("--out",type=Path,default=Path("out/masked-knight-cn-tianyabooks"))
    p.add_argument("--delay",type=float,default=2.0)
    p.add_argument("--sample-only",action="store_true")
    args=p.parse_args()
    if not args.rights_confirmed:
        print("Book-specific permission required",file=sys.stderr)
        return 2
    try:
        d=collect(args.out,args.delay,sample_only=args.sample_only)
    except Exception as exc:
        print(f"STOP: {type(exc).__name__}: {exc}",file=sys.stderr)
        return 1
    print((args.out/"summary.md").read_text(),flush=True)
    return 0 if not d["failed_pages"] and d["recovered_text_ordinals"]>=1 else 1


if __name__=="__main__":
    raise SystemExit(main())
