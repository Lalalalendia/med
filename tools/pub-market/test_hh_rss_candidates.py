import unittest
from pathlib import Path
import tempfile

import importlib.util
import sys

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("hh_rss_candidates", HERE / "hh_rss_candidates.py")
rss = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = rss
SPEC.loader.exec_module(rss)


def feed(items):
    body = "".join(
        f"""<item>
<title>{item['title']}</title>
<link>{item['url']}</link>
<pubDate>{item['published']}</pubDate>
<description><![CDATA[
Вакансия компании: {item['employer']}
Создана: {item['published']}
Регион: {item['region']}
Предполагаемый уровень дохода: 1
]]></description>
</item>"""
        for item in items
    )
    return f"<?xml version='1.0' encoding='UTF-8'?><rss><channel>{body}</channel></rss>".encode()


class HHRssCandidateTests(unittest.TestCase):
    def test_parse_keeps_candidate_provenance(self):
        rows = rss.parse_hh_rss(
            feed([{
                "title": "Методист",
                "url": "https://hh.ru/vacancy/42",
                "published": "2026-10-05T10:00:00+03:00",
                "employer": "Example Academy",
                "region": "Москва",
            }]),
            "MS Publisher",
        )
        self.assertEqual(1, len(rows))
        row = rows[0]
        self.assertEqual("hh-rss", row.source)
        self.assertEqual("42", row.vacancy_id)
        self.assertEqual("Example Academy", row.employer)
        self.assertEqual("Москва", row.region)
        self.assertEqual(("MS Publisher",), row.query_matches)
        self.assertEqual("candidate_only", row.evidence_level)

    def test_scan_deduplicates_across_queries(self):
        payload = feed([{
            "title": "Методист",
            "url": "https://hh.ru/vacancy/42",
            "published": "2026-10-05T10:00:00+03:00",
            "employer": "Example Academy",
            "region": "Москва",
        }])

        def fetcher(query, area):
            self.assertEqual("113", area)
            return payload

        rows = rss.run_candidate_scan(
            ["Microsoft Publisher", "MS Publisher"],
            "113",
            fetcher=fetcher,
        )
        self.assertEqual(1, len(rows))
        self.assertEqual(("MS Publisher", "Microsoft Publisher"), rows[0].query_matches)

    def test_outputs_explicitly_say_candidate_only(self):
        row = rss.HHRssCandidate(
            source="hh-rss",
            vacancy_id="42",
            url="https://hh.ru/vacancy/42",
            title="Методист",
            employer="Example Academy",
            region="Москва",
            published="2026-10-05T10:00:00+03:00",
            query_matches=("MS Publisher",),
        )
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)
            rss.write_outputs([row],out,"113")
            summary=(out/"summary.md").read_text(encoding="utf-8")
            self.assertIn("candidate-only", summary)
            self.assertNotIn("A —", summary)


if __name__ == "__main__":
    unittest.main()
