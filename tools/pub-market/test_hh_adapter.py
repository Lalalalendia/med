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


class HeadHunterAdapterTests(unittest.TestCase):
    def test_normalize_hh_source_direct_publisher_work_is_a(self):
        payload = {
            "id": "hh-a1",
            "name": "Верстальщик",
            "alternate_url": "https://hh.ru/vacancy/hh-a1",
            "employer": {"id": "e1", "name": "Example LLC"},
            "area": {"id": "1", "name": "Москва"},
            "initial_created_at": "2026-10-01T10:00:00+0300",
            "description": "<p>Верстка каталогов и брошюр в Microsoft Publisher.</p>",
            "key_skills": [{"name": "Microsoft Publisher"}],
        }
        record = vr.normalize_hh_source(payload)
        klass, reason, hits, paths, context = vr.classify_record(record)

        self.assertEqual("hh", record.source)
        self.assertEqual("hh-a1", record.source_id)
        self.assertEqual("A", klass)
        self.assertEqual("publisher_plus_operational_duty", reason)
        self.assertIn("каталог", hits)
        self.assertIn("description", paths)
        self.assertTrue(any("Microsoft Publisher" in text for text in context))

    def test_normalize_hh_source_skill_only_medical_noise_is_c(self):
        payload = {
            "id": "hh-c1",
            "name": "Врач-терапевт",
            "alternate_url": "https://hh.ru/vacancy/hh-c1",
            "employer": {"id": "e2", "name": "Clinic"},
            "area": {"id": "2", "name": "Самара"},
            "published_at": "2026-10-01T10:00:00+0300",
            "description": "<p>Амбулаторный прием пациентов.</p>",
            "key_skills": [{"name": "MS Publisher"}, {"name": "Медицина"}],
        }
        record = vr.normalize_hh_source(payload)
        klass, reason, *_ = vr.classify_record(record)
        self.assertEqual("C", klass)
        self.assertEqual("unrelated_role_and_skill_tag_only", reason)

    def test_fetch_hh_paginates_and_hydrates_full_vacancies(self):
        calls = []
        details = {
            "1": {
                "id": "1",
                "name": "Верстальщик",
                "alternate_url": "https://hh.ru/vacancy/1",
                "employer": {"id": "e1", "name": "One"},
                "area": {"name": "Москва"},
                "initial_created_at": "2026-10-01T10:00:00+0300",
                "description": "<p>Верстка в Microsoft Publisher.</p>",
                "key_skills": [],
            },
            "2": {
                "id": "2",
                "name": "Офис-менеджер",
                "alternate_url": "https://hh.ru/vacancy/2",
                "employer": {"id": "e2", "name": "Two"},
                "area": {"name": "Казань"},
                "initial_created_at": "2026-10-02T10:00:00+0300",
                "description": "<p>Документооборот.</p>",
                "key_skills": [{"name": "MS Publisher"}],
            },
        }

        def requester(path, params):
            calls.append((path, dict(params)))
            if path == "/vacancies":
                page = params["page"]
                if page == 0:
                    return {"items": [{"id": "1"}], "pages": 2}
                if page == 1:
                    return {"items": [{"id": "2"}], "pages": 2}
                raise AssertionError(f"unexpected page {page}")
            vacancy_id = path.rsplit("/", 1)[-1]
            return details[vacancy_id]

        rows = vr.fetch_hh(
            "Microsoft Publisher",
            "2026-10-01T00:00:00+0000",
            access_token="fixture-token",
            user_agent="Fixture/1.0 (test@example.invalid)",
            per_page=1,
            requester=requester,
        )

        self.assertEqual(["1", "2"], [row.source_id for row in rows])
        search_calls = [call for call in calls if call[0] == "/vacancies"]
        self.assertEqual(2, len(search_calls))
        self.assertEqual("2026-10-01T00:00:00+0000", search_calls[0][1]["date_from"])
        self.assertEqual(1, search_calls[0][1]["per_page"])
        self.assertEqual(
            ["/vacancies/1", "/vacancies/2"],
            [path for path, _ in calls if path != "/vacancies"],
        )

    def test_hh_bounds_are_explicit(self):
        with self.assertRaises(ValueError):
            vr.fetch_hh(
                "Publisher",
                None,
                access_token="fixture-token",
                user_agent="Fixture/1.0 (test@example.invalid)",
                per_page=101,
                requester=lambda path, params: {},
            )
        with self.assertRaises(ValueError):
            vr.fetch_hh(
                "Publisher",
                None,
                access_token="fixture-token",
                user_agent="Fixture/1.0 (test@example.invalid)",
                max_pages=21,
                requester=lambda path, params: {},
            )

    def test_hh_request_requires_credentials_before_network(self):
        with self.assertRaises(ValueError):
            vr.request_hh_json("/vacancies", {}, access_token="", user_agent="Fixture")
        with self.assertRaises(ValueError):
            vr.request_hh_json("/vacancies", {}, access_token="token", user_agent="")


if __name__ == "__main__":
    unittest.main()
