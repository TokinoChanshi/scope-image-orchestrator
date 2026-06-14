#!/usr/bin/env python3
"""Small regression checks for run_video_skill natural-language parsing."""

from __future__ import annotations

import importlib.util
import sys
from argparse import Namespace
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "run_video_skill.py"

spec = importlib.util.spec_from_file_location("run_video_skill", SCRIPT)
if spec is None or spec.loader is None:
    raise RuntimeError("failed to load run_video_skill module")
mod = importlib.util.module_from_spec(spec)
sys.modules["run_video_skill"] = mod
spec.loader.exec_module(mod)


def u(raw: str) -> str:
    return raw.encode("utf-8").decode("unicode_escape")


def args_for(text: str) -> Namespace:
    return Namespace(
        user_input=text,
        target_duration=0,
        shot_duration=0,
        candidate_count=3,
        max_shots=0,
        route="",
        env_file=Path("references/.env.example"),
        preset_file=None,
        llm_env_file=None,
        llm_model="gpt-5.5",
        video_model=None,
        fps=24,
        aspect_ratio="",
        response_format="url",
        max_prompt_chars=1200,
        timeout=180,
        video_request_retries=2,
        poll_attempts=8,
        poll_delay=6.0,
        send=False,
        dry_run=False,
        selection_strategy="auto",
        interactive=False,
        require_pass=False,
        max_pass_retry=0,
        no_assemble=False,
        assembly_timeout=1200,
        ffmpeg_path="",
        out_dir=Path("tmp"),
        print_only=False,
    )


CASES = [
    (u("\\u4e09\\u5206\\u949f\\u7eaa\\u5149\\u6545\\u4e8b\\uff0c10\\u79d2\\u6bcf\\u4e2a\\u955c\\u5934\\uff0c\\u6bcf\\u4e2a\\u955c\\u5934\\u4e09\\u4e2a\\u5019\\u9009"), 180, 10, 3, 0),
    (u("\\u6bcf\\u4e2a\\u955c\\u59348\\u79d2\\uff0c\\u6700\\u591a5\\u4e2a\\u955c\\u5934\\uff0c\\u7ed9\\u62112\\u4e2a\\u5019\\u9009"), 180, 8, 2, 5),
    (u("\\u521b\\u4f5c\\u4e00\\u4e2a120\\u79d2\\u6821\\u56ed\\u6545\\u4e8b"), 120, 10, 3, 0),
    (u("\\u505a\\u4e00\\u4e2a\\u7b80\\u5355\\u573a\\u666f 50\\u79d2\\u6545\\u4e8b"), 50, 10, 3, 0),
    (u("\\u5236\\u4f5c2\\u5206\\u949f\\u89c6\\u9891\\uff0c\\u5355\\u955c\\u5934\\u98ce\\u683c"), 120, 10, 3, 0),
    (u("\\u6211\\u60f3\\u89815s\\u6bcf\\u955c\\u5934\\uff0c\\u6700\\u591a4\\u4e2a\\u955c\\u5934\\uff0c2\\u90091"), 180, 5, 2, 4),
    ("about 90 seconds, each shot 12 sec, 4 variants", 90, 12, 4, 0),
    ("each shot 8 seconds with 5 candidates", 8, 8, 5, 0),
    (u("\\u7b80\\u5355\\u573a\\u666f 5\\u79d2\\u5f15\\u4e2d"), 5, 10, 3, 0),
    (u("\\u5236\\u4f5c3\\u5206\\u949f\\u6545\\u4e8b\\uff0c\\u6bcf\\u4e2a\\u955c\\u5934\\u5e265\\u79d2"), 180, 5, 3, 0),
    (u("\\u6bcf\\u4e2a\\u955c\\u5934\\u5e262\\u79d2\\uff0c\\u7ed9\\u62112\\u4e2a\\u5907\\u9009\\uff0c\\u6700\\u591a3\\u4e2a\\u955c\\u5934\\uff0c3\\u5206\\u949f"), 180, 2, 2, 3),
    (u("\\u6700\\u591a5\\u4e2a\\u955c\\u5934\\uff0c\\u5f3a\\u8bf7\\u5bf9\\u6bcf\\u4e2a\\u955c\\u5934\\u751f\\u62104\\u79d2"), 180, 4, 3, 5),
    (u("about 75 seconds, at most 4 shots"), 75, 10, 3, 4),
]


def main() -> int:
    fail = 0
    for case_idx, (text, exp_target, exp_shot, exp_candidates, exp_max_shots) in enumerate(CASES, start=1):
        parsed = mod.parse_intent(text, args_for(text))
        ok = (
            parsed.target_duration == exp_target
            and parsed.shot_duration == exp_shot
            and parsed.candidate_count == exp_candidates
            and parsed.max_shots == exp_max_shots
        )
        if ok:
            print(f"[OK] case#{case_idx}: {text[:20]}...")
        else:
            fail += 1
            print(
                "[FAIL] case#{0}: {1!r}\n"
                "\texpected target={2}, shot={3}, candidates={4}, max_shots={5}; got target={6}, shot={7}, candidates={8}, max_shots={9}".format(
                    case_idx,
                    text,
                    exp_target,
                    exp_shot,
                    exp_candidates,
                    exp_max_shots,
                    parsed.target_duration,
                    parsed.shot_duration,
                    parsed.candidate_count,
                    parsed.max_shots,
                )
            )
    if fail:
        print(f"\nRegression result: FAIL ({fail}/{len(CASES)} cases).")
        return 1
    print(f"\nRegression result: PASS ({len(CASES)} cases).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
