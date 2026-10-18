#!/usr/bin/env python3
"""Metadata-only availability check for Bleach book #7 (not a text downloader).

Compares the publisher and mirror table of contents without treating repeated
per-volume chapter numbers as global chapter IDs. A small public-body sample is
read only in memory by ordinary Chromium; chapter prose is never saved/logged.
No login, CAPTCHA solving, robots bypass, or paid-content access.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import re
import shutil
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

BOOK_TITLE = "死神：尸魂界的禁忌之人"
BOOK_AUTHOR = "月过千山"
MIRROR_HOST = "m.fanqiexsw.com"
PUBLISHER_HOST = "www.readnovel.com"
MIRROR_ID = "65504"
MIRROR_PAGE_3 = f"https://{MIRROR_HOST}/{MIRROR_ID}_3/"
PUBLISHER_INDEX = f"https://{PUBLISHER_HOST}/bookquery/jdycosqbbphv"
EXPECTED_PUBLISHER_INDEX_COUNT = 650  # Research baseline; not a scan result.
EXPECTED_MIRROR_INDEX_COUNT = 665  # Research baseline; not a scan result.
USER_AGENT = "MedBleachMetadataAudit/1.0 (+https://github.com/Lalalalendia/med)"
MIRROR_CHAPTER = re.compile(r"^/65504/(\d{4,16})\.html$")
MIRROR_PAGE = re.compile(r"^/65504_(\d{1,2})/$")
CHAPTER_PREFIX = re.compile(r"^\s*第\s*([零〇一二三四五六七八九十百千万\d]+)\s*(?:章|回|节|節|篇)\s*[:：.、\-— ]*", re.I)
AUXILIARY = re.compile(
    r"完本感言|上架感言|卷末感言|作者的话|请假|请个假|告个假|"
    r"新书(?:通知|发布|预告|《)|^关于本书$|后记$|一点心里话|"
    r"不能更新|今天休息|中招了|有点卡文"
)
CHALLENGE = ("正在验证浏览器", "正在驗證瀏覽器", "安全验证", "人机验证",
             "just a moment", "captcha", "verify you are human", "access denied",
             "login to read", "unlock this chapter", "purchase this chapter")
BODY_SELECTORS = ("#content", "#chaptercontent", "#chapter-content", "#txtcontent",
                  "#txtcontent0", "#readcontent", ".chapter-content",
                  ".read-content", "article", ".content")
MAX_HTML_BYTES = 5_000_000
MAX_INDEX_PAGES = 20


@dataclass(frozen=True)
class Entry:
    source: str
    url: str
    title: str
    volume: str = ""
    chapter_number: str | None = None
    auxiliary: bool = False
    page: int = 0
    position: int = 0  # Global *index position*, not an author chapter number.


class AuditError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def validate_url(url: str, host: str, *, chapter: bool = False) -> str:
    """Pin all inputs and discovered links to known HTTPS hosts and book paths."""
    p = urlsplit(url)
    if (p.scheme != "https" or p.hostname != host or p.username or p.password
            or p.port not in (None, 443) or p.query or p.fragment):
        raise AuditError("unsafe_url", "Unexpected source host, scheme, or URL attributes")
    if host == MIRROR_HOST:
        valid_path = (bool(MIRROR_CHAPTER.fullmatch(p.path)) if chapter else
                      p.path == f"/{MIRROR_ID}/" or bool(MIRROR_PAGE.fullmatch(p.path)))
    elif host == PUBLISHER_HOST:
        # Unknown opaque publisher chapter routes must not be guessed/fetched.
        valid_path = p.path == urlsplit(PUBLISHER_INDEX).path and not chapter
    else:
        valid_path = False
    if not valid_path:
        raise AuditError("unsafe_url", "URL is outside the pinned book routes")
    return url


def text_title(label: str) -> str:
    return re.sub(r"\s+", " ", label).strip()


def title_key(label: str) -> str:
    value = CHAPTER_PREFIX.sub("", label)
    value = re.sub(r"[\s\u3000.,。!！?？:：—\-（）()《》\[\]【】‘’'\"]+", "", value)
    return value.casefold()


def entry_from_link(source: str, href: str, label: str, base: str,
                    *, page: int = 0, volume: str = "") -> Entry | None:
    url = urljoin(base, href)
    if source == "mirror":
        try:
            validate_url(url, MIRROR_HOST, chapter=True)
        except AuditError:
            return None
    else:
        # Never follow unverified opaque ReadNovel chapter links. We still
        # compare chapter *titles* from publisher listings, without URLs.
        p = urlsplit(url)
        if p.scheme != "https" or p.hostname != PUBLISHER_HOST or p.username or p.password:
            return None
        if not p.path.startswith(("/chapter/", "/book/", "/bqx/", "/bookquery/")):
            return None
        url = ""  # Do not offer unproven chapter routes for browser sampling.
    name = text_title(label)
    if not name or len(name) > 200:
        return None
    match = CHAPTER_PREFIX.match(name)
    # Mirror page count includes unnumbered author notices and interludes.
    # Only same-book chapter-shaped URLs after the catalog marker are accepted.
    auxiliary = not bool(match) or bool(AUXILIARY.search(name))
    return Entry(source, url, name, volume, match.group(1) if match else None,
                 auxiliary, page)


def parse_mirror_page(html: str, *, page: int) -> tuple[list[Entry], int | None]:
    soup = BeautifulSoup(html, "html.parser")
    heading = soup.title.get_text(" ", strip=True) if soup.title else soup.get_text(" ", strip=True)[:300]
    if BOOK_TITLE not in heading and BOOK_TITLE not in soup.get_text(" ", strip=True)[:500]:
        raise AuditError("wrong_book", "Mirror page is not the pinned Bleach novel")
    blob = soup.get_text(" ", strip=True)
    m = re.search(r"共\s*(\d{1,4})\s*章", blob)
    claimed_total = int(m.group(1)) if m else None
    # Every mirror page includes an extra global "latest chapter" link in
    # its header. It is NOT one of this page's fifty catalog positions.
    # Require the catalog's '共 665 章' marker and parse anchors after it.
    # This also keeps the actual epilogue entry on the last catalog page.
    marker = soup.find(string=lambda s: s is not None and
                       bool(re.search(r"共\s*\d{1,4}\s*章", str(s))))
    if marker is None:
        raise AuditError("catalog_marker_missing", "Chapter-list total marker is absent")
    entries: list[Entry] = []
    seen: set[str] = set()
    for node in marker.next_elements:
        if getattr(node, "name", None) != "a" or not node.get("href"):
            continue
        entry = entry_from_link("mirror", node["href"], node.get_text(" ", strip=True),
                                f"https://{MIRROR_HOST}/{MIRROR_ID}_{page}/", page=page)
        if entry is not None and entry.url not in seen:
            seen.add(entry.url)
            entries.append(entry)
    return entries, claimed_total


def publisher_dom_diagnostics(html: str) -> dict:
    """Retain layout statistics only; do not store HTML or chapter prose."""
    soup = BeautifulSoup(html, "html.parser")
    page_text = soup.get_text(" ", strip=True)
    m = re.search(r"目录\s*[·・]?\s*共\s*(\d{1,4})\s*章", page_text)
    if not m:
        m = re.search(r"共\s*(\d{1,4})\s*章", page_text)
    per_tag = {}
    for name in ("a", "li", "span", "p", "div"):
        count = 0
        for node in soup.find_all(name):
            if CHAPTER_PREFIX.match(text_title(node.get_text(" ", strip=True))):
                count += 1
        per_tag[name] = count
    unusual_titles = []
    all_catalog_links = 0
    for container in soup.select(".volume"):
        for a in container.select("a[href]"):
            all_catalog_links += 1
            label = text_title(a.get_text(" ", strip=True))
            if label and not CHAPTER_PREFIX.match(label):
                unusual_titles.append(label[:100])
    path_counts = {}
    for a in soup.find_all("a", href=True):
        label = text_title(a.get_text(" ", strip=True))
        if not CHAPTER_PREFIX.match(label):
            continue
        parsed = urlsplit(urljoin(PUBLISHER_INDEX, a["href"]))
        if parsed.scheme != "https" or parsed.hostname != PUBLISHER_HOST:
            key = "external"
        else:
            key = "/" + parsed.path.lstrip("/").split("/", 1)[0]
        path_counts[key] = path_counts.get(key, 0) + 1
    selectors = (".volume", ".volume-item", ".volume-list",
                 "#chapterList", ".chapter-list", ".catalog-list")
    return {"declared_chapter_count": int(m.group(1)) if m else None,
            "chapter_tag_counts": per_tag,
            "chapter_link_prefixes": path_counts,
            "recognized_container_counts": {css: len(soup.select(css)) for css in selectors},
            "html_bytes": len(html.encode("utf-8")),
            "volume_link_count": all_catalog_links,
            "unparsed_volume_link_count": len(unusual_titles),
            "unparsed_volume_link_titles": unusual_titles[:35]}


def parse_publisher_page(html: str) -> list[Entry]:
    soup = BeautifulSoup(html, "html.parser")
    full = soup.get_text(" ", strip=True)
    if BOOK_TITLE not in full and (not soup.title or BOOK_TITLE not in soup.title.get_text(" ", strip=True)):
        raise AuditError("wrong_book", "Publisher page does not identify the Bleach novel")
    containers = soup.select(".volume, .volume-item, .volume-list, #chapterList, .chapter-list, .catalog-list")
    result: list[Entry] = []
    for container in containers:
        if any(container in candidate.descendants for candidate in containers if candidate is not container):
            continue
        header = container.select_one("h2, h3, h4, .volume-title")
        volume = text_title(header.get_text(" ", strip=True)) if header else ""
        # Publisher catalog links may point to a separate Yuewen subdomain.
        # Only record the text of links inside the verified book's volume
        # containers; do not follow or guess chapter URLs.
        for link in container.select("a[href]"):
            title = text_title(link.get_text(" ", strip=True))
            if not title or len(title) > 200:
                continue
            match = CHAPTER_PREFIX.match(title)
            result.append(Entry("publisher", "", title, volume,
                                match.group(1) if match else None,
                                not bool(match) or bool(AUXILIARY.search(title))))
    if result:
        return result

    # Metadata-only fallback for publishers rendering list items without
    # the known volume selectors. It still never fetches chapter links and
    # never fabricates an exact 650-cardinality when markup is incomplete.
    diag = publisher_dom_diagnostics(html)
    if diag["declared_chapter_count"] != EXPECTED_PUBLISHER_INDEX_COUNT:
        return []
    candidates: list[list[Entry]] = []
    for tag in ("a", "li", "span", "p"):
        items: list[Entry] = []
        for node in soup.find_all(tag):
            title = text_title(node.get_text(" ", strip=True))
            match = CHAPTER_PREFIX.match(title)
            is_aux = bool(AUXILIARY.search(title))
            if not match and not is_aux:
                continue
            if len(title) > 180:
                continue
            items.append(Entry("publisher", "", title, "",
                               match.group(1) if match else None, is_aux))
        candidates.append(items)
    exact = next((c for c in candidates if len(c) == EXPECTED_PUBLISHER_INDEX_COUNT), None)
    return exact if exact is not None else max(candidates, key=len, default=[])


def number_entries(entries: list[Entry]) -> list[Entry]:
    return [Entry(e.source, e.url, e.title, e.volume, e.chapter_number,
                  e.auxiliary, e.page, i) for i, e in enumerate(entries, 1)]


EDITORIAL_SUFFIX = re.compile(
    r"[（(]\s*(?:(?:\d+|[一二三四五六七八九十百千万]+)字(?:大章)?|"
    r"二合一|大结局)\s*[）)]\s*$"
)

def comparison_key(title: str) -> str:
    title = CHAPTER_PREFIX.sub("", title)
    while True:
        reduced = EDITORIAL_SUFFIX.sub("", title)
        if reduced == title:
            break
        title = reduced
    return title_key(title)


def compare_indices(publisher: list[Entry], mirror: list[Entry],
                    *, publisher_complete: bool, mirror_complete: bool) -> dict:
    outcome = {"publisher_count": len(publisher), "mirror_count": len(mirror),
               "expected_publisher_count": EXPECTED_PUBLISHER_INDEX_COUNT,
               "expected_mirror_count": EXPECTED_MIRROR_INDEX_COUNT,
               "status": "unavailable_or_partial"}
    if not (publisher_complete and mirror_complete and publisher and mirror):
        return outcome
    a = [comparison_key(e.title) for e in publisher]
    b = [comparison_key(e.title) for e in mirror]
    ops = difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes()
    shared = sum(i2 - i1 for kind, i1, i2, _, _ in ops if kind == "equal")
    discrepancies = []
    for kind, i1, i2, j1, j2 in ops:
        if kind == "equal":
            continue
        discrepancies.append({"kind": kind,
                              "publisher_positions": [i1 + 1, i2],
                              "mirror_positions": [j1 + 1, j2],
                              "publisher_titles": [e.title for e in publisher[i1:min(i2, i1 + 3)]],
                              "mirror_titles": [e.title for e in mirror[j1:min(j2, j1 + 3)]]})
    publisher_stories = [comparison_key(e.title) for e in publisher if not e.auxiliary]
    mirror_stories = [comparison_key(e.title) for e in mirror if not e.auxiliary]
    outcome.update(story_sequences_identical=publisher_stories == mirror_stories,
                   extra_auxiliary_entries=sum(e.auxiliary for e in mirror) -
                                           sum(e.auxiliary for e in publisher))
    outcome.update(status="compared", shared_title_positions=shared,
                   unmatched_blocks=len(discrepancies),
                   publisher_auxiliary=sum(e.auxiliary for e in publisher),
                   mirror_auxiliary=sum(e.auxiliary for e in mirror),
                   publisher_story=sum(not e.auxiliary for e in publisher),
                   mirror_story=sum(not e.auxiliary for e in mirror),
                   mismatches=discrepancies[:40],
                   mismatches_truncated=len(discrepancies) > 40)
    return outcome


def sample_entries(entries: list[Entry], mode: str) -> list[Entry]:
    # Sample story chapters only. A 100-character author afterword is not a
    # 100-character story chapter and must never count as an incomplete chapter.
    story = [e for e in entries if not e.auxiliary]
    if not story:
        return []
    n = len(story)
    if mode == "pilot":
        at = [0, n // 2, n - 1]
    else:
        # For this book the first 136 catalogue positions are marked free by
        # the publisher. Probe either side of the boundary and several later
        # volumes to identify where mirror bodies become mere previews.
        at = [0, 1, n // 6, n // 5, n // 5 + 3, n // 5 + 7,
              n // 5 + 8, n // 5 + 9, n // 5 + 10, n // 5 + 11,
              n // 5 + 15, n // 5 + 20, n // 3, n // 2,
              (4 * n) // 5, n - 40, n - 3, n - 2, n - 1]
    return [story[i] for i in sorted(set(i for i in at if 0 <= i < n))]

def inspect_body(html: str, entry: Entry) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    heading = soup.select_one("h1")
    displayed_title = text_title(heading.get_text(" ", strip=True)) if heading else (
        text_title(soup.title.get_text(" ", strip=True)) if soup.title else "")
    summary = soup.get_text(" ", strip=True)[:900].lower()
    if any(term in summary for term in CHALLENGE):
        return {"state": "challenge", "page_title": displayed_title[:150]}
    options = [(key, soup.select_one(key)) for key in BODY_SELECTORS]
    options = [(key, node) for key, node in options if node is not None]
    if not options:
        return {"state": "selector_missing", "page_title": displayed_title[:150]}
    selector, container = max(options, key=lambda x: len(x[1].get_text(" ", strip=True)))
    for junk in container.select("script,style,nav,header,footer,form,iframe,aside,.ad,.advertisement"):
        junk.decompose()
    plain = re.sub(r"\s+", " ", container.get_text(" ", strip=True))
    cjk = len(re.findall(r"[\u3400-\u9fff]", plain))
    expected = title_key(entry.title)
    actual = title_key(displayed_title)
    title_matches = bool(expected and len(expected) >= 2 and
                         (expected in actual or (entry.auxiliary and expected[:4] in actual)))
    if cjk < 400:
        status = "too_short"
    elif not title_matches:
        status = "title_unverified"
    else:
        status = "readable"
    # Only metadata and a digest leave memory, never chapter prose.
    return {"state": status, "page_title": displayed_title[:150],
            "title_matches": title_matches, "selector": selector,
            "cjk_chars": cjk, "text_chars": len(plain),
            "sha256": hashlib.sha256(plain.encode("utf-8")).hexdigest()}


class PublicSession:
    def __init__(self, delay: float = 1.5, session: requests.Session | None = None):
        self.delay = delay
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        self.robots: dict[str, RobotFileParser] = {}
        self.last_request: dict[str, float] = {}

    def _pace(self, host: str) -> None:
        previous = self.last_request.get(host)
        robot_delay = self.robots[host].crawl_delay(USER_AGENT) or 0
        interval = max(self.delay, robot_delay)
        if previous is not None:
            time.sleep(max(0, interval - (time.monotonic() - previous)))
        self.last_request[host] = time.monotonic()

    def ensure_robots(self, host: str) -> None:
        if host in self.robots:
            return
        try:
            response = self.session.get(f"https://{host}/robots.txt", timeout=(6, 18), allow_redirects=False)
        except requests.RequestException as exc:
            raise AuditError("robots_unavailable", type(exc).__name__) from exc
        rp = RobotFileParser()
        if response.status_code in (404, 410):
            rp.parse(["User-agent: *", "Allow: /"])
        elif response.status_code == 200 and "user-agent:" in response.text.lower() and "<html" not in response.text[:400].lower():
            rp.parse(response.text.splitlines())
        else:
            raise AuditError("robots_unavailable", f"robots.txt HTTP {response.status_code}")
        self.robots[host] = rp

    def check_allowed(self, url: str, host: str, *, chapter: bool = False) -> None:
        validate_url(url, host, chapter=chapter)
        self.ensure_robots(host)
        if not self.robots[host].can_fetch(USER_AGENT, url):
            raise AuditError("robots_disallow", "Source robots.txt does not permit URL")

    def html(self, url: str, host: str, *, chapter: bool = False) -> str:
        self.check_allowed(url, host, chapter=chapter)
        self._pace(host)
        try:
            response = self.session.get(url, timeout=(7, 25), allow_redirects=False,
                                        headers={"Accept": "text/html"}, stream=True)
        except requests.RequestException as exc:
            raise AuditError("network_error", type(exc).__name__) from exc
        if response.status_code in (401, 402, 403, 429, 451, 503) or 300 <= response.status_code < 400:
            response.close()
            raise AuditError("blocked", f"HTTP {response.status_code}")
        if response.status_code != 200:
            response.close()
            raise AuditError("http_error", f"HTTP {response.status_code}")
        if "html" not in response.headers.get("content-type", "").lower():
            response.close()
            raise AuditError("invalid_content_type", "Expected HTML page")
        total = 0
        chunks = []
        try:
            for chunk in response.iter_content(65536):
                total += len(chunk)
                if total > MAX_HTML_BYTES:
                    raise AuditError("oversize_page", "Page larger than HTML audit limit")
                chunks.append(chunk)
        except requests.RequestException as exc:
            raise AuditError("network_error", type(exc).__name__) from exc
        finally:
            response.close()
        charset = response.encoding or response.apparent_encoding or "utf-8"
        return b"".join(chunks).decode(charset, errors="replace")


def discover_mirror(transport: PublicSession, mode: str) -> tuple[list[Entry], dict]:
    entries: list[Entry] = []
    report: dict = {"status": "unknown", "pages": [], "advertised_count": None}
    pages = [3] if mode == "pilot" else list(range(1, MAX_INDEX_PAGES + 1))
    seen: set[str] = set()
    for number in pages:
        url = f"https://{MIRROR_HOST}/{MIRROR_ID}_{number}/"
        try:
            html = transport.html(url, MIRROR_HOST)
            rows, claimed = parse_mirror_page(html, page=number)
        except AuditError as exc:
            report["pages"].append({"number": number, "state": exc.code, "details": str(exc)[:160]})
            report["status"] = "blocked_or_partial"
            break
        report["pages"].append({"number": number, "state": "ok", "entries": len(rows)})
        if claimed is not None:
            if report["advertised_count"] not in (None, claimed):
                report["status"] = "conflicting_total"
                break
            report["advertised_count"] = claimed
        for row in rows:
            if row.url in seen:
                report["status"] = "duplicate_url"
                report["duplicate_url_detected"] = row.url
                break
            seen.add(row.url)
            entries.append(row)
        if report["status"] in ("duplicate_url", "conflicting_total"):
            break
        if mode == "full" and report["advertised_count"] is not None:
            expected_pages = (report["advertised_count"] + 49) // 50
            if expected_pages > MAX_INDEX_PAGES:
                report["status"] = "too_many_pages"
                break
            if number >= expected_pages:
                break
    numbered = number_entries(entries)
    report["entries_found"] = len(numbered)
    report["complete"] = (mode == "full" and report["advertised_count"] is not None
                          and report["advertised_count"] == len(numbered)
                          and report["status"] not in ("blocked_or_partial", "duplicate_url", "conflicting_total", "too_many_pages"))
    if report["status"] == "unknown":
        report["status"] = "complete" if report["complete"] else "pilot_partial"
    return numbered, report


def discover_publisher(transport: PublicSession) -> tuple[list[Entry], dict]:
    try:
        html = transport.html(PUBLISHER_INDEX, PUBLISHER_HOST)
        entries = number_entries(parse_publisher_page(html))
        diagnostics = publisher_dom_diagnostics(html)
    except AuditError as exc:
        return [], {"status": exc.code, "details": str(exc)[:160], "complete": False}
    # The publisher may paginate or dynamically load chapter list. Never
    # claim complete with a partial embedded DOM even when titles are present.
    complete = (len(entries) == EXPECTED_PUBLISHER_INDEX_COUNT and
                diagnostics["declared_chapter_count"] == EXPECTED_PUBLISHER_INDEX_COUNT)
    return entries, {"status": "complete" if complete else "partial_or_dynamic",
                     "entries_found": len(entries), "complete": complete,
                     "dom_diagnostics": diagnostics}


def browser_audit(entries: list[Entry], transport: PublicSession,
                  *, max_failures: int = 3) -> list[dict]:
    out: list[dict] = []
    if not entries:
        return out
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return [{"state": "playwright_unavailable"}]
    executable = shutil.which("google-chrome") or shutil.which("chromium")
    if not executable:
        return [{"state": "chrome_unavailable"}]
    failures = 0
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, executable_path=executable,
                                     args=["--no-sandbox", "--disable-dev-shm-usage"])
        context = browser.new_context(locale="zh-CN")
        page = context.new_page()
        try:
            for e in entries:
                item = {"position": e.position, "index_title": e.title,
                        "index_page": e.page, "url": e.url}
                try:
                    transport.check_allowed(e.url, MIRROR_HOST, chapter=True)
                    transport._pace(MIRROR_HOST)
                    response = page.goto(e.url, wait_until="domcontentloaded", timeout=28000)
                    status = response.status if response else None
                    item["http_status"] = status
                    if status in (401, 402, 403, 429, 451, 503):
                        item["state"] = "blocked"
                    elif status != 200:
                        item["state"] = "http_error"
                    else:
                        validate_url(page.url, MIRROR_HOST, chapter=True)
                        if page.url != e.url:
                            raise AuditError("unexpected_redirect", "Unexpected chapter URL")
                        page.wait_for_timeout(1000)
                        item.update(inspect_body(page.content(), e))
                except AuditError as exc:
                    item.update(state=exc.code, details=str(exc)[:160])
                except Exception as exc:
                    item.update(state="navigation_error", error_type=type(exc).__name__)
                out.append(item)
                print(f"Mirror index position {e.position}: {item['state']}", flush=True)
                if item["state"] in ("challenge", "blocked", "robots_disallow", "robots_unavailable"):
                    break
                if item["state"] != "readable":
                    failures += 1
                    if failures >= max_failures:
                        break
        finally:
            context.close()
            browser.close()
    return out


def run(mode: str, delay: float, *, skip_browser: bool = False,
        session: requests.Session | None = None) -> dict:
    report: dict = {
        "schema_version": 1, "book_cn": BOOK_TITLE, "author": BOOK_AUTHOR,
        "checked_utc": datetime.now(timezone.utc).isoformat(), "mode": mode,
        "source_policy": "metadata only, robots-aware, no authentication or bypass",
        "raw_text_collected": False,
        "publisher_url": PUBLISHER_INDEX, "mirror_url": MIRROR_PAGE_3,
    }
    transport = PublicSession(delay=delay, session=session)
    mirror_entries, mr = discover_mirror(transport, mode)
    pub_entries, pr = discover_publisher(transport)
    report["mirror"] = mr
    report["publisher"] = pr
    report["comparison"] = compare_indices(pub_entries, mirror_entries,
                    publisher_complete=pr.get("complete", False),
                    mirror_complete=mr.get("complete", False))
    report["catalog"] = {
        "mirror": [asdict(e) for e in mirror_entries],
        "publisher": [asdict(e) for e in pub_entries],
    }
    selected = sample_entries(mirror_entries, mode)
    report["samples_requested"] = len(selected)
    report["samples"] = [] if skip_browser else browser_audit(
        selected, transport, max_failures=(len(selected) if mode == "full" else 3))
    # Preserve publisher volume/access metadata in chapter receipts. Never
    # claim that readable mirror text is licensed or equivalent to VIP source.
    if pr.get("complete") and mr.get("complete"):
        p_keys = [comparison_key(e.title) for e in pub_entries]
        m_keys = [comparison_key(e.title) for e in mirror_entries]
        for match in difflib.SequenceMatcher(None, p_keys, m_keys, autojunk=False).get_matching_blocks():
            for offset in range(match.size):
                item_pos = match.b + offset + 1
                sample = next((x for x in report["samples"] if x.get("position") == item_pos), None)
                if sample is not None:
                    volume = pub_entries[match.a + offset].volume
                    sample["publisher_volume"] = volume
                    sample["publisher_access"] = ("vip" if "VIP" in volume else
                                                   "free" if "免费" in volume else "unknown")
    report["sampled_readable"] = sum(x.get("state") == "readable" for x in report["samples"])
    report["samples_inspected"] = len(report["samples"])
    report["sampled_short"] = sum(x.get("state") == "too_short" for x in report["samples"])
    if skip_browser:
        report["status"] = "catalog_only"
    elif mr.get("status") in ("blocked_or_partial", "duplicate_url", "conflicting_total", "too_many_pages"):
        report["status"] = "incomplete"
    elif report["sampled_readable"] != len(selected) or not selected:
        report["status"] = "sample_incomplete"
    elif mode == "full" and not mr.get("complete"):
        report["status"] = "catalog_incomplete"
    elif not pr.get("complete"):
        report["status"] = "publisher_unverified"
    else:
        report["status"] = "metadata_check_pass"
    return report


def save(report: dict, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# Bleach source availability audit", "",
             "- **Metadata only. No novel chapter prose stored or published.**",
             f"- Status: **{report['status']}**",
             f"- Mirror catalog: {report['mirror']['entries_found']} entries, "
             f"complete={report['mirror']['complete']}",
             f"- Publisher: {report['publisher'].get('entries_found', 0)} entries, "
             f"state={report['publisher']['status']}",
             f"- Index comparison: {report['comparison']['status']}",
             f"- Story sequences identical: {report['comparison'].get('story_sequences_identical', 'not verified')}",
             f"- Additional mirror administrative entries: {report['comparison'].get('extra_auxiliary_entries', 'not verified')}",
             f"- Sampled chapters verified: {report['sampled_readable']}/{report['samples_requested']} requested ({report['samples_inspected']} inspected; {report['sampled_short']} short)",
             "- A discovered link or book completion label does **not** establish full RAW availability.",
             ""]
    for item in report["samples"]:
        lines.append(f"- Sample {item.get('position', '?')}: {item['state']}, "
                     f"{item.get('cjk_chars', 0)} CJK; {item.get('url', '')}")
    (out / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mode", choices=("pilot", "full"), default="pilot")
    p.add_argument("--delay", type=float, default=2.0)
    p.add_argument("--skip-browser", action="store_true", help="Catalog metadata only")
    p.add_argument("--out", type=Path, default=Path("out/bleach-source-audit"))
    args = p.parse_args()
    if args.delay < 1.5:
        p.error("Requests must be spaced by at least 1.5 seconds")
    report = run(args.mode, args.delay, skip_browser=args.skip_browser)
    save(report, args.out)
    print(json.dumps({"state": report["status"],
                      "mirror_entries": report["mirror"]["entries_found"],
                      "publisher_state": report["publisher"]["status"],
                      "samples": [report["sampled_readable"], report["samples_requested"]]},
                     ensure_ascii=False))
    return 0 if report["status"] in ("metadata_check_pass", "catalog_only", "publisher_unverified") else 2


if __name__ == "__main__":
    raise SystemExit(main())
