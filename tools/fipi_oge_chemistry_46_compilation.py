#!/usr/bin/env python3
"""Cross-index 46 FIPI chemistry QIDs in an accessible third-party compilation.

The site is NOT FIPI. These records are secondary copies and must never be
labeled verified_exact_fipi. Missing figures are explicitly marked.
"""
from __future__ import annotations

import argparse
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from fipi_oge_chemistry_46 import QIDS

ROOT = "https://gdzotvet.ru/oge-ege/himiya"
INDEX_RE = re.compile(r"Задание\s+(\d+)(?:\s*[-–]\s*(\d+))?\s+ОГЭ\s+по\s+химии", re.I)
QID_RE = re.compile(r"\bНомер\s*:\s*([A-F0-9]{6})\b", re.I)
INSTRUCTIONS = ("Выберите", "Впишите", "Установите", "Расположите", "Прочитайте",
                "Из предложенного", "Используя", "Запишите", "Вычислите", "Определите")


def parse_indexes(page: str) -> dict[int, list[str]]:
    soup = BeautifulSoup(page, "lxml")
    by_line: dict[int, list[str]] = {}
    for link in soup.select("a[href]"):
        label = " ".join(link.stripped_strings)
        found = INDEX_RE.search(label)
        if not found:
            continue
        number = int(found.group(1))
        other = int(found.group(2)) if found.group(2) else number
        url = urljoin(ROOT, link["href"])
        if "/oge-ege/himiya/" not in url:
            continue
        for n in range(number, other + 1):
            if n > 23:
                continue
            by_line.setdefault(n, [])
            if url not in by_line[n]:
                by_line[n].append(url)
    return by_line


def strip_extra(text: str) -> str:
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()
    if len(text) > 3500:
        text = text[-3500:]
    # remove top-of-page navigation before the first question
    starters = [re.search(r"(?:^|\n)" + re.escape(start), text) for start in INSTRUCTIONS]
    starters = [x for x in starters if x is not None]
    if starters and len(text) > 2400:
        text = text[min(x.start() for x in starters):]
    return text.strip()


def inspect_article(article_html: str) -> dict[str, dict]:
    soup = BeautifulSoup(article_html, "lxml")
    body = soup.select_one("article") or soup.select_one(".item-page") or soup.select_one("main") or soup.body or soup
    text = body.get_text("\n", strip=True)
    anchors = list(QID_RE.finditer(text))
    result = {}
    start = 0
    for match in anchors:
        qid = match.group(1).upper()
        prefix = text[start:match.start()]
        start = match.end()
        if qid in result:
            continue
        answer_match = list(re.finditer(r"(?:Ответ|Правильный ответ)\s*:", prefix, re.I))
        if answer_match:
            last = answer_match[-1]
            condition = strip_extra(prefix[:last.start()])
            after = prefix[last.end():].strip()
            answer = re.match(r"([^\n]{1,120})", after)
            answer_text = answer.group(1).strip() if answer else ""
        else:
            condition = strip_extra(prefix)
            answer_text = ""
        # Prevent the first site's navigation from being counted as condition.
        if len(condition) > 1800:
            cutoff = [condition.rfind(s) for s in INSTRUCTIONS if s in condition]
            if cutoff:
                condition = condition[max(cutoff) :]
        image_references = bool(re.search(r"рисунк|схем[аеыу]|диаграмм", condition, re.I))
        result[qid] = {
            "condition_text": condition,
            "answer_as_mirrored": answer_text,
            "has_visual_reference": image_references,
            "chars": len(condition),
        }
    return result


def collect(limit: int, pause: float, out: Path):
    out.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 (compatible; educational cross-index/1.0)",
                            "Accept-Language": "ru-RU,ru;q=.9"})
    main = session.get(ROOT, timeout=(6, 15))
    main.raise_for_status()
    pages = parse_indexes(main.text)
    print("INDEX", json.dumps({str(k): len(v) for k, v in sorted(pages.items())}), flush=True)

    articles: dict[str, dict[str, dict]] = {}
    failures: dict[str, str] = {}
    for line, urls in sorted(pages.items()):
        for url in urls:
            if url in articles or url in failures:
                continue
            try:
                r = session.get(url, timeout=(6, 15))
                r.raise_for_status()
                articles[url] = inspect_article(r.text)
                print(f"PAGE {line} {url} qids={len(articles[url])}", flush=True)
            except Exception as exc:
                failures[url] = f"{type(exc).__name__}: {exc}"
                print(f"PAGE FAIL {line} {url} {failures[url][:110]}", flush=True)
            time.sleep(pause)

    selected = [(line, qid.upper()) for line, *qids in QIDS for qid in qids][:limit]
    results = []
    for line, qid in selected:
        ln = int(line)
        urls = pages.get(ln, [])
        found = [(url, articles[url][qid]) for url in urls if qid in articles.get(url, {})]
        status = "secondary_copy_present" if found else "not_found_in_compilation"
        info = found[0][1] if found else {}
        if found and (info["chars"] < 35 or (info["has_visual_reference"] and not info.get("diagram_captured"))):
            status = "secondary_copy_requires_review"
        results.append({"line": line, "qid": qid, "status": status,
                        "source_provenance": "third_party_compilation_not_FIPI",
                        "fipi_verified": False,
                        "fipi_url": ("https://oge.fipi.ru/bank/index.php?"
                                     "proj=33B3A93C5A6599124B04FB95616C835B&qid=" + qid),
                        "mirror_url": found[0][0] if found else None,
                        **info})
        print(f"QID {line} {qid} {status} ({info.get('chars',0)} chars)", flush=True)

    summary = {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "requested": len(selected),
        "secondary_found": sum(r["status"].startswith("secondary_copy") for r in results),
        "text_only_candidates": sum(r["status"] == "secondary_copy_present" for r in results),
        "requires_review": sum(r["status"] == "secondary_copy_requires_review" for r in results),
        "not_found": sum(r["status"] == "not_found_in_compilation" for r in results),
        "fipi_directly_verified": 0,
        "index_lines": sorted(pages),
        "articles_loaded": len(articles),
        "article_errors": failures,
        "warning": "Secondary source. Matching QID does not prove the copy is identical to the current bank.",
    }
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "questions.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    with (out / "preview.md").open("w", encoding="utf-8") as f:
        f.write("# 46 selected OGE chemistry qids: secondary-source audit\n\n")
        f.write("No direct FIPI verification. Source: gdzotvet.ru.\n\n")
        for r in results:
            f.write(f"## Line {r['line']}, {r['qid']}: {r['status']}\n\n")
            f.write(f"Source: {r['mirror_url'] or 'not found'}\n\n")
            # Only small excerpts here; full parsed text is in the structured JSON.
            f.write(r.get("condition_text", "")[:260].replace("\n", " ") + "\n\n")
    print("SUMMARY", json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=46)
    ap.add_argument("--pause", type=float, default=.35)
    ap.add_argument("--out", default="artifacts/fipi-oge-chemistry-46-compilation")
    a = ap.parse_args()
    collect(a.limit, a.pause, Path(a.out))
