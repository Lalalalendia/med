#!/usr/bin/env python3
"""Mechanical Chinese->Russian first-pass translation of chapters 607-756.

The output is a DRAFT requiring literary review. Uses an unauthenticated
Google Translate web endpoint, with integrity checks and no invented chapters.
The original Chinese source and prior Russian 1-606 are not modified.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import random
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
BOOK = HERE.parent
SOURCE = BOOK / "source/meiman-zh-607-756.txt"
GLOSSARY = BOOK / "localization/westernization-ru.json"
OUTPUT = BOOK / "ru/continuation-607-756"
NAME_PAIRS = [
    ("林家老祖", "ancestor of the Frost family"),
    ("林家", "Frost family"),
    ("黑影洛基", "Shadow Loki"),
    ("聂小倩", "Evelyn Moore"),
    ("玛丽肖", "Mary Shaw"),
    ("左千户", "Roland Stone"),
    ("燕赤霞", "Edward Rain"),
    ("宁采臣", "Nathan Kane"),
    ("张美玉", "Madison Rose"),
    ("张家", "Rose family"),
    ("叶天", "Ethan York"),
    ("苏林", "Silas Lane"),
    ("菜菜", "Molly"),
    ("林峰", "Leon Frost"),
    ("林天龙", "Lawrence Frost"),
    ("林海", "Henry Frost"),
    ("将臣", "Julian Kane"),
    ("马小玲", "Mei Martin"),
    ("马丹娜", "Martha Martin"),
    ("楚人美", "Chu Renmei"),
    ("贞子", "Sadako"),
    ("佛莱迪", "Freddy"),
    ("洛基", "Loki"),
    ("克拉克", "Clark"),
    ("灭霸", "Thanos"),
    ("托尔", "Thor"),
    ("万磁王", "Magneto"),
    ("绿巨人", "Hulk"),
    ("浩克", "Hulk"),
    ("美国队长", "Captain America"),
    ("奇异博士", "Doctor Strange"),
    ("通天塔", "Sky Tower"),
    ("天元大世界", "Aetheria"),
    ("倩女幽魂", "A Chinese Ghost Story"),
    ("兰若寺", "Ravenwood Temple"),
    ("兰水城", "Azure Waters"),
    ("玄心神诀", "Divine Art of the Mystic Heart"),
    ("军神诀", "Art of the War God"),
    ("阴曹地府", "Underworld"),
    ("天庭", "Heavenly Court"),
]
NAME_PAIRS.sort(key=lambda x: -len(x[0]))
ENDPOINTS = [
    "https://clients5.google.com/translate_a/t",
    "https://translate.googleapis.com/translate_a/t",
]
HEAD = re.compile(r"(?m)^(\d{3})章[ \u3000]*([^\n]*)$")
HAN = re.compile(r"[\u3400-\u9fff]")
CYR = re.compile(r"[А-Яа-яЁё]")
LOCK = threading.Lock()


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def chapters():
    txt = SOURCE.read_text(encoding="utf-8").replace("\r\n", "\n")
    heads = list(HEAD.finditer(txt))
    result = {}
    for i, match in enumerate(heads):
        n = int(match.group(1))
        if not 607 <= n <= 756:
            raise RuntimeError(f"Unexpected source heading {n}")
        if n in result:
            raise RuntimeError(f"Repeated source heading {n}")
        title = match.group(2).strip()
        body = txt[match.end():heads[i + 1].start() if i + 1 < len(heads) else len(txt)]
        result[n] = (title, body.strip())
    if sorted(result) != list(range(607, 757)):
        raise RuntimeError("Source has missing or duplicate chapters")
    return result


def process_zh(txt: str) -> str:
    txt = re.sub(r"(?m)^[\u3000 \t]+", "", txt)
    txt = re.sub(r"(?m)^\s*(?:飞.?鹿.?|\\.\\.\\.\\s*\\.\\.\\.\\.\\.\\.\\s*0)\\s*$", "", txt)
    # Suppress obvious standalone ad page counters; do not delete narrative numbers.
    txt = re.sub(r"(?m)^\s*(?:790|807|930|4[.]2)\s*$", "", txt)
    for chinese, english in NAME_PAIRS:
        txt = txt.replace(chinese, english)
    return txt.strip()


def chunks(txt: str, length: int = 560) -> list[str]:
    lines = [line.strip() for line in txt.splitlines()]
    chunks, buf = [], ""
    for line in lines:
        if not line:
            continue
        if buf and len(buf) + len(line) > length:
            chunks.append(buf)
            buf = ""
        # Chinese original is sentence-per-line; join fragments into actual prose.
        if line.startswith(("“", "”")) and len(buf) > 180:
            chunks.append(buf)
            buf = ""
        buf += ("\n" if buf else "") + line
    if buf:
        chunks.append(buf)
    return chunks


def parse_response(raw: bytes) -> str:
    parsed = json.loads(raw.decode("utf-8"))
    if isinstance(parsed, list) and parsed and isinstance(parsed[0], str):
        return parsed[0].strip()
    if isinstance(parsed, list) and parsed and isinstance(parsed[0], list):
        return "".join(str(p[0]) for p in parsed[0] if isinstance(p, list) and p and p[0]).strip()
    raise ValueError(f"Unexpected translation payload: {str(parsed)[:200]}")


def translate_api(txt: str) -> str:
    params = urllib.parse.urlencode({
        "client": "dict-chrome-ex", "sl": "zh-CN", "tl": "ru", "q": txt
    })
    errors = []
    for attempt in range(7):
        for endpoint in ENDPOINTS:
            try:
                req = urllib.request.Request(endpoint + "?" + params,
                                             headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=28) as response:
                    output = parse_response(response.read())
                if not output or len(CYR.findall(output)) < max(2, min(15, int(len(txt) * 0.20))):
                    raise ValueError("Translation returned no meaningful Cyrillic")
                if len(HAN.findall(output)) > 2:
                    raise ValueError("Untranslated Chinese remains")
                return output
            except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
                errors.append(f"{endpoint.rsplit('/',1)[0]}:{str(exc)[:90]}")
        time.sleep(min(17, (1.6 ** attempt) + random.random()))
    raise RuntimeError("All translation endpoints failed: " + " | ".join(errors[-5:]))


def westernize_ru(txt: str) -> str:
    data = json.loads(GLOSSARY.read_text(encoding="utf-8"))
    pairs = list(data["names"]) + list(data["terms"])
    substitutions = dict(pairs)
    # Variants seen in machine translation, retained to match the 1-606 names.
    substitutions.update({
        "Су Лин": "Сайлас Лейн",
        "Су Лина": "Сайласа Лейна",
        "Су Лину": "Сайласу Лейну",
        "Су Лином": "Сайласом Лейном",
        "Су Лине": "Сайласе Лейне",
        "Силос Лейн": "Сайлас Лейн",
        "Мэри Шо": "Мэри Шоу",
        "Теневой Локки": "Теневой Локи",
        "Башня Тяньтун": "Небесная башня",
        "Небесная башня": "Небесная башня",
        "Скай Тауэр": "Небесная башня",
    })
    ordered = sorted((k for k, v in substitutions.items() if k != v), key=lambda x: (-len(x), x))
    pattern = re.compile(r"(?<![^\W\d_])(?:" + "|".join(re.escape(x) for x in ordered) + r")(?![^\W\d_])")
    return pattern.sub(lambda m: substitutions[m.group(0)], txt)


def run_one(n: int, title: str, body: str):
    prepared = process_zh(body)
    portions = chunks(prepared)
    translated_title = translate_api(process_zh(title))
    text = []
    for chunk in portions:
        translated = translate_api(chunk)
        text.append(translated.replace("\r", "").strip())
        time.sleep(0.07)
    # No empty or obviously clipped outputs.
    merged = westernize_ru("\n\n".join(text))
    ru_title = westernize_ru(translated_title).strip().replace("\n", " ")
    output = f"Глава {n}. {ru_title}\n\n{merged.strip()}\n"
    if HAN.search(output) or output.count("Глава ") == 0:
        raise RuntimeError(f"Translation integrity failed for chapter {n}")
    cyr_count = len(CYR.findall(output))
    if cyr_count < max(260, len(HAN.findall(body)) * 0.4):
        raise RuntimeError(f"Translation appears incomplete: chapter {n}, {cyr_count} Cyrillic chars")
    return n, output, {"zh_chars": len(body), "ru_chars": len(output), "segments": len(portions)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=int, default=607)
    ap.add_argument("--end", type=int, default=756)
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    if not 607 <= args.start <= args.end <= 756:
        raise ValueError("Invalid range")
    source = chapters()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    stats = {}
    combined = {}
    failures = []
    nums = range(args.start, args.end + 1)
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        pending = {pool.submit(run_one, n, *source[n]): n for n in nums}
        for task in concurrent.futures.as_completed(pending):
            n = pending[task]
            try:
                _, text, meta = task.result()
                (OUTPUT / f"ru-{n:03d}.txt").write_text(text, encoding="utf-8")
                combined[n] = text
                stats[n] = meta
                with LOCK:
                    print(f"CHAPTER_OK {n} zh={meta['zh_chars']} ru={meta['ru_chars']} segments={meta['segments']}", flush=True)
            except Exception as exc:
                failures.append({"chapter": n, "error": str(exc)})
                with LOCK:
                    print(f"CHAPTER_FAIL {n}: {str(exc)[:220]}", flush=True)
    report = {"requested": [args.start, args.end], "completed": len(combined),
              "missing": [i for i in nums if i not in combined],
              "failures": failures, "method": "machine first-pass translation; requires human literary editing",
              "stats": stats}
    if combined:
        assembled = "\n\n\n".join(combined[n].rstrip() for n in sorted(combined)) + "\n"
        name = f"combined-ru-{args.start:03d}-{args.end:03d}-WESTERNIZED-DRAFT.txt"
        (OUTPUT / name).write_text(assembled, encoding="utf-8")
        report["combined_sha256"] = sha(assembled.encode("utf-8"))
        report["bytes"] = len(assembled.encode("utf-8"))
        if not failures:
            namezip = f"reader-ru-{args.start:03d}-{args.end:03d}-DRAFT.zip"
            with zipfile.ZipFile(OUTPUT / namezip, "w", zipfile.ZIP_DEFLATED) as z:
                for n in nums:
                    z.write(OUTPUT / f"ru-{n:03d}.txt", f"ru-{n:03d}.txt")
            with zipfile.ZipFile(OUTPUT / namezip) as z:
                assert z.testzip() is None
    (OUTPUT / f"audit-{args.start:03d}-{args.end:03d}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print("FINAL_REPORT " + json.dumps({k:v for k,v in report.items() if k!="stats"},ensure_ascii=False),flush=True)
    if failures:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
