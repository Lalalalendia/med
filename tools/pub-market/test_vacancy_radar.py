import json
import tempfile
import unittest
from pathlib import Path

import importlib.util
import sys

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("vacancy_radar", HERE / "vacancy_radar.py")
vr = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = vr
SPEC.loader.exec_module(vr)


def vac(vacancy_id, title, duties, skills=None, company="Example LLC"):
    payload = {
        "id": vacancy_id,
        "job-name": title,
        "company": {"name": company, "inn": "7700000000"},
        "region": {"name": "Москва"},
        "creation-date": "2026-10-01",
        "vac_url": f"https://example.test/{vacancy_id}",
        "duty": duties,
    }
    if skills is not None:
        payload["hard-skills"] = [{"hard-skill": {"hard-skill-name": s}} for s in skills]
    return payload


class ClassifierTests(unittest.TestCase):
    def test_a_operational_diar_like(self):
        payload = vac(
            "a1",
            "Контент-маркетолог",
            "Оформление каталогов, брошюр и презентаций; дизайн и верстка для полиграфии.",
            ["Microsoft Publisher", "Adobe InDesign"],
            "DiAR-Engineering",
        )
        klass, reason, hits, paths, _ = vr.classify_vacancy(payload)
        self.assertEqual("A", klass)
        self.assertEqual("publisher_plus_operational_duty", reason)
        self.assertIn("каталог", hits)
        self.assertTrue(any("hard-skills" in p for p in paths))

    def test_b_skill_only(self):
        payload = vac("b1", "Офис-менеджер", "Ведение документооборота и прием звонков.", ["MS Publisher"])
        klass, reason, *_ = vr.classify_vacancy(payload)
        self.assertEqual("B", klass)
        self.assertEqual("publisher_skill_only", reason)

    def test_c_negative_control_pharmacist(self):
        payload = vac("c1", "Фармацевт", "Отпуск лекарственных препаратов.", ["MS Publisher"])
        klass, reason, *_ = vr.classify_vacancy(payload)
        self.assertEqual("C", klass)
        self.assertEqual("unrelated_role_and_skill_tag_only", reason)

    def test_no_publisher_is_n(self):
        payload = vac("n1", "Дизайнер", "Верстка каталогов", ["Adobe InDesign"])
        klass, *_ = vr.classify_vacancy(payload)
        self.assertEqual("N", klass)

    def test_publisher_in_requirement_plus_duty_is_a(self):
        payload = vac("a2", "Специалист", "Подготовка макетов этикеток к печати")
        payload["requirement"] = "Опыт Microsoft Publisher 2019"
        klass, *_ = vr.classify_vacancy(payload)
        self.assertEqual("A", klass)


class FetchTests(unittest.TestCase):
    def test_paginates_and_deduplicates(self):
        rows = [
            vac("1", "Верстальщик", "Верстка буклетов", ["Publisher"]),
            vac("2", "Верстальщик", "Верстка каталогов", ["Publisher"]),
            vac("3", "Верстальщик", "Предпечатная подготовка", ["Publisher"]),
        ]
        calls = []

        def requester(url, params):
            calls.append(dict(params))
            offset = params["offset"]
            if offset == 0:
                page = rows[:2]
            elif offset == 1:
                page = [rows[1], rows[2]]
            else:
                page = []
            return {
                "status": "200",
                "meta": {"total": "3"},
                "results": {"vacancies": [{"vacancy": x} for x in page]},
            }

        got = vr.fetch_trudvsem("Publisher", "2026-10-01T00:00:00Z", limit=2, requester=requester)
        self.assertEqual(["1", "2", "3"], [x["id"] for x in got])
        self.assertEqual(2, len(calls))
        self.assertEqual("2026-10-01T00:00:00Z", calls[0]["modifiedFrom"])

    def test_scan_deduplicates_across_queries_and_tracks_matches(self):
        one = vac("same", "Верстальщик", "Верстка каталогов", ["Microsoft Publisher"])

        def fetcher(query, modified_from):
            return [one]

        rows = vr.run_scan(["Microsoft Publisher", "MS Publisher"], None, fetcher=fetcher)
        self.assertEqual(1, len(rows))
        self.assertEqual(("MS Publisher", "Microsoft Publisher"), rows[0].query_matches)


class OutputTests(unittest.TestCase):
    def test_outputs_are_split(self):
        payloads = [
            vac("a", "Верстальщик", "Верстка каталогов", ["Publisher"]),
            vac("b", "Офис-менеджер", "Документы", ["Publisher"]),
            vac("c", "Фармацевт", "Лекарства", ["Publisher"]),
        ]
        rows = [vr.normalize_vacancy(p, ["Publisher"]) for p in payloads]
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            vr.write_outputs(rows, out, "2026-10-01T00:00:00Z")
            self.assertEqual(1, len(json.loads((out / "qualified.json").read_text(encoding="utf-8"))))
            self.assertEqual(1, len(json.loads((out / "review.json").read_text(encoding="utf-8"))))
            self.assertEqual(1, len(json.loads((out / "rejected.json").read_text(encoding="utf-8"))))
            summary = (out / "summary.md").read_text(encoding="utf-8")
            self.assertIn("A — operational: **1**", summary)


if __name__ == "__main__":
    unittest.main()
