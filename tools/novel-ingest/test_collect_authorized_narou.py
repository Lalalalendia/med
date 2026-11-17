"""Offline-only tests; no requests to the source website."""
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location('collector', Path(__file__).with_name('collect_authorized_narou.py'))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

HTML = '''<html><body><h1 class="p-novel__title">Prologue テスト</h1>
<div class="js-novel-text p-novel__text"><p>これはテスト用の長い文章です。{repeat}</p><p><ruby>漢字<rt>かんじ</rt></ruby>と文章。</p><p>段落３。</p><p>段落４。</p><p>段落５。</p></div><div class="advertisement">ADVERTISEMENT</div></body></html>'''.format(repeat='あいうえお'*40)

class Response:
    status_code = 200
    headers = {'content-type': 'text/html'}
    text = HTML

class FakeSession:
    def __init__(self, deny_at=None):
        self.headers = {}
        self.deny_at=deny_at
        self.calls = []
    def get(self, url, **kwargs):
        self.calls.append(url)
        r=Response()
        if self.deny_at and url.endswith(f'/{self.deny_at}/'):
            r.status_code=403
        return r

class Robots:
    def __init__(self, allowed=True): self.allowed=allowed
    def can_fetch(self, agent, url): return self.allowed

class CollectorTests(unittest.TestCase):
    def test_extract_preserves_ruby_and_paragraphs(self):
        title, body=mod.parse_episode(HTML,1)
        self.assertEqual(title,'Prologue テスト')
        self.assertIn('｜漢字《かんじ》',body)
        self.assertIn('\n\n', body)
        self.assertNotIn('ADVERTISEMENT',body)
    def test_no_body_fails(self):
        with self.assertRaisesRegex(mod.CollectionFailure,'canonical'):
            mod.parse_episode('<html><title>Oops</title></html>',1)
    def test_full_capture_and_zip(self):
        with tempfile.TemporaryDirectory() as td, patch.object(mod.time,'sleep'):
            p=Path(td)/'run'
            result=mod.collect(out=p,expected=3,session=FakeSession(),robots=Robots())
            self.assertEqual(result['status'],'COMPLETE')
            self.assertEqual(result['collected'],3)
            self.assertEqual(len(list((p/'episodes').glob('*.txt'))),3)
            import zipfile
            with zipfile.ZipFile(p/'complete_ja.zip') as z:
                self.assertIsNone(z.testzip())
                self.assertEqual(len(z.namelist()),5)
    def test_robots_denial_stops_without_fetch(self):
        with tempfile.TemporaryDirectory() as td, patch.object(mod.time,'sleep'):
            session=FakeSession()
            result=mod.collect(out=Path(td)/'run',expected=2,session=session,robots=Robots(False))
            self.assertEqual(result['status'],'PARTIAL')
            self.assertEqual(result['collected'],0)
            self.assertEqual(session.calls,[])
    def test_http_denial_stops_and_preserves_partial(self):
        with tempfile.TemporaryDirectory() as td, patch.object(mod.time,'sleep'):
            p=Path(td)/'run'
            result=mod.collect(out=p,expected=3,session=FakeSession(deny_at=2),robots=Robots())
            self.assertEqual(result['status'],'PARTIAL')
            self.assertEqual(result['collected'],1)
            self.assertFalse((p/'complete_ja.zip').exists())
            self.assertTrue((p/'manifest.json').exists())
    def test_bad_min_delay_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(ValueError,'Minimum delay'):
                mod.collect(out=Path(td)/'run',expected=3,delay=0.1,session=FakeSession(),robots=Robots())

if __name__ == '__main__':
    unittest.main()
