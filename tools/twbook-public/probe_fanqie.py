#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

BOOK_URL = "https://fanqienovel.com/page/7353917626914982974"
TARGETS = {232, 233, 234, 235, 356, 357}
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36"
FONTMAP_PATH = Path(__file__).with_name("fanqie_content_fontmap.json")
FONTMAP = {int(k, 16): v for k, v in json.loads(FONTMAP_PATH.read_text("utf-8")).items()}


def is_pua(ch: str) -> bool:
    return "\ue000" <= ch <= "\uf8ff"


def decode_pua(text: str) -> str:
    return "".join(FONTMAP.get(ord(ch), ch) for ch in text)


def extract_initial_state(html: str) -> dict | None:
    m = re.search(r"window\.__INITIAL_STATE__\s*=\s*(\{.*?\})\s*;</script>", html, re.DOTALL)
    if not m:
        m = re.search(r"window\.__INITIAL_STATE__\s*=\s*(\{.*?\})\s*;", html, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except Exception as exc:
        print("STATE_JSON_ERROR", repr(exc), "len", len(m.group(1)))
        return None


def extract_reader_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    candidates = []
    for selector in (
        "div.muye-reader-content",
        "div.reader-content",
        "[class*=reader-content]",
        "[class*=muye-reader-content]",
        "article",
    ):
        for node in soup.select(selector):
            text = "\n".join(node.stripped_strings)
            if len(text) >= 100:
                candidates.append((len(text), text))
    if not candidates:
        for node in soup.select("[class*=reader], [class*=content]"):
            text = "\n".join(node.stripped_strings)
            if len(text) >= 100:
                candidates.append((len(text), text))
    if not candidates:
        return ""
    # Prefer the largest content-ish node and strip title/metadata prefix later.
    return max(candidates)[1]


def main() -> int:
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.5"})
    r = s.get(BOOK_URL, timeout=30)
    print("directory", r.status_code, r.url, len(r.text))
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    found = {}
    for a in soup.select("a[href]"):
        label = " ".join(a.stripped_strings)
        m = re.search(r"第\s*(\d+)\s*章", label)
        if not m:
            continue
        n = int(m.group(1))
        if n in TARGETS:
            found[n] = (label, urljoin(r.url, a.get("href")))

    for n in sorted(TARGETS):
        print("TARGET", n, found.get(n))
    if set(found) != TARGETS:
        print("missing target links", sorted(TARGETS - set(found)))
        return 2

    for n in sorted(found):
        label, url = found[n]
        rr = s.get(url, timeout=30)
        text = extract_reader_text(rr.text)
        state = extract_initial_state(rr.text)
        cd = ((state or {}).get("reader") or {}).get("chapterData") or {}
        raw_content = cd.get("content") or ""
        decoded = decode_pua(raw_content)
        unknown_pua = {ch for ch in decoded if is_pua(ch)}
        print(
            "FETCH", n, rr.status_code, rr.url, len(rr.text),
            "TEXT", len(text),
            "PUA", sum(is_pua(ch) for ch in text),
            "PUA_UNIQUE", len({ch for ch in text if is_pua(ch)}),
            "STATE_CONTENT", len(raw_content),
            "STATE_DECODED", len(decoded),
            "STATE_UNKNOWN_PUA", len(unknown_pua),
            "STATE_TITLE", cd.get("title"),
        )

    # Determine whether Fanqie's PUA obfuscation changes per public rendering.
    n = 232
    url = found[n][1]
    variants = []
    for i in range(6):
        rr = s.get(url, timeout=30)
        text = extract_reader_text(rr.text)
        variants.append(text)
        print(
            "VARIANT", i,
            "len", len(text),
            "pua", sum(is_pua(ch) for ch in text),
            "sha", hashlib.sha256(text.encode()).hexdigest()[:16],
        )

    same_len = len({len(x) for x in variants}) == 1
    print("VARIANTS_SAME_LEN", same_len)
    if same_len and variants:
        diff_positions = 0
        exposed_positions = 0
        all_pua_positions = 0
        pua_switch_positions = 0
        for chars in zip(*variants):
            if len(set(chars)) > 1:
                diff_positions += 1
            if any(is_pua(ch) for ch in chars):
                if any(not is_pua(ch) for ch in chars):
                    exposed_positions += 1
                else:
                    all_pua_positions += 1
                    if len(set(chars)) > 1:
                        pua_switch_positions += 1
        print(
            "DIFF_POSITIONS", diff_positions,
            "PUA_EXPOSED", exposed_positions,
            "ALL_PUA", all_pua_positions,
            "PUA_SWITCH", pua_switch_positions,
        )

    # Print font URLs / embedded font references, not font bytes.
    rr = s.get(url, timeout=30)
    font_urls = sorted(set(re.findall(r'https?://[^"\'\s)]+\.(?:woff2?|ttf|otf)(?:\?[^"\'\s)]*)?', rr.text)))
    css_urls = sorted(set(re.findall(r'https?://[^"\'\s)]+\.css(?:\?[^"\'\s)]*)?', rr.text)))
    print("FONT_URLS", font_urls[:20])
    print("CSS_URLS", css_urls[:20])
    for marker in ("font-face", "woff", "ttf", "fontFamily", "font-family"):
        print("HTML_HAS", marker, marker in rr.text)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
