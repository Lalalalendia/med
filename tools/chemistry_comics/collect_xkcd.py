#!/usr/bin/env python3
"""Fetch licensed xkcd chemistry strips and build a Russian private reader.

Original artwork is never modified. Russian translations appear alongside
the images, with source links and license attribution.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import html
import json
import re
import tempfile
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

MAX_IMAGE_BYTES = 12 * 1024 * 1024
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
CSS = """
:root {color-scheme:light;--ink:#1f2630;--muted:#6b7280;--paper:#f4f3ef;--card:#fff;--edge:#d9dde4}
*{box-sizing:border-box} body{margin:0;background:var(--paper);color:var(--ink);font:17px/1.58 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1040px;margin:0 auto;padding:24px 18px 76px} header{padding:20px 0 12px}
h1{font-size:clamp(27px,4.5vw,40px);line-height:1.15;margin:0 0 13px}h2{font-size:21px;margin:4px 0 13px}
a{color:#15528c}a:hover{text-decoration:none}.muted{color:var(--muted)}.top{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap}
.comic{background:var(--card);padding:24px;border:1px solid var(--edge);border-radius:16px;overflow:auto;text-align:center}
.comic img{height:auto;max-width:100%;object-fit:contain}
.layout{display:grid;grid-template-columns:minmax(0,1.15fr) minmax(310px,.85fr);gap:22px;align-items:start}
.translation{background:#fff;border:1px solid var(--edge);padding:21px;border-radius:16px}
.panel{padding:12px 0;border-bottom:1px solid #e5e7eb}.panel:last-of-type{border-bottom:none}
.panel h3{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.12em;margin:0 0 7px}
.panel p{margin:0 0 9px}.panel p:last-child{margin-bottom:0}
footer{font-size:13px;color:var(--muted);padding-top:22px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:16px}
.card{background:#fff;border:1px solid var(--edge);border-radius:14px;overflow:hidden;display:block;text-decoration:none;color:inherit}
.card .preview{height:205px;padding:12px;display:grid;place-items:center;background:#fbfbfb}
.card img{max-height:185px;max-width:100%;object-fit:contain}.card .meta{padding:14px}
.card h2{font-size:18px;margin:0}.card p{font-size:14px;color:var(--muted);margin:5px 0 0}
details{margin-top:18px;border-top:1px solid var(--edge);padding-top:10px}summary{cursor:pointer}
@media(max-width:730px){.layout{grid-template-columns:1fr}.comic,.translation{padding:14px}.comic{order:0}.translation{order:1}}
"""

def q(value: str) -> str:
    return html.escape(str(value), quote=True)


def load_catalog(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data["comics"]
    if not isinstance(items, list) or not items:
        raise ValueError("Catalog must contain comics")
    ids: set[int] = set()
    for c in items:
        number = c["id"]
        if not isinstance(number, int) or number in ids:
            raise ValueError(f"Duplicate/invalid comic id: {number}")
        ids.add(number)
        if not re.fullmatch(r"[a-z0-9-]+", c["slug"]):
            raise ValueError("Invalid slug")
        if c["source_url"] != f"https://xkcd.com/{number}/":
            raise ValueError("Source URL mismatch")
        url = urllib.parse.urlsplit(c["image_url"])
        if (url.scheme, url.netloc) != ("https", "imgs.xkcd.com") or not url.path.startswith("/comics/") or not url.path.endswith(".png"):
            raise ValueError("Unapproved image source")
        if not c.get("panels") or any(not p.get("lines_ru") for p in c["panels"]):
            raise ValueError("Russian translation is incomplete")
    return items


def get_image(url: str) -> bytes:
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "MED-chemistry-personal-reader/1.0", "Accept": "image/png"})
            with urllib.request.urlopen(req, timeout=25) as reply:
                if urllib.parse.urlsplit(reply.url).hostname != "imgs.xkcd.com":
                    raise ValueError("Unexpected image redirect")
                content = reply.read(MAX_IMAGE_BYTES + 1)
            if len(content) > MAX_IMAGE_BYTES or not content.startswith(PNG_MAGIC):
                raise ValueError(f"Invalid PNG content: {url}")
            return content
        except (OSError, TimeoutError) as error:
            if attempt == 2:
                raise RuntimeError(f"Failed to download {url}") from error
            time.sleep(1 + attempt)
    raise AssertionError("unreachable")


def panel_markup(panel: dict, index: int) -> str:
    lines = "".join(f"<p>{q(line)}</p>" for line in panel["lines_ru"])
    return f'<section class="panel"><h3>{q(panel.get("label_ru") or "Кадр " + str(index))}</h3>{lines}</section>'


def page_markup(c: dict, image_name: str) -> str:
    panel_html = "".join(panel_markup(p, index) for index, p in enumerate(c["panels"], 1))
    hover = f'<div class="panel"><h3>Дополнительная шутка при наведении</h3><p>{q(c["hover_ru"])}</p></div>' if c.get("hover_ru") else ""
    notes = f"<details><summary>Пояснение каламбура</summary><p>{q(c['note_ru'])}</p></details>" if c.get("note_ru") else ""
    return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{q(c['title_ru'])} — xkcd #{c['id']}</title><style>{CSS}</style></head>
<body><main><div class="top"><a href="../index.html">← Все комиксы</a><span class="muted">xkcd #{c['id']}</span></div>
<header><h1>{q(c['title_ru'])}</h1><p class="muted">Рэндалл Манро · оригинал: <a href="{q(c['source_url'])}">{q(c['title_en'])}</a></p></header>
<div class="layout"><div class="comic"><img src="../originals/{q(image_name)}" alt="Оригинальная иллюстрация xkcd #{c['id']}"></div>
<article class="translation"><h2>Русский перевод</h2>{panel_html}{hover}{notes}</article></div>
<footer>Оригинальный рисунок: Randall Munroe, xkcd #{c['id']}. Русский неофициальный перевод — для личного некоммерческого чтения.
<a href="https://xkcd.com/license.html">CC BY-NC 2.5</a>. В изображении сохранён оригинальный английский текст.</footer></main></body></html>"""


def index_markup(items: list[dict]) -> str:
    cards = []
    for c in items:
        name = f"{c['id']}-{c['slug']}.png"
        target = f"ru/{c['id']}-{c['slug']}.html"
        cards.append(f'<a class="card" href="{q(target)}"><div class="preview"><img src="originals/{q(name)}" alt=""></div>'
                     f'<div class="meta"><h2>#{c["id"]} · {q(c["title_ru"])}</h2>'
                     f'<p>{q(c["tagline_ru"])}</p></div></a>')
    return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Комиксы о химии — личная русская подборка</title><style>{CSS}</style></head>
<body><main><header><h1>Химия: англоязычные комиксы по-русски</h1>
<p class="muted">Оригинальные рисунки xkcd и перевод реплик рядом. Нажмите на комикс, чтобы читать.</p></header>
<div class="cards">{''.join(cards)}</div><footer>Автор оригиналов: Randall Munroe · <a href="https://xkcd.com/license.html">CC BY-NC 2.5</a> · только некоммерческое чтение.</footer></main></body></html>"""


def build(items: list[dict], destination: Path, fetch=get_image) -> dict:
    original_dir = destination / "originals"
    ru_dir = destination / "ru"
    original_dir.mkdir(parents=True, exist_ok=True)
    ru_dir.mkdir(parents=True, exist_ok=True)
    manifest = {"source": "xkcd", "license": "CC BY-NC 2.5", "license_url": "https://xkcd.com/license.html",
                "generated_utc": datetime.now(timezone.utc).isoformat(), "comics": []}
    for c in items:
        png = fetch(c["image_url"])
        if not png.startswith(PNG_MAGIC):
            raise ValueError(f"Download is not a PNG: {c['id']}")
        name = f"{c['id']}-{c['slug']}.png"
        (original_dir / name).write_bytes(png)
        (ru_dir / f"{c['id']}-{c['slug']}.html").write_text(page_markup(c, name), encoding="utf-8")
        manifest["comics"].append({"id": c["id"], "title_ru": c["title_ru"],
                                    "source_url": c["source_url"], "image_url": c["image_url"],
                                    "image_sha256": hashlib.sha256(png).hexdigest(), "bytes": len(png),
                                    "original_path": f"originals/{name}",
                                    "translation_path": f"ru/{c['id']}-{c['slug']}.html"})
    (destination / "index.html").write_text(index_markup(items), encoding="utf-8")
    (destination / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (destination / "README_RU.txt").write_text(
        "КОМИКСЫ О ХИМИИ · xkcd · ЛИЧНЫЙ ЧИТАТЕЛЬСКИЙ НАБОР\n\n"
        "Откройте index.html в браузере. Внутри оригинальные картинки и русские переводы рядом.\n"
        "Автор рисунков: Randall Munroe. Оригинал: https://xkcd.com\n"
        "Лицензия оригинальных рисунков: Creative Commons BY-NC 2.5:\n"
        "https://xkcd.com/license.html\n"
        "Адаптация предназначена для личного некоммерческого чтения.\n", encoding="utf-8")
    return manifest


def selftest(items: list[dict]) -> None:
    # Valid PNG signature is sufficient for the packaging test. No network is used.
    fake_png = PNG_MAGIC + b"\x00" * 32
    with tempfile.TemporaryDirectory() as tmp:
        destination = Path(tmp) / "reader"
        result = build(items, destination, fetch=lambda url: fake_png)
        assert len(result["comics"]) == len(items)
        assert all((destination / c["original_path"]).exists() for c in result["comics"])
        assert all((destination / c["translation_path"]).exists() for c in result["comics"])
        assert "Русский перевод" in (destination / result["comics"][0]["translation_path"]).read_text(encoding="utf-8")
        assert "CC BY-NC 2.5" in (destination / "README_RU.txt").read_text(encoding="utf-8")
    print(f"PASS: {len(items)} curated strips; offline build and attribution verified")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", type=Path, default=Path(__file__).with_name("catalog.json"))
    parser.add_argument("--out", type=Path, default=Path("out/chemistry-xkcd-reader"))
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    items = load_catalog(args.catalog)
    if args.selftest:
        selftest(items)
    else:
        result = build(items, args.out)
        print(json.dumps({"status": "complete", "comics": len(result["comics"]), "out": str(args.out)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
