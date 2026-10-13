import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ixdzs8_ultron_probe import BOOK_URL, approved_page, cn_number, parse_catalog, chapter_body, run


class Response:
    status_code = 200
    headers = {'Content-Type': 'text/html; charset=utf-8'}
    encoding = 'utf-8'

    def __init__(self, text):
        self.text = text


class Session:
    def __init__(self, routes):
        self.routes = routes
        self.headers = {}

    def get(self, url, **_):
        return Response(self.routes[url])


class TestMirror(unittest.TestCase):
    def test_numbers(self):
        self.assertEqual([cn_number(s) for s in ['一', '六十四', '一百二十', '二百零一', '201']],
                         [1, 64, 120, 201, 201])

    def test_approved_urls(self):
        self.assertEqual(approved_page('/read/319824/p124.html')[1], 124)
        self.assertIsNone(approved_page('https://evil.example/read/319824/p124.html'))
        self.assertIsNone(approved_page('http://ixdzs8.com/read/319824/p124.html'))
        self.assertIsNone(approved_page('/read/319825/p124.html'))

    def test_parse_and_service(self):
        doc = '''<h1>我在漫威当奥创</h1><div>目录 共206章</div>
         <a href="/read/319824/p2.html">第一章 起源</a>
         <a href="/read/319824/p4.html">第三章 风暴</a>
         <a href="/read/319824/p124.html">第120章 新挑战</a>
         <a href="/read/319824/p206.html">第201章 大结局</a>
         <a href="/read/319824/p3.html">作者的话</a>'''
        data = parse_catalog(doc)
        self.assertEqual(data['announced_entries'], 206)
        self.assertEqual(data['numbered_chapters'], 4)
        self.assertEqual(data['service_page_slots'], [3])
        self.assertIn(2, data['missing_numbered'])

    def test_blocks_challenge_and_short(self):
        with self.assertRaisesRegex(ValueError, 'browser_challenge'):
            chapter_body('<h1>正在验证浏览器</h1>', 120)
        with self.assertRaisesRegex(ValueError, 'no_verified_chapter_body'):
            chapter_body('<title>我在漫威当奥创 第120章</title><article>太短</article>', 120)
        count, digest = chapter_body('<title>我在漫威当奥创 第120章</title><article>' +
                                     '奥创展开攻击。' * 120 + '</article>', 120)
        self.assertGreater(count, 500)
        self.assertEqual(len(digest), 64)

    def test_manifest_not_claimed_as_full_text(self):
        index = ('<h1>我在漫威当奥创</h1><div>目录 共2章</div>'
                 '<a href="/read/319824/p2.html">第一章 开始</a>')
        s = Session({BOOK_URL: index,
                     'https://ixdzs8.com/read/319824/p2.html': '<h1>正在验证浏览器</h1>'})
        with tempfile.TemporaryDirectory() as temp, patch('ixdzs8_ultron_probe.time.sleep'):
            result = run(Path(temp) / 'out', session=s)
            self.assertEqual(result['status'], 'catalog_only_no_verified_text')
            self.assertEqual(result['probe'][0]['status'], 'body_not_verified')
            self.assertTrue((Path(temp) / 'out' / 'manifest.json').exists())
            self.assertEqual(len(list((Path(temp) / 'out').iterdir())), 1)


if __name__ == '__main__':
    unittest.main()
