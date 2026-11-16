import unittest
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
from linked_collector import overview

B='a'*24
C='b'*24
URL=f'https://jiuxiaozw.com/sim/book/{B}'
HTML=f'<html><head><title>测试书 - 作者 - 在线阅读</title></head><body><h1>测试书</h1><button class="book-latest-catalog">完整目录 1600 章</button><a href="/book/{B}/{C}">开始阅读</a></body></html>'
class TestLinked(unittest.TestCase):
 def test_overview_large_catalog(self):
  d=overview(HTML,URL)
  self.assertEqual(d['announced_catalog_count'],1600)
  self.assertEqual(d['first_url'],f'https://jiuxiaozw.com/book/{B}/{C}')
 def test_reject_missing_start(self):
  with self.assertRaisesRegex(ValueError,'Start chapter'):
   overview(HTML.replace('开始阅读','其他'),URL)
 def test_reject_wrong_host(self):
  with self.assertRaisesRegex(ValueError,'Invalid host'):
   overview(HTML,f'https://evil.example/sim/book/{B}')

if __name__=='__main__':unittest.main()
