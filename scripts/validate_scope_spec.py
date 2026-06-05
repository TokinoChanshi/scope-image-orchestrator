#!/usr/bin/env python3
"""Validate a minimal SCOPE image orchestration specification.

Usage:
    python scripts/validate_scope_spec.py specification.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ALLOWED_ENTITY_PRIORITIES = {"critical", "important", "nice_to_have"}
ALLOWED_CONSTRAINT_TYPES = {"attribute", "relation", "layout", "style", "text", "factual"}
ALLOWED_UNKNOWN_METHODS = {"retrieval", "reasoning", "user", "none"}
ALLOWED_UNKNOWN_STATUS = {"open", "resolved", "deferred"}


def fail(msg: str) -> None:
    print(f"[FAIL] {msg}")
    raise SystemExit(1)


def warn(msg: str) -> None:
    print(f"[WARN] {msg}")


def require_obj(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        fail(f"{name} must be an object")
    return value


def require_list(value: Any, name: str) -> list[Any]:
    if not isinstance(value, list):
        fail(f"{name} must be a list")
    return value


def require_str(obj: dict[str, Any], key: str, owner: str) -> str:
    value = obj.get(key)
    if not isinstance(value, str) or not value.strip():
        fail(f"{owner}.{key} must be a non-empty string")
    return value


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[1] in {"-h", "--help"}:
        print(__doc__.strip())
        return 0 if len(argv) == 2 and argv[1] in {"-h", "--help"} else 2

    path = Path(argv[1])
    try:
        spec = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:  # noqa: BLE001 - CLI validation utility
        fail(f"could not read JSON: {exc}")

    spec = require_obj(spec, "root")
    version = spec.get("version", "")
    if version != "scope-spec-v1":
        warn("version should be 'scope-spec-v1'")
    require_str(spec, "prompt", "root")

    entities = require_list(spec.get("entities"), "entities")
    constraints = require_list(spec.get("constraints"), "constraints")
    unknowns = require_list(spec.get("unknowns", []), "unknowns")

    entity_ids: set[str] = set()
    for i, item in enumerate(entities):
        ent = require_obj(item, f"entities[{i}]")
        ent_id = require_str(ent, "id", f"entities[{i}]")
        if ent_id in entity_ids:
            fail(f"duplicate entity id: {ent_id}")
        entity_ids.add(ent_id)
        require_str(ent, "name", ent_id)
        require_str(ent, "description", ent_id)
        priority = ent.get("priority", "important")
        if priority not in ALLOWED_ENTITY_PRIORITIES:
            fail(f"{ent_id}.priority must be one of {sorted(ALLOWED_ENTITY_PRIORITIES)}")

    constraint_ids: set[str] = set()
    for i, item in enumerate(constraints):
        con = require_obj(item, f"constraints[{i}]")
        con_id = require_str(con, "id", f"constraints[{i}]")
        if con_id in constraint_ids:
            fail(f"duplicate constraint id: {con_id}")
        constraint_ids.add(con_id)
        ctype = require_str(con, "type", con_id)
        if ctype not in ALLOWED_CONSTRAINT_TYPES:
            fail(f"{con_id}.type must be one of {sorted(ALLOWED_CONSTRAINT_TYPES)}")
        require_str(con, "text", con_id)
        depends_on = require_list(con.get("depends_on", []), f"{con_id}.depends_on")
        for dep in depends_on:
            if dep not in entity_ids:
                fail(f"{con_id}.depends_on references unknown entity id: {dep}")
        priority = con.get("priority", "important")
        if priority not in ALLOWED_ENTITY_PRIORITIES:
            fail(f"{con_id}.priority must be one of {sorted(ALLOWED_ENTITY_PRIORITIES)}")

    owner_ids = {"prompt", *entity_ids, *constraint_ids}
    unknown_ids: set[str] = set()
    for i, item in enumerate(unknowns):
        unk = require_obj(item, f"unknowns[{i}]")
        unk_id = require_str(unk, "id", f"unknowns[{i}]")
        if unk_id in unknown_ids:
            fail(f"duplicate unknown id: {unk_id}")
        unknown_ids.add(unk_id)
        owner = require_str(unk, "owner", unk_id)
        if owner not in owner_ids:
            fail(f"{unk_id}.owner references unknown owner: {owner}")
        require_str(unk, "question", unk_id)
        method = unk.get("resolution_method", "reasoning")
        if method not in ALLOWED_UNKNOWN_METHODS:
            fail(f"{unk_id}.resolution_method must be one of {sorted(ALLOWED_UNKNOWN_METHODS)}")
        status = unk.get("status", "open")
        if status not in ALLOWED_UNKNOWN_STATUS:
            fail(f"{unk_id}.status must be one of {sorted(ALLOWED_UNKNOWN_STATUS)}")
        if status == "resolved" and not unk.get("answer"):
            warn(f"{unk_id} is resolved but has no answer")

    print(f"[OK] {path}: {len(entity_ids)} entities, {len(constraint_ids)} constraints, {len(unknown_ids)} unknowns")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
