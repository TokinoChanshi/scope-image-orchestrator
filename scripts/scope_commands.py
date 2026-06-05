#!/usr/bin/env python3
"""Command-mode helpers for SCOPE Image Orchestrator.

This wrapper keeps the human-facing command set small while delegating actual
image work to generate_single_v2.py and the unified preset library.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT_ROOT = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_ROOT.parent
DEFAULT_PRESET_FILE = SKILL_ROOT / "references" / "scope-preset-library.json"
RUNNER = SCRIPT_ROOT / "generate_single_v2.py"


def load_library(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"preset library not found: {path}")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def compact_route(route: str, cfg: dict[str, Any]) -> dict[str, Any]:
    return {
        "route": route,
        "route_hint": cfg.get("route_hint"),
        "aspect_ratio": cfg.get("aspect_ratio"),
        "route_keywords": cfg.get("route_keywords", []),
        "fallback_prompt": cfg.get("fallback_prompt"),
        "negative": cfg.get("negative"),
        "style_blocks": cfg.get("style_blocks", []),
        "booster_lines": cfg.get("booster_lines", []),
        "external_patterns": cfg.get("external_patterns", []),
        "composition_patterns": cfg.get("composition_patterns", []),
        "quality_controls": cfg.get("quality_controls", []),
    }


def list_presets(args: argparse.Namespace) -> int:
    lib = load_library(args.preset_file)
    routes = lib.get("routes", {})
    selected = [args.route] if args.route else list(routes.keys())
    records = []
    for route in selected:
        cfg = routes.get(route)
        if not isinstance(cfg, dict):
            continue
        record = compact_route(route, cfg)
        if not args.detail:
            record = {
                "route": record["route"],
                "aspect_ratio": record["aspect_ratio"],
                "route_hint": record["route_hint"],
                "route_keywords": record["route_keywords"],
            }
        records.append(record)
    if args.format == "json":
        print(json.dumps(records, ensure_ascii=False, indent=2))
        return 0
    for record in records:
        print(f"## {record['route']}")
        print(f"- aspect_ratio: {record.get('aspect_ratio')}")
        print(f"- route_hint: {record.get('route_hint')}")
        keywords = record.get("route_keywords") or []
        if keywords:
            print("- route_keywords: " + ", ".join(str(x) for x in keywords[:24]))
        if args.detail:
            for key in ("fallback_prompt", "negative"):
                if record.get(key):
                    print(f"- {key}: {record[key]}")
            for key in ("style_blocks", "booster_lines", "external_patterns", "composition_patterns", "quality_controls"):
                values = record.get(key) or []
                if values:
                    print(f"- {key}:")
                    for item in values[:12]:
                        print(f"  - {item}")
        print()
    return 0


def append_if(cmd: list[str], flag: str, value: Any) -> None:
    if value is None or value == "":
        return
    cmd.extend([flag, str(value)])


def run_child(cmd: list[str], dry_print: bool = False) -> int:
    print("[CMD]", " ".join(cmd), flush=True)
    if dry_print:
        return 0
    return subprocess.run(cmd, check=False).returncode


def base_runner_cmd(args: argparse.Namespace, out_dir: Path) -> list[str]:
    cmd = [sys.executable, str(RUNNER), "--env-file", str(args.env_file), "--user-prompt", args.user_prompt, "--out-dir", str(out_dir)]
    append_if(cmd, "--llm-env-file", args.llm_env_file)
    append_if(cmd, "--vision-env-file", args.vision_env_file)
    append_if(cmd, "--llm-model", args.llm_model)
    append_if(cmd, "--vision-model", args.vision_model)
    append_if(cmd, "--image-model", args.image_model)
    append_if(cmd, "--route", args.route)
    append_if(cmd, "--max-generation-attempts", args.max_generation_attempts)
    append_if(cmd, "--response-formats", args.response_formats)
    append_if(cmd, "--max-prompt-chars", args.max_prompt_chars)
    append_if(cmd, "--timeout", args.timeout)
    if getattr(args, "dry_run", False):
        cmd.append("--dry-run")
    return cmd


def batch_run(args: argparse.Namespace) -> int:
    args.out_dir.mkdir(parents=True, exist_ok=True)
    summary: list[dict[str, Any]] = []
    for idx in range(1, args.count + 1):
        item_dir = args.out_dir / f"item_{idx:03d}"
        cmd = base_runner_cmd(args, item_dir)
        rc = run_child(cmd, dry_print=args.print_only)
        summary.append({"index": idx, "out_dir": str(item_dir), "returncode": rc})
        (args.out_dir / "batch_command_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        if rc != 0 and not args.keep_going:
            return rc
    return 0


def reference_run(args: argparse.Namespace) -> int:
    cmd = base_runner_cmd(args, args.out_dir)
    append_if(cmd, "--reference-image", args.reference_image)
    append_if(cmd, "--reference-mode", args.reference_mode)
    return run_child(cmd, dry_print=args.print_only)


def print_commands(_: argparse.Namespace) -> int:
    print("""SCOPE Image Orchestrator command mode

Chinese command aliases used by the skill:
- 生图优化: enter command mode in the current thread
- 查看预设 [route]: list route presets from references/scope-preset-library.json
- 批量跑 N 张 <prompt>: run generate_single_v2.py N times
- 参考生图 <image> <prompt>: run with --reference-image
- 单张跑 / 跑图 <prompt>: run generate_single_v2.py once
- 严格链路 <prompt>: use run_scope_pipeline.py
- 回归测试: use run_v2_route_regression.py
- 审核 <image_root>: use audit_generated_images_with_vision.py
- 退出生图优化: leave command mode
""")
    return 0


def add_common_run_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--env-file", required=True, type=Path)
    parser.add_argument("--user-prompt", required=True)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--llm-env-file", type=Path)
    parser.add_argument("--vision-env-file", type=Path)
    parser.add_argument("--llm-model", default="gpt-5.5")
    parser.add_argument("--vision-model", default="grok-4.3")
    parser.add_argument("--image-model", default="gpt-image-2")
    parser.add_argument("--route", default="auto")
    parser.add_argument("--max-generation-attempts", type=int, default=3)
    parser.add_argument("--response-formats", default="b64_json,url")
    parser.add_argument("--max-prompt-chars", type=int, default=900)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--print-only", action="store_true", help="Print child commands without running them.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Command helpers for SCOPE Image Orchestrator.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_cmds = sub.add_parser("commands", help="Print command-mode aliases.")
    p_cmds.set_defaults(func=print_commands)

    p_list = sub.add_parser("list-presets", help="List route presets from the unified preset library.")
    p_list.add_argument("--preset-file", type=Path, default=DEFAULT_PRESET_FILE)
    p_list.add_argument("--route", help="Optional single route, e.g. bathroom, poster, product.")
    p_list.add_argument("--format", choices=["markdown", "json"], default="markdown")
    p_list.add_argument("--detail", action="store_true", help="Include fallback prompts, negatives, and distilled prompt patterns.")
    p_list.set_defaults(func=list_presets)

    p_batch = sub.add_parser("batch-run", help="Run the same prompt multiple times through generate_single_v2.py.")
    add_common_run_args(p_batch)
    p_batch.add_argument("--count", type=int, required=True)
    p_batch.add_argument("--keep-going", action="store_true")
    p_batch.set_defaults(func=batch_run)

    p_ref = sub.add_parser("reference-run", help="Run one image generation with a reference image.")
    add_common_run_args(p_ref)
    p_ref.add_argument("--reference-image", required=True, type=Path)
    p_ref.add_argument("--reference-mode", default="auto", choices=["auto", "style", "composition", "identity", "character", "product"])
    p_ref.set_defaults(func=reference_run)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
