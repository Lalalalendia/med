#!/usr/bin/env python3
"""Probe official FIPI document hosts independently of blocked interactive bank.

Does not conflate PDF accessibility with access to individual bank qids.
"""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

URLS = {
    "fipi_2026_guidance": "https://doc.fipi.ru/navigator-podgotovki/navigator-oge/MR_himiya_oge_2026.pdf",
    "fipi_2026_training": "https://doc.fipi.ru/navigator-podgotovki/navigator-oge/hi-9_tren.pdf",
    "fipi_2027_official": "https://doc.fipi.ru/oge/demoversii-specifikacii-kodifikatory/2027/hi_9_2027.zip",
    "fipi_site": "https://fipi.ru/oge/demoversii-specifikacii-kodifikatory",
}

def main() -> None:
    dest = Path("artifacts/fipi-official-document-audit")
    dest.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers["User-Agent"] = "Mozilla/5.0 (compatible; education-source-check/1.0)"
    results = []
    for label, url in URLS.items():
        row = {"name": label, "url": url, "utc": datetime.now(timezone.utc).isoformat()}
        try:
            response = session.get(url, timeout=(6, 14), allow_redirects=True)
            row.update({"http_status": response.status_code,
                        "content_type": response.headers.get("Content-Type", ""),
                        "size_bytes": len(response.content),
                        "sha256": hashlib.sha256(response.content).hexdigest(),
                        "final_url": response.url})
            response.raise_for_status()
            if label.endswith("guidance") or label.endswith("training"):
                row["valid_magic"] = response.content.startswith(b"%PDF")
                if row["valid_magic"]:
                    import fitz
                    pdf = fitz.open(stream=response.content, filetype="pdf")
                    row["page_count"] = len(pdf)
                    row["example_numbers"] = sorted({
                        int(x) for p in pdf for x in __import__("re").findall(r"[Пп]ример задания\s+(\d+)", p.get_text())
                    })
            if label == "fipi_2027_official":
                row["valid_magic"] = response.content.startswith(b"PK")
                if row["valid_magic"]:
                    from zipfile import ZipFile
                    from io import BytesIO
                    archive = ZipFile(BytesIO(response.content))
                    row["zip_files"] = [{"name": i.filename, "size": i.file_size} for i in archive.infolist()]
        except Exception as error:
            row["error"] = f"{type(error).__name__}: {error}"
        results.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
        time.sleep(.3)
    (dest / "official_hosts.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# Audit of official FIPI document hosts", "", "This is a connectivity and provenance test. It does NOT verify the 46 individual question qids.", ""]
    for row in results:
        lines.append(f"- {row['name']}: HTTP {row.get('http_status', 'no response')}; "
                     f"{row.get('page_count','')} pages; "
                     f"{row.get('error', '')[:120]}")
    (dest / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("SUMMARY", {"success": sum(r.get("http_status")==200 for r in results),
                      "total": len(results)}, flush=True)

if __name__ == "__main__":
    main()
