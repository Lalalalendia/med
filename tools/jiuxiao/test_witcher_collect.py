import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from sys import path as sys_path

sys_path.insert(0, str(Path(__file__).parent))
from witcher_collect_text import chapter_number, read_catalog, load_progress, BOOK_ID

class WitcherCollectorTests(unittest.TestCase):
    def test_arabic_and_chinese_chapter_numbers(self):
        examples = {
            '第600章 我们从正门进': 600,
            '第九百零一章 菜鸟，欢迎来到现实世界！': 901,
            '第九百五十一章 新王': 951,
            '第十章 其他': 10,
            '第十一章 其他': 11,
            '第1003章 其他': 1003,
            '上架感言': None,
        }
        for title, expected in examples.items():
            self.assertEqual(chapter_number(title), expected)

    def test_anchor_uses_heading_not_shifted_api_field(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows=[
                {'index':1,'id':'a'*24,'chapter_number':598,'title':'第599章 前章'},
                {'index':2,'id':'b'*24,'chapter_number':599,'title':'第600章 我们从正门进'},
                {'index':3,'id':'c'*24,'chapter_number':600,'title':'第601章 奥托兰'},
            ]
            fp=Path(tmp)/'catalog.json'
            fp.write_text(json.dumps({'book_id':BOOK_ID,'version':'4','total':3,'rows':rows}),encoding='utf-8')
            data,all_rows,selection=read_catalog(fp,600,601)
            self.assertEqual(len(selection),2)
            self.assertEqual(selection[0]['title'],'第600章 我们从正门进')
            self.assertEqual(selection[0]['chapter_number'],599)

    def test_gaps_are_hard_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows=[
                {'index':1,'id':'a'*24,'chapter_number':599,'title':'第600章 开始'},
                {'index':2,'id':'b'*24,'chapter_number':601,'title':'第602章 不完整'},
            ]
            fp=Path(tmp)/'catalog.json'
            fp.write_text(json.dumps({'book_id':BOOK_ID,'version':'4','total':2,'rows':rows}),encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'missing, duplicated'):
                read_catalog(fp,600,602)

    def test_mismatched_resume_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'progress.json'
            data=load_progress(p,version='4',first=600,last=1003)
            p.write_text(json.dumps(data),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'Cannot resume'):
                load_progress(p,version='5',first=600,last=1003)

if __name__=='__main__':
    unittest.main()
