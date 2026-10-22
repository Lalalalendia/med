#!/usr/bin/env python3
"""Bounded, read-only host availability check of the Atarax source register."""
import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
import requests

USER_AGENT = "AtaraxSourceRegistryAudit/1.0 (public metadata only)"
BLOCK_TERMS = ("captcha", "just a moment", "verify you are human", "cloudflare challenge", "人机验证", "安全验证")
MAX_BYTES = 180000

def probe(url, timeout=8):
    result = {"url": url, "status": "unverified"}
    try:
        p = urlsplit(url)
        if p.scheme not in ("http", "https") or not p.hostname or p.username or p.password:
            result["status"] = "invalid_url"
            return result
        with requests.get(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
                          timeout=(timeout, timeout), allow_redirects=False,
                          stream=True) as resp:
            result["http_status"] = resp.status_code
            result["content_type"] = resp.headers.get("content-type", "").split(";")[0][:90]
            if resp.is_redirect:
                location = resp.headers.get("location", "")
                parsed = urlsplit(location)
                result["status"] = "redirect"
                result["redirect_host"] = parsed.hostname
                return result
            if resp.status_code in (401, 402, 403, 429, 451, 503):
                result["status"] = "blocked_or_restricted"
                return result
            if resp.status_code in (404, 410):
                result["status"] = "not_found"
                return result
            if resp.status_code >= 400:
                result["status"] = "http_error"
                return result
            if resp.status_code != 200:
                result["status"] = "unexpected_http"
                return result
            data = b""
            for chunk in resp.iter_content(16000):
                data += chunk
                if len(data) >= MAX_BYTES:
                    break
            raw = data.decode(resp.encoding or "utf-8", errors="replace").lower()
            result["sample_bytes"] = len(data)
            if any(term in raw for term in BLOCK_TERMS):
                result["status"] = "challenge_or_block"
            elif "html" in result["content_type"] or "<html" in raw[:1500]:
                result["status"] = "html_reachable"
            else:
                result["status"] = "non_html_response"
    except requests.exceptions.SSLError:
        result["status"] = "tls_error"
    except requests.exceptions.Timeout:
        result["status"] = "timeout"
    except requests.exceptions.ConnectionError:
        result["status"] = "network_error"
    except requests.exceptions.RequestException:
        result["status"] = "request_error"
    return result

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--config", default="tools/novel-ingest/config/atarax_source_hosts_20261018.json")
    ap.add_argument("--out", default="out/atarax-source-host-audit")
    ap.add_argument("--limit",type=int,default=61)
    args=ap.parse_args()
    source=json.loads(Path(args.config).read_text(encoding="utf-8"))
    rows=[]
    for site in source["hosts"][:max(0,min(61,args.limit))]:
        url=site["example_urls"][0]
        got=probe(url)
        rows.append({"host":site["host"],"family":site["family"],
                     "linked_books":len(site["book_ids"]),"source_links":site["primary"]+site["additional"],
                     **got})
        print(site["host"],got["status"],flush=True)
        time.sleep(1.5)
    report={"schema_version":1,"checked_at":datetime.now(timezone.utc).isoformat(),
            "note":"Only representative URL reachability from this CI runner. No chapter texts downloaded or stored.",
            "source_book_count":source["total_books"],"hosts_total":len(source["hosts"]),
            "hosts_checked":len(rows),"results":rows}
    out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
    (out/"manifest.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    buckets={}
    for row in rows:buckets[row["status"]]=buckets.get(row["status"],0)+1
    lines=["# Atarax source host audit","",f"Checked: {len(rows)}/{len(source['hosts'])} host examples.","",
           "Statuses: "+", ".join(f"{k}: {v}" for k,v in sorted(buckets.items())),"",
           "| Host | Status | HTTP | Example |","|---|---|---:|---|"]
    lines += [f"| {r['host']} | {r['status']} | {r.get('http_status','—')} | {r['url']} |" for r in rows]
    (out/"summary.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
if __name__=="__main__":main()
