"""Offline regression: merge renders titles from chapter bodies and enforces hashes."""
from __future__ import annotations
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

sp = importlib.util.spec_from_file_location(
    "merge_marvel_taylor_zhys", Path(__file__).with_name("merge_marvel_taylor_zhys.py"))
m = importlib.util.module_from_spec(sp)
sys.modules[sp.name] = m
sp.loader.exec_module(m)


class MergeTest(unittest.TestCase):
    def setup_shards(self, root):
        items = [{"ordinal":i, "source_id":99+i,
                  "url":f"https://cn.zhys.tw/read/2268838/{99+i}.html"}
                 for i in range(1,5)]
        for i in range(1,5):
            folder = root / ("shard-" + str(i))
            (folder/"raw").mkdir(parents=True)
            story = ("这是一本真正的中文故事，其情节正在慢慢展开。" * 21) + str(i)
            prefix = ("无\n" if i == 1 else "")
            suffix = ("无\n" if i == 1 else "")
            original = ("Entry "+str(99+i)+"\n\n"+"第"+str(i)+"章 开始\n"
                        +"漫威，谁把他救出来的？！\n"+prefix+story+"\n"
                        +suffix+"分享\n猜你喜欢\n")
            source_file=folder/"raw"/f"{i:04d}.txt"
            source_file.write_text(original,encoding="utf-8")
            manifest={
                "book_id":2268838,"source":"zhys","status":"PASS","catalog_count":4,
                "catalog":items,"requested":{"start":i,"end":i},
                "chapters":[{"ordinal":i,"status":"ok",
                              "file":f"raw/{i:04d}.txt",
                              "sha256":hashlib.sha256(original.encode()).hexdigest(),
                              "body_sha256":hashlib.sha256(story.encode()).hexdigest()}]}
            (folder/"manifest.json").write_text(
                json.dumps(manifest,ensure_ascii=False),encoding="utf-8")

    def test_fixes_titles_and_preserves_provenance(self):
        with tempfile.TemporaryDirectory() as d:
            inp=Path(d)/"shards"; inp.mkdir()
            self.setup_shards(inp)
            out=Path(d)/"verified"
            result=m.merge(inp,out,expected=4)
            self.assertEqual(result["verified"],4)
            self.assertEqual(result["title_fixes"],4)
            self.assertEqual(result["status"],"PASS")
            data=(out/"raw"/"0001.txt").read_text(encoding="utf-8")
            self.assertTrue(data.startswith("第1章 开始\n\n"))
            self.assertNotIn("Entry",data)
            self.assertNotIn("漫威，谁把他救出来的",data)
            self.assertNotIn("猜你喜欢",data)
            self.assertNotIn("分享",data)
            self.assertTrue(data.splitlines()[2].startswith("这是"))
            self.assertEqual(m.sha(data),result["chapters"][0]["sha256"])

    def test_detects_tampered_raw(self):
        with tempfile.TemporaryDirectory() as d:
            inp=Path(d)/"shards"; inp.mkdir()
            self.setup_shards(inp)
            (inp/"shard-1"/"raw"/"0001.txt").write_text("BAD",encoding="utf-8")
            with self.assertRaises(ValueError):
                m.merge(inp,Path(d)/"verified",expected=4)


if __name__=="__main__":
    unittest.main()
