import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def load_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


tlb = load_module("tlb_experiment_compiler", "tlb_experiment_compiler.py")
opal = load_module("operation_algebra", "operation_algebra.py")


class TlbCompilerTests(unittest.TestCase):
    def test_conservative_property_put_selection(self):
        inventory = {
            "types": [
                {
                    "name": "TextFrame",
                    "functions": [
                        {
                            "name": "AutoFitText",
                            "dispid": 6,
                            "invkind": "INVOKE_PROPERTYPUT",
                            "params": [{"type": "PbTextAutoFitType"}],
                            "flags": [],
                        },
                        {
                            "name": "Delete",
                            "dispid": 99,
                            "invkind": "INVOKE_PROPERTYPUT",
                            "params": [{"type": "VT_BOOL"}],
                            "flags": [],
                        },
                        {
                            "name": "UnsafeObject",
                            "dispid": 100,
                            "invkind": "INVOKE_PROPERTYPUT",
                            "params": [{"type": "VT_DISPATCH"}],
                            "flags": [],
                        },
                        {
                            "name": "HiddenScalar",
                            "dispid": 101,
                            "invkind": "INVOKE_PROPERTYPUT",
                            "params": [{"type": "VT_I4"}],
                            "flags": ["FUNCFLAG_FHIDDEN"],
                        },
                        {
                            "name": "ReadOnly",
                            "dispid": 102,
                            "invkind": "INVOKE_PROPERTYGET",
                            "params": [],
                            "flags": [],
                        },
                    ],
                }
            ]
        }

        candidates, stats = tlb.compile_candidates(inventory)
        self.assertEqual(1, len(candidates))
        c = candidates[0]
        self.assertEqual("TextFrame", c.type_name)
        self.assertEqual("AutoFitText", c.member_name)
        self.assertEqual(6, c.dispid)
        self.assertEqual("PbTextAutoFitType".upper(), c.value_type)
        self.assertEqual(["control", "same_value", "changed_value"], [a["name"] for a in c.arms])
        self.assertEqual(4, stats["property_put_seen"])
        self.assertEqual(1, stats["excluded_hidden_or_restricted"])
        self.assertEqual(1, stats["excluded_name_risk"])
        self.assertEqual(1, stats["excluded_type_risk"])

    def test_real_inventory_schema_scalar_and_enum(self):
        inventory = {
            "types": [{
                "name": "_Document",
                "functions": [
                    {
                        "name": "EnvelopeVisible",
                        "dispid": 9,
                        "invocationKind": "INVOKE_PROPERTYPUT",
                        "parameters": [{"type": {"vtName": "VT_BOOL"}}],
                        "flags": {"names": []},
                    },
                    {
                        "name": "DocumentDirection",
                        "dispid": 28,
                        "invocationKind": "INVOKE_PROPERTYPUT",
                        "parameters": [{
                            "type": {
                                "vtName": "VT_USERDEFINED",
                                "userDefinedType": {
                                    "name": "PbDirectionType",
                                    "kind": "TKIND_ENUM",
                                },
                            }
                        }],
                        "flags": {"names": []},
                    },
                    {
                        "name": "AliasColor",
                        "dispid": 29,
                        "invocationKind": "INVOKE_PROPERTYPUT",
                        "parameters": [{
                            "type": {
                                "vtName": "VT_USERDEFINED",
                                "userDefinedType": {
                                    "name": "MsoRGBType",
                                    "kind": "TKIND_ALIAS",
                                },
                            }
                        }],
                        "flags": {"names": []},
                    },
                ],
            }]
        }
        candidates, stats = tlb.compile_candidates(inventory)
        self.assertEqual(["DocumentDirection", "EnvelopeVisible"],
                         sorted(c.member_name for c in candidates))
        enum = next(c for c in candidates if c.member_name == "DocumentDirection")
        self.assertIn("TKIND_ENUM", enum.value_type)
        scalar = next(c for c in candidates if c.member_name == "EnvelopeVisible")
        self.assertEqual("VT_BOOL", scalar.value_type)
        self.assertEqual(1, stats["excluded_type_risk"])

    def test_hidden_can_be_emitted_only_when_explicit(self):
        inventory = {
            "name": "TextFrame",
            "functions": [{
                "name": "HiddenScalar",
                "dispid": 101,
                "invkind": "INVOKE_PROPERTYPUT",
                "params": [{"type": "VT_I4"}],
                "flags": ["FUNCFLAG_FHIDDEN"],
            }],
        }
        candidates, _ = tlb.compile_candidates(inventory, include_hidden=True)
        self.assertEqual(1, len(candidates))
        self.assertTrue(candidates[0].hidden)
        self.assertIn("metadata-hidden-or-restricted", candidates[0].risk_reasons)

    def test_include_hidden_does_not_override_name_safety_filter(self):
        inventory = {
            "name": "Options",
            "functions": [{
                "name": "PrintLineByLine",
                "dispid": 16,
                "invkind": "INVOKE_PROPERTYPUT",
                "params": [{"type": "VT_BOOL"}],
                "flags": ["FUNCFLAG_FHIDDEN"],
            }],
        }
        candidates, stats = tlb.compile_candidates(inventory, include_hidden=True)
        self.assertEqual([], candidates)
        self.assertEqual(1, stats["excluded_name_risk"])


class OperationAlgebraTests(unittest.TestCase):
    @staticmethod
    def complete_row(ab, ba):
        guard = {
            "status": "ok",
            "semantic_fingerprint": {"guard": "stable"},
            "persistence_fingerprint": {"guard": "stable"},
            "render_fingerprint": "guard-stable",
        }
        return {
            "AB": ab,
            "BA": ba,
            "A_only": dict(guard),
            "B_only": dict(guard),
            "control": dict(guard),
        }

    def test_generates_only_high_information_pairs(self):
        ops = opal.load_operations({
            "operations": [
                {
                    "id": "ApplyStyle",
                    "fixture": "table-1",
                    "domain": "style",
                    "risk": "bounded",
                    "semantic_targets": ["cell.fill", "cell.font"],
                    "tags": ["style", "precedence"],
                },
                {
                    "id": "DirectFillOverride",
                    "fixture": "table-1",
                    "domain": "direct-format",
                    "risk": "bounded",
                    "semantic_targets": ["cell.fill"],
                    "tags": ["precedence"],
                },
                {
                    "id": "MoveUnrelatedShape",
                    "fixture": "table-1",
                    "domain": "geometry",
                    "risk": "bounded",
                    "semantic_targets": ["shape.bounds"],
                    "tags": [],
                },
            ]
        })
        pairs, stats = opal.generate_pairs(ops)
        self.assertEqual(1, len(pairs))
        self.assertEqual(("cell.fill",), pairs[0].overlap_targets)
        self.assertEqual(3, stats["pairs_considered"])

    def test_classifies_semantic_commute_persistence_diverge(self):
        row = self.complete_row(
            {
                "status": "ok",
                "semantic_fingerprint": {"fill": "red", "font": "Arial"},
                "persistence_fingerprint": {"Contents": "aaa", "Escher": "bbb"},
                "render_fingerprint": "r1",
            },
            {
                "status": "ok",
                "semantic_fingerprint": {"font": "Arial", "fill": "red"},
                "persistence_fingerprint": {"Contents": "ccc", "Escher": "bbb"},
                "render_fingerprint": "r1",
            },
        )
        row["pair_id"] = "OPALG-X"
        verdict = opal.classify_pair(row)
        self.assertEqual("semantic_commute_persistence_diverges", verdict["classification"])
        self.assertTrue(verdict["semantic_equal"])
        self.assertFalse(verdict["persistence_equal"])

    def test_classifies_hidden_precedence(self):
        row = self.complete_row(
            {
                "status": "ok",
                "semantic_fingerprint": {"fill": "red"},
                "persistence_fingerprint": {"Contents": "aaa"},
                "render_fingerprint": "red",
            },
            {
                "status": "ok",
                "semantic_fingerprint": {"fill": "blue"},
                "persistence_fingerprint": {"Contents": "bbb"},
                "render_fingerprint": "blue",
            },
        )
        verdict = opal.classify_pair(row)
        self.assertEqual("non_commutative_semantic_or_hidden_precedence", verdict["classification"])

    def test_missing_fingerprint_is_inconclusive(self):
        row = self.complete_row(
            {
                "status": "ok",
                "semantic_fingerprint": {"fill": "red"},
                "persistence_fingerprint": {"Contents": "aaa"},
                "render_fingerprint": None,
            },
            {
                "status": "ok",
                "semantic_fingerprint": {"fill": "red"},
                "persistence_fingerprint": {"Contents": "aaa"},
                "render_fingerprint": None,
            },
        )
        verdict = opal.classify_pair(row)
        self.assertEqual("inconclusive", verdict["classification"])
        self.assertEqual(["AB.render_fingerprint"], verdict["missing"])

    def test_missing_control_arm_is_inconclusive(self):
        row = self.complete_row(
            {
                "status": "ok",
                "semantic_fingerprint": {"fill": "red"},
                "persistence_fingerprint": {"Contents": "aaa"},
                "render_fingerprint": "r1",
            },
            {
                "status": "ok",
                "semantic_fingerprint": {"fill": "red"},
                "persistence_fingerprint": {"Contents": "aaa"},
                "render_fingerprint": "r1",
            },
        )
        del row["control"]
        verdict = opal.classify_pair(row)
        self.assertEqual("inconclusive", verdict["classification"])
        self.assertEqual("control missing or failed", verdict["reason"])


if __name__ == "__main__":
    unittest.main()
