#!/usr/bin/env python3
"""Public metadata audit of Fanqie Bleach book #1.

No chapter text, fonts, screenshots, HTML snapshots, login credentials, or
private/unpublished content are stored. The audit only inspects content already
displayed on three known public chapter pages through ordinary Chromium.
A possible canonical book URL must be discovered and validated from those pages.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import requests

TITLE = "死神：我在四番队中养花"
AUTHOR = "晋西北面点师"
HOST = "fanqienovel.com"
USER_AGENT = "MedPublicMetadataAudit/1.0 (+https://github.com/Lalalalendia/med)"
SEEDS = (
    ("chapter_3", "https://fanqienovel.com/reader/7614146817650868761"),
    ("chapter_6", "https://fanqienovel.com/reader/7614525218136015385"),
    ("chapter_48", "https://fanqienovel.com/reader/7622308190054531646"),
)
READER_RE = re.compile(r"^/reader/\d{12,23}/?$")
BOOK_RE = re.compile(r"^/page/\d{12,23}/?$")
WORD_COUNT_RE = re.compile(r"(?:本章字数|章节字数)\s*[:：]\s*(\d{2,6})\s*字")
CHAPTER_RE = re.compile(r"第\s*(\d{1,4})\s*章")
FINAL_RE = re.compile(r"第\s*364\s*章.*(?:大结局|完结|终章)")
MAX_TOTAL_PUBLIC_PAGES = 9
MIN_REQUEST_INTERVAL = 2.0

# Only counts/sha256 are returned. This javascript never returns the prose
# outside the browser process or exposes custom font bytes.
JS_STATS = r"""async () => {
  const bookTitle = "死神：我在四番队中养花";
  const urls = new Set();
  for (const element of document.querySelectorAll('a[href],link[rel=canonical],meta[property="og:url"]')) {
    const v = element.getAttribute('href') || element.getAttribute('content') || '';
    if (v) urls.add(v);
  }
  const selectors = [
    '.muye-reader-content', '.reader-content', '.chapter-content',
    '#reader-content', '#readerContent', '.chapter-body', 'article', 'main'
  ];
  const found = [];
  for (const css of selectors) {
    const el = document.querySelector(css);
    if (el) {
      const t = el.innerText || el.textContent || '';
      found.push({ selector: css, node: el, content: t });
    }
  }
  // Do not treat page chrome, menu text or meta descriptions as a chapter body.
  const chosen = found.sort((a,b) => b.content.length - a.content.length)[0];
  const str = chosen ? chosen.content : '';
  let cjk=0, pua=0, ascii=0;
  for (const ch of str) {
    const n = ch.codePointAt(0);
    if ((n>=0x3400 && n<=0x9fff) || (n>=0x20000 && n<=0x2ebef)) cjk++;
    else if (n>=0xe000 && n<=0xf8ff) pua++;
    else if (n>=0x20 && n<=0x7e) ascii++;
  }
  const dig = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(str));
  const sha = Array.from(new Uint8Array(dig)).map(b=>b.toString(16).padStart(2,'0')).join('');
  const firstFont = chosen ? getComputedStyle(chosen.node).fontFamily : '';
  const registeredFonts = [];
  document.fonts.forEach(face => {
    if (face.status === 'loaded') registeredFonts.push(face.family);
  });
  // Inspect metadata IDs in the public page state, never prose, fonts or secrets.
  const state = window.__INITIAL_STATE__;
  const pending = state && typeof state === 'object' ? [{ node: state, depth: 0 }] : [];
  const walked = new Set(), foundBookIds = new Set();
  let walkedNodes = 0;
  while (pending.length && walkedNodes++ < 250) {
    const { node, depth } = pending.shift();
    if (!node || typeof node !== 'object' || Array.isArray(node) || walked.has(node)) continue;
    walked.add(node);
    for (const key of Object.keys(node).slice(0, 80)) {
      if (/^(?:bookId|book_id|bookID)$/.test(key)) {
        const value = node[key];
        if (typeof value === 'string' && /^\d{12,23}$/.test(value)) {
          foundBookIds.add(value);
        }
      } else if (depth < 4 && !/(?:content|text|body|html|token|cookie|user|auth|password|secret|config|payload|font)/i.test(key)) {
        const value = node[key];
        if (value && typeof value === 'object' && !Array.isArray(value)) {
          pending.push({ node: value, depth: depth + 1 });
        }
      }
    }
  }
  const authorMatched = (document.body?.innerText || '').slice(0,2500).includes("晋西北面点师");
  const heading = document.querySelector('h1, h2, .chapter-title');
  const titles = [document.title, heading?.innerText || ''].filter(Boolean);
  const textOfHead = document.body?.innerText.slice(0,1200) || '';
  const declared = textOfHead.match(/(?:本章字数|章节字数)\s*[:：]\s*(\d{2,6})\s*字/);
  return {
    page_title: document.title.slice(0,170),
    heading: (heading?.innerText || '').slice(0,170),
    book_identity_found: titles.some(t => t.includes(bookTitle)),
    book_author_found: authorMatched,
    declared_chars: declared ? Number(declared[1]) : null,
    initial_state_present: Boolean(state && typeof state === 'object'),
    metadata_book_urls: Array.from(foundBookIds).slice(0, 6).map(id => 'https://fanqienovel.com/page/' + id),
    selected_css: chosen?.selector || null,
    text_chars: str.length,
    cjk_chars: cjk, private_use_chars: pua, ascii_chars: ascii,
    sha256: sha,
    font_family: firstFont.slice(0,170),
    custom_font_face_count: registeredFonts.length,
    discovered_hrefs: Array.from(urls).slice(0,200)
  };
}"""

class AuditError(Exception):
    def __init__(self, code: str, detail: str = ""):
        self.code = code
        self.detail = detail
        super().__init__(detail)


def fixed_url(url: str, *, kind: str) -> str:
    p = urlsplit(url)
    if (p.scheme != "https" or p.hostname != HOST or p.username or p.password
            or p.port not in (None, 443) or p.query or p.fragment):
        raise AuditError("unsafe_url", "Unexpected host, query, or URL scheme")
    matcher = READER_RE if kind == "reader" else BOOK_RE
    if not matcher.fullmatch(p.path):
        raise AuditError("unsafe_path", "Unexpected book or chapter route")
    return f"https://{HOST}{p.path.rstrip('/')}"


def discovered_urls(hrefs: list[str], *, parent: str, kind: str) -> list[str]:
    valid: list[str] = []
    for href in hrefs:
        try:
            url = fixed_url(urljoin(parent, href), kind=kind)
        except (AuditError, ValueError):
            continue
        if url not in valid:
            valid.append(url)
    return valid


def classify_chapter(d: dict) -> str:
    if not d.get("book_identity_found"):
        return "wrong_book_or_unidentified"
    if not d.get("selected_css"):
        return "no_chapter_container"
    cjk = d.get("cjk_chars", 0)
    pua = d.get("private_use_chars", 0)
    total = max(1, cjk + pua)
    if pua / total >= 0.1:
        return "private_use_glyphs"
    if cjk < 400:
        return "short_or_unavailable"
    declared = d.get("declared_chars")
    if declared is not None and cjk < declared * 0.4:
        return "possibly_truncated"
    return "readable_unicode_sample"


class RestrictedBrowser:
    def __init__(self, interval: float):
        self.interval = max(MIN_REQUEST_INTERVAL, interval)
        self.previous: float | None = None
        self.robots = RobotFileParser()

    def init_robots(self) -> None:
        try:
            resp = requests.get(f"https://{HOST}/robots.txt",
                                headers={"User-Agent": USER_AGENT},
                                allow_redirects=False, timeout=(8, 25))
        except requests.RequestException as exc:
            raise AuditError("robots_unavailable", type(exc).__name__) from exc
        if resp.status_code in (404, 410):
            self.robots.parse(["User-agent: *", "Allow: /"])
        elif resp.status_code == 200 and "user-agent:" in resp.text.lower() and "<html" not in resp.text[:200].lower():
            self.robots.parse(resp.text.splitlines())
        else:
            raise AuditError("robots_unavailable", f"robots status {resp.status_code}")

    def allowed(self, url: str, kind: str) -> None:
        fixed_url(url, kind=kind)
        if not self.robots.can_fetch(USER_AGENT, url):
            raise AuditError("robots_disallow", "Source robots.txt denies the route")

    def pace(self) -> None:
        if self.previous is not None:
            time.sleep(max(0.0, self.interval - (time.monotonic() - self.previous)))
        self.previous = time.monotonic()


def sanitized_probe(page, ctl: RestrictedBrowser, url: str, kind: str) -> dict:
    item: dict = {"url": url}
    try:
        ctl.allowed(url, kind)
        ctl.pace()
        response = page.goto(url, wait_until="domcontentloaded", timeout=29000)
        status = response.status if response is not None else None
        item["http_status"] = status
        if status in (401, 402, 403, 429, 451, 503) or (status is not None and 300 <= status < 400):
            item["state"] = "blocked"
            return item
        if status != 200:
            item["state"] = "http_error"
            return item
        if fixed_url(page.url, kind=kind) != fixed_url(url, kind=kind):
            item["state"] = "redirected"
            return item
        page.wait_for_timeout(900)
        data = page.evaluate(JS_STATS)
        trace = [{"observed_chars": data.get("text_chars", 0),
                  "observed_cjk": data.get("cjk_chars", 0),
                  "observed_pua": data.get("private_use_chars", 0)}]
        # Reader text may load asynchronously; inspect metadata after waiting
        # before diagnosing a short visible chapter as an excerpt.
        if kind == "reader":
            for _ in range(2):
                declared = data.get("declared_chars") or 0
                present = data.get("cjk_chars", 0) + data.get("private_use_chars", 0)
                if not declared or present >= declared * 0.65:
                    break
                page.wait_for_timeout(2500)
                newer = page.evaluate(JS_STATS)
                trace.append({"observed_chars": newer.get("text_chars", 0),
                              "observed_cjk": newer.get("cjk_chars", 0),
                              "observed_pua": newer.get("private_use_chars", 0)})
                if newer.get("text_chars", 0) > data.get("text_chars", 0):
                    data = newer
        links = data.pop("discovered_hrefs", [])
        metadata_urls = data.pop("metadata_book_urls", [])
        item.update(data)
        total_letters = data.get("cjk_chars", 0) + data.get("private_use_chars", 0)
        declared = data.get("declared_chars") or 0
        if kind == "reader":
            item["state"] = classify_chapter(data)
            item["body_coverage_ratio"] = round(total_letters / declared, 3) if declared else None
            item["possible_excerpt"] = bool(declared and total_letters < declared * 0.45)
            item["body_growth_observations"] = trace
            item["book_url_candidates"] = discovered_urls(
                links + metadata_urls, parent=url, kind="book")[:10]
            item["reader_url_candidates_count"] = len(discovered_urls(links, parent=url, kind="reader"))
        else:
            item["state"] = ("catalog_identity_found" if
                             data.get("book_identity_found") and data.get("book_author_found")
                             else "unverified_catalog")
            item["reader_url_candidates"] = discovered_urls(links, parent=url, kind="reader")[:400]
    except AuditError as exc:
        item["state"] = exc.code
        item["details"] = exc.detail[:180]
    except Exception as exc:
        # No HTML/text/log dumping, including Playwright stack traces.
        item["state"] = "browser_error"
        item["error_class"] = type(exc).__name__
    return item


def choose_chapters(catalog: dict) -> list[tuple[str, str]]:
    """Never invent chapter IDs or infer book identity from a keyword page."""
    if catalog.get("state") != "catalog_identity_found":
        return []
    links = catalog.get("reader_url_candidates", [])
    if len(links) < 3:
        return []
    positions = [0, len(links) // 3, (2 * len(links)) // 3, len(links)-1]
    return [(f"catalog_position_{i+1}", links[i]) for i in dict.fromkeys(positions)][:4]


def audit(interval: float) -> dict:
    report: dict = {
        "book_title": TITLE, "author": AUTHOR,
        "checked_utc": datetime.now(timezone.utc).isoformat(),
        "policy": "public metadata only; no stored prose, HTML, custom fonts, credentials, or screenshots",
        "keyword_url_not_canonical": "https://fanqienovel.com/keyword/7331082734615398435",
        "known_reader_samples": [],
        "canonical_book": {"state": "not_found"},
        "extra_samples": []
    }
    ctl = RestrictedBrowser(interval)
    try:
        ctl.init_robots()
    except AuditError as exc:
        report["state"] = exc.code
        report["robots_details"] = exc.detail
        return report
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        report["state"] = "playwright_unavailable"
        return report
    chrome = shutil.which("google-chrome") or shutil.which("chromium")
    if not chrome:
        report["state"] = "chrome_unavailable"
        return report
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, executable_path=chrome,
                                     args=["--no-sandbox", "--disable-dev-shm-usage"])
        context = browser.new_context(locale="zh-CN")
        page = context.new_page()
        try:
            seeds = list(SEEDS)
            for key, url in seeds:
                receipt = sanitized_probe(page, ctl, url, "reader")
                receipt["sample"] = key
                report["known_reader_samples"].append(receipt)
                print(f"sample {key}: {receipt['state']}", flush=True)
                if receipt["state"] in ("robots_unavailable", "robots_disallow", "blocked"):
                    break

            book_candidates: list[str] = []
            for receipt in report["known_reader_samples"]:
                for href in receipt.get("book_url_candidates", []):
                    if href not in book_candidates:
                        book_candidates.append(href)
            report["canonical_book"]["discovered_candidates"] = book_candidates[:8]
            for candidate in book_candidates[:2]:
                cat = sanitized_probe(page, ctl, candidate, "book")
                cat.pop("reader_url_candidates", None) if cat.get("state") != "catalog_identity_found" else None
                if cat.get("state") == "catalog_identity_found":
                    report["canonical_book"] = cat
                    break
                report["canonical_book"] = {**cat, "state": "catalog_not_verified"}

            if report["canonical_book"].get("state") == "catalog_identity_found":
                chosen = choose_chapters(report["canonical_book"])
                known = {url for _, url in SEEDS}
                for key, url in chosen:
                    if url in known:
                        continue
                    receipt = sanitized_probe(page, ctl, url, "reader")
                    receipt["sample"] = key
                    report["extra_samples"].append(receipt)
                    print(f"sample {key}: {receipt['state']}", flush=True)
                    if receipt["state"] in ("robots_unavailable", "robots_disallow", "blocked"):
                        break
            # Avoid retaining huge URL catalogs in the public metadata artifact.
            report["canonical_book"].pop("reader_url_candidates", None)
        finally:
            context.close()
            browser.close()
    results = report["known_reader_samples"] + report["extra_samples"]
    report["probe_count"] = len(results)
    report["pua_probes"] = sum(s.get("state") == "private_use_glyphs" for s in results)
    report["readable_unicode_probes"] = sum(s.get("state") == "readable_unicode_sample" for s in results)
    report["status"] = ("unicode_samples_verified" if report["readable_unicode_probes"] > 0
                        else "pua_or_access_problem" if report["pua_probes"] > 0
                        else "no_readable_samples")
    return report


def write_report(report: dict, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "manifest.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    lines = ["# Bleach Flowers / Fanqie public source audit", "",
             f"- Status: **{report.get('status', report.get('state', 'unknown'))}**",
             f"- Stable book page: **{report['canonical_book'].get('state', 'not_found')}**",
             "- No chapter prose was stored or exported.", ""]
    for sample in report["known_reader_samples"] + report["extra_samples"]:
        lines.append(f"- {sample['url']}: **{sample['state']}**, " +
                     f"declared={sample.get('declared_chars')}, CJK={sample.get('cjk_chars')}, " +
                     f"PUA={sample.get('private_use_chars')}, "
                     f"coverage={sample.get('body_coverage_ratio')}, "
                     f"excerpt={sample.get('possible_excerpt')}, CSS={sample.get('selected_css')}")
    (out / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--delay", type=float, default=2.0)
    ap.add_argument("--out", type=Path, default=Path("out/bleach-flowers-public-audit"))
    args = ap.parse_args()
    if args.delay < MIN_REQUEST_INTERVAL:
        ap.error(f"Minimum delay is {MIN_REQUEST_INTERVAL}s")
    report = audit(args.delay)
    write_report(report, args.out)
    print(json.dumps({"status": report.get("status", report.get("state")),
                      "canonical_book": report["canonical_book"].get("state"),
                      "probe_count": report.get("probe_count", 0)}, ensure_ascii=False))
    # Inability to read a public source is an audit outcome, not a code error.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
