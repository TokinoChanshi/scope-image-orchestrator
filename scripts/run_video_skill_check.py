#!/usr/bin/env python3
"""Local checks for video skill parsing and command-chain smoke test."""
from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
VIDEO_SKILL = SCRIPT_DIR / "run_video_skill.py"
VIDEO_SKILL_REGRESSION = SCRIPT_DIR / "run_video_skill_parse_regression.py"
from generate_video import ensure_writable_out_dir


def _safe_out_dir(path: Path) -> Path:
    try:
        return ensure_writable_out_dir(path)
    except Exception:
        fallback = Path(tempfile.gettempdir()) / "scope_image_runs" / path.name
        fallback.parent.mkdir(parents=True, exist_ok=True)
        return ensure_writable_out_dir(fallback)


def _run_parse_regression() -> int:
    cmd = [sys.executable, str(VIDEO_SKILL_REGRESSION)]
    return subprocess.run(cmd, check=False).returncode


def _run_smoke(args: argparse.Namespace) -> int:
    out_dir = args.out_dir / f"smoke_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    out_dir = _safe_out_dir(out_dir)

    cmd = [
        sys.executable,
        str(VIDEO_SKILL),
        "--env-file",
        str(args.env_file),
        "--user-input",
        args.smoke_user_input,
        "--out-dir",
        str(out_dir),
    ]
    if args.print_only:
        cmd.append("--print-only")
    return subprocess.run(cmd, check=False).returncode


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Video skill regression + smoke checks.")
    parser.add_argument("--env-file", required=True, type=Path, help="Environment file path for the story pipeline.")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("scope_runs") / datetime.now().strftime("video_skill_check_%Y%m%d_%H%M%S"),
        help="Base output directory for smoke artifacts.",
    )
    parser.add_argument(
        "--smoke-user-input",
        default="制作一个90秒故事，每镜头5秒，最多4个镜头，给我2个备选。",
        help="Natural-language prompt used for smoke command-chain check.",
    )
    parser.add_argument("--skip-smoke", action="store_true", help="Only run parse-regression checks.")
    parser.add_argument(
        "--print-only",
        action="store_true",
        help="Run run_video_skill only with --print-only for zero-output validation.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if not args.env_file.exists():
        raise SystemExit(f"--env-file not found: {args.env_file}")

    if not args.out_dir.is_absolute():
        args.out_dir = (Path.cwd() / args.out_dir).resolve()
    args.out_dir = _safe_out_dir(args.out_dir)

    rc = _run_parse_regression()
    if rc != 0:
        print("[FAIL] video skill parse regression failed.")
        return rc

    if not args.skip_smoke:
        rc = _run_smoke(args)
        if rc != 0:
            print("[FAIL] video skill smoke run failed.")
            return rc

    print("[PASS] video skill check completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
