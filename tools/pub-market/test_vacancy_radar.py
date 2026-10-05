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
            ["Adobe InDesign"],
            "DiAR-Engineering",
        )
        payload["requirement"] = "Adobe InDesign, Illustrator, Microsoft Publisher или CorelDRAW для полиграфии."
        klass, reason, hits, paths, _ = vr.classify_vacancy(payload)
        self.assertEqual("A", klass)
        self.assertEqual("publisher_plus_operational_duty", reason)
        self.assertIn("каталог", hits)
        self.assertIn("requirement", paths)

    def test_skill_only_publisher_plus_print_duty_stays_b(self):
        payload = vac(
            "b-print-skill-only",
            "Методист",
            "Формирование методической базы: печатные и электронные материалы.",
            ["MS Publisher", "Ведение документации"],
            "Морская Техническая Академия",
        )
        klass, reason, hits, paths, _ = vr.classify_vacancy(payload)
        self.assertEqual("B", klass)
        self.assertEqual("publisher_skill_only", reason)
        self.assertEqual((), hits)
        self.assertTrue(all(p.startswith("skills[") for p in paths))

    def test_a_direct_publisher_document_editing(self):
        payload = vac(
            "a-direct-edit",
            "Администратор офиса",
            "Редактирование документов в программе Microsoft Publisher: замена информации и изображений.",
        )
        klass, reason, hits, paths, _ = vr.classify_vacancy(payload)
        self.assertEqual("A", klass)
        self.assertEqual("publisher_plus_operational_duty", reason)
        self.assertIn("редактир", hits)
        self.assertIn("duty", paths)

    def test_company_description_cannot_promote_skill_only_publisher(self):
        payload = vac(
            "b-company-noise",
            "Офис-менеджер",
            "Прием звонков и ведение календаря.",
            ["MS Publisher"],
        )
        payload["company"]["description"] = "Студия дизайна, полиграфии и печати каталогов."
        klass, reason, *_ = vr.classify_vacancy(payload)
        self.assertEqual("B", klass)
        self.assertEqual("publisher_skill_only", reason)

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


class SourceContractTests(unittest.TestCase):
    def test_classifier_is_source_neutral(self):
        raw = vac(
            "trud-1",
            "Верстальщик",
            "Верстка каталогов и брошюр.",
            ["Microsoft Publisher"],
            "Example LLC",
        )
        raw["region"] = {"name": "Москва"}
        raw["creation-date"] = "2026-10-01"

        trud = vr.normalize_trudvsem_source(raw)
        mirror = vr.NormalizedVacancy(
            source="hh",
            source_id="hh-42",
            url="https://example.test/hh-42",
            employer=trud.employer,
            employer_inn="",
            employer_code="",
            job_name=trud.job_name,
            region=trud.region,
            creation_date=trud.creation_date,
            modified_date="",
            evidence=trud.evidence,
            skills=trud.skills,
        )

        self.assertEqual(vr.classify_record(trud), vr.classify_record(mirror))
        self.assertNotEqual(vr._record_key(trud), vr._record_key(mirror))
        self.assertEqual(vr._mirror_key(trud), vr._mirror_key(mirror))

    def test_mirror_key_is_not_guessed_without_date(self):
        record = vr.NormalizedVacancy(
            source="hh",
            source_id="hh-1",
            url="https://example.test/hh-1",
            employer="Example LLC",
            employer_inn="",
            employer_code="",
            job_name="Верстальщик",
            region="Москва",
            creation_date="",
            modified_date="",
            evidence=(("duty", "Верстка каталогов в Microsoft Publisher"),),
            skills=(),
        )
        self.assertEqual("", vr._mirror_key(record))

    def test_publisher_in_source_metadata_is_not_classification_evidence(self):
        payload = vac("metadata-only", "Офис-менеджер", "Прием звонков.")
        payload["company"]["description"] = "Работаем в Microsoft Publisher."
        klass, reason, *_ = vr.classify_vacancy(payload)
        self.assertEqual("N", klass)
        self.assertEqual("publisher_not_present", reason)


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

    def test_normalization_does_not_invent_modified_date(self):
        payload = vac("dated", "Верстальщик", "Верстка каталогов", ["Publisher"])
        row = vr.normalize_vacancy(payload, ["Publisher"])
        self.assertEqual("2026-10-01", row.creation_date)
        self.assertEqual("", row.modified_date)

        payload["modified-date"] = "2026-10-02T12:34:56Z"
        row = vr.normalize_vacancy(payload, ["Publisher"])
        self.assertEqual("2026-10-02T12:34:56Z", row.modified_date)

    def test_scan_deduplicates_across_queries_and_tracks_matches(self):
        one = vac("same", "Верстальщик", "Верстка каталогов", ["Microsoft Publisher"])

        def fetcher(query, modified_from):
            return [one]

        rows = vr.run_scan(["Microsoft Publisher", "MS Publisher"], None, fetcher=fetcher)
        self.assertEqual(1, len(rows))
        self.assertEqual(("MS Publisher", "Microsoft Publisher"), rows[0].query_matches)


class NormalizedRunnerTests(unittest.TestCase):
    def test_normalized_scan_deduplicates_and_tracks_queries(self):
        record = vr.NormalizedVacancy(
            source="hh",
            source_id="42",
            url="https://hh.ru/vacancy/42",
            employer="Example LLC",
            employer_inn="",
            employer_code="e42",
            job_name="Верстальщик",
            region="Москва",
            creation_date="2026-10-01T10:00:00+0300",
            modified_date="",
            evidence=(("description", "Верстка каталогов в Microsoft Publisher."),),
            skills=("Microsoft Publisher",),
        )

        def fetcher(query, since):
            self.assertEqual("2026-10-01T00:00:00+0000", since)
            return [record]

        rows = vr.run_normalized_scan(
            ["Microsoft Publisher", "MS Publisher"],
            "2026-10-01T00:00:00+0000",
            fetcher=fetcher,
        )
        self.assertEqual(1, len(rows))
        self.assertEqual("hh:42", rows[0].key)
        self.assertEqual(("MS Publisher", "Microsoft Publisher"), rows[0].query_matches)
        self.assertEqual("A", rows[0].classification)

    def test_hh_scan_reuses_normalized_runner(self):
        seen = []

        def fetcher(query, since):
            seen.append((query, since))
            return [
                vr.NormalizedVacancy(
                    source="hh",
                    source_id="7",
                    url="https://hh.ru/vacancy/7",
                    employer="Example LLC",
                    employer_inn="",
                    employer_code="e7",
                    job_name="Офис-менеджер",
                    region="Москва",
                    creation_date="2026-10-01T10:00:00+0300",
                    modified_date="",
                    evidence=(("description", "Ведение документооборота."),),
                    skills=("MS Publisher",),
                )
            ]

        rows = vr.run_hh_scan(
            ["MS Publisher"],
            "2026-10-01T00:00:00+0000",
            access_token="unused-fixture-token",
            user_agent="Fixture/1.0 (test@example.invalid)",
            fetcher=fetcher,
        )
        self.assertEqual([("MS Publisher", "2026-10-01T00:00:00+0000")], seen)
        self.assertEqual("B", rows[0].classification)


class OutputTests(unittest.TestCase):
    def test_outputs_are_split(self):
        a = vac("a", "Верстальщик", "Верстка каталогов")
        a["requirement"] = "Опыт Microsoft Publisher"
        payloads = [
            a,
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
