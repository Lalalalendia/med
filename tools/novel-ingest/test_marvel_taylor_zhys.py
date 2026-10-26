"""Offline tests: complete index, chapter content, blocked pages and receipts."""
from __future__ import annotations
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

sp=importlib.util.spec_from_file_location(
    "marvel_taylor_zhys",Path(__file__).with_name("marvel_taylor_zhys.py"))
m=importlib.util.module_from_spec(sp)
sys.modules[sp.name]=m
sp.loader.exec_module(m)


def catalog(*links):
    return ("<html><title>漫威，谁把他救出来的？！</title>"
            '<section id="full-catalog">'
            + "".join(f'<a href="/read/2268838/{src_id}.html">第{number}章 {name}</a>'
                      for src_id,number,name in links)
            + "</section></html>")


def chapter(text=None):
    text=text or ("泰勒发现了新的事情，接着发生了奇怪的事件。"*28)
    return ('<article><header>目录</header><div class="reading-content">'
            +'<h1>第1章 开端</h1><p>'+text+'</p>'
            +'<nav>上一章 下一章</nav><a href="/book/2268838.html">目录</a>'
            +'</div></article>')


class Resp:
    def __init__(self,content,status=200):
        self.text=content
        self.status_code=status
        self.encoding="utf-8"
        self.headers={"Content-Type":"text/html; charset=utf-8"}


class FakeSession:
    def __init__(self, data, robot="User-agent: *\nAllow: /\n"):
        self.data,self.robot=data,robot
        self.headers={}
    def get(self,url,**kwargs):
        if url.endswith("robots.txt"):
            return Resp(self.robot)
        v=self.data.get(url,("",404))
        return Resp(*v) if isinstance(v,tuple) else Resp(v)


class CollectorTests(unittest.TestCase):
    def test_catalog_keeps_repeated_author_numbers(self):
        entries=m.parse_catalog(catalog((11,1,"一"),(12,306,"二"),(13,307,"三"),(14,306,"四")))
        self.assertEqual([c.ordinal for c in entries],[1,2,3,4])
        self.assertEqual([c.author_number for c in entries],[1,306,307,306])
        self.assertEqual([c.source_id for c in entries],[11,12,13,14])

    def test_catalog_duplicate_id_fails(self):
        with self.assertRaises(m.CollectionError):
            m.parse_catalog(catalog((11,1,"一"),(11,2,"二")))

    def test_url_restricts_book_and_host(self):
        self.assertEqual(m.canon(m.BOOK_URL,catalog=True),m.BOOK_URL)
        for url in ("https://evil.test/read/2268838/1.html",
                    "https://cn.zhys.tw/read/other/11.html",
                    "https://cn.zhys.tw/book/2268838.html#here",
                    "http://cn.zhys.tw/read/2268838/11.html"):
            with self.subTest(url=url), self.assertRaises(m.CollectionError):
                m.canon(url)

    def test_chapter_cleaning_and_quality_gate(self):
        text=m.clean_body(chapter())
        self.assertIn("泰勒发现了新的事情",text)
        self.assertNotIn("上一章",text)
        self.assertNotIn("目录",text)
        with self.assertRaises(m.CollectionError):
            m.clean_body(chapter("短文"),min_han=100)
        with self.assertRaises(m.CollectionError):
            m.clean_body(chapter("놇"+"这是很长的故事。"*40))

    def test_blocked_catalog_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            r=m.collect(out=Path(td)/"out",start=1,end=2,expected=2,
                        session=FakeSession({},robot="User-agent: *\nDisallow: /\n"),
                        sleep=lambda _:None)
            self.assertEqual(r["status"],"BLOCKED")

    def test_two_chapters_manifest_sha_and_output(self):
        source={m.BOOK_URL: catalog((100,1,"开端"),(101,1,"新的开始")),
                "https://cn.zhys.tw/read/2268838/100.html":chapter("第一段故事发生了。"*48),
                "https://cn.zhys.tw/read/2268838/101.html":chapter("第二段故事发生了。"*48)}
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)/"run"
            result=m.collect(out=out,start=1,end=2,expected=2,
                             session=FakeSession(source),sleep=lambda _:None)
            self.assertEqual(result["status"],"PASS")
            self.assertEqual(result["ok_count"],2)
            for c in result["chapters"]:
                f=out/c["file"]
                self.assertEqual(m.sha256(f.read_text(encoding="utf-8")),c["sha256"])


if __name__=="__main__":
    unittest.main()
