import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import sys
file=Path(__file__).with_name("kakuyomu_ingest.py")
spec=importlib.util.spec_from_file_location("kakuyomu_ingest",file)
mod=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=mod
spec.loader.exec_module(mod)

def catalog(count=2):
    state={
      "Work:1234567890":{"title":"Test","publicEpisodeCount":count,
                          "tableOfContentsV2":[{"__ref":"TOC:1"}]},
      "TOC:1":{"chapter":{"__ref":"Section:1"},
               "episodeUnions":[{"__ref":"Episode:1"},{"__ref":"Episode:2"}]},
      "Section:1":{"title":"Part I"},
      "Episode:1":{"id":"101","title":"First"},
      "Episode:2":{"id":"202","title":"Second"}}
    return '<script id="__NEXT_DATA__">'+json.dumps({"props":{"pageProps":{"__APOLLO_STATE__":state}}})+'</script>'

class Response:
    headers={"content-type":"text/html; charset=utf-8"}
    def __init__(self,text,status_code=200):
        self.text=text
        self.status_code=status_code

class Session:
    def __init__(self,duplicate=False,block=False):
        self.headers={}
        self.duplicate=duplicate
        self.block=block
    def get(self,url,**kw):
        if "/episodes/" not in url:return Response(catalog())
        if url.endswith("/202") and self.block:return Response("denied",403)
        body="identical" if self.duplicate else url
        return Response('<div class="widget-episodeBody"><p>'+body*10+'</p></div>')

class Tests(unittest.TestCase):
    def setUp(self):
        self.book={"work_id":"1234567890","directory":"test","expected_episodes":2}
    def test_toc(self):
        m,rows=mod.parse_toc(catalog(),"1234567890")
        self.assertEqual(len(rows),2)
        self.assertEqual(rows[1]["section"],"Part I")
    def test_count_mismatch(self):
        with self.assertRaises(mod.IngestError):mod.parse_toc(catalog(3),"1234567890")
    def test_body_ruby(self):
        text=mod.parse_body('<div class="widget-episodeBody"><p>日<ruby>本<rt>ほん</rt></ruby></p></div>')
        self.assertEqual(text,"日本")
    def test_full(self):
        with tempfile.TemporaryDirectory() as d,patch.object(mod.time,"sleep"):
            res=mod.collect(self.book,Path(d),session=Session(),min_chars=1)
            self.assertTrue(res["complete"])
            self.assertTrue((Path(d)/"test/full_book.txt").exists())
    def test_duplicate(self):
        with tempfile.TemporaryDirectory() as d,patch.object(mod.time,"sleep"):
            res=mod.collect(self.book,Path(d),session=Session(duplicate=True),min_chars=1)
            self.assertFalse(res["complete"])
            self.assertFalse((Path(d)/"test/full_book.txt").exists())
    def test_access_block(self):
        with tempfile.TemporaryDirectory() as d,patch.object(mod.time,"sleep"):
            res=mod.collect(self.book,Path(d),session=Session(block=True),min_chars=1)
            self.assertEqual(res["failed"],1)
            self.assertFalse(res["complete"])
    def test_truncated(self):
        self.book["expected_episodes"]=3
        with tempfile.TemporaryDirectory() as d,patch.object(mod.time,"sleep"):
            res=mod.collect(self.book,Path(d),session=Session(),min_chars=1)
            self.assertFalse(res["complete"])

if __name__=="__main__":unittest.main()
