#!/usr/bin/env python3
import importlib.util
from pathlib import Path
import sys
import unittest

p=Path(__file__).with_name("slime_paginated_source_probe.py")
spec=importlib.util.spec_from_file_location("slime_paginated_source_probe",p)
m=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=m
spec.loader.exec_module(m)

class MetadataTests(unittest.TestCase):
    def test_scope(self):
        s=m.SITES[0]
        self.assertTrue(m.scoped("https://www.znwx.cc/114/114150/1.html",s))
        self.assertFalse(m.scoped("http://www.znwx.cc/114/114150/1.html",s))
        self.assertFalse(m.scoped("https://www.znwx.cc/114/else/1.html",s))
        self.assertFalse(m.scoped("https://evil.example/114/114150/1.html",s))
    def test_catalog_titles(self):
        s=m.SITES[0]
        html=('<a href="/114/114150/43.html">第449章 银霜仙子</a>'
              '<a href="/114/114150/44.html">第450章 工业城市雏形</a>')
        self.assertEqual(sorted(m.entries(s,html)),[449,450])
    def test_detect_pagination_and_body_without_nav(self):
        html=('<div id="content">'+('天空充满光芒。'*360)+'</div>'
              '<nav><a href="abc-2.html">下一页</a></nav>')
        size, selector, next_rel=m.content_diagnostic(html)
        self.assertGreater(size,2500)
        self.assertEqual(selector,"#content")
        self.assertEqual(next_rel,"abc-2.html")

if __name__=="__main__":
    unittest.main()
