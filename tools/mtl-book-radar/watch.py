#!/usr/bin/env python3
"""MTL book metadata discovery. No chapters, logins, or anti-bot bypass."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

USER_AGENT = "MTLBookRadar/0.2 (public metadata only; respects robots.txt)"
BLOCK_MARKERS = ("checking your browser", "verify you are human", "captcha", "attention required!", "access denied")


def now_utc():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def atomic_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fp:
            json.dump(value, fp, ensure_ascii=False, indent=2, sort_keys=True)
            fp.write("\n")
            fp.flush()
            os.fsync(fp.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def atomic_text(path: Path, content: str):
    """Atomic file replacement, used for the JSONL view of durable state."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".txt")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fp:
            fp.write(content)
            fp.flush()
            os.fsync(fp.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def load_json(path: Path, default):
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as fp:
        return json.load(fp)


def book_match(site, url):
    parsed = urlparse(url)
    expected = urlparse(site["catalog_url"])
    if parsed.scheme != "https" or parsed.netloc.lower() != expected.netloc.lower():
        return None
    match = re.fullmatch(site["book_path_regex"], parsed.path)
    if not match:
        return None
    return match.group("id")


def parse_catalog(site, html):
    """Only same-host book links; preserve stable ID even when slug changes."""
    parsed = BeautifulSoup(html, "html.parser")
    found = {}
    for link in parsed.select("a[href]"):
        url = urljoin(site["catalog_url"], link.get("href", ""))
        bid = book_match(site, url)
        if bid is None:
            continue
        title = link.get_text(" ", strip=True)
        # Avoid misleading generic CTA as a book title.
        if not title or title.lower() in ("start reading", "novel details", "read", "view more"):
            title = ""
        previous = found.get(bid)
        if previous and not title:
            title = previous.get("title", "")
        found[bid] = {"id": bid, "url": url.split("?", 1)[0], "title": title}
    # JS-rendered TomatoMTL may embed book URLs in serialized data, not <a> tags.
    # This fallback discovers candidate IDs only. They are verified before insertion.
    if site.get("embedded_urls"):
        for match in re.finditer(r"(?:https?:\\?/\\?/[^\"'<> ]+)?/book/(\d{16,20})", html):
            bid = match.group(1)
            url = urljoin(site["catalog_url"], "/book/" + bid)
            if book_match(site, url) and bid not in found:
                found[bid] = {"id": bid, "url": url, "title": "", "unverified": True}
    return found


def parse_detail_title(site, html):
    soup = BeautifulSoup(html, "html.parser")
    title = soup.select_one("h1")
    if title:
        value = title.get_text(" ", strip=True)
        if value and len(value) > 3:
            return value[:500]
    meta = soup.select_one('meta[property="og:title"]')
    if meta and meta.get("content"):
        return meta.get("content", "")[:500].strip()
    return ""


class HttpClient:
    def __init__(self, session=None, sleep_fn=time.sleep):
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self.sleep_fn = sleep_fn
        self.robot_cache = {}
        self.last_request = {}

    def _robot(self, url):
        parsed = urlparse(url)
        key = parsed.scheme + "://" + parsed.netloc
        if key in self.robot_cache:
            return self.robot_cache[key]
        robots_url = key + "/robots.txt"
        try:
            response = self.session.get(robots_url, timeout=(8, 15), allow_redirects=True)
            # Fail closed on inaccessible robots; never bypass a 403/429.
            if response.status_code != 200 or urlparse(response.url).netloc != parsed.netloc:
                raise RuntimeError(f"robots.txt unavailable (HTTP {response.status_code})")
            rp = RobotFileParser()
            rp.parse(response.text.splitlines())
            self.robot_cache[key] = rp
            return rp
        except requests.RequestException as exc:
            raise RuntimeError(f"robots.txt unavailable ({type(exc).__name__})") from exc

    def get(self, url, delay):
        parsed = urlparse(url)
        if parsed.scheme != "https":
            raise RuntimeError("Refusing non-HTTPS URL")
        rp = self._robot(url)
        if not rp.can_fetch(USER_AGENT, url):
            raise RuntimeError("Disallowed by robots.txt: " + url)
        host = parsed.netloc
        elapsed = time.monotonic() - self.last_request.get(host, 0)
        effective_delay = max(float(delay), float(rp.crawl_delay(USER_AGENT) or 0))
        if elapsed < effective_delay:
            self.sleep_fn(effective_delay - elapsed)
        try:
            response = self.session.get(url, timeout=(8, 20), allow_redirects=True)
        except requests.RequestException as exc:
            raise RuntimeError(f"HTTP failure: {type(exc).__name__}") from exc
        self.last_request[host] = time.monotonic()
        if urlparse(response.url).netloc != host:
            raise RuntimeError("Cross-host redirect rejected")
        if response.status_code in (404, 410):
            return ("missing", response.url, "")
        if response.status_code in (401, 403, 429):
            raise RuntimeError(f"Access blocked HTTP {response.status_code}; stopping source")
        if response.status_code >= 400:
            raise RuntimeError(f"Unexpected HTTP {response.status_code}; stopping source")
        content_type = response.headers.get("Content-Type", "")
        if content_type and "html" not in content_type.lower():
            raise RuntimeError("Unexpected content type: " + content_type)
        html = response.text
        if any(marker in html[:12000].lower() for marker in BLOCK_MARKERS):
            raise RuntimeError("Anti-bot/login/error HTML; stopping source")
        return ("ok", response.url, html)


def make_event(site, record, method):
    return {"site": site["name"], "id": record["id"], "url": record["url"],
            "title": record.get("title", ""), "first_seen_utc": now_utc(), "method": method,
            "meaning": "first observed here; not necessarily newly authored"}


def verify_detail(client, site, bid, url):
    status, final_url, html = client.get(url, site.get("delay_seconds", 3))
    if status != "ok" or book_match(site, final_url) != str(bid):
        return None
    title = parse_detail_title(site, html)
    if not title:
        return None
    return {"id": str(bid), "url": final_url, "title": title}


def run_site(site, store, client):
    result = {"site": site["name"], "status": "ok", "observed_in_catalog": 0,
              "new_items": [], "attempted_ids": 0, "rechecked_holes": 0, "warnings": []}
    state = store.setdefault(site["name"], {"seen": {}, "cursor": None, "holes": [], "last_success": None})
    if not site.get("enabled", False):
        result["status"] = "disabled"
        return result
    try:
        status, _, html = client.get(site["catalog_url"], site.get("delay_seconds", 3))
        if status != "ok":
            raise RuntimeError("Catalog unavailable")
        records = parse_catalog(site, html)
        result["observed_in_catalog"] = len(records)
        if not records:
            raise RuntimeError("NO_BOOK_LINKS: page may require JavaScript; parser not verified")
        old_seen = state.setdefault("seen", {})
        first_run = not state.get("initialized", False)
        if first_run:
            # Baseline without falsely declaring all historical novels newly published.
            for bid, rec in records.items():
                if rec.get("unverified") or site.get("verify_catalog", False):
                    try:
                        checked = verify_detail(client, site, bid, rec["url"])
                    except RuntimeError as exc:
                        result["warnings"].append(str(exc))
                        result["status"] = "partial"
                        break
                    if checked is None:
                        result["warnings"].append("Baseline candidate unverified: " + bid)
                        continue
                    rec = checked
                old_seen[bid] = {"url": rec["url"], "title": rec.get("title", ""), "first_seen_utc": now_utc()}
            if site.get("probe_url") and any(k.isdigit() for k in records):
                state["cursor"] = max(int(k) for k in records if k.isdigit())
            if result["status"] != "partial":
                if not old_seen:
                    raise RuntimeError("NO_VERIFIED_BOOKS: no candidate passed metadata validation")
                state["initialized"] = True
                result["status"] = "baseline"
        else:
            # No unchecked embedded JS IDs are accepted as discoveries.
            for bid, rec in records.items():
                if bid in old_seen:
                    continue
                if rec.get("unverified") or (site.get("verify_catalog", False)):
                    checked = verify_detail(client, site, bid, rec["url"])
                    if checked is None:
                        result["warnings"].append("Unverified catalog ID " + bid)
                        continue
                    rec = checked
                old_seen[bid] = {"url": rec["url"], "title": rec.get("title", ""), "first_seen_utc": now_utc()}
                result["new_items"].append(make_event(site, rec, "catalog"))

        # Sequential-ish numeric scanning is ONLY enabled on sites with a tested
        # short /novel/{ID} route. Holes are retained and revisited; +1 is not proof.
        if not first_run and site.get("probe_url") and state.get("cursor") is not None:
            cursor = int(state["cursor"])
            upper = max(int(k) for k in records if k.isdigit())
            end = min(upper, cursor + int(site.get("probe_limit", 30)))
            holes = [int(x) for x in state.get("holes", [])]
            retry_limit = min(int(site.get("retry_limit", 10)), len(holes))
            for bid in holes[:retry_limit]:
                result["rechecked_holes"] += 1
                try:
                    found = verify_detail(client, site, bid, site["probe_url"].format(id=bid))
                except RuntimeError as exc:
                    result["warnings"].append(str(exc))
                    result["status"] = "partial"
                    break
                if found:
                    state["holes"].remove(bid)
                    if str(bid) not in old_seen:
                        old_seen[str(bid)] = {"url": found["url"], "title": found["title"], "first_seen_utc": now_utc()}
                        result["new_items"].append(make_event(site, found, "gap_retry"))
            if result["status"] != "partial":
                for bid in range(cursor + 1, end + 1):
                    result["attempted_ids"] += 1
                    try:
                        found = verify_detail(client, site, bid, site["probe_url"].format(id=bid))
                    except RuntimeError as exc:
                        result["warnings"].append(str(exc))
                        result["status"] = "partial"
                        break  # NEVER advance cursor across transient failure.
                    if not found:
                        if bid not in state["holes"]:
                            state["holes"].append(bid)
                    elif str(bid) not in old_seen:
                        old_seen[str(bid)] = {"url": found["url"], "title": found["title"], "first_seen_utc": now_utc()}
                        result["new_items"].append(make_event(site, found, "numeric_probe"))
                    state["cursor"] = bid
            # Limit growing failed-ID queue; do not silently forget unvisited gaps.
            if len(state["holes"]) > int(site.get("max_holes", 5000)):
                result["warnings"].append("Gap queue too large; source requires review")
                result["status"] = "partial"
        if result["status"] in ("ok", "baseline"):
            state["last_success"] = now_utc()
    except (RuntimeError, requests.RequestException) as exc:
        result["status"] = "error"
        result["warnings"].append(str(exc))
    return result


def render_report(results, output: Path):
    lines = ["# MTL book discovery", "", "Run: " + now_utc(), "",
             "**First seen** does not prove first publication or permission to translate.", "",
             "| Site | Status | Catalog IDs | New observations | ID probes | Warnings |",
             "|---|---|---:|---:|---:|---|"]
    for row in results:
        warnings = "; ".join(row["warnings"]).replace("|", "/")[:160]
        lines.append(f"| {row['site']} | {row['status']} | {row['observed_in_catalog']} | "
                     f"{len(row['new_items'])} | {row['attempted_ids']} | {warnings} |")
    lines.extend(["", "## Newly observed URLs", ""])
    for row in results:
        for item in row["new_items"]:
            title = item["title"] or "(title unavailable)"
            lines.append(f"- **{item['site']}** `{item['id']}` [{title}]({item['url']}) — {item['method']}")
    if not any(row["new_items"] for row in results):
        lines.append("No confirmed new observations in this run.")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path(__file__).with_name("sites.json"))
    parser.add_argument("--state", type=Path, default=Path("state/mtl-book-watch.json"))
    parser.add_argument("--report", type=Path, default=Path("reports/mtl-book-watch.md"))
    parser.add_argument("--events", type=Path, default=Path("state/mtl-discoveries.jsonl"))
    args = parser.parse_args()
    config = load_json(args.config, None)
    if not config or not isinstance(config.get("sites"), list):
        parser.error("Invalid sites.json")
    state = load_json(args.state, {"schema": 2, "sites": {}, "events": []})
    if state.get("schema") == 1:
        # Migration from initial prototype: older event log is imported once.
        previous = []
        if args.events.exists():
            with args.events.open(encoding="utf-8") as fp:
                for row in fp:
                    if row.strip():
                        previous.append(json.loads(row))
        state["schema"] = 2
        state["events"] = previous
    if state.get("schema") != 2 or not isinstance(state.get("events"), list):
        parser.error("Unsupported state schema")
    client = HttpClient()
    results = []
    for site in config["sites"]:
        result = run_site(site, state["sites"], client)
        results.append(result)
        print(f"{site['name']}: {result['status']}, new={len(result['new_items'])}, "
              f"links={result['observed_in_catalog']}, probes={result['attempted_ids']}")
    # The canonical event log and deduplication indices share one atomic file.
    # If the process stops after this write, JSONL can be rebuilt on next run.
    for result in results:
        state["events"].extend(result["new_items"])
    atomic_json(args.state, state)
    atomic_text(args.events, "".join(
        json.dumps(event, ensure_ascii=False) + "\n" for event in state["events"]
    ))
    render_report(results, args.report)
    if any(r["status"] in ("error", "partial") for r in results):
        sys.exit(2)  # Alert caller without losing saved partial evidence.


if __name__ == "__main__":
    main()
