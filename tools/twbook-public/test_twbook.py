from pathlib import Path
import importlib.util
import sys

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("tw", HERE / "fetch_twbook.py")
tw = importlib.util.module_from_spec(SPEC)
sys.modules["tw"] = tw
SPEC.loader.exec_module(tw)


def test_decode_bootstrap():
    mapping = tw.load_mapping(HERE / "mapping.json")
    decoded, substitutions, unknown = tw.decode_text("놖놊知道놛놅名字", mapping)
    assert decoded == "我不知道他的名字"
    assert substitutions == 4
    assert not unknown


def test_unknown_fails_closed():
    decoded, _, unknown = tw.decode_text("甲갗乙", {})
    assert decoded == "甲갗乙"
    assert unknown["갗"] == 1


def test_catalog_extracts_chapter_roots():
    html = """<div class="chaplist"><ul></ul><ul>
      <li><a href="/0912500831/1.html">第1章 A</a></li>
      <li><a href="/0912500831/2.html">第2章 B</a></li>
      <li><a href="/0912500831/8096_1_2.html">part</a></li>
    </ul></div>"""
    got = tw.extract_catalog(html, "https://www.twbook.cc/0912500831/dir")
    assert [x[0] for x in got] == [
        "https://www.twbook.cc/0912500831/1.html",
        "https://www.twbook.cc/0912500831/2.html",
    ]


def test_extract_content_removes_ads_and_notice():
    html = """<div class="chapter-content"><h1>第1章 測試</h1><div class="content">
      <p>第一段놅正文。</p><div class="adBlock">廣告</div>
      <p><span style="color:#ff6666">溫馨提示:</span> 廣告提示</p>
      <p>第二段正文。</p></div></div>"""
    mapping = tw.load_mapping(HERE / "mapping.json")
    decoded, _, _ = tw.decode_text(html, mapping)
    soup = tw.soup_from_html(decoded)
    text = tw.extract_content(soup)
    assert "第一段的正文" in text
    assert "第二段正文" in text
    assert "廣告" not in text
    assert "溫馨提示" not in text


def test_next_part_url():
    html = """<div class="foot-nav">
      <a href="/0220699805/8095_1.html">上一章</a>
      <a href="/0220699805/dir">目錄</a>
      <a href="/0220699805/8096_1_2.html">下一章</a>
    </div>"""
    soup = tw.soup_from_html(html)
    assert tw.next_part_url(
        soup, "https://www.twbook.cc/0220699805/8096_1.html"
    ) == "https://www.twbook.cc/0220699805/8096_1_2.html"


def test_html_entity_is_decoded_after_dom_extraction():
    mapping = tw.load_mapping(HERE / "mapping.json")
    soup = tw.soup_from_html(
        '<div class="chapter-content"><div class="content"><p>這是測試&#45445;正文。</p></div></div>'
    )
    raw = tw.extract_content(soup)
    assert "놅" in raw
    decoded, substitutions, unknown = tw.decode_text(raw, mapping)
    assert decoded == "這是測試的正文。"
    assert substitutions == 1
    assert not unknown


def test_render_consensus_ignores_global_hangul_identity():
    merged, resolved, unknown = tw.merge_renderings(["甲꾊乙", "甲支乙"])
    assert merged == "甲支乙"
    assert resolved == 1
    assert not unknown

    # The same Hangul codepoint may represent a different character in another
    # response pair. Consensus is positional, not dictionary-based.
    merged, resolved, unknown = tw.merge_renderings(["甲꾊乙", "甲根乙"])
    assert merged == "甲根乙"
    assert resolved == 1
    assert not unknown


def test_render_consensus_fails_closed_if_every_render_is_masked():
    merged, resolved, unknown = tw.merge_renderings(["甲꾊乙", "甲껦乙"])
    assert merged[0] == "甲"
    assert merged[-1] == "乙"
    assert resolved == 0
    assert sum(unknown.values()) == 1


def test_catalog_sorts_by_url_when_titles_are_blank():
    html = """<div class="chaplist">
      <a href="/0912500831/3.html">第3章 C</a>
      <a href="/0912500831/1.html">第1章 A</a>
      <a href="/0912500831/2.html">第2章</a>
    </div>"""
    got = tw.extract_catalog(html, "https://www.twbook.cc/0912500831/dir")
    assert [x[0].rsplit("/", 1)[-1] for x in got] == ["1.html", "2.html", "3.html"]


def test_short_placeholder_is_not_plausible_body():
    assert not tw.body_is_plausible("本章內容暫時無法顯示，請稍後再試。")
    assert tw.body_is_plausible("正文" * 200)



def test_ilwxs_catalog_page_url():
    assert tw.ilwxs_catalog_page_url(1) == "https://m.ilwxs.com/shu/307344/"
    assert tw.ilwxs_catalog_page_url(51) == "https://m.ilwxs.com/shu/307344_2/"
    assert tw.ilwxs_catalog_page_url(382) == "https://m.ilwxs.com/shu/307344_8/"


def test_extract_ilwxs_content():
    html = """<div class="content"><p>第一段正文。</p><script>bad()</script><p>第二段正文。</p></div>"""
    text = tw.extract_ilwxs_content(tw.soup_from_html(html))
    assert "第一段正文" in text
    assert "第二段正文" in text
    assert "bad()" not in text


def test_resolve_ilwxs_chapter_url(monkeypatch):
    class FakeResponse:
        status_code = 200
        url = "https://m.ilwxs.com/shu/307344_5/"

    html = """<a href="/shu/307344/177494083.html">第232章 可怜的弗莱迪</a>"""

    def fake_fetch_html(session, url, timeout, **kwargs):
        return FakeResponse(), html

    monkeypatch.setattr(tw, "fetch_html", fake_fetch_html)
    got = tw.resolve_ilwxs_chapter_url(object(), 232, 20)
    assert got == (
        "https://m.ilwxs.com/shu/307344/177494083.html",
        "第232章 可怜的弗莱迪",
    )
