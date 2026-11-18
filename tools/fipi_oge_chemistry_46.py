#!/usr/bin/env python3
"""Snapshot 46 selected OGE chemistry questions from the public FIPI bank.

This script is intentionally limited to the 46 qids already selected in Notion.
It never invents question text and never marks a different qid as verified.
"""
from __future__ import annotations

import argparse
import datetime as dt
import html as html_module
import json
import re
import time
import urllib.parse
from pathlib import Path

import requests
import urllib3
from bs4 import BeautifulSoup

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

PROJECT = "33B3A93C5A6599124B04FB95616C835B"
BASE = "https://oge.fipi.ru/bank/"
QIDS = [
    ("01", "152E46", "DBC949"),
    ("02", "21B54C", "523A4F"),
    ("03", "0D9141", "AEDB4A"),
    ("04", "D95A4E", "FB57F9"),
    ("05", "449648", "FCDD47"),
    ("06", "AE3442", "049702"),
    ("07", "329E35", "F6A189"),
    ("08", "E32431", "1E1984"),
    ("09", "0690C0", "211765"),
    ("10", "57FD85", "01AFC7"),
    ("11", "71F942", "8D864E"),
    ("12", "A1764F", "698840"),
    ("13", "5B0A4B", "96B74E"),
    ("14", "4A9C4A", "06B548"),
    ("15", "08724F", "7FD043"),
    ("16", "5C6B4F", "5B2342"),
    ("17", "28D53B", "65C13C"),
    ("18", "94984A", "ADA542"),
    ("19", "352B0F", "F0EFDE"),
    ("20", "F3DB40", "04114B"),
    ("21", "5F5D46", "E0E0F7"),
    ("22", "C74978", "CA9BD5"),
    ("23", "158E0F", "7D0312"),
]
AGENT = "Mozilla/5.0 (compatible; OGE-chemistry-research/1.0; educational audit)"


def decode_response(resp: requests.Response) -> str:
    raw = resp.content
    if b"<html" in raw[:300].lower() and b"charset=utf-8" in raw[:1000].lower():
        return raw.decode("utf-8", errors="replace")
    return raw.decode("cp1251", errors="replace")


def blocks(document: str):
    soup = BeautifulSoup(document, "lxml")
    found = []
    for block in soup.select("div.qblock[id]"):
        ident = str(block.get("id", ""))
        if not re.fullmatch(r"q[0-9a-fA-F]{6}", ident):
            continue
        qid = ident[1:].upper()
        cond = block.select_one("td.cell_0")
        if cond is None:
            continue
        full_html = cond.decode_contents()
        visible = " ".join(cond.stripped_strings)
        visible = re.sub(r"\s+", " ", visible).strip()
        guided = block.find("input", attrs={"name": "guid"})
        imgs = [urllib.parse.urljoin(BASE, str(n.get("src"))) for n in cond.select("img[src]")]
        found.append({"qid": qid, "guid": guided.get("value", "") if guided else "",
                      "condition_text": html_module.unescape(visible),
                      "condition_html": full_html, "images": imgs})
    return found


def request_once(session: requests.Session, qid: str):
    payload = {"proj": PROJECT, "page": "0", "pagesize": "10",
               "crtm": str(int(time.time())), "qid": qid,
               "search": "1"}
    r = session.post(BASE + "questions.php", data=payload, timeout=32)
    r.raise_for_status()
    doc = decode_response(r)
    seen = blocks(doc)
    exact = next((item for item in seen if item["qid"] == qid), None)
    if exact and exact["condition_text"]:
        return exact, "fipi_POST_filter", "", len(doc)
    # The qid filter is not guaranteed to work in all versions of the bank.
    r = session.get(BASE + "questions.php",
                    params={"proj": PROJECT, "qid": qid, "page": "0", "pagesize": "10"},
                    timeout=32)
    r.raise_for_status()
    doc2 = decode_response(r)
    more = blocks(doc2)
    exact = next((item for item in more if item["qid"] == qid), None)
    if exact and exact["condition_text"]:
        return exact, "fipi_GET_qid", "", len(doc2)
    sample = [e["qid"] for e in seen[:3]]
    return None, "", f"qid not found in response; POST sample ids={sample}; GET sample={[e['qid'] for e in more[:3]]}", len(doc2)


def collect(outdir: Path, sleep_seconds: float, limit: int):
    outdir.mkdir(parents=True, exist_ok=True)
    s = requests.Session()
    s.verify = False  # FIPI's certificate chain is not always accepted by requests.
    s.headers.update({"User-Agent": AGENT, "Accept-Language": "ru-RU,ru;q=0.9",
                      "Accept": "text/html,application/xhtml+xml,*/*;q=0.5"})
    setup_errors = []
    for path, params in [("index.php", None), ("index.php", {"proj": PROJECT}),
                         ("questions.php", {"proj": PROJECT, "page": "0", "pagesize": "5"})]:
        try:
            r = s.get(BASE + path, params=params, timeout=32)
            r.raise_for_status()
        except Exception as exc:
            setup_errors.append(f"warmup {path}: {type(exc).__name__}: {exc}")

    records = []
    for line, *qids in QIDS:
        for qid in qids:
            if len(records) >= limit:
                break
            detail = None
            source = ""
            error = ""
            length = 0
            for attempt in range(2):
                try:
                    detail, source, error, length = request_once(s, qid)
                    if detail:
                        break
                except Exception as exc:
                    error = f"{type(exc).__name__}: {exc}"
                if attempt == 0:
                    time.sleep(2.0)
            record = {"line": line, "qid": qid,
                      "fipi_url": f"{BASE}index.php?proj={PROJECT}&qid={qid}",
                      "status": "verified_exact_qid" if detail else "unverified",
                      "source": source or None, "error": error or None,
                      "response_chars": length,
                      "collected_utc": dt.datetime.now(dt.timezone.utc).isoformat()}
            if detail:
                record.update(detail)
            records.append(record)
            print(f"{line}/{qid}: {record['status']} ({len(record.get('condition_text',''))} chars) {error[:110]}", flush=True)
            time.sleep(sleep_seconds)
        if len(records) >= limit:
            break

    (outdir / "questions.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    good = [r for r in records if r["status"] == "verified_exact_qid"]
    missing = [r for r in records if r["status"] != "verified_exact_qid"]
    summary = {
        "scope": "46 selected OGE chemistry questions",
        "project": PROJECT,
        "processed": len(records),
        "verified_exact_qid": len(good),
        "unverified": len(missing),
        "source": "https://oge.fipi.ru/bank/",
        "warmup_errors": setup_errors,
        "failed_qids": [{"line": r["line"], "qid": r["qid"], "error": r["error"]} for r in missing],
    }
    (outdir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    with (outdir / "preview.md").open("w", encoding="utf-8") as f:
        f.write("# OGE chemistry: 46 tasks, qid verification\n\n")
        f.write(f"Verified: **{len(good)} / {len(records)}**. Source: FIPI bank (direct requests).\n\n")
        for r in records:
            f.write(f"## Line {r['line']} | {r['qid']} | {r['status']}\n\n")
            if r.get("condition_text"):
                f.write(r["condition_text"][:350].replace("|", "\\|") + "\n\n")
            else:
                f.write("Error: " + str(r.get("error")) + "\n\n")
    print("SUMMARY", json.dumps(summary, ensure_ascii=False), flush=True)
    return 0 if len(records) > 0 else 2


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="artifacts/fipi-oge-chemistry-46")
    ap.add_argument("--sleep", type=float, default=0.7)
    ap.add_argument("--limit", type=int, default=46)
    a = ap.parse_args()
    raise SystemExit(collect(Path(a.out), a.sleep, a.limit))
