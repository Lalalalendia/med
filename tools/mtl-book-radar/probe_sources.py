#!/usr/bin/env python3
"""Read-only, robots-aware eligibility probe for candidate MTL catalogues."""
import json
from pathlib import Path
from urllib.parse import urlparse

from watch import HttpClient, parse_catalog

CONFIG = json.loads(Path(__file__).with_name("sites.json").read_text(encoding="utf-8"))
BY_NAME = {item["name"]: item for item in CONFIG["sites"]}
TRIALS = [
    ("fanmtl", "https://www.fanmtl.com/"),
    ("fanmtl", "https://www.fanmtl.com/list/all/all-newstime-0.html"),
    ("ranobes", "https://ranobes.net/novels/"),
    ("mtl-novel", "https://mtl-novel.com/"),
    ("mtl-novel", "https://mtl-novel.com/novel/"),
    ("readnovelmtl", "https://readnovelmtl.com/novel"),
]
client = HttpClient()
rows = []
for name, url in TRIALS:
    site = dict(BY_NAME[name], catalog_url=url)
    item = {"site": name, "catalog_url": url, "status": "error", "books": 0, "samples": [], "error": ""}
    try:
        status, final_url, html = client.get(url, site["delay_seconds"])
        if status != "ok":
            raise RuntimeError(f"Unexpected response: {status}")
        book_rows = parse_catalog(site, html)
        item.update(status="ok", books=len(book_rows), samples=list(book_rows.values())[:5],
                    final_url=final_url, bytes=len(html))
        if not book_rows:
            item["status"] = "parser_empty"
    except Exception as exc:
        item["error"] = f"{type(exc).__name__}: {exc}"
    rows.append(item)
    print(json.dumps(item, ensure_ascii=False))
lines = ["# MTL site preflight", "", "| Source | URL | Status | Books | Error |", "|---|---|---|---:|---|"]
for row in rows:
    err = str(row["error"]).replace("|", "/")[:160]
    lines.append(f"| {row['site']} | {row['catalog_url']} | {row['status']} | {row['books']} | {err} |")
lines += ["", "## Samples", ""]
for row in rows:
    lines.append(f"### {row['site']} {urlparse(row['catalog_url']).path}")
    for entry in row["samples"]:
        lines.append(f"- {entry['id']} {entry['title']} {entry['url']}")
out = Path("out/mtl-site-probe/report.md")
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text("\n".join(lines) + "\n", encoding="utf-8")
