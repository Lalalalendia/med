import importlib.util
import pathlib
import unittest

HERE = pathlib.Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "extract_chapter", HERE / "extract_chapter.py"
)
MOD = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MOD)


class ExtractChapterTests(unittest.TestCase):
    def test_spacing_and_extras(self):
        text = """Book

第1章 One
aaa

第 2章 Two
bbb

第3 章 Three
ccc

第 4 章。
ddd

番外 ：Extra A
eee

番外 Extra B
fff
"""
        chapters = MOD.parse_book(text)
        self.assertEqual(len(chapters), 6)
        self.assertEqual([c.author_number for c in chapters[:4]], [1, 2, 3, 4])
        self.assertEqual(chapters[3].title, "")
        self.assertEqual(chapters[4].author_number, None)
        self.assertEqual(chapters[4].title, "Extra A")
        self.assertEqual(chapters[5].ordinal, 6)

    def test_irregular_numbered_headings(self):
        text = """第111章 A
x
第 112章 B
x
第113章 C
x
第 114章 D
x
第115 章 E
x
第 116 章 F
x
第117章 G
x
第118章 H
x
"""
        chapters = MOD.parse_book(text)
        self.assertEqual(
            [c.author_number for c in chapters],
            list(range(111, 119)),
        )


if __name__ == "__main__":
    unittest.main()
