"""Offline regression tests: preserve chapter splits and avoid false complete."""
import pathlib
import sys
import unittest

ROOT=pathlib.Path(__file__).parent
sys.path.insert(0,str(ROOT))
import masked_knight_tianyabooks_collect as mod


class TianyaCollectionTests(unittest.TestCase):
    def test_catalog_all_329_plus_conflicts(self):
        html="<h1>变脸武士</h1>"+''.join(
            f'<a href="{60000+i}.html">第{i}章 标题</a>' for i in range(1,331) if i!=241)
        html+='<a href="60500.html">第159章 不同版本</a>'
        obj=mod.catalog(html)
        self.assertEqual(obj["indexed_ordinals"],329)
        self.assertEqual(obj["index_unique_pages"],330)
        self.assertEqual(obj["missing_ordinals"],[241])
        self.assertEqual(len(obj["multiple_pages"]["159"]),2)

    def test_long_story_extraction(self):
        html=('<html><h1>宫廷卷 第两百章 针锋相对</h1>'
              '<div id="main"><div><a>上一章</a></div>'
              '<p>'+'罗迪看见了骑士挥舞长剑。'*150+'</p>'
              '<p><a>下一章</a></p></div></html>')
        obj=mod.parse_story(html,200)
        self.assertEqual(obj["status"],"long_candidate")
        self.assertGreater(obj["cjk"],1200)
        self.assertNotIn("上一章",obj["text"])
        self.assertNotIn("下一章",obj["text"])

    def test_short_unverified(self):
        html='<h1>第两百章</h1><div id="main">'+'少年朝前走。'*60+'</div>'
        self.assertEqual(mod.parse_story(html,200)["status"],"needs_review")

    def test_wrong_heading(self):
        html='<h1>第两百章</h1><div id="main">'+'罗迪看见骑士。'*300+'</div>'
        self.assertEqual(mod.parse_story(html,201)["status"],"wrong_heading")

    def test_access_page(self):
        html='<title>Just a moment</title><div id="main">请登录</div>'
        self.assertEqual(mod.parse_story(html,240)["status"],"access_page")


if __name__=="__main__":
    unittest.main()
