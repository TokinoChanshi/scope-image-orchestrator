#!/usr/bin/env python3
"""Command-mode helpers for SCOPE Image Orchestrator.

This wrapper keeps the human-facing command set small while delegating actual
image work to existing runner scripts.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

SCRIPT_ROOT = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_ROOT.parent
DEFAULT_PRESET_FILE = SKILL_ROOT / "references" / "scope-preset-library.json"
RUNNER = SCRIPT_ROOT / "generate_single_v2.py"
SCOPE_PIPELINE = SCRIPT_ROOT / "run_scope_pipeline.py"
REGRESSION_RUNNER = SCRIPT_ROOT / "run_v2_route_regression.py"
AUDIT_RUNNER = SCRIPT_ROOT / "audit_generated_images_with_vision.py"
VIDEO_RUNNER = SCRIPT_ROOT / "generate_video.py"
VIDEO_STORY_RUNNER = SCRIPT_ROOT / "video_story_pipeline.py"


def ensure_writable_out_dir(requested: Path) -> Path:
    requested = requested.expanduser()

    def can_write_dir(path: Path) -> bool:
        probe = path / ".scope_rw_probe"
        try:
            path.mkdir(parents=True, exist_ok=True)
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return True
        except Exception:
            return False

    candidates = [
        requested,
        (Path.cwd() / requested).resolve(),
        (Path("scope_runs") / requested.name).resolve(),
        (Path(tempfile.gettempdir()) / "scope_image_runs" / requested.name).resolve(),
    ]

    seen: set[str] = set()
    for candidate in candidates:
        normalized = candidate.resolve()
        if str(normalized) in seen:
            continue
        seen.add(str(normalized))
        try:
            if can_write_dir(normalized):
                return normalized
        except OSError:
            continue
    raise RuntimeError(f"cannot create writable directory: {requested}")


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


def compact_theme_pack(theme_pack: str, cfg: dict[str, Any]) -> dict[str, Any]:
    return {
        "theme_pack": theme_pack,
        "bind_routes": cfg.get("bind_routes", []),
        "pack_hint": cfg.get("pack_hint"),
        "activation_keywords": cfg.get("activation_keywords", []),
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


def list_theme_packs(args: argparse.Namespace) -> int:
    lib = load_library(args.preset_file)
    packs = lib.get("image_theme_packs", {})
    selected = [args.theme_pack] if args.theme_pack else list(packs.keys())
    records = []
    for theme_pack in selected:
        cfg = packs.get(theme_pack)
        if not isinstance(cfg, dict):
            continue
        record = compact_theme_pack(theme_pack, cfg)
        if not args.detail:
            record = {
                "theme_pack": record["theme_pack"],
                "bind_routes": record["bind_routes"],
                "pack_hint": record["pack_hint"],
                "activation_keywords": record["activation_keywords"],
            }
        records.append(record)
    if args.format == "json":
        print(json.dumps(records, ensure_ascii=False, indent=2))
        return 0
    for record in records:
        print(f"## {record['theme_pack']}")
        bind_routes = record.get("bind_routes") or []
        if bind_routes:
            print("- bind_routes: " + ", ".join(str(x) for x in bind_routes[:16]))
        print(f"- pack_hint: {record.get('pack_hint')}")
        keywords = record.get("activation_keywords") or []
        if keywords:
            print("- activation_keywords: " + ", ".join(str(x) for x in keywords[:24]))
        if args.detail:
            if record.get("negative"):
                print(f"- negative: {record['negative']}")
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


def run_child_with_optional(cmd: list[str], args: argparse.Namespace, dry_field: str = "print_only") -> int:
    return run_child(cmd, dry_print=bool(getattr(args, dry_field, False)))


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
    args.out_dir = ensure_writable_out_dir(args.out_dir)
    summary: list[dict[str, Any]] = []
    for idx in range(1, args.count + 1):
        item_dir = args.out_dir / f"item_{idx:03d}"
        cmd = base_runner_cmd(args, item_dir)
        rc = run_child_with_optional(cmd, args)
        summary.append({"index": idx, "out_dir": str(item_dir), "returncode": rc})
        (args.out_dir / "batch_command_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        if rc != 0 and not args.keep_going:
            return rc
    return 0


def reference_run(args: argparse.Namespace) -> int:
    args.out_dir = ensure_writable_out_dir(args.out_dir)
    cmd = base_runner_cmd(args, args.out_dir)
    append_if(cmd, "--reference-image", args.reference_image)
    append_if(cmd, "--reference-mode", args.reference_mode)
    return run_child_with_optional(cmd, args)


def strict_chain_run(args: argparse.Namespace) -> int:
    args.out_dir = ensure_writable_out_dir(args.out_dir)
    cmd = [
        sys.executable,
        str(SCOPE_PIPELINE),
        "--env-file",
        str(args.env_file),
        "--user-prompt",
        args.user_prompt,
        "--out-dir",
        str(args.out_dir),
        "--retries",
        str(args.retries),
        "--max-prompt-repair-rounds",
        str(args.max_prompt_repair_rounds),
        "--max-generation-attempts",
        str(args.max_generation_attempts),
        "--timeout",
        str(args.timeout),
    ]
    append_if(cmd, "--llm-model", args.llm_model)
    append_if(cmd, "--vision-model", args.vision_model)
    append_if(cmd, "--image-model", args.image_model)
    if args.llm_env_file:
        cmd.extend(["--llm-env-file", str(args.llm_env_file)])
    if args.vision_provider == "vision":
        cmd.extend(["--vision-provider", "vision"])
        if args.vision_env_file:
            cmd.extend(["--vision-env-file", str(args.vision_env_file)])
    append_if(cmd, "--optimizer-guide", args.optimizer_guide)
    append_if(cmd, "--preset-guide", args.preset_guide)
    return run_child_with_optional(cmd, args)


def regression_run(args: argparse.Namespace) -> int:
    args.out_dir = ensure_writable_out_dir(args.out_dir)
    cmd = [
        sys.executable,
        str(REGRESSION_RUNNER),
        "--env-file",
        str(args.env_file),
        "--out-dir",
        str(args.out_dir),
        "--max-generation-attempts",
        str(args.max_generation_attempts),
        "--image-retries",
        str(args.image_retries),
        "--timeout",
        str(args.timeout),
        "--max-prompt-chars",
        str(args.max_prompt_chars),
        "--response-formats",
        args.response_formats,
    ]
    if args.llm_env_file:
        cmd.extend(["--llm-env-file", str(args.llm_env_file)])
    if args.vision_env_file:
        cmd.extend(["--vision-env-file", str(args.vision_env_file)])
    append_if(cmd, "--image-model", args.image_model)
    append_if(cmd, "--llm-model", args.llm_model)
    append_if(cmd, "--vision-model", args.vision_model)
    append_if(cmd, "--only-categories", args.only_categories)
    append_if(cmd, "--only-cases", args.only_cases)
    append_if(cmd, "--max-cases", args.max_cases)
    append_if(cmd, "--delay", args.delay)
    if args.skip_vision:
        cmd.append("--skip-vision")
    if args.resume:
        cmd.append("--resume")
    if args.dry_run:
        cmd.append("--dry-run")
    return run_child_with_optional(cmd, args)


def audit_run(args: argparse.Namespace) -> int:
    cmd = [
        sys.executable,
        str(AUDIT_RUNNER),
        "--env-file",
        str(args.env_file),
        "--image-root",
        str(args.image_root),
        "--pattern",
        args.pattern,
        "--limit",
        str(args.limit),
        "--timeout",
        str(args.timeout),
        "--delay",
        str(args.delay),
    ]
    append_if(cmd, "--out-file", args.out_file)
    if args.vision_models:
        cmd.extend(["--vision-models", args.vision_models])
    else:
        cmd.extend(["--model", args.model])
    return run_child_with_optional(cmd, args)


def _append_if_not_empty(cmd: list[str], flag: str, value: Any) -> None:
    if value is None:
        return
    if isinstance(value, str) and value == "":
        return
    cmd.extend([flag, str(value)])


def video_run(args: argparse.Namespace) -> int:
    args.out_dir = ensure_writable_out_dir(args.out_dir)
    cmd = [
        sys.executable,
        str(VIDEO_RUNNER),
        "--env-file",
        str(args.env_file),
        "--user-prompt",
        args.user_prompt,
        "--out-dir",
        str(args.out_dir),
        "--route",
        args.route,
        "--duration",
        str(args.duration),
        "--fps",
        str(args.fps),
        "--max-prompt-chars",
        str(args.max_prompt_chars),
        "--timeout",
        str(args.timeout),
        "--preset-file",
        str(args.preset_file),
    ]
    _append_if_not_empty(cmd, "--video-model", args.video_model)
    _append_if_not_empty(cmd, "--aspect-ratio", args.aspect_ratio)
    _append_if_not_empty(cmd, "--response-format", args.response_format)
    _append_if_not_empty(cmd, "--video-request-retries", args.video_request_retries)
    _append_if_not_empty(cmd, "--poll-attempts", args.poll_attempts)
    _append_if_not_empty(cmd, "--poll-delay", args.poll_delay)
    if args.dry_run:
        cmd.append("--dry-run")
    elif args.send:
        cmd.append("--send")
    return run_child_with_optional(cmd, args)


def video_batch(args: argparse.Namespace) -> int:
    if args.count < 1:
        raise SystemExit("--count must be >= 1")
    args.out_dir = ensure_writable_out_dir(args.out_dir)
    cmd = [
        sys.executable,
        str(VIDEO_RUNNER),
        "--env-file",
        str(args.env_file),
        "--user-prompt",
        args.user_prompt,
        "--out-dir",
        str(args.out_dir),
        "--route",
        args.route,
        "--count",
        str(args.count),
        "--duration",
        str(args.duration),
        "--fps",
        str(args.fps),
        "--max-prompt-chars",
        str(args.max_prompt_chars),
        "--timeout",
        str(args.timeout),
        "--preset-file",
        str(args.preset_file),
    ]
    _append_if_not_empty(cmd, "--video-model", args.video_model)
    _append_if_not_empty(cmd, "--aspect-ratio", args.aspect_ratio)
    _append_if_not_empty(cmd, "--response-format", args.response_format)
    _append_if_not_empty(cmd, "--video-request-retries", args.video_request_retries)
    _append_if_not_empty(cmd, "--poll-attempts", args.poll_attempts)
    _append_if_not_empty(cmd, "--poll-delay", args.poll_delay)
    if args.dry_run:
        cmd.append("--dry-run")
    elif args.send:
        cmd.append("--send")
    return run_child_with_optional(cmd, args)


def video_story_run(args: argparse.Namespace) -> int:
    args.out_dir = ensure_writable_out_dir(args.out_dir)
    cmd = [
        sys.executable,
        str(VIDEO_STORY_RUNNER),
        "--env-file",
        str(args.env_file),
        "--user-prompt",
        args.user_prompt,
        "--out-dir",
        str(args.out_dir),
        "--preset-file",
        str(args.preset_file),
        "--route",
        args.route,
        "--target-duration",
        str(args.target_duration),
        "--fps",
        str(args.fps),
        "--shot-duration",
        str(args.shot_duration),
        "--min-shot-duration",
        str(args.min_shot_duration),
        "--max-shot-duration",
        str(args.max_shot_duration),
        "--max-shots",
        str(args.max_shots),
        "--candidate-count",
        str(args.candidate_count),
        "--score-threshold",
        str(args.score_threshold),
        "--selection-strategy",
        args.selection_strategy,
        "--max-prompt-chars",
        str(args.max_prompt_chars),
        "--timeout",
        str(args.timeout),
        "--video-request-retries",
        str(args.video_request_retries),
        "--poll-attempts",
        str(args.poll_attempts),
        "--poll-delay",
        str(args.poll_delay),
    ]
    if args.duration > 0:
        cmd.extend(["--duration", str(args.duration)])
    _append_if_not_empty(cmd, "--llm-model", args.llm_model)
    if args.video_model:
        cmd.extend(["--video-model", args.video_model])
    if args.llm_env_file:
        cmd.extend(["--llm-env-file", str(args.llm_env_file)])
    if args.aspect_ratio:
        cmd.extend(["--aspect-ratio", args.aspect_ratio])
    if args.response_format:
        cmd.extend(["--response-format", args.response_format])
    if args.selection_file:
        cmd.extend(["--selection-file", str(args.selection_file)])
    if args.disable_llm_score:
        cmd.append("--disable-llm-score")
    if args.require_pass:
        cmd.append("--require-pass")
    if args.max_pass_retry:
        cmd.extend(["--max-pass-retry", str(args.max_pass_retry)])
    if args.no_assemble:
        cmd.append("--no-assemble")
    if args.interactive:
        cmd.append("--interactive")
    if args.assembly_timeout:
        cmd.extend(["--assembly-timeout", str(args.assembly_timeout)])
    if args.ffmpeg_path:
        cmd.extend(["--ffmpeg-path", str(args.ffmpeg_path)])
    if args.dry_run:
        cmd.append("--dry-run")
    if args.send:
        cmd.append("--send")
    if args.print_only:
        cmd.append("--print-only")
    return run_child_with_optional(cmd, args)


def print_commands(_: argparse.Namespace) -> int:
    print(
        """SCOPE Image Orchestrator command mode

命令列表（command mode）：
  - 生图优化: 进入图像 / 视频命令模式（当前会话内会持续解析生图类指令）
  - 查看预设 [route]: 查看路由配置（可加 --route）
  - 查看主题包 [name]: 查看主题包（可加 --detail）
  - 生图 <prompt> / 单张生图 <prompt>: 生成 1 张图
  - 批量生图 N <prompt>: 一次生成 N 张图
  - 参考生图 <image> <prompt>: 基于参考图生成
  - 严格链路 <prompt>: 执行 run_scope_pipeline.py 的完整链路
  - 回归测试: 运行 run_v2_route_regression.py
  - 审核 <image_root>: 运行 audit_generated_images_with_vision.py
  - 三模型对比 <image_root>: 对图片集合做多模型视觉评测

视频链路（含示例）：
  - 跑视频 <prompt>: `python scripts/scope_commands.py video-run --env-file <env> --user-prompt "<prompt>" --out-dir <out> [--send]`
  - 批量跑视频 N <prompt>: `python scripts/scope_commands.py video-batch --env-file <env> --user-prompt "<prompt>" --out-dir <out> --count N [--send]`
  - 视频分镜创作 <prompt> / 创作 <prompt> 视频: `python scripts/scope_commands.py video-story --env-file <env> --user-prompt "<prompt>" --out-dir <out>`
    - 示例（建议起步）：3分钟 / 每镜10秒 / 每镜3候选
      `... video-story --env-file <env> --user-prompt "<prompt>" --out-dir <out> --target-duration 180 --shot-duration 10 --candidate-count 3`
    - 仅生成规划（不走视频 API）：追加 --dry-run
    - 人工逐镜：追加 --interactive
"""
    )
    return 0


def add_common_run_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--env-file", required=True, type=Path)
    parser.add_argument("--user-prompt", required=True)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--llm-env-file", type=Path)
    parser.add_argument("--vision-env-file", type=Path)
    parser.add_argument("--llm-model", help="Optional override. Defaults to SCOPE_LLM_MODEL from env file.")
    parser.add_argument("--vision-model", help="Optional override. Defaults to SCOPE_VISION_MODEL from env file.")
    parser.add_argument("--image-model", help="Optional override. Defaults to SCOPE_IMAGE_MODEL from env file.")
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

    p_themes = sub.add_parser("list-theme-packs", help="List image theme packs from the unified preset library.")
    p_themes.add_argument("--preset-file", type=Path, default=DEFAULT_PRESET_FILE)
    p_themes.add_argument("--theme-pack", help="Optional single theme pack, e.g. mecha_tokusatsu.")
    p_themes.add_argument("--format", choices=["markdown", "json"], default="markdown")
    p_themes.add_argument("--detail", action="store_true", help="Include negatives and distilled theme-pack details.")
    p_themes.set_defaults(func=list_theme_packs)

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

    p_strict = sub.add_parser("strict-run", help="Run the strict paper-style pipeline via run_scope_pipeline.py.")
    add_common_run_args(p_strict)
    p_strict.add_argument("--optimizer-guide", type=Path, default=SKILL_ROOT / "references" / "scope-preset-library.json")
    p_strict.add_argument("--preset-guide", type=Path, default=SKILL_ROOT / "references" / "scope-preset-library.json")
    p_strict.add_argument("--max-prompt-repair-rounds", type=int, default=1)
    p_strict.add_argument("--retries", type=int, default=2)
    p_strict.add_argument("--vision-provider", choices=["vision", "none"], default="none")
    p_strict.set_defaults(func=strict_chain_run)

    p_reg = sub.add_parser("regression-run", help="Run route/regression matrix via run_v2_route_regression.py.")
    p_reg.add_argument("--env-file", required=True, type=Path)
    p_reg.add_argument("--llm-env-file", type=Path)
    p_reg.add_argument("--vision-env-file", type=Path)
    p_reg.add_argument("--out-dir", required=True, type=Path)
    p_reg.add_argument("--llm-model", help="Optional override. Defaults to SCOPE_LLM_MODEL from env file.")
    p_reg.add_argument("--vision-model", help="Optional override. Defaults to SCOPE_VISION_MODEL from env file.")
    p_reg.add_argument("--image-model", help="Optional override. Defaults to SCOPE_IMAGE_MODEL from env file.")
    p_reg.add_argument("--max-generation-attempts", type=int, default=4)
    p_reg.add_argument("--image-retries", type=int, default=3)
    p_reg.add_argument("--timeout", type=int, default=340)
    p_reg.add_argument("--max-prompt-chars", type=int, default=840)
    p_reg.add_argument("--response-formats", default="url,b64_json")
    p_reg.add_argument("--only-categories")
    p_reg.add_argument("--only-cases")
    p_reg.add_argument("--max-cases", type=int)
    p_reg.add_argument("--skip-vision", action="store_true")
    p_reg.add_argument("--resume", action="store_true")
    p_reg.add_argument("--dry-run", action="store_true")
    p_reg.add_argument("--delay", type=float, default=3.8)
    p_reg.add_argument("--print-only", action="store_true", help="Print child command without running.")
    p_reg.set_defaults(func=regression_run)

    p_audit = sub.add_parser("audit-run", help="Audit images in a folder with vision model.")
    p_audit.add_argument("--env-file", required=True, type=Path)
    p_audit.add_argument("--image-root", required=True, type=Path)
    p_audit.add_argument("--out-file", type=Path)
    p_audit.add_argument("--model", default="grok-4.3", help="Legacy single-model shortcut.")
    p_audit.add_argument("--vision-models", default="", help="Comma/semicolon-separated vision model list.")
    p_audit.add_argument("--pattern", default="*.png")
    p_audit.add_argument("--limit", type=int, default=0)
    p_audit.add_argument("--timeout", type=int, default=180)
    p_audit.add_argument("--delay", type=float, default=2.0)
    p_audit.add_argument("--print-only", action="store_true", help="Print child command without running.")
    p_audit.set_defaults(func=audit_run)

    p_video = sub.add_parser("video-run", help="Run one video generation job via generate_video.py.")
    p_video.add_argument("--env-file", required=True, type=Path)
    p_video.add_argument("--user-prompt", required=True)
    p_video.add_argument("--out-dir", required=True, type=Path)
    p_video.add_argument("--preset-file", type=Path, default=SKILL_ROOT / "references" / "scope-video-presets.json")
    p_video.add_argument("--route", default="", help="Route key, e.g. single_take | shot_driven | photo_to_video | magazine_broll.")
    p_video.add_argument("--video-model")
    p_video.add_argument("--duration", type=int, default=8)
    p_video.add_argument("--fps", type=int, default=24)
    p_video.add_argument("--aspect-ratio", default="")
    p_video.add_argument("--response-format", default="url")
    p_video.add_argument("--max-prompt-chars", type=int, default=1200)
    p_video.add_argument("--timeout", type=int, default=180)
    p_video.add_argument("--video-request-retries", type=int, default=2)
    p_video.add_argument("--poll-attempts", type=int, default=8)
    p_video.add_argument("--poll-delay", type=float, default=6.0)
    p_video.add_argument("--send", action="store_true", help="Actually request the video API. Without this flag, run in dry mode.")
    p_video.add_argument("--dry-run", action="store_true", help="Print generated request only.")
    p_video.add_argument("--print-only", action="store_true", help="Print child command without running it.")
    p_video.set_defaults(func=video_run)

    p_video_batch = sub.add_parser("video-batch", help="Run the same video prompt N times.")
    p_video_batch.add_argument("--env-file", required=True, type=Path)
    p_video_batch.add_argument("--user-prompt", required=True)
    p_video_batch.add_argument("--out-dir", required=True, type=Path)
    p_video_batch.add_argument("--count", type=int, required=True)
    p_video_batch.add_argument("--preset-file", type=Path, default=SKILL_ROOT / "references" / "scope-video-presets.json")
    p_video_batch.add_argument("--route", default="", help="Route key.")
    p_video_batch.add_argument("--video-model")
    p_video_batch.add_argument("--duration", type=int, default=8)
    p_video_batch.add_argument("--fps", type=int, default=24)
    p_video_batch.add_argument("--aspect-ratio", default="")
    p_video_batch.add_argument("--response-format", default="url")
    p_video_batch.add_argument("--max-prompt-chars", type=int, default=1200)
    p_video_batch.add_argument("--timeout", type=int, default=180)
    p_video_batch.add_argument("--video-request-retries", type=int, default=2)
    p_video_batch.add_argument("--poll-attempts", type=int, default=8)
    p_video_batch.add_argument("--poll-delay", type=float, default=6.0)
    p_video_batch.add_argument("--send", action="store_true", help="Actually request the video API. Without this flag, run in dry mode.")
    p_video_batch.add_argument("--dry-run", action="store_true", help="Print generated request only.")
    p_video_batch.add_argument("--print-only", action="store_true", help="Print child command without running it.")
    p_video_batch.set_defaults(func=video_batch)

    p_video_story = sub.add_parser("video-story", help="Run video storyboard pipeline (storyboard + multiple candidate variants per shot).")
    p_video_story.add_argument("--env-file", required=True, type=Path)
    p_video_story.add_argument("--llm-env-file", type=Path)
    p_video_story.add_argument("--user-prompt", required=True)
    p_video_story.add_argument("--out-dir", required=True, type=Path)
    p_video_story.add_argument("--preset-file", type=Path, default=SKILL_ROOT / "references" / "scope-video-presets.json")
    p_video_story.add_argument("--route", default="", help="Route key, e.g. single_take | shot_driven | photo_to_video | magazine_broll.")
    p_video_story.add_argument("--llm-model", default="gpt-5.5")
    p_video_story.add_argument("--video-model")
    p_video_story.add_argument("--target-duration", type=int, default=60)
    p_video_story.add_argument("--shot-duration", type=int, default=0)
    p_video_story.add_argument("--min-shot-duration", type=int, default=4)
    p_video_story.add_argument("--max-shot-duration", type=int, default=16)
    p_video_story.add_argument("--max-shots", type=int, default=0)
    p_video_story.add_argument("--candidate-count", type=int, default=3)
    p_video_story.add_argument("--score-threshold", type=float, default=0.68)
    p_video_story.add_argument("--selection-strategy", choices=["auto", "first", "manual"], default="auto")
    p_video_story.add_argument("--selection-file", type=Path)
    p_video_story.add_argument("--interactive", action="store_true", help="Enable interactive per-shot manual selection.")
    p_video_story.add_argument("--disable-llm-score", action="store_true", help="Use heuristic scoring only.")
    p_video_story.add_argument("--require-pass", action="store_true", help="Skip all candidates that do not pass the quality threshold.")
    p_video_story.add_argument("--max-pass-retry", type=int, default=0, help="Extra candidate attempts when require-pass is enabled.")
    p_video_story.add_argument("--duration", type=int, default=0, help="Compatibility alias for target-duration.")
    p_video_story.add_argument("--fps", type=int, default=24)
    p_video_story.add_argument("--aspect-ratio", default="")
    p_video_story.add_argument("--response-format", default="url")
    p_video_story.add_argument("--max-prompt-chars", type=int, default=1200)
    p_video_story.add_argument("--timeout", type=int, default=180)
    p_video_story.add_argument("--video-request-retries", type=int, default=2)
    p_video_story.add_argument("--poll-attempts", type=int, default=8)
    p_video_story.add_argument("--poll-delay", type=float, default=6.0)
    p_video_story.add_argument("--no-assemble", action="store_true", help="Skip final local ffmpeg assembly.")
    p_video_story.add_argument("--assembly-timeout", type=int, default=1200, help="Local ffmpeg command timeout in seconds.")
    p_video_story.add_argument("--ffmpeg-path", help="Custom ffmpeg executable path.")
    p_video_story.add_argument("--send", action="store_true", help="Actually call the video API. Without this flag, run in dry mode.")
    p_video_story.add_argument("--dry-run", action="store_true", help="Print generated request only.")
    p_video_story.add_argument("--print-only", action="store_true", help="Print child command without running it.")
    p_video_story.set_defaults(func=video_story_run)

    return parser.parse_args()


def main() -> int:
    args = parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

