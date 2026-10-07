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
