import unittest
from pathlib import Path

import importlib.util
import sys

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("hh_rss_discovery", HERE / "hh_rss_discovery.py")
rss = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = rss
SPEC.loader.exec_module(rss)


def feed(items):
    body = "".join(items)
    return (
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
        "<rss version=\"2.0\"><channel><title>HeadHunter Vacancy</title>"
        + body
        + "</channel></rss>"
    ).encode("utf-8")


def item(vacancy_id, title, company, region, query_marker="", published="2026-10-05T10:00:00+03:00"):
    description = (
        f"<p>Вакансия компании: {company}</p>"
        f"<p>Создана: 05.10.2026</p>"
        f"<p>Регион: {region}</p>"
        f"<p>Предполагаемый уровень месячного дохода: от 50 000 ₽</p>"
        f"{query_marker}"
    )
    return (
        "<item>"
        f"<guid>https://hh.ru/vacancy/{vacancy_id}</guid>"
        f"<link>https://hh.ru/vacancy/{vacancy_id}</link>"
        f"<title>{title}</title>"
        f"<pubDate>{published}</pubDate>"
        f"<description><![CDATA[{description}]]></description>"
        "</item>"
    )


class HHRssDiscoveryTests(unittest.TestCase):
    def test_feed_url_is_bounded_to_russia(self):
        url = rss.build_feed_url("MS Publisher")
        self.assertIn("text=MS+Publisher", url)
        self.assertIn("area=113", url)

    def test_parse_extracts_provenance_without_claiming_classification(self):
        rows = rss.parse_feed(
            feed([item("42", "Методист", "Example LLC", "Москва")]),
            "MS Publisher",
        )
        self.assertEqual(1, len(rows))
        row = rows[0]
        self.assertEqual("hh:42", row.key)
        self.assertEqual("42", row.source_id)
        self.assertEqual("Example LLC", row.employer)
        self.assertEqual("Москва", row.region)
        self.assertEqual("от 50 000 ₽", row.salary)
        self.assertEqual(("MS Publisher",), row.query_matches)
        self.assertEqual("search_match_only", row.evidence_level)
        self.assertEqual("unverified", row.qualification_status)

    def test_merge_deduplicates_across_exact_queries(self):
        first = rss.parse_feed(
            feed([item("42", "Методист", "Example LLC", "Москва")]),
            "Microsoft Publisher",
        )
        second = rss.parse_feed(
            feed([item("42", "Методист", "Example LLC", "Москва")]),
            "MS Publisher",
        )
        rows = rss.merge_candidates([first, second])
        self.assertEqual(1, len(rows))
        self.assertEqual(("MS Publisher", "Microsoft Publisher"), rows[0].query_matches)

    def test_missing_vacancy_id_is_skipped(self):
        raw = (
            "<?xml version=\"1.0\"?><rss><channel>"
            "<item><title>No ID</title><link>https://hh.ru/search/vacancy</link></item>"
            "</channel></rss>"
        ).encode("utf-8")
        self.assertEqual([], rss.parse_feed(raw, "MS Publisher"))

    def test_run_discovery_uses_each_query_once(self):
        calls = []

        def fetcher(query, *, area):
            calls.append((query, area))
            vacancy_id = "1" if query == "Microsoft Publisher" else "2"
            return feed([item(vacancy_id, query, "Example", "Москва")])

        rows = rss.run_discovery(
            ["Microsoft Publisher", "MS Publisher"],
            area="113",
            fetcher=fetcher,
        )
        self.assertEqual(
            [("Microsoft Publisher", "113"), ("MS Publisher", "113")],
            calls,
        )
        self.assertEqual(2, len(rows))


if __name__ == "__main__":
    unittest.main()
