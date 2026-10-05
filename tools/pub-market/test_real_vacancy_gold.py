import json
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


def load_cases():
    return json.loads((HERE / "real_vacancy_gold.json").read_text(encoding="utf-8"))


def to_vacancy(case):
    payload = {
        "id": case["id"],
        "job-name": case["title"],
        "company": {"name": case["company"]},
        "duty": case["duty"],
        "requirement": case["requirement"],
        "vac_url": case["source_url"],
    }
    skills = case.get("skills", [])
    if skills:
        payload["hard-skills"] = [
            {"hard-skill": {"hard-skill-name": skill}}
            for skill in skills
        ]
    return payload


class RealVacancyGoldTests(unittest.TestCase):
    def test_real_vacancy_gold_classifications(self):
        cases = load_cases()
        self.assertGreaterEqual(len(cases), 8)

        for case in cases:
            with self.subTest(case=case["id"]):
                record = vr.normalize_trudvsem_source(to_vacancy(case))
                klass, reason, hits, paths, context = vr.classify_record(record)
                self.assertEqual(
                    case["expected_classification"],
                    klass,
                    msg=(
                        f"{case['id']}: expected {case['expected_classification']} "
                        f"but got {klass} ({reason}); hits={hits}; "
                        f"publisher_paths={paths}; context={context}"
                    ),
                )

    def test_gold_cases_have_reviewable_provenance(self):
        for case in load_cases():
            with self.subTest(case=case["id"]):
                self.assertTrue(case["source_url"].startswith("https://"))
                self.assertTrue(case["observed_at"])
                self.assertIn(case["expected_classification"], {"A", "B", "C"})
                self.assertTrue(case["evidence_note"])


if __name__ == "__main__":
    unittest.main()
