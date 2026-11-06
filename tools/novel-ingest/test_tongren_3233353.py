#!/usr/bin/env python3
"""Offline coverage for short legitimate pages, multipart checks, and safe URLs."""
import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from bs4 import BeautifulSoup

HERE=Path(__file__).resolve().parent
spec=spec_from_file_location("tongren",HERE/"tongren_3233353.py")
mod=module_from_spec(spec)
spec.loader.exec_module(mod)


def page(n,part,total,text,next_part=None):
    extra=("<a href='?page=%d'>下一頁</a>" % next_part) if next_part else ""
    source="<html><head><title>第%d節-基金會第%d章(%d/%d)-同人小說</title></head><body><div id='content'>%s</div>%s</body></html>" % (n,n,part,total,text,extra)
    return BeautifulSoup(source,"html.parser")


class TongrenTests(unittest.TestCase):
    def test_short_final_page_is_accepted(self):
        url=mod.ROOT+"/c/18848634?page=4"
        tiny="本章終。" * 8
        text,next_url=mod.split_page(page(1,4,4,tiny),url)
        self.assertEqual(text,tiny)
        self.assertIsNone(next_url)

    def test_short_next_page_not_accepted_as_complete(self):
        url=mod.ROOT+"/c/18848634?page=2"
        with self.assertRaisesRegex(ValueError,"Missing continuation"):
            mod.split_page(page(1,2,4,"正文內容"*50),url)

    def test_page_continuation(self):
        url=mod.ROOT+"/c/18848634"
        text,next_url=mod.split_page(page(1,1,4,"小說正文"*50,2),url)
        self.assertGreater(len(text),50)
        self.assertEqual(next_url,url+"?page=2")

    def test_wrong_pagination_declared(self):
        url=mod.ROOT+"/c/18848634?page=2"
        with self.assertRaisesRegex(ValueError,"Invalid multipart"):
            mod.split_page(page(1,1,4,"小說正文"*50,3),url)

    def test_block_outside_source(self):
        with self.assertRaisesRegex(ValueError,"Unsafe external"):
            mod.checked("https://example.com/b/3233353/c/1")

    def test_block_other_book(self):
        with self.assertRaisesRegex(ValueError,"Unrecognized book path"):
            mod.checked("https://m.tongrenxiaoshuo.com/b/99999/c/1")

    def test_block_unknown_query(self):
        with self.assertRaisesRegex(ValueError,"Unexpected query"):
            mod.checked(mod.ROOT+"/c/18848634?download=true")


if __name__=="__main__":
    unittest.main()
