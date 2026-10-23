#!/usr/bin/env python3
"""Fetch nine Chinese Masked Knight source chapters for targeted U+FFFD QA.

Source site: Tianyabooks public chapters indexed from the verified catalog.
Only fetch exact ordinal matches, obey PoliteClient robots rules, never
commit prose to Git. The output is a temporary GitHub Actions artifact.
"""
from __future__ import annotations
import datetime as dt
import hashlib
import json
from pathlib import Path
from chapter_coverage_census import PoliteClient
from masked_knight_tianyabooks_collect import INDEX, catalog, parse_story

TARGETS = (184, 227, 229, 252, 263, 283, 290, 295, 298)
SOURCE = "https://www.tianyabooks.com/net/bianlianwushi/"

def run(out: Path, delay:float=2.0):
    if not 1.5<=delay<=12:
        raise ValueError("Invalid request delay")
    if out.exists() and any(out.iterdir()):
        raise ValueError("Output dir must be empty")
    out.mkdir(parents=True,exist_ok=True)
    (out/"raw").mkdir()
    session=PoliteClient(delay)
    report={"book":"变脸武士","target_ordinals":list(TARGETS),
            "source":SOURCE,"created":dt.datetime.now(dt.timezone.utc).isoformat(),
            "rows":[],"missing":[]}
    try:
        html=session.get(INDEX)
        if "变脸武士" not in html and "變臉武士" not in html:
            raise RuntimeError("Book identity mismatch")
        idx=catalog(html)
        for n in TARGETS:
            candidates=[x for x in idx["links"] if x["ordinal"]==n]
            if not candidates:
                report["missing"].append(n)
                continue
            for c in candidates:
                row={"ordinal":n,"title":c["title"],"url":c["url"],
                     "status":"unverified"}
                try:
                    page=session.get(c["url"])
                    parsed=parse_story(page,n)
                    row.update({k:v for k,v in parsed.items() if k!="text"})
                    if parsed["status"] not in ("long_candidate","needs_review"):
                        raise ValueError("Unverified story body")
                    text=parsed["text"]
                    if text.count("\ufffd"):
                        raise ValueError("Reference also has U+FFFD")
                    if parsed["cjk"]<1200:
                        raise ValueError("Short source")
                    blob=text.encode("utf-8")
                    name=f"raw/{n:03d}_{c['source_id']}.txt"
                    (out/name).write_bytes(blob)
                    row.update(sha256=hashlib.sha256(blob).hexdigest(),
                               filename=name,status="candidate")
                except Exception as e:
                    row["status"]="failed"
                    row["error"]=type(e).__name__+": "+str(e)[:160]
                    report["rows"].append(row)
                    if isinstance(e,RuntimeError):
                        break
                    continue
                report["rows"].append(row)
    finally:
        session.session.close()
    report["verified"] = sorted({
        r["ordinal"] for r in report["rows"] if r["status"]=="candidate"})
    report["status"]="PASS" if list(report["verified"])==list(TARGETS) else "PARTIAL"
    (out/"manifest.json").write_text(
        json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({k:report[k] for k in ("status","verified","missing")},
                     ensure_ascii=False))
    return 0 if report["status"]=="PASS" else 1

if __name__=="__main__":
    raise SystemExit(run(Path("out/masked-knight-cn-nine-reference")))
