#!/usr/bin/env python3
"""Offline release checks for SCOPE Image Orchestrator.

This script is intentionally network-free. It validates syntax, provider
configuration, adapter payload rendering, response extraction, preset routes,
and representative dry-run prompts.

Usage:
    python scripts/run_release_checks.py --out-dir .codex_tmp/scope_release_checks
    python scripts/run_release_checks.py --out-dir .codex_tmp/scope_release_checks --skip-dry-run
"""
from __future__ import annotations

import argparse
import base64
import json
import pathlib
import py_compile
import tempfile
import shutil
import subprocess
import sys
from typing import Any

SCRIPT_ROOT = pathlib.Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_ROOT.parent
REFERENCES = SKILL_ROOT / "references"
PROVIDER_CONFIG = REFERENCES / "provider-config.example.json"
PRESET_FILE = REFERENCES / "scope-preset-library.json"
CASES_FILE = REFERENCES / "release-test-cases.json"

sys.path.insert(0, str(SCRIPT_ROOT))

from api_adapters import (  # noqa: E402
    build_image_request,
    build_text_request,
    build_vision_request,
    extract_image_items,
    normalize_adapter,
)
from render_provider_payload import load_config, render  # noqa: E402


TINY_PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
EXPECTED_ROUTES = {"portrait", "magazine", "poster", "cosplay", "interior", "product", "bathroom"}


def ok(message: str) -> None:
    print(f"[OK] {message}")


def fail(failures: list[str], message: str) -> None:
    print(f"[FAIL] {message}")
    failures.append(message)


def run_cmd(argv: list[str], cwd: pathlib.Path, failures: list[str], label: str) -> subprocess.CompletedProcess[str] | None:
    proc = subprocess.run(argv, cwd=str(cwd), text=True, capture_output=True)  # noqa: S603
    if proc.returncode != 0:
        fail(failures, f"{label} exited {proc.returncode}: {proc.stderr.strip() or proc.stdout.strip()}")
        return None
    ok(label)
    return proc


def load_json(path: pathlib.Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_tiny_png(path: pathlib.Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(base64.b64decode(TINY_PNG_B64))


def compile_scripts(failures: list[str]) -> None:
    for path in sorted(SCRIPT_ROOT.glob("*.py")):
        try:
            with tempfile.TemporaryDirectory() as td:
                py_compile.compile(
                    str(path),
                    doraise=True,
                    cfile=str(pathlib.Path(td) / f"{path.stem}.pyc"),
                )
        except Exception as exc:  # noqa: BLE001
            fail(failures, f"compile failed: {path.name}: {exc}")
    if not failures:
        ok(f"compiled {len(list(SCRIPT_ROOT.glob('*.py')))} scripts")


def validate_provider_config(failures: list[str]) -> dict[str, Any]:
    run_cmd([sys.executable, str(SCRIPT_ROOT / "validate_provider_config.py"), str(PROVIDER_CONFIG)], SKILL_ROOT, failures, "provider config validation")
    cfg = load_config(PROVIDER_CONFIG)
    roles = cfg.get("roles", {})
    for role in sorted(roles):
        try:
            rendered = render(cfg, role, "release test prompt", "Return concise JSON.", "1024x1024", 1)
        except Exception as exc:  # noqa: BLE001
            fail(failures, f"render provider role failed: {role}: {exc}")
            continue
        for key in ("role", "provider", "adapter", "endpoint", "headers", "payload"):
            if key not in rendered:
                fail(failures, f"rendered role {role} missing key: {key}")
    ok(f"rendered {len(roles)} provider roles")
    return cfg


def validate_spec_sample(out_dir: pathlib.Path, failures: list[str]) -> None:
    sample = {
        "version": "scope-spec-v1",
        "prompt": "release test prompt",
        "entities": [
            {"id": "person_1", "name": "portrait subject", "description": "camera-facing person", "priority": "critical"},
            {"id": "object_1", "name": "prop", "description": "camera-facing prop", "priority": "important"}
        ],
        "constraints": [
            {"id": "c1", "type": "style", "text": "cinematic lighting", "depends_on": ["person_1"], "priority": "important"},
            {"id": "c2", "type": "layout", "text": "vertical 2:3 frame", "depends_on": [], "priority": "important"}
        ],
        "unknowns": []
    }
    sample_path = out_dir / "sample_scope_spec.json"
    sample_path.parent.mkdir(parents=True, exist_ok=True)
    sample_path.write_text(json.dumps(sample, ensure_ascii=False, indent=2), encoding="utf-8")
    run_cmd([sys.executable, str(SCRIPT_ROOT / "validate_scope_spec.py"), str(sample_path)], SKILL_ROOT, failures, "sample SCOPE spec validation")


def validate_presets(failures: list[str]) -> None:
    presets = load_json(PRESET_FILE)
    if isinstance(presets, dict) and isinstance(presets.get("routes"), dict):
        routes = set(presets["routes"].keys())
    elif isinstance(presets, dict):
        routes = set(presets.keys())
    else:
        fail(failures, "preset library root must be an object")
        return
    missing = sorted(EXPECTED_ROUTES - routes)
    if missing:
        fail(failures, f"preset library missing routes: {missing}")
    else:
        ok(f"preset routes present: {', '.join(sorted(EXPECTED_ROUTES))}")


def assert_payload_case(case: dict[str, Any], tiny_image: pathlib.Path, failures: list[str]) -> None:
    adapter = case["adapter"]
    kind = case["kind"]
    env = dict(case.get("env") or {})
    base_url = case.get("base_url", "https://example.test/v1")
    model = case.get("model", "release-test-model")
    api_key = "test_key"
    prompt = "release test prompt"
    system = "Return concise JSON."
    if kind == "text":
        url, _headers, payload, normalized = build_text_request(adapter, base_url, api_key, model, system, prompt, env)
    elif kind == "vision":
        url, _headers, payload, normalized = build_vision_request(adapter, base_url, api_key, model, system, prompt, [tiny_image], env)
    elif kind == "image":
        url, _headers, payload, normalized = build_image_request(adapter, base_url, api_key, model, prompt, env)
    else:
        fail(failures, f"{case['id']} has unsupported kind: {kind}")
        return

    expected_adapter = normalize_adapter(adapter, adapter)
    if normalized != expected_adapter:
        fail(failures, f"{case['id']} normalized adapter mismatch: {normalized} != {expected_adapter}")
    expected_endpoint = case.get("expect_endpoint_contains")
    if expected_endpoint and expected_endpoint not in url:
        fail(failures, f"{case['id']} endpoint missing {expected_endpoint!r}: {url}")
    for key in case.get("expect_payload_keys", []):
        if key not in payload:
            fail(failures, f"{case['id']} payload missing key: {key}")
    for key in case.get("forbid_payload_keys", []):
        if key in payload:
            fail(failures, f"{case['id']} payload should not include key: {key}")
    if kind == "image" and normalized == "openai-images" and "response_format" in payload:
        fail(failures, f"{case['id']} current OpenAI Images payload must not send response_format")


def validate_adapter_cases(out_dir: pathlib.Path, failures: list[str]) -> dict[str, Any]:
    cases = load_json(CASES_FILE)
    if cases.get("schema_version") != "scope-release-tests-v1":
        fail(failures, "release-test-cases.json schema_version mismatch")
    tiny_image = out_dir / "tiny.png"
    write_tiny_png(tiny_image)
    for case in cases.get("adapter_payload_cases", []):
        try:
            assert_payload_case(case, tiny_image, failures)
        except Exception as exc:  # noqa: BLE001
            fail(failures, f"{case.get('id', '<unknown>')} raised {exc!r}")
    ok(f"adapter payload cases checked: {len(cases.get('adapter_payload_cases', []))}")
    return cases


def validate_response_extraction(cases: dict[str, Any], failures: list[str]) -> None:
    count = 0
    for case in cases.get("response_extraction_cases", []):
        items = extract_image_items(case.get("body"))
        count += 1
        expected_count = int(case.get("expected_count", 0))
        expected_field = case.get("expected_field")
        if len(items) != expected_count:
            fail(failures, f"{case['id']} expected {expected_count} extracted image(s), got {len(items)}")
            continue
        if expected_field and items and expected_field not in items[0]:
            fail(failures, f"{case['id']} expected field {expected_field!r}, got {items[0]}")
    ok(f"response extraction cases checked: {count}")


def write_fake_env(path: pathlib.Path) -> None:
    path.write_text(
        "\n".join(
            [
                "SCOPE_IMAGE_FORMAT=openai-images",
                "SCOPE_IMAGE_BASE_URL=https://api.openai.com/v1",
                "SCOPE_IMAGE_API_KEY=test_key",
                "SCOPE_IMAGE_MODEL=gpt-image-2",
                "SCOPE_LLM_FORMAT=openai-responses",
                "SCOPE_LLM_BASE_URL=https://api.openai.com/v1",
                "SCOPE_LLM_API_KEY=test_key",
                "SCOPE_LLM_MODEL=gpt-5.5",
                "SCOPE_VISION_FORMAT=openai-responses",
                "SCOPE_VISION_BASE_URL=https://api.openai.com/v1",
                "SCOPE_VISION_API_KEY=test_key",
                "SCOPE_VISION_MODEL=gpt-5.5",
                "",
            ]
        ),
        encoding="utf-8",
    )


def validate_dry_runs(cases: dict[str, Any], out_dir: pathlib.Path, failures: list[str]) -> None:
    fake_env = out_dir / "release_fake.env"
    write_fake_env(fake_env)
    dry_root = out_dir / "dry_runs"
    if dry_root.exists():
        shutil.rmtree(dry_root)
    dry_root.mkdir(parents=True, exist_ok=True)
    checked = 0
    for case in cases.get("dry_run_prompts", []):
        case_dir = dry_root / case["id"]
        argv = [
            sys.executable,
            str(SCRIPT_ROOT / "generate_single_v2.py"),
            "--env-file",
            str(fake_env),
            "--user-prompt",
            case["prompt"],
            "--out-dir",
            str(case_dir),
            "--route",
            case["route"],
            "--dry-run",
        ]
        proc = run_cmd(argv, SKILL_ROOT, failures, f"dry-run prompt {case['id']}")
        if proc is None:
            continue
        summary_path = case_dir / "final_summary.json"
        if not summary_path.exists():
            fail(failures, f"{case['id']} did not write final_summary.json")
            continue
        summary = load_json(summary_path)
        if not summary.get("dry_run"):
            fail(failures, f"{case['id']} summary is not marked dry_run")
        if summary.get("route") != case["route"]:
            fail(failures, f"{case['id']} route mismatch: {summary.get('route')} != {case['route']}")
        checked += 1
    ok(f"dry-run prompt cases checked: {checked}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run offline release checks for SCOPE Image Orchestrator.")
    parser.add_argument("--out-dir", required=True, type=pathlib.Path, help="Directory for temporary release-check artifacts.")
    parser.add_argument("--skip-dry-run", action="store_true", help="Skip generate_single_v2.py dry-run prompt cases.")
    parser.add_argument("--skip-compile", action="store_true", help="Skip Python compilation checks.")
    args = parser.parse_args(argv)

    out_dir = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    failures: list[str] = []

    if args.skip_compile:
        ok("script compilation check skipped")
    else:
        compile_scripts(failures)
    validate_provider_config(failures)
    validate_spec_sample(out_dir, failures)
    validate_presets(failures)
    cases = validate_adapter_cases(out_dir, failures)
    validate_response_extraction(cases, failures)
    if args.skip_dry_run:
        ok("dry-run prompt cases skipped")
    else:
        validate_dry_runs(cases, out_dir, failures)

    if failures:
        print(f"[FAIL] release checks failed: {len(failures)} issue(s)")
        return 1
    print("[OK] release checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
