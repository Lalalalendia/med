#!/usr/bin/env python3
"""Build a personal-use reader of Katie B.'s SCIENCE cartoon collection.

The public repository holds only source metadata and this collector.
Artwork is downloaded into a local output directory / CI artifact, never
committed to this public repository. Keep author credit and source URLs.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import io
import json
import re
import sys
import time
import urllib.parse
import urllib.robotparser
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from PIL import Image

ROOT = "https://katiebcartoons.com"
COLLECTION = f"{ROOT}/science-pun-cartoons"
ALLOWED = {"katiebcartoons.com", "www.katiebcartoons.com", "s.katiebcartoons.com"}
CARTOON_PATH = re.compile(r"^/cartoon/([a-z0-9-]+)/?$")
EXPECTED_AS_OF_2026_11_19 = 28
LIMIT_BYTES = 12_000_000
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; PersonalKatieBScienceReader/1.0)",
    "Accept-Language": "en-US,en;q=0.8",
}


def canon(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED:
        raise ValueError(f"Disallowed URL: {url}")
    return url


def http_get(session: requests.Session, url: str, binary=False) -> bytes | str:
    canon(url)
    last = None
    for trial in range(3):
        try:
            result = session.get(url, timeout=(12, 35), allow_redirects=True)
            canon(result.url)
            result.raise_for_status()
            if len(result.content) > LIMIT_BYTES:
                raise ValueError("Content exceeds bounded size")
            return result.content if binary else result.text
        except (requests.RequestException, ValueError) as err:
            last = err
            if trial < 2:
                time.sleep(1 + 2 * trial)
    raise RuntimeError(f"Fetch failed: {url}: {last}")


def respect_robots(session: requests.Session) -> None:
    response = session.get(f"{ROOT}/robots.txt", timeout=(12, 20))
    if response.status_code == 404:
        return
    if response.status_code != 200:
        raise RuntimeError(f"Could not verify robots policy: {response.status_code}")
    robot = urllib.robotparser.RobotFileParser()
    robot.parse(response.text.splitlines())
    for check in (f"{COLLECTION}/1/", f"{ROOT}/cartoon/the-knights-of-the-periodic-table/"):
        if not robot.can_fetch(HEADERS["User-Agent"], check):
            raise RuntimeError("Access prohibited by robots policy: " + check)


def find_links(markup: str) -> list[dict]:
    doc = BeautifulSoup(markup, "html.parser")
    result = []
    seen = set()
    for a in doc.select("a[href]"):
        url = urllib.parse.urljoin(ROOT, a.get("href", ""))
        u = urllib.parse.urlparse(url)
        match = CARTOON_PATH.match(u.path)
        if not match or u.hostname not in ALLOWED:
            continue
        slug = match.group(1)
        if slug in seen:
            continue
        seen.add(slug)
        result.append({"slug": slug, "url": f"{ROOT}/cartoon/{slug}/"})
    return result


def best_image(markup: str, slug: str) -> str | None:
    doc = BeautifulSoup(markup, "html.parser")
    proposals = []
    for meta in doc.select('meta[property="og:image"],meta[name="twitter:image"]'):
        proposals.append(meta.get("content", ""))
    for img in doc.select("img"):
        proposals.extend([img.get("data-src", ""), img.get("src", "")])
        for part in (img.get("srcset", "") or "").split(","):
            proposals.append(part.strip().split(" ")[0])
    # Prefer the cartoon media in the canonical original and ignore UI/icons.
    for raw in proposals:
        url = urllib.parse.urljoin(ROOT, raw)
        u = urllib.parse.urlparse(url)
        if u.hostname in ALLOWED and ("/media/cartoons/" in u.path or f"{slug}" in u.path) and any(u.path.lower().endswith(ext) for ext in (".webp", ".png", ".jpg", ".jpeg")):
            return url
    return None


def detail_data(markup: str, slug: str) -> dict:
    doc = BeautifulSoup(markup, "html.parser")
    heading = doc.find("h1")
    label = heading.get_text(" ", strip=True) if heading else ""
    if not label:
        label = (doc.title.get_text(" ", strip=True) if doc.title else "").split(" - ")[0]
    label = re.sub(r"\s*(?:Pun )?Cartoon(?:\s+-.*)?$", "", label, flags=re.I)
    label = label if label and label.lower() not in {"katiebcartoons", "cartoons"} else slug.replace("-", " ").title()
    return {"title": label, "image_url": best_image(markup, slug)}


def safe_img(raw: bytes) -> str:
    with Image.open(io.BytesIO(raw)) as img:
        width, height = img.size
        image_format = img.format
        if width > 9000 or height > 9000 or width < 80 or height < 80:
            raise ValueError(f"Suspicious image dimensions: {img.size}")
        img.verify()
    ext = {"WEBP": ".webp", "PNG": ".png", "JPEG": ".jpg"}.get(image_format)
    if not ext:
        raise ValueError("Unexpected image format " + str(image_format))
    return ext


def card(c: dict) -> str:
    title = html.escape(c.get("title_ru") or c["title"])
    en = html.escape(c["title"])
    original = html.escape(c["url"], quote=True)
    src = html.escape(c.get("local_image") or c.get("image_url") or "", quote=True)
    visual = f'<a href="{original}" target="_blank" rel="noreferrer"><img loading="lazy" src="{src}" alt="{en}"></a>' if src else '<p>Original artwork: open source link.</p>'
    return f'<article><div class="picture">{visual}</div><h2>{title}</h2><p class="en">{en}</p><p><a href="{original}">Открыть у автора</a></p></article>'


def reader_html(comics: list[dict]) -> str:
    html_cards = "\n".join(card(c) for c in comics)
    return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Научные карикатуры Katie B. — личный каталог</title>
<style>
*{{box-sizing:border-box}}body{{margin:0;background:#f3f0e9;color:#252d34;font:16px/1.5 system-ui,sans-serif}}
main{{margin:auto;max-width:1120px;padding:20px}}h1{{font-size:clamp(25px,4vw,38px)}}
section{{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:14px}}
article{{background:white;border:1px solid #ddd7cc;border-radius:12px;padding:14px;min-width:0}}
.picture{{height:265px;display:grid;place-items:center;background:#faf9f6;border-radius:8px}}
img{{max-width:100%;max-height:252px;object-fit:contain}}h2{{font-size:18px;margin:12px 0 3px}}
p{{margin:5px 0}}.en,footer{{color:#66717a;font-size:13px}}
a{{color:#135784}}footer{{padding:20px 0}}
</style></head><body><main><h1>Научные карикатуры Katie B.</h1>
<p>Каталог оригиналов для личного чтения. Рисунки и все права на них принадлежат Katie Brookoff.
Источник: <a href="https://katiebcartoons.com/science-pun-cartoons/1/">Science Pun Cartoons</a>.</p>
<p>Здесь не воспроизводятся чужие переводы: подписи — краткие названия, а оригинальные страницы открываются у автора.</p>
<section>{html_cards}</section>
<footer>Source &amp; original art: © Katie B. Cartoons; collected for personal reading only. Not for redistribution.</footer>
</main></body></html>"""


def run(out: Path, local_images: bool = True, require_complete: bool = True) -> dict:
    session = requests.Session()
    session.headers.update(HEADERS)
    respect_robots(session)
    found = []
    seen = set()
    page_counts = []
    for page in (1, 2, 3):
        url = f"{COLLECTION}/{page}/"
        markup = http_get(session, url)
        items = find_links(markup)
        page_counts.append(len(items))
        for entry in items:
            if entry["slug"] not in seen:
                found.append({**entry, "collection_page": page})
                seen.add(entry["slug"])
        print(f"catalog page {page}: {len(items)} links, cumulative {len(found)}", flush=True)
        time.sleep(.2)
    if require_complete and len(found) != EXPECTED_AS_OF_2026_11_19:
        raise RuntimeError(f"Incomplete/changed source collection: expected 28, found {len(found)}, per-page={page_counts}")

    output = []
    original_dir = out / "originals"
    if local_images:
        original_dir.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)
    errors = []
    for idx, entry in enumerate(found, 1):
        slug = entry["slug"]
        item = dict(entry)
        try:
            markup = http_get(session, item["url"])
            item.update(detail_data(markup, slug))
            if not item["image_url"]:
                raise RuntimeError("No source artwork URL in cartoon detail page")
            if local_images:
                raw = http_get(session, item["image_url"], binary=True)
                ext = safe_img(raw)
                target = original_dir / f"{idx:02d}-{slug}{ext}"
                target.write_bytes(raw)
                item["local_image"] = f"originals/{target.name}"
                item["bytes"] = len(raw)
                item["sha256"] = hashlib.sha256(raw).hexdigest()
        except Exception as exc:
            errors.append({"slug": slug, "error": str(exc)})
            item.setdefault("title", slug.replace("-", " ").title())
            print("WARN", slug, str(exc)[:220], flush=True)
        output.append(item)
        time.sleep(.25)
    manifest = {
        "source": "Katie B. Cartoons", "author": "Katie Brookoff",
        "collection_url": f"{COLLECTION}/1/",
        "observed_utc": datetime.now(timezone.utc).isoformat(),
        "expected_count": EXPECTED_AS_OF_2026_11_19,
        "indexed_count": len(output), "downloaded_count": sum("local_image" in x for x in output),
        "complete": len(output) == EXPECTED_AS_OF_2026_11_19 and not errors,
        "copyright": "Copyright Katie Brookoff; for personal use only, do not distribute",
        "errors": errors,
        "comics": output
    }
    (out / "catalog.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (out / "index.html").write_text(reader_html(output),encoding="utf-8")
    (out / "README_RU.txt").write_text(
        "Кэти Брукофф — Science Pun Cartoons\n\n"
        "Откройте index.html для просмотра рисунков. Авторские страницы доступны по ссылкам.\n"
        "Карикатуры © Katie Brookoff; личное некоммерческое чтение, без публикации.\n"
        f"Подборка: {COLLECTION}/1/\n",encoding="utf-8")
    print(json.dumps({"indexed":len(output),"downloaded":manifest["downloaded_count"],"errors":len(errors)},ensure_ascii=False),flush=True)
    if require_complete and not manifest["complete"]:
        raise RuntimeError(f"Source collection was indexed but not completely downloaded; {len(errors)} errors")
    return manifest


def selftest() -> None:
    fake = """<html><a href="/cartoon/test-iron/">visit cartoon</a>
    <a href="/cartoon/test-iron/"><img alt="Iron" src="/icons/a.png"></a>
    <a href="https://katiebcartoons.com/cartoon/test-neon/">visit cartoon</a>
    <a href="/about/">About</a></html>"""
    links = find_links(fake)
    assert [c["slug"] for c in links] == ["test-iron", "test-neon"]
    markup = """<html><h1>Test Iron Pun Cartoon</h1>
    <meta property="og:image" content="https://s.katiebcartoons.com/media/cartoons/test-iron-cartoon-pun.webp"></html>"""
    assert detail_data(markup, "test-iron")["image_url"].endswith("test-iron-cartoon-pun.webp")
    assert len(reader_html([{"slug":"test-iron","url":f"{ROOT}/cartoon/test-iron/","title":"Test Iron"}])) > 100
    print("PASS: links, dedup, source image parsing, and portable reader",flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out",type=Path,default=Path("out/katieb-science"))
    parser.add_argument("--selftest",action="store_true")
    parser.add_argument("--links-only",action="store_true")
    parser.add_argument("--allow-partial",action="store_true")
    args=parser.parse_args()
    if args.selftest:
        selftest()
    else:
        run(args.out,local_images=not args.links_only,require_complete=not args.allow_partial)


if __name__ == "__main__":
    main()
