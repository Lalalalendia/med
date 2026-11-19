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


    def test_biquge_full_chapter_container(self):
        prose="史莱姆真仙进入城墙，精灵和骑士共同迎战。"*170
        page=("<html><h1>第219章 战争开启</h1><main>"
              '<div class="bookname">第219章 战争开启</div>'
              '<div id="chaptercontent"><p>'+prose+'</p></div>'
              '<div class="recommend">无关书籍推荐</div></main></html>')
        text=mod.parse_prose(page,219,"战争开启",minimum=1300)
        self.assertEqual(text,prose)
        self.assertNotIn("无关书籍推荐",text)


    def test_sudugu_pagination_joins_four_parts_without_navigation(self):
        import requests
        from unittest.mock import patch
        src=mod.Source("sudugu","https://www.sudugu520.com/978/","978",
                       requests.Session())
        root="https://www.sudugu520.com/978/1116259"
        pages={}
        for part in range(1,5):
            uri=root+("" if part==1 else f"-{part}")+".html"
            next_anchor=(f'<a href="1116259-{part+1}.html">下一页</a>'
                         if part<4 else "")
            prose=("史莱姆与骑士在森林里研究魔法。"*130) + str(part)
            pages[uri]=(f'<div class="container"><p>设置</p>'
                        f'<p>第450章 工业城市雏形</p><p>{prose}</p>'
                        f'<p>目录</p>{next_anchor}</div>')
        def fake_fetch(uri, source):
            if uri not in pages:
                raise AssertionError("unexpected URL "+uri)
            return pages[uri]
        with patch.object(mod,"fetch_html",side_effect=fake_fetch), \
             patch.object(mod.time,"sleep",return_value=None):
            body,parts=mod.paginated_sudugu_prose(
                src,root+".html",450,"工业城市雏形",minimum=2500)
        self.assertEqual(parts,4)
        self.assertGreater(mod.cjk(body),2500)
        self.assertNotIn("下一页",body)
        self.assertNotIn("目录",body)
        self.assertNotIn("设置",body)

    def test_sudugu_page_scope_rejects_adjacent_chapter(self):
        first="https://www.sudugu520.com/978/1116259.html"
        self.assertTrue(mod.exact_sudugu_part(
            first,"https://www.sudugu520.com/978/1116259-2.html",2))
        self.assertFalse(mod.exact_sudugu_part(
            first,"https://www.sudugu520.com/978/1116260.html",2))
        self.assertFalse(mod.exact_sudugu_part(
            first,"https://evil.example/978/1116259-2.html",2))
        self.assertFalse(mod.exact_sudugu_part(
            first,"https://www.sudugu520.com/978/1116259-3.html",2))

    def test_sudugu_wrong_chapter_title_is_rejected(self):
        html=('<div class="container"><p>第451章 另一个标题</p>'
              '<p>'+('魔法森林正在复苏。'*180)+'</p></div>')
        with self.assertRaisesRegex(ValueError,"number/title mismatch"):
            mod.sudugu_part(html,450,"工业城市雏形")

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
            with ZipFile(Path(a.out)/"slime_220-544_cn.zip") as z:
                self.assertEqual(len([x for x in z.namelist() if x.startswith("chapters/")]),1)
                self.assertIsNone(z.testzip())

if __name__=="__main__":
    unittest.main()
