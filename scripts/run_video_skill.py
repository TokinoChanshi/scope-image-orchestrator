#!/usr/bin/env python3
"""Natural-language entrypoint for video storyboard generation."""

from __future__ import annotations

import argparse
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from typing import Optional


SCRIPT_ROOT = Path(__file__).resolve().parent
VIDEO_STORY_RUNNER = SCRIPT_ROOT / "video_story_pipeline.py"

CN_NUMBERS = {
    "零": 0,
    "一": 1,
    "两": 2,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}


def _to_int(token: str) -> Optional[int]:
    if not token:
        return None
    token = token.strip()
    if token.isdigit():
        return int(token)
    if token in CN_NUMBERS:
        return CN_NUMBERS[token]
    if "十" in token:
        if token == "十":
            return 10
        head, tail = token.split("十", 1)
        base = CN_NUMBERS.get(head, 1)
        if tail:
            base *= 10
            base += CN_NUMBERS.get(tail, 0)
            return base
        return base * 10
    return None


def _first_match(patterns: list[tuple[str, int]], text: str) -> Optional[int]:
    for pattern, factor in patterns:
        m = re.search(pattern, text, flags=re.I)
        if not m:
            continue
        raw = m.group(1)
        value = _to_int(raw)
        if value is None or value <= 0:
            continue
        return value * factor
    return None


def _first_match_range(patterns: list[str], text: str, minimum: int, maximum: int) -> Optional[int]:
    for pattern in patterns:
        m = re.search(pattern, text, flags=re.I)
        if not m:
            continue
        value = _to_int(m.group(1))
        if value is None:
            continue
        if minimum <= value <= maximum:
            return value
    return None


@dataclass
class ParsedIntent:
    user_input: str
    target_duration: int
    shot_duration: int
    candidate_count: int
    max_shots: int
    route: str
    send: bool
    print_only: bool
    interactive: bool
    selection_strategy: str


def infer_target_duration(text: str) -> Optional[int]:
    patterns = [
        (r"([0-9一二三四五六七八九十]+)\s*分钟", 60),
        (r"(\d+)\s*min(?:ute)?s?", 60),
        (r"([0-9一二三四五六七八九十]+)\s*秒", 1),
        (r"(\d+)\s*秒", 1),
        (r"(\d+)\s*s(?:ec(?:ond)?s?)?", 1),
    ]
    return _first_match(patterns, text)


def infer_shot_duration(text: str) -> Optional[int]:
    patterns = [
        r"(?:每|每个|每一)镜(?:头)?\s*(?:时长|长度)?\s*(?:约|左右|大约)?\s*([0-9一二三四五六七八九十]+)\s*秒",
        r"(?:每|每个|每一)镜(?:头)?\s*(?:时长|长度)?\s*(?:约|左右|大约)?\s*(\d+)\s*秒",
        r"(?:each|每)\s*([0-9一二三四五六七八九十]+)\s*(?:秒|s|sec|second)s?\s*(?:镜|镜头|shot)",
        r"(?:each|每)\s*(\d+)\s*(?:秒|s|sec|second)s?\s*(?:镜|镜头|shot)",
        r"(?:each|每)\s*(?:镜|镜头|shot)\s*(?:约|about|around|~)?\s*([0-9一二三四五六七八九十]+)\s*(?:秒|s|sec|second)s?",
        r"(?:each|每)\s*(?:镜|镜头|shot)\s*(?:约|about|around|~)?\s*(\d+)\s*(?:秒|s|sec|second)s?",
        r"(?:每|each)\s*(?:个|a)?\s*(?:镜|镜头|shot)\s*(?:约|around|~|about)?\s*([0-9一二三四五六七八九十]+)\s*(?:秒|s|sec|second)s?",
        r"(?:每|each)\s*(?:个|a)?\s*(?:镜|镜头|shot)\s*(?:约|around|~|about)?\s*(\d+)\s*(?:秒|s|sec|second)s?",
        r"(?:shot|镜头)\s*(?:duration|时长)\s*([0-9一二三四五六七八九十]+)\s*秒",
        r"(?:shot|镜头)\s*(?:duration|时长)\s*(\d+)\s*(?:sec|秒)",
    ]
    return _first_match_range(patterns, text, 2, 60)


def infer_candidate_count(text: str) -> Optional[int]:
    patterns = [
        r"(?:每|每个|每一)镜(?:头)?\s*(?:做|生成)?\s*([0-9一二三四五六七八九十]+)\s*(?:个|张|条)?\s*(?:备选|变体|版本|候选|样本|条)",
        r"(?:每|每个|每一)镜(?:头)?\s*(?:做|生成)?\s*(\d+)\s*(?:个|张|条)?\s*(?:备选|变体|版本|候选|样本|条)",
        r"(?:each|per)\s*shot\s*(?:with)?\s*([0-9一二三四五六七八九十]+)\s*(?:candidates?|variants?|options?|copies?)",
        r"(?:each|per)\s*shot\s*(?:with)?\s*(\d+)\s*(?:candidates?|variants?|options?|copies?)",
        r"(\d+)\s*(?:candidates?|variants?|options?|copies?)\s*each shot",
        r"([0-9一二三四五六七八九十]+)\s*(?:candidates?|variants?|options?|copies?)\s*each shot",
        r"(?:each|per)\s*(?:\d+\s*)?(?:镜|镜头|shot)\s*(?:with)?\s*([0-9一二三四五六七八九十]+)\s*(?:candidates|variants|options|copies|shots)",
        r"(?:each|per)\s*(?:\d+\s*)?(?:镜|镜头|shot)\s*(?:with)?\s*(\d+)\s*(?:candidates|variants|options|copies|shots)",
        r"(?:候选|备选|变体|版本)\s*(?:每|给|出)?\s*镜(?:头)?\s*(?:各|个)?\s*([0-9一二三四五六七八九十]+)\s*(?:个|张|条)?",
        r"(?:候选|备选|变体|版本)\s*(?:每|给|出)?\s*镜(?:头)?\s*(?:各|个)?\s*(\d+)\s*(?:个|张|条)?",
    ]
    return _first_match_range(patterns, text, 1, 12)


def infer_max_shots(text: str) -> Optional[int]:
    patterns = [
        r"(?:共|共计|总共|总计|需要|拍摄)\s*(\d+)\s*(?:个)?\s*镜(?:头)?",
        r"(?:共|共计|总共|总计|需要|拍摄)\s*([0-9一二三四五六七八九十]+)\s*(?:个)?\s*镜(?:头)?",
    ]
    return _first_match_range(patterns, text, 1, 30)


def infer_route(text: str) -> str:
    t = text.lower()
    route_hints = {
        "single_take": ["单镜", "single", "single take", "single-shot", "单次", "固定镜头"],
        "shot_driven": ["分镜", "分段", "timeline", "时间线", "故事", "多镜", "多段", "剧情"],
        "photo_to_video": ["参考图", "图片", "photo", "参照", "图生视频", "image to video", "image-to-video"],
        "magazine_broll": ["杂志", "broll", "花絮", "纪录", "空间", "室内", "街拍", "广告"],
    }
    for route, keys in route_hints.items():
        if any(k in t for k in keys):
            return route
    return ""


def parse_intent(text: str, args: argparse.Namespace) -> ParsedIntent:
    target = infer_target_duration(text) or (args.target_duration if args.target_duration > 0 else 180)
    shot = infer_shot_duration(text) or (args.shot_duration if args.shot_duration > 0 else 10)
    candidate_count = infer_candidate_count(text) or max(1, args.candidate_count)
    max_shots = infer_max_shots(text) or args.max_shots
    route = args.route.strip() or infer_route(text)

    send = bool(args.send)
    if args.dry_run:
        send = False

    return ParsedIntent(
        user_input=text.strip(),
        target_duration=target,
        shot_duration=shot,
        candidate_count=candidate_count,
        max_shots=max_shots,
        route=route,
        send=send,
        print_only=bool(args.print_only),
        interactive=bool(args.interactive),
        selection_strategy=args.selection_strategy,
    )


def build_command(args: argparse.Namespace, intent: ParsedIntent) -> list[str]:
    cmd = [
        sys.executable,
        str(VIDEO_STORY_RUNNER),
        "--env-file",
        str(args.env_file),
        "--user-prompt",
        intent.user_input,
        "--out-dir",
        str(args.out_dir),
        "--target-duration",
        str(intent.target_duration),
        "--shot-duration",
        str(intent.shot_duration),
        "--candidate-count",
        str(intent.candidate_count),
        "--selection-strategy",
        intent.selection_strategy,
        "--max-shots",
        str(intent.max_shots),
        "--send" if intent.send else "--dry-run",
    ]

    if args.preset_file:
        cmd += ["--preset-file", str(args.preset_file)]
    if intent.route:
        cmd += ["--route", intent.route]
    if args.llm_env_file:
        cmd += ["--llm-env-file", str(args.llm_env_file)]
    if args.llm_model:
        cmd += ["--llm-model", args.llm_model]
    if args.video_model:
        cmd += ["--video-model", args.video_model]
    if args.fps:
        cmd += ["--fps", str(args.fps)]
    if args.aspect_ratio:
        cmd += ["--aspect-ratio", args.aspect_ratio]
    if args.response_format:
        cmd += ["--response-format", args.response_format]
    if args.max_prompt_chars:
        cmd += ["--max-prompt-chars", str(args.max_prompt_chars)]
    if args.timeout:
        cmd += ["--timeout", str(args.timeout)]
    if args.video_request_retries:
        cmd += ["--video-request-retries", str(args.video_request_retries)]
    if args.poll_attempts:
        cmd += ["--poll-attempts", str(args.poll_attempts)]
    if args.poll_delay:
        cmd += ["--poll-delay", str(args.poll_delay)]
    if args.assembly_timeout:
        cmd += ["--assembly-timeout", str(args.assembly_timeout)]
    if args.ffmpeg_path:
        cmd += ["--ffmpeg-path", args.ffmpeg_path]
    if args.no_assemble:
        cmd += ["--no-assemble"]
    if args.interactive:
        cmd += ["--interactive"]
    if args.require_pass:
        cmd += ["--require-pass"]
    if args.max_pass_retry:
        cmd += ["--max-pass-retry", str(args.max_pass_retry)]
    if intent.print_only:
        cmd += ["--print-only"]
    return cmd


def print_summary(intent: ParsedIntent) -> None:
    print("[INFO] video-story intent:")
    print(f"  target_duration: {intent.target_duration}s")
    print(f"  shot_duration: {intent.shot_duration}s")
    print(f"  candidate_count: {intent.candidate_count}")
    print(f"  max_shots: {intent.max_shots if intent.max_shots > 0 else '(auto by duration)'}")
    print(f"  route: {intent.route or 'auto'}")
    print(f"  send: {'ON' if intent.send else 'DRY-RUN'}")
    print(f"  selection_strategy: {intent.selection_strategy}")
    if intent.interactive:
        print("  interactive: on")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Natural-language front-end for video storyboard flow.")
    parser.add_argument("--env-file", required=True, type=Path, help="Environment file for video generation.")
    parser.add_argument("--user-input", required=True, help="User natural-language instruction.")
    parser.add_argument("--out-dir", required=True, type=Path, help="Output directory.")
    parser.add_argument("--preset-file", type=Path, default=None, help="Video presets file.")
    parser.add_argument("--target-duration", type=int, default=0, help="Override inferred total duration in seconds.")
    parser.add_argument("--shot-duration", type=int, default=0, help="Override inferred shot duration in seconds.")
    parser.add_argument("--candidate-count", type=int, default=3, help="Candidates per shot.")
    parser.add_argument("--max-shots", type=int, default=0, help="Maximum number of shots; optional.")
    parser.add_argument("--route", default="", help="Force route name.")
    parser.add_argument("--llm-env-file", type=Path)
    parser.add_argument("--llm-model", default="gpt-5.5")
    parser.add_argument("--video-model")
    parser.add_argument("--fps", type=int, default=24)
    parser.add_argument("--aspect-ratio", default="")
    parser.add_argument("--response-format", default="url")
    parser.add_argument("--max-prompt-chars", type=int, default=1200)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--video-request-retries", type=int, default=2)
    parser.add_argument("--poll-attempts", type=int, default=8)
    parser.add_argument("--poll-delay", type=float, default=6.0)
    parser.add_argument("--send", action="store_true", help="Call the real video API (default is dry-run).")
    parser.add_argument("--dry-run", action="store_true", help="Force dry-run even if --send is present.")
    parser.add_argument("--selection-strategy", choices=["auto", "first", "manual"], default="auto")
    parser.add_argument("--interactive", action="store_true", help="Enable per-shot manual selection.")
    parser.add_argument("--require-pass", action="store_true", help="Keep only passing candidates.")
    parser.add_argument("--max-pass-retry", type=int, default=0, help="Retry count when require-pass is enabled.")
    parser.add_argument("--no-assemble", action="store_true", help="Skip final local ffmpeg assembly.")
    parser.add_argument("--assembly-timeout", type=int, default=1200, help="ffmpeg timeout seconds.")
    parser.add_argument("--ffmpeg-path", default="")
    parser.add_argument("--print-only", action="store_true", help="Print command only.")
    return parser.parse_args()


def run_child(cmd: list[str], print_only: bool) -> int:
    print("[CMD]", " ".join(shlex.quote(part) for part in cmd))
    if print_only:
        return 0
    return subprocess.run(cmd, check=False).returncode


def main() -> int:
    args = parse_args()
    if not args.user_input.strip():
        raise SystemExit("--user-input is required")

    intent = parse_intent(args.user_input, args)
    print_summary(intent)
    cmd = build_command(args, intent)
    return run_child(cmd, args.print_only)


if __name__ == "__main__":
    raise SystemExit(main())
