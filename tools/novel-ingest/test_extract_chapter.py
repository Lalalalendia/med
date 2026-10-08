import importlib.util
import pathlib
import sys
import unittest

HERE = pathlib.Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "extract_chapter", HERE / "extract_chapter.py"
)
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
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
        self.assertEqual(chapters[4].entry_type, "extra")
        self.assertEqual(chapters[5].entry_type, "extra")
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
        self.assertTrue(all(c.entry_type == "chapter" for c in chapters))

    def test_service_headings_are_separate_records(self):
        service_headings = [
            "上架感言",
            "群炸了，请前往评论区",
            "电脑炸了……请假",
            "请假条",
            "没办法再请天假，顺便说下近况",
            "罪己诏",
            "新书已发，《司教大人深不可测》",
            "群炸了，转至备用群，加群方式见评论区",
        ]
        parts = ["第1章 One\nchapter one"]
        parts.extend(f"{heading}\nservice body" for heading in service_headings)
        parts.append("第2章 Two\nchapter two")

        chapters = MOD.parse_book("\n\n".join(parts))

        self.assertEqual(len(chapters), 10)
        self.assertEqual(
            [c.author_number for c in chapters if c.author_number is not None],
            [1, 2],
        )
        self.assertEqual(
            [c.heading for c in chapters if c.entry_type == "service"],
            service_headings,
        )
        self.assertEqual(
            sum(c.entry_type == "extra" for c in chapters),
            0,
        )

        meta = MOD.metadata(chapters[-1], chapters)
        self.assertEqual(meta["numbered_chapters"], 2)
        self.assertEqual(meta["extra_entries"], 0)
        self.assertEqual(meta["service_entries"], 8)
        self.assertEqual(meta["extras"], 8)
        self.assertEqual(meta["max_author_number"], 2)
        self.assertEqual(meta["missing_author_numbers"], [])

    def test_service_like_body_sentence_is_not_heading(self):
        text = """第1章 One
今天真的很累，只能请假。
still chapter one

第2章 Two
done
"""
        chapters = MOD.parse_book(text)
        self.assertEqual(len(chapters), 2)
        self.assertIn("只能请假", chapters[0].body)


if __name__ == "__main__":
    unittest.main()
