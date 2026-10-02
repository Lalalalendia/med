#!/usr/bin/env python3
"""
Compile a static MSPUB.TLB inventory into a conservative native experiment matrix.

This tool does not invoke Publisher. It only turns static type-library metadata into
candidate experiment specifications that a separate Windows/native harness may run.

Design goals:
- fail closed;
- emit only PROPERTYPUT / PROPERTYPUTREF members by default;
- exclude object/array/pointer/VARIANT/string surfaces from the default safe queue;
- keep hidden/restricted/nonbrowsable members out unless explicitly requested;
- never infer PUB on-disk semantics from TLB metadata alone.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterable

SAFE_SCALARS = {
    "VT_BOOL",
    "VT_I1", "VT_I2", "VT_I4", "VT_I8", "VT_INT",
    "VT_UI1", "VT_UI2", "VT_UI4", "VT_UI8", "VT_UINT",
    "VT_R4", "VT_R8",
}

RISKY_NAME_RE = re.compile(
    r"(delete|remove|close|quit|save|open|print|mail|send|export|import|"
    r"insert|add|unlink|link|convert|replace|move|copy|execute|run|publish|"
    r"merge|split|group|ungroup)",
    re.IGNORECASE,
)

PUT_KINDS = {"INVOKE_PROPERTYPUT", "INVOKE_PROPERTYPUTREF", "PROPERTYPUT", "PROPERTYPUTREF"}


@dataclass(frozen=True)
class Candidate:
    type_name: str
    member_name: str
    dispid: int | str | None
    invkind: str
    value_type: str
    hidden: bool
    restricted: bool
    nonbrowsable: bool
    risk: str
    risk_reasons: list[str]
    experiment_id: str
    arms: list[dict[str, Any]]
    evidence_boundary: str = (
        "TLB candidate only. A native Save/Close/Reopen experiment plus persisted-byte "
        "and reopened semantic evidence is required before any PUB-format claim."
    )


def _norm_token(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return "|".join(_norm_token(x) for x in value)
    return str(value).strip()


def _first(d: dict[str, Any], *keys: str) -> Any:
    for k in keys:
        if k in d and d[k] not in (None, "", []):
            return d[k]
    return None


def _boolish(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    return s in {"1", "true", "yes", "hidden", "restricted", "nonbrowsable"}


def _extract_flags(d: dict[str, Any]) -> tuple[bool, bool, bool]:
    raw = _first(d, "flags", "func_flags", "funcFlags", "named_flags", "namedFlags")
    tokens = _norm_token(raw).upper()
    hidden = _boolish(d.get("hidden")) or "HIDDEN" in tokens
    restricted = _boolish(d.get("restricted")) or "RESTRICTED" in tokens
    nonbrowsable = _boolish(d.get("nonbrowsable")) or "NONBROWSABLE" in tokens
    return hidden, restricted, nonbrowsable


def _extract_name(d: dict[str, Any]) -> str:
    direct = _first(d, "member_name", "memberName", "name")
    if isinstance(direct, str) and direct:
        return direct
    names = _first(d, "names", "Names")
    if isinstance(names, list) and names:
        return str(names[0])
    return ""


def _extract_type_name(d: dict[str, Any], parents: list[dict[str, Any]]) -> str:
    direct = _first(d, "type_name", "typeName", "interface_name", "interfaceName", "owner")
    if direct:
        return str(direct)
    for p in reversed(parents):
        v = _first(p, "type_name", "typeName", "name")
        if isinstance(v, str) and v:
            return v
    return "<unknown-type>"


def _extract_invkind(d: dict[str, Any]) -> str:
    return _norm_token(_first(d, "invkind", "invoke_kind", "invokeKind", "invocation_kind", "invocationKind")).upper()


def _extract_dispid(d: dict[str, Any]) -> int | str | None:
    return _first(d, "dispid", "memid", "member_id", "memberId", "id")


def _extract_params(d: dict[str, Any]) -> list[Any]:
    p = _first(d, "params", "parameters", "args", "arguments")
    return p if isinstance(p, list) else []


def _type_token(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, str):
        return v.upper()
    if isinstance(v, dict):
        # Common dump shapes: {"vt":"VT_I4"}, {"kind":"VT_USERDEFINED","name":"PbFoo"}
        for k in ("vt", "vartype", "var_type", "type", "kind", "name", "display"):
            if k in v and v[k]:
                return _type_token(v[k])
        return json.dumps(v, sort_keys=True).upper()
    return str(v).upper()


def _extract_value_type(d: dict[str, Any]) -> str:
    params = _extract_params(d)
    if params:
        # PROPERTYPUT value is conventionally the last argument; indexed properties may
        # have earlier index args. We only use the last arg to classify the set value.
        last = params[-1]
        if isinstance(last, dict):
            return _type_token(_first(last, "type", "vartype", "var_type", "vt", "typedesc", "type_desc"))
        return _type_token(last)

    # Some inventories flatten the setter argument.
    return _type_token(
        _first(d, "value_type", "valueType", "param_type", "paramType", "parameter_type", "parameterType")
    )


def _looks_like_function_record(d: dict[str, Any]) -> bool:
    inv = _extract_invkind(d)
    if inv:
        return True
    keys = {k.lower() for k in d}
    return bool({"memid", "dispid"} & keys and {"params", "parameters", "funckind", "invkind"} & keys)


def _walk(node: Any, parents: list[dict[str, Any]] | None = None) -> Iterable[tuple[dict[str, Any], list[dict[str, Any]]]]:
    parents = parents or []
    if isinstance(node, dict):
        if _looks_like_function_record(node):
            yield node, parents
        new_parents = parents + [node]
        for v in node.values():
            yield from _walk(v, new_parents)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v, parents)


def _classify_value_type(token: str) -> tuple[str, list[str]]:
    t = token.upper()
    if any(x in t for x in ("PTR", "ARRAY", "SAFEARRAY", "BYREF", "DISPATCH", "UNKNOWN", "VARIANT", "BSTR")):
        return "blocked", [f"non-scalar-or-reference:{token or '<unknown>'}"]
    if "USERDEFINED" in t or "ENUM" in t or t.startswith("PB"):
        return "candidate", [f"enum-or-userdefined:{token}"]
    if t in SAFE_SCALARS:
        return "candidate", []
    return "blocked", [f"unsupported-value-type:{token or '<unknown>'}"]


def _changed_value_strategy(value_type: str) -> dict[str, Any]:
    t = value_type.upper()
    if "BOOL" in t:
        return {"kind": "toggle_bool"}
    if "USERDEFINED" in t or "ENUM" in t or t.startswith("PB"):
        return {"kind": "alternate_enum_value", "rule": "choose one valid value != current"}
    if any(x in t for x in ("I1", "I2", "I4", "I8", "INT", "UI1", "UI2", "UI4", "UI8", "UINT", "R4", "R8")):
        return {"kind": "bounded_numeric_delta", "delta": 1, "rule": "respect documented/runtime-valid range"}
    return {"kind": "manual"}


def _experiment_id(type_name: str, member_name: str, dispid: Any) -> str:
    raw = f"{type_name}-{member_name}-{dispid}"
    slug = re.sub(r"[^A-Za-z0-9]+", "-", raw).strip("-").upper()
    return f"TLB-AUTO-{slug}"


def compile_candidates(data: Any, *, include_hidden: bool = False) -> tuple[list[Candidate], dict[str, int]]:
    out: list[Candidate] = []
    stats = {
        "function_records_seen": 0,
        "property_put_seen": 0,
        "excluded_hidden_or_restricted": 0,
        "excluded_name_risk": 0,
        "excluded_type_risk": 0,
        "candidates": 0,
    }
    seen: set[tuple[str, str, str, str]] = set()

    for d, parents in _walk(data):
        stats["function_records_seen"] += 1
        inv = _extract_invkind(d)
        if not any(k in inv for k in PUT_KINDS):
            continue
        stats["property_put_seen"] += 1

        member = _extract_name(d)
        owner = _extract_type_name(d, parents)
        dispid = _extract_dispid(d)
        hidden, restricted, nonbrowsable = _extract_flags(d)
        value_type = _extract_value_type(d)

        key = (owner, member, str(dispid), inv)
        if key in seen:
            continue
        seen.add(key)

        reasons: list[str] = []
        if hidden or restricted or nonbrowsable:
            reasons.append("metadata-hidden-or-restricted")
            if not include_hidden:
                stats["excluded_hidden_or_restricted"] += 1
                continue

        if not member:
            reasons.append("missing-member-name")
        if RISKY_NAME_RE.search(member):
            reasons.append("destructive-or-lifecycle-name")
            stats["excluded_name_risk"] += 1
            continue

        risk, type_reasons = _classify_value_type(value_type)
        reasons.extend(type_reasons)
        if risk == "blocked":
            stats["excluded_type_risk"] += 1
            continue

        arms = [
            {"name": "control", "operation": "no_semantic_mutation_then_save_reopen"},
            {"name": "same_value", "operation": "read_current_then_set_same_value_save_reopen"},
            {
                "name": "changed_value",
                "operation": "set_changed_value_save_reopen",
                "value_strategy": _changed_value_strategy(value_type),
            },
        ]
        out.append(
            Candidate(
                type_name=owner,
                member_name=member,
                dispid=dispid,
                invkind=inv,
                value_type=value_type,
                hidden=hidden,
                restricted=restricted,
                nonbrowsable=nonbrowsable,
                risk="review-required",
                risk_reasons=reasons,
                experiment_id=_experiment_id(owner, member, dispid),
                arms=arms,
            )
        )

    stats["candidates"] = len(out)
    out.sort(key=lambda x: (x.type_name, x.member_name, str(x.dispid)))
    return out, stats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("inventory", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--include-hidden", action="store_true")
    ns = ap.parse_args()

    data = json.loads(ns.inventory.read_text(encoding="utf-8-sig"))
    candidates, stats = compile_candidates(data, include_hidden=ns.include_hidden)

    payload = {
        "schema": "chaptera.pub.tlb-experiment-matrix.v1",
        "source_inventory": str(ns.inventory),
        "policy": {
            "mode": "generate-only",
            "native_execution": False,
            "default_hidden_members": "excluded",
            "semantic_claim_boundary": (
                "Generated experiments are hypotheses only. Native Publisher execution, "
                "Save/Close/Reopen, persisted-byte attribution, and reopened semantic evidence "
                "are required before promotion."
            ),
        },
        "stats": stats,
        "experiments": [asdict(x) for x in candidates],
    }
    ns.out.parent.mkdir(parents=True, exist_ok=True)
    ns.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
