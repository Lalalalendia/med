#!/usr/bin/env python3
import importlib.util
import unittest
from pathlib import Path

P = Path(__file__).with_name('bingfong_736.py')
SPEC = importlib.util.spec_from_file_location('bingfong_736', P)
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


def sample(number, body):
    return (f'<html><head><title>book</title></head><body>'
            f'<h2>\u7b2c{number}\u7ae0 fixture</h2>'
            f'<div id="content">{body}</div></body></html>')


class Bingfong736Tests(unittest.TestCase):
    def test_url_mapping(self):
        self.assertEqual(M.source_url(M.FIRST), 'https://bingfong.com/novel/m/read/1135947/3013487')
        self.assertEqual(M.source_url(M.LAST), 'https://bingfong.com/novel/m/read/1136534/3014074')
        self.assertEqual(M.LAST - M.FIRST + 1, 588)
        self.assertEqual(M.expected_number(M.FIRST + 475), 476)
        self.assertEqual(M.expected_number(M.FIRST + 476), 476)
        self.assertEqual(M.expected_number(M.FIRST + 477), 477)

    def test_unsafe_links(self):
        self.assertTrue(M.validate_url(M.source_url(M.FIRST)))
        self.assertFalse(M.validate_url('https://example.org/novel/m/read/1135947/3013487'))
        self.assertFalse(M.validate_url(M.source_url(M.FIRST) + '?page=2'))
        self.assertFalse(M.validate_url('https://bingfong.com/novel/m/read/1135947/3013488'))
        self.assertFalse(M.validate_url('https://bingfong.com/novel/m/read/999/999'))

    def test_readable_page(self):
        n, title, body, han = M.parse_chapter(sample(7, '\u4fee\u771f\u7db2\u8def\u6642\u4ee3' * 100))
        self.assertEqual(n, 7)
        self.assertIn('fixture', title)
        self.assertGreater(han, 250)
        self.assertEqual(len(body), 600)

    def test_empty_and_wrong_titles(self):
        with self.assertRaisesRegex(ValueError, 'short'):
            M.parse_chapter(sample(1, 'short'))
        with self.assertRaisesRegex(ValueError, 'number'):
            M.parse_chapter('<html><h2>book</h2></html>')

    def test_duplicate_chapter_must_match(self):
        a = {'source_id': M.FIRST + 475, 'number': 476, 'body_sha256': 'same'}
        b = {'source_id': M.FIRST + 476, 'number': 476, 'body_sha256': 'same'}
        self.assertEqual(M.coverage([a, b])['duplicates'], {'476': [a['source_id'], b['source_id']]})
        with self.assertRaisesRegex(ValueError, 'different text'):
            M.coverage([a, {**b, 'body_sha256': 'different'}])
        with self.assertRaisesRegex(ValueError, 'unexpected duplicate'):
            M.coverage([{**a, 'number': 475}, {**b, 'number': 475}])

    def test_all_pages_and_missing(self):
        rows = []
        for n in range(1, 588):
            source_id = M.FIRST + n - 1 + int(n > 476)
            rows.append({'source_id': source_id, 'number': n, 'body_sha256': f'{n:04d}'})
        rows.insert(476, {'source_id': M.FIRST + 476, 'number': 476, 'body_sha256': '0476'})
        self.assertEqual(M.coverage(rows, True)['unique_chapters'], 587)
        with self.assertRaisesRegex(ValueError, 'incomplete inventory'):
            M.coverage(rows[:-1], True)


if __name__ == '__main__':
    unittest.main()
