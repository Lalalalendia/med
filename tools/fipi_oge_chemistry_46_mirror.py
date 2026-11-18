#!/usr/bin/env python3
"""Research mirror audit for selected OGE chemistry qids.

The output is unverified THIRD-PARTY material. It is NEVER marked FIPI-verified.
Only visit preselected qids in the existing FIPI collector.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from fipi_oge_chemistry_46 import QIDS

DOMAIN = "https://reshai.online/oge/subjects/chemistry/tasks/"
UA = "Mozilla/5.0 (compatible; research-extract/1.0; education)"


def extract_condition(soup: BeautifulSoup) -> str:
    body = soup.select_one("main") or soup.body or soup
    text = body.get_text("\n", strip=True)
    # Extract visible task statement around its explicit section boundary.
    m = re.search(r"Исходное условие\s*[—–-]\s*открыть и сверить", text, re.I)
    if m:
        rest = text[m.end():]
        cut = re.search(r"\n(?:Ваш ответ|Подсказки|Показать ответ|Правильный ответ|Калькулятор)\b", rest, re.I)
        snippet = rest[:cut.start()] if cut else rest[:3000]
    else:
        m = re.search(r"\n(?:Условие|Задание)\s*\n", text, re.I)
        snippet = text[m.end():m.end()+3000] if m else text[:1800]
    snippet = re.sub(r"\n{3,}", "\n\n", snippet).strip()
    return snippet[:5000]


def collect(out: Path, limit: int, pause: float, timeout: int):
    out.mkdir(parents=True, exist_ok=True)
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "ru-RU,ru;q=0.9"})
    rows = []
    for line, *qids in QIDS:
        for code in qids:
            if len(rows) >= limit:
                break
            url = DOMAIN + code
            row = {"line": line, "qid": code, "mirror_url": url,
                   "source_status": "NOT_FIPI_VERIFIED", "status": "unavailable",
                   "checked_at_utc": dt.datetime.now(dt.timezone.utc).isoformat()}
            try:
                response = s.get(url, timeout=timeout)
                row["http_status"] = response.status_code
                response.raise_for_status()
                soup = BeautifulSoup(response.content, "lxml")
                title = soup.title.get_text(" ", strip=True) if soup.title else ""
                h1 = soup.h1.get_text(" ", strip=True) if soup.h1 else ""
                full = soup.get_text(" ", strip=True)
                row["page_title"] = title
                row["h1"] = h1
                row["qid_visible"] = bool(re.search(r"\b" + re.escape(code) + r"\b", full, re.I))
                row["condition_excerpt"] = extract_condition(soup)
                row["status"] = ("mirror_qid_visible" if row["qid_visible"] and
                                 len(row["condition_excerpt"]) >= 35 else "unverified_page")
            except requests.RequestException as exc:
                row["error"] = f"{type(exc).__name__}: {exc}"
            rows.append(row)
            print(f"{line} {code} {row['status']} {row.get('http_status','-')} "
                  f"excerpt={len(row.get('condition_excerpt',''))}", flush=True)
            time.sleep(pause)
        if len(rows) >= limit:
            break
    good = sum(r["status"] == "mirror_qid_visible" for r in rows)
    (out / "mirror_questions.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {"processed": len(rows), "mirror_qid_visible": good,
               "fipi_verified": 0, "source": DOMAIN,
               "warning": "THIRD-PARTY MIRROR, not direct FIPI verification"}
    (out / "mirror_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    with (out / "mirror_preview.md").open("w", encoding="utf-8") as f:
        f.write("# Selected chemistry qids: third-party mirror audit\n\n")
        f.write(f"Matching code visible in mirror: {good}/{len(rows)}. FIPI-verified: 0.\n\n")
        for r in rows:
            f.write(f"## {r['line']} {r['qid']} — {r['status']}\n\n")
            f.write("Source: " + r["mirror_url"] + "\n\n")
            f.write(r.get("condition_excerpt", "")[:700] + "\n\n")
    print("SUMMARY", json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="artifacts/fipi-oge-chemistry-46-mirror")
    ap.add_argument("--limit", type=int, default=46)
    ap.add_argument("--pause", type=float, default=0.25)
    ap.add_argument("--timeout", type=int, default=12)
    a = ap.parse_args()
    collect(Path(a.out), a.limit, a.pause, a.timeout)
