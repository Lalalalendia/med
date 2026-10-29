#!/usr/bin/env python3
"""Index public Kakuyomu episode links without downloading chapter bodies.

Usage:
    python tools/novel-ingest/kakuyomu_toc_index.py \
      --work-id 2912051607778505262 \
      --output novels/kakuyomu/2912051607778505262/toc.json
"""
import argparse
import json
from pathlib import Path
from urllib.request import Request, urlopen
from html.parser import HTMLParser


class NextDataParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_data = False
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag == "script" and dict(attrs).get("id") == "__NEXT_DATA__":
            self.in_data = True

    def handle_endtag(self, tag):
        if tag == "script":
            self.in_data = False

    def handle_data(self, data):
        if self.in_data:
            self.parts.append(data)


def fetch_toc(work_id):
    base = f"https://kakuyomu.jp/works/{work_id}"
    request = Request(base, headers={"User-Agent": "Mozilla/5.0 (compatible; metadata-indexer/1.0)"})
    with urlopen(request, timeout=25) as response:
        html = response.read().decode("utf-8")
    parser = NextDataParser()
    parser.feed(html)
    if not parser.parts:
        raise RuntimeError("Kakuyomu __NEXT_DATA__ missing; no output written")
    state = json.loads("".join(parser.parts))["props"]["pageProps"]["__APOLLO_STATE__"]
    work = state[f"Work:{work_id}"]
    episodes = []
    for toc_ref in work["tableOfContentsV2"]:
        toc = state[toc_ref["__ref"]]
        section = state[toc["chapter"]["__ref"]].get("title", "")
        for episode_ref in toc["episodeUnions"]:
            episode = state[episode_ref["__ref"]]
            episode_id = str(episode["id"])
            episodes.append({
                "ordinal": len(episodes) + 1,
                "episode_id": episode_id,
                "title": episode.get("title", ""),
                "section": section,
                "official_url": f"{base}/episodes/{episode_id}",
            })
    if not episodes or len({e["episode_id"] for e in episodes}) != len(episodes):
        raise RuntimeError("Empty or duplicate episode index; no output written")
    return {"schema_version": 1, "source_url": base,
            "work_id": work_id, "episode_count": len(episodes),
            "content_stored": False, "episodes": episodes}


def main():
    arg = argparse.ArgumentParser(description=__doc__)
    arg.add_argument("--work-id", default="2912051607778505262")
    arg.add_argument("--output", default="novels/kakuyomu/2912051607778505262/toc.json")
    args = arg.parse_args()
    data = fetch_toc(args.work_id)
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Indexed {data['episode_count']} chapter links (no bodies) -> {target}")


if __name__ == "__main__":
    main()
