"""17K public HTML adapter: strict same-book chapter identity and body validation."""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

HOST = "www.17k.com"
CHAPTER_RE = re.compile(r"^/chapter/(\d+)/(\d+)\.html$")
CATALOG_RE = re.compile(r"^/list/(\d+)\.html$")
BLOCK_MARKERS = ("验证码", "人机验证", "请先登录", "登录后阅读", "本章为VIP",
                 "购买本章", "订阅本章", "access denied", "captcha",
                 "verify you are human", "just a moment")
CONTENT_SELECTORS = (".readArea .readAreaBox.content .p",
                     ".readAreaBox.content .p", ".readAreaBox .p",
                     ".readArea .p", "#chapterContent", ".chapter-content")
HAN_RE = re.compile(r"[\u3400-\u9fff]")


class SourceError(Exception):
    def __init__(self, status: str, message: str):
        self.status = status
        super().__init__(message)


@dataclass(frozen=True)
class Chapter:
    ordinal: int
    chapter_id: str
    title: str
    volume: str
    url: str
    kind: str


def safe_url(url: str, book_id: str, *, allow_catalog: bool = False) -> str:
    p = urlsplit(url)
    if (p.scheme != "https" or p.hostname != HOST or p.username
            or p.password or p.port not in (None, 443) or p.query or p.fragment):
        raise SourceError("unsafe_url", url)
    m = CHAPTER_RE.fullmatch(p.path)
    if m and m.group(1) == book_id:
        return url
    if allow_catalog and p.path == f"/list/{book_id}.html":
        return url
    raise SourceError("unsafe_url", url)


def catalog_url(book_id: str) -> str:
    if not re.fullmatch(r"[1-9]\d{1,11}", book_id):
        raise ValueError("Invalid 17K book id")
    return f"https://{HOST}/list/{book_id}.html"


def parse_catalog(html: str, book_id: str) -> list[Chapter]:
    soup = BeautifulSoup(html, "html.parser")
    volumes = soup.select("dl.Volume, dl.volume")
    if not volumes:
        raise SourceError("catalog_missing", "No 17K Volume blocks found")
    result = []
    seen = set()
    for volume in volumes:
        header = volume.find("dt")
        volume_name = header.get_text(" ", strip=True) if header else "Unlabelled"
        first_entry = len(result)
        for a in volume.select("dd a[href]"):
            url = urljoin(catalog_url(book_id), a["href"])
            try:
                safe_url(url, book_id)
            except SourceError:
                continue
            chapter_id = CHAPTER_RE.fullmatch(urlsplit(url).path).group(2)
            if chapter_id in seen:
                continue
            title = re.sub(r"\s+", " ", a.get_text(" ", strip=True)).strip()
            if not title:
                raise SourceError("catalog_invalid", f"Missing chapter title: {url}")
            seen.add(chapter_id)
            is_note = ("作品相关" in volume_name or "感言" in title or "通知" in title
                       or "请假" in title or "断更" in title or "减更" in title)
            result.append(Chapter(len(result) + 1, chapter_id, title,
                                  volume_name, url, "note" if is_note else "story"))
        declared = re.search(r"已更新\s*(\d+)\s*章", volume_name)
        if declared and len(result) - first_entry != int(declared.group(1)):
            raise SourceError("catalog_incomplete",
                              f"{volume_name}: found {len(result) - first_entry} chapter links")
    if not result:
        raise SourceError("catalog_missing", "No matching 17K chapter links")
    return result


def normalize_body(value: str) -> str:
    lines = [re.sub(r"[\t \u00a0\u3000]+", " ", line).strip()
             for line in value.replace("\r", "").split("\n")]
    out = []
    for line in lines:
        if not line:
            if out and out[-1]:
                out.append("")
        else:
            out.append(line)
    return "\n".join(out).strip()


def parse_chapter(html: str, chapter: Chapter) -> str:
    soup = BeautifulSoup(html, "html.parser")
    text_head = soup.get_text(" ", strip=True)[:1200].lower()
    if any(marker.lower() in text_head for marker in BLOCK_MARKERS):
        raise SourceError("blocked", "Challenge or restricted chapter page")
    element = next((soup.select_one(css) for css in CONTENT_SELECTORS
                    if soup.select_one(css)), None)
    if element is None:
        raise SourceError("missing_body", f"No supported 17K content container: {chapter.url}")
    for junk in element.select("script,style,iframe,noscript,nav,header,footer,"
                               "form,button,.ad,.ads,.advert,.read_bottom"):
        junk.decompose()
    body = normalize_body(element.get_text("\n", strip=True))
    count = len(HAN_RE.findall(body))
    threshold = 35 if chapter.kind == "note" else 180
    if count < threshold or count < len(body) * 0.35:
        raise SourceError("invalid_body", f"Too little Chinese chapter text: {count}")
    if any(marker.lower() in body[:700].lower() for marker in BLOCK_MARKERS):
        raise SourceError("blocked", "Restricted content in chapter body")
    return body


def fetch_html(session: requests.Session, url: str, book_id: str,
               *, allow_catalog: bool = False, retries: int = 3) -> str:
    safe_url(url, book_id, allow_catalog=allow_catalog)
    for attempt in range(retries):
        try:
            response = session.get(url, timeout=30, allow_redirects=False)
        except (requests.ConnectionError, requests.Timeout) as exc:
            if attempt == retries - 1:
                raise SourceError("network_error", str(exc)) from exc
            time.sleep(3 * 2 ** attempt)
            continue
        if response.status_code in (429, 500, 502, 503, 504) and attempt < retries - 1:
            time.sleep(min(30, 5 * 2 ** attempt))
            continue
        if response.status_code in (401, 402, 403, 429, 451) or 300 <= response.status_code < 400:
            raise SourceError("blocked", f"HTTP {response.status_code}: {url}")
        if response.status_code != 200:
            raise SourceError("http_error", f"HTTP {response.status_code}: {url}")
        if "html" not in response.headers.get("content-type", "").lower():
            raise SourceError("invalid_response", "Expected HTML")
        if len(response.content) > 5_000_000:
            raise SourceError("invalid_response", "Oversize HTML")
        return str(BeautifulSoup(response.content, "html.parser"))
    raise AssertionError("unreachable")
