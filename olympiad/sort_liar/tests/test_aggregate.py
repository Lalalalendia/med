import json
import sys
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from aggregate import load_reports
from judge import Result


class AggregateTests(unittest.TestCase):
    def row(self, name):
        return Result(name, 'smoke', 2, 0, 2, 'honest', 'sorted', 0, 42,
                      True, 1, 0, 1.75, 0.1, 'correct')

    def test_loads_shards_without_duplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for i, name in enumerate(('a', 'b')):
                folder = root / f'shard-{i}'
                folder.mkdir()
                (folder / 'results.json').write_text(json.dumps([asdict(self.row(name))]))
            self.assertEqual(len(load_reports(root)), 2)

    def test_rejects_duplicate_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for i in range(2):
                folder = root / f'shard-{i}'
                folder.mkdir()
                (folder / 'results.json').write_text(json.dumps([asdict(self.row('same'))]))
            with self.assertRaises(ValueError):
                load_reports(root)


if __name__ == '__main__':
    unittest.main()
