#!/usr/bin/env python3
"""Archive complete authorized Kakuyomu chapter bodies with a verifiable manifest.

The source website must allow the requested access and the operator must hold
permission to store/reproduce the text. Do not bypass access controls.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

DEFAULT_ID = "2912051607778505262"
DEFAULT_DIR = f"novels/kakuyomu/{DEFAULT_ID}/raw"


def session():
    client = requests.Session()
    client.headers.update({
        "User-Agent": "Mozilla/5.0 (compatible; med-Kakuyomu-source-archiver/1.0)",
        "Accept-Language": "ja-JP,ja;q=0.9,en;q=0.5",
    })
    retry = Retry(
        total=3, connect=3, read=3, backoff_factor=1.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"], respect_retry_after_header=True,
    )
    client.mount("https://", HTTPAdapter(max_retries=retry))
    return client


def fetch(client, url):
    response = client.get(url, timeout=(15, 45))
    response.raise_for_status()
    response.encoding = "utf-8"
    return response.text


def get_episode_index(client, work_id):
    base = f"https://kakuyomu.jp/works/{work_id}"
    soup = BeautifulSoup(fetch(client, base), "lxml")
    script = soup.find("script", id="__NEXT_DATA__")
    if not script:
        raise ValueError("Work page has no __NEXT_DATA__: parser needs review")
    data = json.loads(script.get_text())
    state = data["props"]["pageProps"]["__APOLLO_STATE__"]
    work = state[f"Work:{work_id}"]
    toc_refs = work.get("tableOfContentsV2")
    if not isinstance(toc_refs, list) or not toc_refs:
        raise ValueError("Work has no tableOfContentsV2: parser needs review")

    result = []
    for toc_ref in toc_refs:
        toc = state[toc_ref["__ref"]]
        chapter_ref = toc.get("chapter")
        chapter = state[chapter_ref["__ref"]] if chapter_ref else {}
        section = chapter.get("title", "")
        for episode_ref in toc["episodeUnions"]:
            episode = state[episode_ref["__ref"]]
            episode_id = str(episode["id"])
            result.append({
                "ordinal": len(result) + 1,
                "episode_id": episode_id,
                "title_hint": episode.get("title", ""),
                "section": section,
                "source_url": f"{base}/episodes/{episode_id}",
            })
    ids = [item["episode_id"] for item in result]
    if not ids or len(set(ids)) != len(ids):
        raise ValueError("Empty index or duplicate episode IDs: refusing archive")
    return base, work, result


def parse_body(html):
    soup = BeautifulSoup(html, "lxml")
    body = soup.find(class_="widget-episodeBody")
    if body is None:
        raise ValueError("Missing widget-episodeBody (no readable chapter body)")
    for tag in body.select("rt, rp"):
        tag.decompose()
    for ruby in body.select("ruby"):
        ruby.unwrap()
    paras = []
    for p in body.find_all("p"):
        if "blank" in (p.get("class") or []):
            paras.append("")
            continue
        for br in p.find_all("br"):
            br.replace_with("\n")
        part = p.get_text("", strip=False).replace("\r", "").rstrip()
        paras.append(part.lstrip("\u3000"))
    while paras and not paras[0].strip():
        paras.pop(0)
    while paras and not paras[-1].strip():
        paras.pop()
    title_node = soup.find(class_="widget-episodeTitle") or soup.find("h1")
    title = title_node.get_text(" ", strip=True) if title_node else ""
    return title, "\n".join(paras).strip()


def archive(work_id, out_dir, delay, min_chars, min_episodes):
    client = session()
    base, work, toc = get_episode_index(client, work_id)
    if len(toc) < min_episodes:
        raise ValueError(f"Only {len(toc)} episodes (minimum expected {min_episodes})")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    records = []
    failures = []
    for entry in toc:
        ordinal = entry["ordinal"]
        try:
            html = fetch(client, entry["source_url"])
            title, body = parse_body(html)
            title = title or entry["title_hint"]
            chars = len(re.sub(r"\s+", "", body))
            if chars < min_chars:
                raise ValueError(f"Body too short: {chars} non-whitespace characters")
            digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
            path = out / f"{ordinal:03d}.txt"
            header = (
                f"Work-ID: {work_id}\n"
                f"Ordinal: {ordinal}\n"
                f"Episode-ID: {entry['episode_id']}\n"
                f"Section: {entry['section']}\n"
                f"JP-Title: {title}\n"
                f"Source: {entry['source_url']}\n"
                f"SHA256-Body: {digest}\n"
                f"Characters-No-Whitespace: {chars}\n\n"
            )
            path.write_text(header + body + "\n", encoding="utf-8")
            records.append({
                "ordinal": ordinal, "episode_id": entry["episode_id"],
                "section": entry["section"], "title_jp": title,
                "source_url": entry["source_url"],
                "file": path.name, "chars_no_whitespace": chars,
                "sha256_body": digest, "status": "PASS",
            })
            print(f"PASS {ordinal:03d}/{len(toc)} {chars} chars", flush=True)
        except Exception as exc:
            errors = {"ordinal": ordinal, "episode_id": entry["episode_id"],
                      "source_url": entry["source_url"], "error": str(exc)}
            failures.append(errors)
            print(f"FAIL {ordinal:03d}/{len(toc)}: {exc}", file=sys.stderr, flush=True)
        time.sleep(max(delay, 0.5))

    if not failures:
        indexed = {f"{n:03d}.txt" for n in range(1, len(toc) + 1)}
        for existing in out.glob("[0-9][0-9][0-9].txt"):
            if existing.name not in indexed:
                existing.unlink()

    manifest = {
        "schema_version": 1, "work_id": work_id,
        "source_url": base,
        "title_original": work.get("title", ""),
        "index_count": len(toc), "stored_count": len(records),
        "failed_count": len(failures),
        "status": "COMPLETE" if not failures else "PARTIAL",
        "chapter_bodies_stored": True,
        "permission_basis": "User reports permission to store full chapter texts",
        "chapters": records, "failures": failures,
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    toc_only = {
        "schema_version": 1, "work_id": work_id,
        "source_url": base, "episode_count": len(toc), "episodes": toc,
    }
    (out / "toc.json").write_text(
        json.dumps(toc_only, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    summary = (
        "# Kakuyomu authorized original archive\n\n"
        f"- Work: {work.get('title', '')}\n"
        f"- URL: {base}\n"
        f"- Indexed episodes: {len(toc)}\n"
        f"- Successfully stored bodies: {len(records)}\n"
        f"- Failed episodes: {len(failures)}\n"
        f"- Status: {manifest['status']}\n"
        f"- Body characters (non-whitespace): "
        f"{sum(c['chars_no_whitespace'] for c in records)}\n"
        "- Permission: user-reported authorization; no license document attached.\n"
        "- Storage does not establish permission to publish on a third-party site.\n"
    )
    (out / "summary.md").write_text(summary, encoding="utf-8")
    print(summary, flush=True)
    return 0 if not failures else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-id", default=DEFAULT_ID)
    parser.add_argument("--out-dir", default=DEFAULT_DIR)
    parser.add_argument("--delay", type=float, default=0.7)
    parser.add_argument("--min-chars", type=int, default=80)
    parser.add_argument("--min-episodes", type=int, default=70)
    args = parser.parse_args()
    return archive(args.work_id, args.out_dir, args.delay,
                   args.min_chars, args.min_episodes)


if __name__ == "__main__":
    sys.exit(main())
