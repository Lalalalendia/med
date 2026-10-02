#!/usr/bin/env python3
"""
Generate and classify PUB operation-algebra experiments.

The generator creates A→B and B→A pairs from a declarative operation catalog.
The classifier compares reopened semantic fingerprints and persisted fingerprints.

This module does not invoke Publisher. It defines a deterministic experiment envelope
for an external native harness such as TRANSITION-FIDELITY-ORACLE-01.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Operation:
    op_id: str
    fixture: str
    domain: str
    risk: str
    semantic_targets: tuple[str, ...]
    tags: tuple[str, ...]
    conflicts_with: tuple[str, ...]
    prerequisites: tuple[str, ...]


@dataclass(frozen=True)
class PairSpec:
    pair_id: str
    fixture: str
    a: str
    b: str
    domain_a: str
    domain_b: str
    overlap_targets: tuple[str, ...]
    arms: tuple[dict[str, Any], ...]
    interpretation_contract: dict[str, str]


SAFE_RISKS = {"read-safe", "bounded", "normal"}


def _tuple(v: Any) -> tuple[str, ...]:
    if v is None:
        return ()
    if isinstance(v, str):
        return (v,)
    if isinstance(v, list):
        return tuple(str(x) for x in v)
    return tuple(str(x) for x in v)


def load_operations(data: Any) -> list[Operation]:
    rows = data["operations"] if isinstance(data, dict) and "operations" in data else data
    if not isinstance(rows, list):
        raise ValueError("operation catalog must be a list or {'operations': [...]}")

    out: list[Operation] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        op_id = str(row.get("id") or row.get("op_id") or "").strip()
        fixture = str(row.get("fixture") or "").strip()
        if not op_id or not fixture:
            continue
        out.append(
            Operation(
                op_id=op_id,
                fixture=fixture,
                domain=str(row.get("domain") or "unknown"),
                risk=str(row.get("risk") or "review-required"),
                semantic_targets=_tuple(row.get("semantic_targets")),
                tags=_tuple(row.get("tags")),
                conflicts_with=_tuple(row.get("conflicts_with")),
                prerequisites=_tuple(row.get("prerequisites")),
            )
        )
    return out


def _pair_id(a: Operation, b: Operation) -> str:
    raw = f"{a.fixture}|{a.op_id}|{b.op_id}".encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()[:12]
    return f"OPALG-{digest.upper()}"


def pairable(a: Operation, b: Operation) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if a.op_id == b.op_id:
        reasons.append("same-operation")
    if a.fixture != b.fixture:
        reasons.append("different-fixture")
    if a.risk not in SAFE_RISKS or b.risk not in SAFE_RISKS:
        reasons.append("risk-not-auto-pairable")
    if b.op_id in a.conflicts_with or a.op_id in b.conflicts_with:
        reasons.append("declared-conflict")
    if "destructive" in a.tags or "destructive" in b.tags:
        reasons.append("destructive-tag")
    if "external-state" in a.tags or "external-state" in b.tags:
        reasons.append("external-state-tag")
    if "nondeterministic" in a.tags or "nondeterministic" in b.tags:
        reasons.append("nondeterministic-tag")
    return not reasons, reasons


def generate_pairs(ops: list[Operation]) -> tuple[list[PairSpec], dict[str, int]]:
    pairs: list[PairSpec] = []
    rejected = 0
    considered = 0

    for i, a in enumerate(ops):
        for b in ops[i + 1 :]:
            considered += 1
            ok, _ = pairable(a, b)
            if not ok:
                rejected += 1
                continue

            overlap = tuple(sorted(set(a.semantic_targets) & set(b.semantic_targets)))
            # High-information default: keep either shared-target pairs or pairs explicitly
            # marked as precedence/default/materialization candidates.
            signal_tags = {"precedence", "inheritance", "materialization", "layout", "style"}
            shared_signal_tags = signal_tags & set(a.tags) & set(b.tags)
            if not overlap and not shared_signal_tags:
                rejected += 1
                continue

            arms = (
                {
                    "name": "AB",
                    "steps": [a.op_id, b.op_id, "SAVE", "CLOSE", "REOPEN"],
                    "capture": ["semantic_snapshot", "stream_fingerprints", "render_fingerprint"],
                },
                {
                    "name": "BA",
                    "steps": [b.op_id, a.op_id, "SAVE", "CLOSE", "REOPEN"],
                    "capture": ["semantic_snapshot", "stream_fingerprints", "render_fingerprint"],
                },
                {
                    "name": "A_only",
                    "steps": [a.op_id, "SAVE", "CLOSE", "REOPEN"],
                    "capture": ["semantic_snapshot", "stream_fingerprints", "render_fingerprint"],
                },
                {
                    "name": "B_only",
                    "steps": [b.op_id, "SAVE", "CLOSE", "REOPEN"],
                    "capture": ["semantic_snapshot", "stream_fingerprints", "render_fingerprint"],
                },
                {
                    "name": "control",
                    "steps": ["SAVE", "CLOSE", "REOPEN"],
                    "capture": ["semantic_snapshot", "stream_fingerprints", "render_fingerprint"],
                },
            )
            pairs.append(
                PairSpec(
                    pair_id=_pair_id(a, b),
                    fixture=a.fixture,
                    a=a.op_id,
                    b=b.op_id,
                    domain_a=a.domain,
                    domain_b=b.domain,
                    overlap_targets=overlap,
                    arms=arms,
                    interpretation_contract={
                        "semantic_equal_persistence_equal": "commute_exact_after_reopen",
                        "semantic_equal_persistence_diff": "semantic_commute_persistence_diverges",
                        "semantic_diff": "non_commutative_semantic_or_hidden_precedence",
                        "render_diff_only": "renderer_or_derived-state_divergence",
                        "failure": "inconclusive",
                    },
                )
            )

    pairs.sort(key=lambda p: (p.fixture, p.a, p.b))
    return pairs, {
        "operations": len(ops),
        "pairs_considered": considered,
        "pairs_rejected": rejected,
        "pairs_emitted": len(pairs),
    }


def _canon(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _canon(value[k]) for k in sorted(value)}
    if isinstance(value, list):
        return [_canon(x) for x in value]
    return value


def _eq(a: Any, b: Any) -> bool:
    return _canon(a) == _canon(b)


def classify_pair(row: dict[str, Any]) -> dict[str, Any]:
    ab = row.get("AB") or {}
    ba = row.get("BA") or {}

    for arm_name, arm in (("AB", ab), ("BA", ba)):
        if not arm or arm.get("status", "ok") != "ok":
            return {
                "classification": "inconclusive",
                "reason": f"{arm_name} missing or failed",
            }

    sem_equal = _eq(ab.get("semantic_fingerprint"), ba.get("semantic_fingerprint"))
    persist_equal = _eq(ab.get("persistence_fingerprint"), ba.get("persistence_fingerprint"))
    render_equal = _eq(ab.get("render_fingerprint"), ba.get("render_fingerprint"))

    if sem_equal and persist_equal and render_equal:
        c = "commute_exact_after_reopen"
    elif sem_equal and not persist_equal:
        c = "semantic_commute_persistence_diverges"
    elif sem_equal and persist_equal and not render_equal:
        c = "renderer_or_derived-state_divergence"
    else:
        c = "non_commutative_semantic_or_hidden_precedence"

    return {
        "classification": c,
        "semantic_equal": sem_equal,
        "persistence_equal": persist_equal,
        "render_equal": render_equal,
    }


def generate_mode(catalog: Path, out: Path) -> int:
    data = json.loads(catalog.read_text(encoding="utf-8-sig"))
    ops = load_operations(data)
    pairs, stats = generate_pairs(ops)
    payload = {
        "schema": "chaptera.pub.operation-algebra.v1",
        "source_catalog": str(catalog),
        "policy": {
            "native_execution": False,
            "pair_selection": "bounded/high-information only",
            "semantic_claim_boundary": (
                "Classification is only meaningful after both arms complete native "
                "Save/Close/Reopen and produce comparable semantic and persistence receipts."
            ),
        },
        "stats": stats,
        "pairs": [asdict(x) for x in pairs],
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0


def classify_mode(results: Path, out: Path) -> int:
    data = json.loads(results.read_text(encoding="utf-8-sig"))
    rows = data.get("pairs", data) if isinstance(data, dict) else data
    if not isinstance(rows, list):
        raise ValueError("results must be list or {'pairs': [...]}")

    classified = []
    counts: dict[str, int] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        verdict = classify_pair(row)
        cls = verdict["classification"]
        counts[cls] = counts.get(cls, 0) + 1
        classified.append({
            "pair_id": row.get("pair_id"),
            "a": row.get("a"),
            "b": row.get("b"),
            **verdict,
        })

    payload = {
        "schema": "chaptera.pub.operation-algebra-results.v1",
        "source_results": str(results),
        "counts": counts,
        "results": classified,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("generate")
    g.add_argument("catalog", type=Path)
    g.add_argument("--out", type=Path, required=True)

    c = sub.add_parser("classify")
    c.add_argument("results", type=Path)
    c.add_argument("--out", type=Path, required=True)

    ns = ap.parse_args()
    if ns.cmd == "generate":
        return generate_mode(ns.catalog, ns.out)
    return classify_mode(ns.results, ns.out)


if __name__ == "__main__":
    raise SystemExit(main())
