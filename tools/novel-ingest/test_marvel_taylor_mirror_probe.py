"""Offline regressions for source-probe access checks."""
import importlib.util
import sys
import unittest
from pathlib import Path

spec=importlib.util.spec_from_file_location("mirror_probe",Path(__file__).with_name("marvel_taylor_mirror_probe.py"))
m=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=m
spec.loader.exec_module(m)


class Response:
    def __init__(self, text, status=200):
        self.text=text
        self.status_code=status
        self.headers={"Content-Type":"text/html; charset=utf-8"}
        self.encoding="utf-8"


class Session:
    def __init__(self, robots, page, chapter):
        self.texts=(robots,page,chapter)
        self.calls=[]
        self.headers={}
    def get(self,url,**kwargs):
        self.calls.append(url)
        index=0 if url.endswith("/robots.txt") else 2 if url.endswith("test.html") else 1
        return Response(self.texts[index])


class Tests(unittest.TestCase):
    def test_host_restrictions(self):
        self.assertTrue(m.same_host("https://m.abbshu.net/book/1/","https://m.abbshu.net/book/1/2.html"))
        self.assertFalse(m.same_host("https://m.abbshu.net/book/1/","https://m.abbshu.net.evil/1/"))
        self.assertFalse(m.same_host("https://m.abbshu.net/book/1/","http://m.abbshu.net/1/"))

    def test_allowed_catalog_and_chapter(self):
        source="https://m.abbshu.net/book/309042/"
        s=Session("User-agent: *\nAllow: /\n",
                  '<title>漫威</title><a href="test.html">第1章 开端</a>',
                  '<div id="content">'+"这是故事的开端。"*30+'</div>')
        result=m.probe(s,"abbshu",source)
        self.assertEqual(result["status"],"ok")
        self.assertEqual(result["chapter_link_count"],1)
        self.assertEqual(result["sample"]["status"],"ok")
        self.assertGreater(result["sample"]["containers"][0]["han"],80)

    def test_disallowed_catalog_not_requested(self):
        source="https://cn.zhys.tw/book/2268838.html"
        s=Session("User-agent: *\nDisallow: /\n","<h1>secret</h1>","")
        result=m.probe(s,"zhys",source)
        self.assertEqual(result["status"],"robots_disallow")
        self.assertEqual(len(s.calls),1)


if __name__=="__main__":
    unittest.main()
