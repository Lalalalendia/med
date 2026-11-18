#!/usr/bin/env python3
import importlib.util
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile
import json

path=Path(__file__).with_name("slime_true_immortal.py")
spec=importlib.util.spec_from_file_location("slime_true_immortal",path)
mod=importlib.util.module_from_spec(spec)
import sys
sys.modules[spec.name]=mod
spec.loader.exec_module(mod)

class SlimeCollectorTest(unittest.TestCase):
    def source(self):
        import requests
        return mod.Source("kanqun","https://www.kanqun.com/114/114159/","114159",requests.Session())

    def test_anchor_offsets(self):
        s=self.source()
        markup="""<a href="/114/114159/218.html">第218章 惊人谋划</a>
        <a href="/114/114159/219.html">第219章 战争开启</a>
        <a href="/114/114159/220.html">第220章 艰难的推进</a>"""
        entries,pages=mod.parse_index(markup,s.index,s)
        self.assertEqual(entries[218][1],"惊人谋划")
        self.assertEqual(entries[219][1],"战争开启")
        self.assertFalse(pages)

    def test_strict_url_scope(self):
        s=self.source()
        self.assertTrue(mod.allowed_url("https://www.kanqun.com/114/114159/219.html",s))
        self.assertFalse(mod.allowed_url("http://www.kanqun.com/114/114159/219.html",s))
        self.assertFalse(mod.allowed_url("https://evil.example/114/114159/219.html",s))
        self.assertFalse(mod.allowed_url("https://www.kanqun.com/1111/other/",s))

    def test_clean_prose(self):
        content="陈屿抬头望去，史莱姆出现在城墙下。"*30
        html=f'<html><h1>第219章 战争开启</h1><div id="content"><p>第219章 战争开启</p><p>{content}</p><nav>下一章</nav></div></html>'
        text=mod.parse_prose(html,219,"战争开启",minimum=100)
        self.assertIn("陈屿抬头",text)
        self.assertNotIn("下一章",text)

    def test_reject_wrong_heading(self):
        html='<h1>第220章 错误</h1><div id="content">'+("这是正文内容。"*100)+'</div>'
        with self.assertRaisesRegex(ValueError,"heading mismatch"):
            mod.parse_prose(html,219,"战争开启",minimum=100)

    def test_merge_detects_missing(self):
        with tempfile.TemporaryDirectory() as td:
            inp=Path(td)/"inputs";shard=inp/"part";shard.mkdir(parents=True)
            (shard/"raw").mkdir()
            data="=== 第220章 战争开启 ===\n\n"+"正文。"*200
            (shard/"raw/0220.txt").write_text(data,encoding="utf-8")
            import hashlib
            digest=hashlib.sha256(data.encode("utf-8")).hexdigest()
            manifest={"chapters":[{"local_number":220,"file":"raw/0220.txt",
                                   "status":"ok","sha256":digest}]}
            (shard/"manifest.json").write_text(json.dumps(manifest),encoding="utf-8")
            class Args: pass
            a=Args(); a.rights_confirmed=True; a.inputs=str(inp); a.out=str(Path(td)/"merged")
            self.assertEqual(mod.merge(a),2)
            with ZipFile(Path(a.out)/"slime_220-545_cn.zip") as z:
                self.assertEqual(len([x for x in z.namelist() if x.startswith("chapters/")]),1)
                self.assertIsNone(z.testzip())

if __name__=="__main__":
    unittest.main()
