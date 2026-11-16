import unittest
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).parent))
from collector import Entry, parse_catalog, parse_chapter, check_next, chapter_url, safe_filename

BOOK_ID='a'*24
IDs=[str(i)*24 for i in range(1,4)]

def book_html(count=3):
    links=''.join(f'<a href="/book/{BOOK_ID}/{IDs[i]}">第{i+1}章 第{i+1}话</a>' for i in reversed(range(3)))
    return f'<html><head><title>测试书 - 作者 - 在线阅读</title></head><body><h1>测试书</h1><button class="book-latest-catalog">完整目录 {count} 章</button><a href="/book/{BOOK_ID}/{IDs[0]}">开始阅读</a>{links}</body></html>'

class JiuxiaoTests(unittest.TestCase):
    def test_catalog_reverses_and_deduplicates(self):
        m, entries = parse_catalog(book_html(),f'https://jiuxiaozw.com/sim/book/{BOOK_ID}')
        self.assertEqual(m['announced_catalog_count'],3)
        self.assertEqual([x.ordinal for x in entries],[1,2,3])
        self.assertEqual([x.title for x in entries],['第1章 第1话','第2章 第2话','第3章 第3话'])
    def test_incomplete_catalog_rejected(self):
        with self.assertRaisesRegex(ValueError,'Catalog incomplete'):
            parse_catalog(book_html(count=4),f'https://jiuxiaozw.com/sim/book/{BOOK_ID}')
    def test_blocked_offsite_url(self):
        self.assertIsNone(chapter_url('https://example.org/book/'+BOOK_ID+'/'+IDs[0],BOOK_ID))
    def test_paragraphs_are_separate(self):
        e = Entry(1,'第1章 第1话','https://jiuxiaozw.com/sim/book/'+BOOK_ID+'/'+IDs[0],IDs[0])
        h='<html><h1>第1章 第1话</h1><div class="reader-columns">' + ''.join(f'<p class="reader-paragraph"><span class="reader-paragraph-text">{c*150}</span></p>' for c in ('天','地')) + f'</div><a href="/book/{BOOK_ID}/{IDs[1]}">下一章</a></html>'
        title,paras,nxt=parse_chapter(h,e)
        self.assertEqual(paras,['天'*150,'地'*150])
        self.assertTrue(nxt.endswith(IDs[1]))
    def test_navigation_mismatch_rejected(self):
        a=Entry(1,'第1章',f'https://jiuxiaozw.com/book/{BOOK_ID}/{IDs[0]}',IDs[0]); b=Entry(2,'第2章',f'https://jiuxiaozw.com/book/{BOOK_ID}/{IDs[1]}',IDs[1])
        with self.assertRaisesRegex(ValueError,'Next chapter mismatch'):
            check_next(a,f'https://jiuxiaozw.com/book/{BOOK_ID}/{IDs[2]}',b)
    def test_bad_title_rejected(self):
        e=Entry(1,'第1章 A',f'https://jiuxiaozw.com/book/{BOOK_ID}/{IDs[0]}',IDs[0])
        with self.assertRaisesRegex(ValueError,'title mismatch'):
            parse_chapter('<h1>错误</h1>',e)
    def test_safe_file_name(self):
        self.assertEqual(safe_filename('第一章：序言?'), '第一章_序言')

if __name__=='__main__': unittest.main()
