#!/usr/bin/env python3
"""SCOPE video story pipeline.

Workflow:
1) Parse user intent into a storyboard (shots)
2) Generate N candidate clips for each shot
3) Score and rank candidates (LLM score when available, heuristic fallback)
4) Select candidates and assemble a target-duration timeline plan

This pipeline is command-driven and artifact-first:

- `story_plan.json`: storyboard extraction result
- `shot_candidates.json`: all candidates and score metadata
- `shot_selection.json`: final per-shot selection
  - `assembly_plan.json`: final stitched timeline plan
  - `assembly_result.json`: local assembly trace and ffmpeg status
- `video_story_final_summary.json`: concise summary for downstream scripts
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from urllib.parse import urlparse
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import generate_video
from api_adapters import build_text_request, extract_text, normalize_adapter


SCRIPT_ROOT = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_ROOT.parent
DEFAULT_PRESET_FILE = SKILL_ROOT / "references" / "scope-video-presets.json"

RETRYABLE_HTTP_STATUS = {408, 409, 425, 429, 500, 502, 503, 504, 520, 521, 522, 523, 524}


DEFAULT_STORY_SYSTEM = """
You are the Storyboard Planner role in a SCOPE-style media workflow.
Given the user's request, return a strict JSON object.

Schema (exact keys required):
{
  "title": "short title",
  "shots": [
    {
      "shot_index": 1,
      "goal": "primary shot goal",
      "visual": "what should appear",
      "camera": "camera guidance",
      "transition": "transition rule/intent",
      "duration_hint": 8,
      "notes": "optional notes"
    }
  ]
}

Rules:
- keep each shot atomic and practical
- avoid unsafe or explicit sexual content
- keep text short and in English
- do not invent unavailable characters
""".strip()

DEFAULT_SCORE_SYSTEM = """
You are the clip quality judge. Score one generated clip against the storyshot.
Return JSON object only:
{
  "score": 0.0,
  "verdict": "pass|weak|reject",
  "continuity": "good|partial|poor",
  "notes": ["short reasons"],
  "highlights": ["good points"],
  "risks": ["risks"],
  "suggestions": "short repair suggestion"
}
Rules:
- score in [0,1]
- prioritize prompt coverage, continuity consistency, and production clarity
""".strip()


DEFAULT_FFMPEG_TIMEOUT_SECONDS = 1200
_CN_DIGITS = {
    "零": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
    "百": 100,
    "千": 1000,
}


def _cn_num_to_int(text: str) -> int | None:
    if not text:
        return None
    text = text.strip()
    if text.isdigit():
        try:
            return int(text)
        except ValueError:
            return None

    # limited support for Chinese numerals like 十、十二、二十、三十五、两分钟
    normalized = text.replace(" ", "")
    if normalized in {"十"}:
        return 10

    total = 0
    unit = 1
    if "千" in normalized:
        parts = normalized.split("千")
        if len(parts) != 2:
            return None
        head, tail = parts[0], parts[1]
        if head:
            total += (_cn_num_to_int(head) or 1) * 1000
        unit = 1
        normalized = tail
    if "百" in normalized:
        parts = normalized.split("百")
        if len(parts) != 2:
            return None
        head, tail = parts[0], parts[1]
        if head:
            total += (_cn_num_to_int(head) or 1) * 100
        normalized = tail
        unit = 1
    if "十" in normalized:
        parts = normalized.split("十")
        if len(parts) != 2:
            return None
        head, tail = parts[0], parts[1]
        tens = _cn_num_to_int(head) if head else 1
        if tens is None:
            return None
        total += tens * 10
        if tail:
            if tail in _CN_DIGITS:
                total += _CN_DIGITS[tail]
            elif tail.isdigit():
                total += int(tail)
        return total
    if normalized in _CN_DIGITS:
        return _CN_DIGITS[normalized]
    if normalized.isdigit():
        return int(normalized)
    return None


def _read_user_index_input(prompt: str) -> str:
    """Read one line from stdin; keep behavior predictable in non-interactive modes."""
    try:
        return input(prompt).strip()
    except EOFError:
        return ""
    except KeyboardInterrupt:
        print("\n[INFO] interactive selection interrupted by user.")
        return ""


def _format_candidate_line(candidate: dict[str, Any], idx: int) -> str:
    status = candidate.get("status") or "unknown"
    score = candidate.get("score")
    score_text = "n/a"
    try:
        score_text = f"{float(score):.2f}"
    except Exception:
        pass
    url = ""
    urls = candidate.get("urls") or []
    if isinstance(urls, list) and urls:
        url = str(urls[0])[:110]
    verdict = candidate.get("verdict") or "-"
    return f"[{idx}] cand={candidate.get('candidate_index')} score={score_text} verdict={verdict} status={status} url={url}"


def _interactive_select_shot_candidates(shot: StoryShot, candidates: list[dict[str, Any]]) -> dict[str, Any]:
    if not candidates:
        return {}
    sorted_candidates = sorted(candidates, key=lambda item: int(item.get("candidate_index") or 0))
    print(f"\n[INTERACTIVE] Shot {shot.shot_index}: {shot.goal}", flush=True)
    for display_idx, candidate in enumerate(sorted_candidates, start=1):
        print(f"  {_format_candidate_line(candidate, display_idx)}", flush=True)
    print("Input candidate number (blank = best auto).", flush=True)
    while True:
        raw = _read_user_index_input("  choose> ")
        if raw == "":
            return sorted_candidates[0]
        normalized = raw.lower()
        if normalized in {"q", "quit", "skip", "auto", "default"}:
            return sorted_candidates[0]
        try:
            num = int(raw)
        except Exception:
            print("  invalid input, please type a candidate number.", flush=True)
            continue
        if 1 <= num <= len(sorted_candidates):
            return sorted_candidates[num - 1]
        print(f"  out of range, expected 1-{len(sorted_candidates)}", flush=True)


def _infer_total_seconds(prompt: str) -> int | None:
    if not prompt:
        return None
    # Examples: "3分钟", "五分钟", "约120秒", "about 2 mins"
    patterns = [
        r"(?:大约|约|about|roughly)?\s*([0-9一二两三四五六七八九十百千]+)\s*分钟",
        r"(?:大约|约|about|roughly)?\s*([0-9一二两三四五六七八九十百千]+)\s*min(?:ute)?s?",
        r"(?:大约|约|about|roughly)?\s*([0-9一二两三四五六七八九十百千]+)\s*秒",
        r"(?:大约|约|about|roughly)?\s*([0-9]+)\s*s\b",
    ]
    for idx, pattern in enumerate(patterns):
        m = re.search(pattern, prompt, flags=re.I)
        if not m:
            continue
        num_text = m.group(1)
        num = _cn_num_to_int(num_text)
        if num is None or num <= 0:
            continue
        if idx in {0, 1}:
            return num * 60
        return num
    return None


def _infer_shot_seconds(prompt: str) -> int | None:
    if not prompt:
        return None
    # e.g. "每段10秒","每个镜头10秒","每镜头约8秒"
    patterns = [
        r"(?:每|每个|每段|每镜头|每个镜头).{0,12}?(?:约|大约)?\s*([0-9一二两三四五六七八九十百千]+)\s*秒",
        r"(?:抽|生成).{0,12}?(?:每|每个|每段|每镜头).{0,12}?(?:约|大约)?\s*([0-9一二两三四五六七八九十百千]+)\s*秒",
    ]
    for pattern in patterns:
        m = re.search(pattern, prompt)
        if not m:
            continue
        num = _cn_num_to_int(m.group(1))
        if num and 2 <= num <= 60:
            return num
    return None


def _infer_candidate_count(prompt: str) -> int | None:
    if not prompt:
        return None
    patterns = [
        r"(?:每个镜头|每段|每次|每shot).{0,10}?(?:抽|生成|生成候选|试拍|拍摄)\s*(?:[为|:：]?\s*)?([0-9一二两三四五六七八九十百]+)\s*个",
        r"(?:每个镜头|每段|每次|每shot).{0,12}?([0-9一二两三四五六七八九十百]+)\s*个(?:候选|版本|备选)?",
        r"(?:我想要|给我|给)\s*([0-9一二两三四五六七八九十百]+)\s*(?:个|幅|次)?(?:候选|版本|备选)",
    ]
    for pattern in patterns:
        m = re.search(pattern, prompt)
        if not m:
            continue
        n = _cn_num_to_int(m.group(1))
        if n and n > 0:
            return n
    return None


def _normalize_inferred_params(prompt: str, args: argparse.Namespace) -> None:
    if args.duration == 0 and args.target_duration == 60:
        inferred_total = _infer_total_seconds(prompt)
        if inferred_total:
            args.target_duration = inferred_total
    if args.shot_duration == 0:
        shot = _infer_shot_seconds(prompt)
        if shot:
            args.shot_duration = shot
    if args.candidate_count == 0:
        inferred_count = _infer_candidate_count(prompt)
        args.candidate_count = inferred_count or 3


def _env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"").strip("'")
        if not re.match(r"^[A-Z_][A-Z0-9_]*$", key):
            continue
        env[key] = value
        os.environ[key] = value
    return env


def _load_video_presets(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"video preset file not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise SystemExit("video preset file format invalid")
    return data


def _pick_route(user_prompt: str, requested: str, presets: dict[str, Any]) -> str:
    routes = (presets.get("video_routes") or {}) if isinstance(presets, dict) else {}
    if requested and requested in routes:
        return requested
    text = (user_prompt or "").lower()
    ranked: list[tuple[int, str]] = []
    for route_name, cfg in routes.items():
        if not isinstance(cfg, dict):
            continue
        hits = 0
        for keyword in cfg.get("keywords") or []:
            if isinstance(keyword, str) and keyword.lower() in text:
                hits += 1
        if hits:
            ranked.append((hits, route_name))
    if not ranked:
        return presets.get("global_rules", {}).get("default_route", "single_take")
    ranked.sort(key=lambda x: (-x[0], x[1]))
    return ranked[0][1]


def _safe_parse_json(text: str) -> dict[str, Any]:
    if not isinstance(text, str):
        raise ValueError("empty text")
    raw = text.strip()
    raw = re.sub(r"^```(?:json)?\\s*", "", raw)
    raw = re.sub(r"\\s*```$", "", raw)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, flags=re.S)
        if not m:
            raise
        parsed = json.loads(m.group(0))
    if not isinstance(parsed, dict):
        raise ValueError("JSON root must be object")
    return parsed


def _build_request_session(timeout: int) -> requests.Session:
    retry = Retry(total=1, status=3, allowed_methods=frozenset(["POST", "GET"]), backoff_factor=0.5, status_forcelist=RETRYABLE_HTTP_STATUS)
    adapter = HTTPAdapter(max_retries=retry)
    session = requests.Session()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({"User-Agent": "SCOPE-Video-Story/1.0", "Accept": "application/json"})
    return session


def _post_json(session: requests.Session, url: str, headers: dict[str, str], payload: dict[str, Any], timeout: int, attempts: int, label: str) -> tuple[int | str, Any, str | None]:
    last_error: str | None = None
    for attempt in range(1, attempts + 1):
        try:
            resp = session.post(url, headers=headers, json=payload, timeout=timeout)
            status = resp.status_code
            try:
                body: Any = resp.json()
            except ValueError:
                body = {"text": resp.text[:1000]}
            if status == 200:
                return status, body, None
            if status not in RETRYABLE_HTTP_STATUS:
                return status, body, f"HTTP {status}: {str(body)[:500]}"
            last_error = f"HTTP {status}: {str(body)[:300]}"
        except Exception as exc:  # noqa: BLE001
            last_error = repr(exc)
            body = {"error": last_error}
            if attempt >= attempts:
                return "error", body, last_error
        if attempt < attempts:
            wait = min(12, (2 ** attempt) + random.uniform(0.5, 1.3))
            print(f"[WARN] {label}: attempt {attempt}/{attempts} failed ({last_error}); retrying in {wait:.1f}s", flush=True)
            time.sleep(wait)
    return "error", {"error": last_error}, last_error


def _call_llm_json(
    env: dict[str, str],
    model: str,
    system: str,
    user: str,
    timeout: int,
    retries: int,
) -> tuple[dict[str, Any], str]:
    base = (
        env.get("SCOPE_LLM_BASE_URL")
        or env.get("SCOPE_CHAT_BASE_URL")
        or env.get("SCOPE_LLM_ENDPOINT_URL")
        or env.get("SCOPE_CHAT_ENDPOINT_URL")
    )
    if not base:
        raise RuntimeError("missing SCOPE_LLM_BASE_URL")
    key = env.get("SCOPE_LLM_API_KEY") or env.get("SCOPE_CHAT_API_KEY") or env.get("SCOPE_REASONER_API_KEY")
    if not key:
        raise RuntimeError("missing SCOPE_LLM_API_KEY")
    adapter = normalize_adapter(env.get("SCOPE_LLM_FORMAT") or env.get("SCOPE_TEXT_FORMAT") or "openai-responses", "openai-responses")
    url, headers, payload, adapter_name = build_text_request(adapter, base, key, model, system, user, env, temperature=0.2, json_object=True)
    session = _build_request_session(timeout)
    status, body, error = _post_json(session, url, headers, payload, timeout, max(1, retries), f"{adapter_name} LLM")
    if status != 200:
        raise RuntimeError(error or f"LLM call failed, status={status}")
    text = extract_text(adapter_name, body)
    return _safe_parse_json(text), text


@dataclass
class StoryShot:
    shot_index: int
    goal: str
    visual: str
    camera: str = ""
    transition: str = ""
    duration_seconds: int = 8
    notes: str = ""


def _clamp_int(value: int, min_value: int, max_value: int) -> int:
    if value < min_value:
        return min_value
    if value > max_value:
        return max_value
    return value


def _normalize_duration_sequence(durations: list[int], target: int, min_seconds: int, max_seconds: int) -> list[int]:
    if not durations:
        return []
    if target <= 0:
        return durations

    sanitized = [max(min_seconds, min(max_seconds, int(round(d)))) for d in durations]
    total = sum(sanitized)
    if total == 0:
        each = max(min_seconds, target // max(1, len(sanitized)))
        sanitized = [each for _ in sanitized]
        total = sum(sanitized)

    while total > target:
        changed = False
        for idx, d in enumerate(sanitized):
            if total <= target:
                break
            if d > min_seconds:
                sanitized[idx] = d - 1
                total -= 1
                changed = True
                if total <= target:
                    break
        if not changed:
            break

    while total < target:
        changed = False
        for idx, d in enumerate(sanitized):
            if total >= target:
                break
            if d < max_seconds:
                sanitized[idx] = d + 1
                total += 1
                changed = True
                if total >= target:
                    break
        if not changed:
            break

    return sanitized


def _extract_story_with_llm(
    llm_env: dict[str, str],
    model: str,
    user_prompt: str,
    route: str,
    target_duration: int,
    target_shot_count: int,
    timeout: int,
    retries: int,
) -> list[StoryShot]:
    system = DEFAULT_STORY_SYSTEM
    user = (
        f"User prompt: {user_prompt}\n"
        f"Route hint: {route}\n"
        f"Target total duration: {target_duration} seconds\n"
        f"Target shot count: {target_shot_count}\n"
        "Output JSON with 3-12 practical shots, each with duration_hint (integer seconds)."
    )
    parsed, _raw = _call_llm_json(llm_env, model, system, user, timeout, retries)
    shots = []
    raw_shots = parsed.get("shots")
    if isinstance(raw_shots, list) and raw_shots:
        for i, item in enumerate(raw_shots, start=1):
            if not isinstance(item, dict):
                continue
            shot = StoryShot(
                shot_index=int(item.get("shot_index") or i),
                goal=str(item.get("goal") or item.get("description") or ""),
                visual=str(item.get("visual") or ""),
                camera=str(item.get("camera") or ""),
                transition=str(item.get("transition") or ""),
                duration_seconds=int(item.get("duration_hint") or 8),
                notes=str(item.get("notes") or ""),
            )
            shots.append(shot)
    if not shots:
        raise ValueError("No valid shots from LLM")
    return shots


def _fallback_story_from_prompt(
    user_prompt: str,
    target_shot_count: int,
    default_duration: int,
    min_seconds: int,
    max_seconds: int,
) -> list[StoryShot]:
    segments = [
        seg.strip()
        for seg in re.split(r"[;,，。.!?！？\n\r\t]+", user_prompt)
        if seg.strip()
    ]
    if not segments:
        segments = [user_prompt.strip()]
    if target_shot_count <= 1:
        segments = segments[:1]
        target_shot_count = 1
    elif len(segments) < target_shot_count:
        while len(segments) < target_shot_count:
            segments.append((segments[-1] + " (continuation)").strip())
    else:
        segments = segments[:target_shot_count]

    shots: list[StoryShot] = []
    for idx, segment in enumerate(segments, start=1):
        shots.append(
            StoryShot(
                shot_index=idx,
                goal=segment[:150],
                visual="continuity-preserving practical action",
                camera="natural camera movement, avoid abrupt cuts",
                transition="clean cut",
                duration_seconds=default_duration,
                notes="fallback prompt split from user text",
            )
        )
    shots = shots[:target_shot_count]
    durations = _normalize_duration_sequence([default_duration for _ in shots], target_shot_count * default_duration, min_seconds, max_seconds)
    for shot, dur in zip(shots, durations):
        shot.duration_seconds = dur
    return shots


def _build_shot_prompt(
    user_prompt: str,
    route_cfg: dict[str, Any],
    shot: StoryShot,
    shot_total: int,
    previous_shot: str | None,
    final_total_seconds: int,
    variant: int = 0,
) -> str:
    route_hint = route_cfg.get("route_hint") or "story-driven practical video"
    planning = route_cfg.get("planning_template") or "Build one clear shot with continuity and practical motion."
    shot_design = route_cfg.get("shot_design") or "A stable single shot with practical camera motion."
    negatives = route_cfg.get("negative") or "No hard artifacts, avoid abrupt distortion."
    boosters = route_cfg.get("booster_lines") or []
    booster = ""
    if isinstance(boosters, list) and boosters:
        booster = str(boosters[(variant - 1) % len(boosters)]) if variant > 0 else str(boosters[0])
    booster_line = f"{booster}\n" if booster else ""

    continuity = f"Continuity context: {previous_shot}" if previous_shot else "Start a clean opening shot."
    return (
        f"{planning}.\n"
        f"Global goal: {user_prompt}\n"
        f"Route: {route_hint}\n"
        f"Shot count target: {shot_total}, target total duration: {final_total_seconds}s.\n"
        f"Current shot index: {shot.shot_index}\n"
        f"Shot goal: {shot.goal}\n"
        f"Shot visual: {shot.visual}\n"
        f"Camera: {shot.camera}\n"
        f"Transition: {shot.transition or 'practical cut'}\n"
        f"Shot design: {shot_design}\n"
        f"Duration control: keep duration near {shot.duration_seconds}s.\n"
        f"{booster_line}"
        f"{continuity}\n"
        f"Notes: {shot.notes}\n"
        f"{negatives}\n"
    )


def _score_candidate_with_llm(
    llm_env: dict[str, str],
    llm_model: str,
    user_prompt: str,
    shot: StoryShot,
    shot_prompt: str,
    candidate: dict[str, Any],
    timeout: int,
    retries: int,
) -> tuple[float, str, list[str], list[str], list[str], str]:
    user = (
        "Rate this candidate for this shot. Return strict JSON.\n"
        f"Shot description: {shot.goal}\n"
        f"Shot prompt:\n{shot_prompt}\n\n"
        f"Candidate metadata:\n{json.dumps(candidate, ensure_ascii=False)}"
    )
    parsed, _raw = _call_llm_json(llm_env, llm_model, DEFAULT_SCORE_SYSTEM, user, timeout, retries)
    score = parsed.get("score", 0.0)
    try:
        score = float(score)
    except Exception:
        score = 0.0
    score = max(0.0, min(1.0, score))
    verdict = str(parsed.get("verdict") or "weak")
    continuity = str(parsed.get("continuity") or "partial")
    highlights = list(parsed.get("highlights") or [])
    risks = list(parsed.get("risks") or [])
    notes = list(parsed.get("notes") or [])
    suggestions = str(parsed.get("suggestions") or "")
    return score, verdict, continuity, highlights, risks, notes, suggestions


def _score_candidate_fallback(candidate: dict[str, Any]) -> tuple[float, str, str, list[str], list[str], list[str], str]:
    score = 0.25
    if candidate.get("ok"):
        score += 0.55
    urls = candidate.get("urls") or []
    if urls:
        score += 0.15
    if candidate.get("task_id"):
        score += 0.08
    if candidate.get("status_task") in {"done", "finished", "completed", "succeeded"}:
        score += 0.1
    score = max(0.0, min(1.0, score))
    continuity = "partial"
    if score >= 0.75:
        verdict = "pass"
    elif score >= 0.5:
        verdict = "weak"
    else:
        verdict = "reject"
    return score, verdict, continuity, ["generated successfully"], ["unknown endpoint-level continuity"], [f"fallback score={score:.2f}"], "No LLM score; consider manual review."


def _is_pass_candidate(candidate: dict[str, Any], threshold: float) -> bool:
    if candidate.get("dry_run"):
        return True
    if not candidate.get("ok"):
        return False
    try:
        score = float(candidate.get("score") or 0.0)
    except Exception:
        score = 0.0
    verdict = str(candidate.get("verdict") or "").strip().lower()
    if verdict in {"pass", "approved", "ok"}:
        return score >= threshold
    return score >= threshold


def _load_selection_map(path: Path | None, shot_count: int) -> dict[int, int]:
    if not path:
        return {}
    if not path.exists():
        raise SystemExit(f"selection file not found: {path}")
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    result: dict[int, int] = {}
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            s = int(item.get("shot_index") or item.get("shot") or 0)
            c = int(item.get("candidate") or item.get("candidate_index") or 0)
            if s > 0 and c > 0:
                result[s] = c
    elif isinstance(raw, dict):
        if "shots" in raw and isinstance(raw["shots"], list):
            for item in raw["shots"]:
                if not isinstance(item, dict):
                    continue
                s = int(item.get("shot_index") or item.get("shot") or 0)
                c = int(item.get("candidate") or item.get("candidate_index") or 0)
                if s > 0 and c > 0:
                    result[s] = c
        else:
            for key, value in raw.items():
                if key in {"notes", "metadata", "route"}:
                    continue
                try:
                    s = int(key)
                    c = int(value)
                except Exception:
                    continue
                if s > 0 and c > 0:
                    result[s] = c
    return result


def _select_candidate(
    shot_candidates: list[dict[str, Any]],
    score_threshold: float,
    strategy: str,
    require_pass: bool,
) -> dict[str, Any]:
    if not shot_candidates:
        return {}
    sorted_candidates = sorted(shot_candidates, key=lambda item: float(item.get("score") or 0.0), reverse=True)
    if require_pass:
        passed = [c for c in sorted_candidates if _is_pass_candidate(c, score_threshold)]
        if passed:
            return passed[0]
    if strategy == "first":
        chosen = shot_candidates[0]
    elif strategy == "manual":
        chosen = sorted_candidates[0]
    else:
        chosen = next((c for c in sorted_candidates if float(c.get("score", 0.0)) >= score_threshold), sorted_candidates[0])
    return chosen


def _build_storyboard(
    user_prompt: str,
    route: str,
    route_cfg: dict[str, Any],
    llm_env: dict[str, str] | None,
    llm_model: str,
    target_duration: int,
    max_shots: int,
    min_shot: int,
    max_shot: int,
    shot_base: int,
    timeout: int,
    retries: int,
) -> tuple[list[StoryShot], dict[str, Any], str]:
    target_shot_count = max(1, math.ceil(target_duration / max(1, shot_base)))
    if max_shots > 0:
        target_shot_count = min(target_shot_count, max_shots)
    llm_used = False

    shots: list[StoryShot] = []
    if llm_env:
        try:
            shots = _extract_story_with_llm(llm_env, llm_model, user_prompt, route, target_duration, target_shot_count, timeout, retries)
            llm_used = True
        except Exception:
            shots = []

    if not shots:
        shots = _fallback_story_from_prompt(user_prompt, target_shot_count, shot_base, min_shot, max_shot)

    shots = _align_shots_to_target_count(
        shots=shots,
        target_count=target_shot_count,
        shot_base=shot_base,
        min_shot=min_shot,
        max_shot=max_shot,
    )

    durations = _normalize_duration_sequence([s.duration_seconds for s in shots], target_duration, min_shot, max_shot)
    for shot, duration in zip(shots, durations):
        shot.duration_seconds = _clamp_int(duration, min_shot, max_shot)

    return shots, {
        "route": route,
        "shot_count_target": target_shot_count,
        "shot_count_actual": len(shots),
        "llm_extracted": llm_used,
        "route_hint": route_cfg.get("route_hint"),
    }, "ok" if llm_used else "fallback"


def _compose_candidate_args(args: argparse.Namespace) -> argparse.Namespace:
    return argparse.Namespace(
        duration=0,
        fps=args.fps,
        aspect_ratio=args.aspect_ratio,
        max_prompt_chars=args.max_prompt_chars,
        video_model=args.video_model,
        response_format=args.response_format,
        timeout=args.timeout,
        video_request_retries=args.video_request_retries,
        poll_attempts=args.poll_attempts,
        poll_delay=args.poll_delay,
        dry_run=args.dry_run,
        send=args.send,
    )


def _build_candidate_record(
    shot: StoryShot,
    cand_idx: int,
    shot_prompt: str,
    user_prompt: str,
    result: dict[str, Any],
    llm_env: dict[str, str] | None,
    llm_model: str,
    timeout: int,
    use_llm_score: bool,
) -> dict[str, Any]:
    urls = [entry.get("url") for entry in result.get("videos", []) if isinstance(entry, dict)]
    urls = [u for u in urls if isinstance(u, str)]
    task_id = result.get("task_id")
    if not task_id:
        video_list = result.get("videos", [])
        if isinstance(video_list, list) and video_list and isinstance(video_list[0], dict):
            task_id = video_list[0].get("task_id")

    record = {
        "shot_index": shot.shot_index,
        "shot_title": shot.goal,
        "candidate_index": cand_idx,
        "duration_seconds": shot.duration_seconds,
        "prompt": shot_prompt,
        "dry_run": bool(result.get("dry_run")),
        "ok": bool(result.get("ok")) or bool(result.get("dry_run")),
        "status": result.get("status"),
        "request_payload": result.get("request"),
        "status_task": result.get("status_task"),
        "task_id": task_id,
        "error": result.get("error") if not result.get("ok") else None,
        "urls": urls,
        "raw": result,
    }

    if use_llm_score and result.get("ok") and llm_env:
        try:
            score, verdict, continuity, highlights, risks, notes, suggestions = _score_candidate_with_llm(
                llm_env=llm_env,
                llm_model=llm_model,
                user_prompt=user_prompt,
                shot=shot,
                shot_prompt=shot_prompt,
                candidate=record,
                timeout=timeout,
                retries=2,
            )
        except Exception:
            score, verdict, continuity, highlights, risks, notes, suggestions = _score_candidate_fallback(record)
    else:
        if result.get("dry_run"):
            score, verdict, continuity, highlights, risks, notes, suggestions = 1.0, "pass", "dry-run", ["dry-run preview"], ["no real validation"], ["dry-run"], "No real score; dry-run selected as placeholder."
        else:
            score, verdict, continuity, highlights, risks, notes, suggestions = _score_candidate_fallback(record)

    record.update({
        "score": round(float(score), 4),
        "verdict": verdict,
        "continuity": continuity,
        "highlights": highlights,
        "risks": risks,
        "notes": notes,
        "suggestions": suggestions,
    })
    return record


def _align_shots_to_target_count(
    shots: list[StoryShot],
    target_count: int,
    shot_base: int,
    min_shot: int,
    max_shot: int,
) -> list[StoryShot]:
    if target_count <= 0:
        return shots
    if not shots:
        return []
    if len(shots) > target_count:
        shots = shots[:target_count]
    elif len(shots) < target_count:
        seed_count = len(shots)
        while len(shots) < target_count:
            seed = shots[len(shots) % seed_count]
            shots.append(
                StoryShot(
                    shot_index=len(shots) + 1,
                    goal=f"{seed.goal}（续）",
                    visual=seed.visual or "continuity-preserving extension",
                    camera=seed.camera or "smooth continuity movement",
                    transition=seed.transition or "clean cut",
                    duration_seconds=_clamp_int(shot_base, min_shot, max_shot),
                    notes=f"{seed.notes or ''} auto-extended".strip(),
                )
            )
    for idx, shot in enumerate(shots, start=1):
        shot.shot_index = idx
    return shots


def _write_selection_template(out_dir: Path, selected_records: list[dict[str, Any]], candidate_records: list[dict[str, Any]]) -> None:
    template: list[dict[str, Any]] = []
    by_shot: dict[int, list[dict[str, Any]]] = {}
    for item in candidate_records:
        idx = int(item.get("shot_index") or 0)
        if idx <= 0:
            continue
        by_shot.setdefault(idx, []).append(item)

    for shot_sel in selected_records:
        shot_idx = int(shot_sel.get("shot_index") or 0)
        candidates = sorted(by_shot.get(shot_idx, []), key=lambda x: int(x.get("candidate_index") or 0))
        options = []
        for c in candidates:
            options.append({
                "candidate_index": c.get("candidate_index"),
                "score": c.get("score"),
                "status": c.get("status"),
                "verdict": c.get("verdict"),
                "url": (c.get("urls") or [None])[0],
                "reason": "auto" if c.get("quality_passed", False) else "candidate",
            })
        template.append({
            "shot_index": shot_idx,
            "shot_title": shot_sel.get("shot_title") or f"shot-{shot_idx}",
            "recommended_candidate_index": shot_sel.get("candidate_index"),
            "recommended_reason": shot_sel.get("selection_reason"),
            "available_candidates": options,
            "selected_by_default": shot_sel.get("candidate_index"),
        })

    out_path = out_dir / "candidate_selection_template.json"
    out_path.write_text(json.dumps(template, ensure_ascii=False, indent=2), encoding="utf-8")


def _timestamped_summary(entries: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(entries)
    passed = sum(1 for item in entries if item.get("ok") is True)
    avg_score = 0.0
    if entries:
        avg_score = sum(float(item.get("score") or 0.0) for item in entries) / len(entries)
    return {
        "total": total,
        "passed": passed,
        "pass_ratio": passed / total if total else 0.0,
        "avg_score": round(avg_score, 4),
    }


def _find_ffmpeg(explicit_path: str | None) -> str | None:
    if explicit_path:
        candidate = Path(explicit_path).expanduser()
        if candidate.is_file():
            return str(candidate)
        if candidate.exists():
            return str(candidate)
        print(f"[WARN] ffmpeg path not found: {explicit_path}", flush=True)
    ffmpeg_path = shutil.which("ffmpeg")
    return ffmpeg_path


def _safe_request_path(url_or_path: str) -> str:
    parsed = urlparse(url_or_path)
    if parsed.scheme and parsed.scheme in {"http", "https"}:
        name = Path(parsed.path or "").name
        suffix = Path(name).suffix
        if suffix:
            return suffix
        return ".mp4"
    return Path(url_or_path).suffix or ".mp4"


def _download_video_file(url: str, out_path: Path, timeout: int) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if url.startswith("file://"):
        src = Path(url[7:])
        if not src.exists():
            raise FileNotFoundError(f"local source file not found: {src}")
        out_path.write_bytes(src.read_bytes())
        return

    parsed = urlparse(url)
    if parsed.scheme in {"http", "https"}:
        resp = requests.get(url, timeout=timeout, stream=True)
        resp.raise_for_status()
        with out_path.open("wb") as fp:
            for chunk in resp.iter_content(chunk_size=1 << 20):
                if chunk:
                    fp.write(chunk)
        return

    if Path(url).exists():
        out_path.write_bytes(Path(url).read_bytes())
        return

    raise ValueError(f"unsupported video source: {url}")


def _run_ffmpeg(cmd: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        check=False,
        text=True,
        capture_output=True,
        timeout=timeout,
    )


def _trim_or_transcode_clip(
    ffmpeg: str,
    in_file: Path,
    out_file: Path,
    target_seconds: int,
    fps: int,
    timeout: int,
) -> tuple[bool, str]:
    """Return (success, method)."""
    out_file.parent.mkdir(parents=True, exist_ok=True)

    if target_seconds <= 0:
        target_seconds = 1

    duration = str(float(target_seconds))
    # First try container-level cut.
    direct_cmd = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(in_file),
        "-t",
        duration,
        "-c",
        "copy",
        str(out_file),
    ]
    proc = _run_ffmpeg(direct_cmd, timeout=timeout)
    if proc.returncode == 0:
        return True, "copy"

    reencode_cmd = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(in_file),
        "-t",
        duration,
        "-r",
        str(max(1, fps)),
        "-vf",
        "scale=trunc(iw/2)*2:trunc(ih/2)*2",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "160k",
        str(out_file),
    ]
    proc = _run_ffmpeg(reencode_cmd, timeout=timeout)
    if proc.returncode == 0:
        return True, "reencode"

    return False, f"ffmpeg copy failed: {proc.stderr.strip()[:500]}"


def _assemble_candidate_clips(
    selections: list[dict[str, Any]],
    ffmpeg: str | None,
    assembly_root: Path,
    fps: int,
    shot_min: int,
    shot_max: int,
    target_total_seconds: int,
    timeout: int,
) -> dict[str, Any]:
    assembly_root.mkdir(parents=True, exist_ok=True)
    clips: list[dict[str, Any]] = []
    clip_files: list[Path] = []

    if not selections:
        return {
            "status": "skip",
            "reason": "No selected shots to assemble.",
            "clips": [],
            "concat_file": str(assembly_root / "concat_list.txt"),
            "final": None,
            "timeline": [],
            "ffmpeg": ffmpeg,
        }

    timeline = _build_assembly_plan(selections, target_total_seconds, shot_min, shot_max, fps).get("shots", [])

    for idx, shot in enumerate(timeline, start=1):
        source_url = shot.get("selected_url")
        clip_duration = int(shot.get("duration_seconds") or 0)
        if not source_url:
            clips.append({
                "shot_index": shot.get("shot_index"),
                "candidate_index": shot.get("candidate_index"),
                "status": "skip",
                "reason": "missing selected_url",
            })
            continue

        source_suffix = _safe_request_path(str(source_url))
        raw_file = assembly_root / f"shot_{idx:03d}_source{source_suffix}"
        trimmed_file = assembly_root / f"shot_{idx:03d}_trim.mp4"

        source_path = Path(str(source_url))
        if isinstance(source_url, str) and source_url.startswith(("http://", "https://", "file://")):
            try:
                _download_video_file(source_url, raw_file, timeout=timeout)
            except Exception as exc:  # noqa: BLE001
                clips.append({
                    "shot_index": shot.get("shot_index"),
                    "candidate_index": shot.get("candidate_index"),
                    "status": "failed",
                    "reason": f"download failed: {exc}",
                })
                continue
        elif str(source_path).startswith("http://") or str(source_path).startswith("https://"):
            try:
                _download_video_file(str(source_path), raw_file, timeout=timeout)
            except Exception as exc:  # noqa: BLE001
                clips.append({
                    "shot_index": shot.get("shot_index"),
                    "candidate_index": shot.get("candidate_index"),
                    "status": "failed",
                    "reason": f"download failed: {exc}",
                })
                continue
        elif source_path.exists():
            try:
                raw_file.write_bytes(source_path.read_bytes())
            except Exception as exc:  # noqa: BLE001
                clips.append({
                    "shot_index": shot.get("shot_index"),
                    "candidate_index": shot.get("candidate_index"),
                    "status": "failed",
                    "reason": f"copy failed: {exc}",
                })
                continue
        else:
            clips.append({
                "shot_index": shot.get("shot_index"),
                "candidate_index": shot.get("candidate_index"),
                "status": "failed",
                "reason": f"unsupported video source type: {source_url}",
            })
            continue

        if not ffmpeg:
            clips.append({
                "shot_index": shot.get("shot_index"),
                "candidate_index": shot.get("candidate_index"),
                "status": "skip",
                "source_file": str(raw_file),
                "reason": "ffmpeg not available",
            })
            continue

        ok, method = _trim_or_transcode_clip(ffmpeg, raw_file, trimmed_file, clip_duration, fps, timeout=timeout)
        if not ok:
            clips.append({
                "shot_index": shot.get("shot_index"),
                "candidate_index": shot.get("candidate_index"),
                "status": "failed",
                "source_file": str(raw_file),
                "reason": method,
            })
            continue

        clip_files.append(trimmed_file)
        clips.append({
            "shot_index": shot.get("shot_index"),
            "candidate_index": shot.get("candidate_index"),
            "status": "ready",
            "source_file": str(raw_file),
            "prepared_file": str(trimmed_file),
            "prepare_method": method,
            "duration_seconds": int(shot.get("duration_seconds") or 0),
            "selection_reason": shot.get("selection_reason"),
            "score": shot.get("score"),
        })

    concat_path = assembly_root / "concat_list.txt"
    concat_lines = [f"file '{p.as_posix()}'\n" for p in clip_files]
    concat_path.write_text("".join(concat_lines), encoding="utf-8")

    # Prepare assemble scripts for reproducibility
    final_path = assembly_root / "final_video.mp4"
    if os.name == "nt":
        sh_path = assembly_root / "assemble_video.bat"
        sh_path.write_text(
            "\r\n".join([
                "@echo off",
                "setlocal",
                f"ffmpeg -y -hide_banner -loglevel error -f concat -safe 0 -i \"{concat_path}\" -c copy \"{final_path}\"",
            ]),
            encoding="utf-8",
        )
    else:
        sh_path = assembly_root / "assemble_video.sh"
        sh_path.write_text(
            "\n".join([
                "#!/usr/bin/env bash",
                f"ffmpeg -y -hide_banner -loglevel error -f concat -safe 0 -i \"{concat_path}\" -c copy \"{final_path}\"",
            ]),
            encoding="utf-8",
        )

    if not clip_files:
        return {
            "status": "failed",
            "reason": "No prepared clips.",
            "clips": clips,
            "concat_file": str(concat_path),
            "assemble_script": str(sh_path),
            "final": str(final_path),
            "ffmpeg": ffmpeg,
            "timeline": timeline,
        }

    if not ffmpeg:
        return {
            "status": "script_only",
            "reason": "ffmpeg unavailable",
            "clips": clips,
            "concat_file": str(concat_path),
            "assemble_script": str(sh_path),
            "final": str(final_path),
            "ffmpeg": ffmpeg,
            "timeline": timeline,
        }

    concat_cmd = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_path),
        "-c",
        "copy",
        str(final_path),
    ]
    proc = _run_ffmpeg(concat_cmd, timeout=timeout)
    if proc.returncode != 0:
        # Fallback re-encode for inconsistent codecs.
        reencode_concat_cmd = [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_path),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-shortest",
            str(final_path),
        ]
        proc2 = _run_ffmpeg(reencode_concat_cmd, timeout=timeout)
        if proc2.returncode != 0:
            return {
                "status": "failed",
                "reason": f"concat failed: {proc2.stderr.strip()[:500]}",
                "clips": clips,
                "concat_file": str(concat_path),
                "assemble_script": str(sh_path),
                "final": str(final_path),
                "ffmpeg": ffmpeg,
                "timeline": timeline,
            }
        return {
            "status": "success_reencode",
            "reason": "concat fallback re-encoded",
            "clips": clips,
            "concat_file": str(concat_path),
            "assemble_script": str(sh_path),
            "final": str(final_path),
            "ffmpeg": ffmpeg,
            "timeline": timeline,
        }

    return {
        "status": "success_copy",
        "reason": "concat copy success",
        "clips": clips,
        "concat_file": str(concat_path),
        "assemble_script": str(sh_path),
        "final": str(final_path),
        "ffmpeg": ffmpeg,
        "timeline": timeline,
    }


def _build_assembly_plan(
    selected: list[dict[str, Any]],
    target_total: int,
    min_shot: int,
    max_shot: int,
    fps: int,
) -> dict[str, Any]:
    if not selected:
        return {
            "target_total_seconds": target_total,
            "actual_total_seconds": 0,
            "shots": [],
            "fps": fps,
            "notes": "No selected candidates.",
        }

    durations = [
        int(max(min_shot, min(max_shot, round(float(s.get("duration_seconds", 0)))))) 
        for s in selected
    ]
    durations = _normalize_duration_sequence(durations, target_total, min_shot, max_shot)

    timeline = []
    cursor = 0.0
    for shot, duration in zip(selected, durations):
        start = round(cursor, 2)
        end = round(cursor + duration, 2)
        cursor = end
        timeline.append({
            "shot_index": shot["shot_index"],
            "candidate_index": shot["candidate_index"],
            "duration_seconds": duration,
            "start_seconds": start,
            "end_seconds": end,
            "selected_url": shot.get("selected_url"),
            "selected_video_task_id": shot.get("selected_video_task_id"),
            "selection_reason": shot.get("selection_reason"),
            "score": shot.get("score"),
        })

    return {
        "target_total_seconds": target_total,
        "actual_total_seconds": sum(item["duration_seconds"] for item in timeline),
        "fps": fps,
        "assembly_mode": "sequential_no_render",
        "shots": timeline,
        "concat_hint": [
            "Download selected outputs by URL",
            "Create file list: selected.txt",
            "ffmpeg -f concat -safe 0 -i selected.txt -c copy result.mp4",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="SCOPE video story pipeline")
    parser.add_argument("--env-file", required=True, type=Path)
    parser.add_argument("--llm-env-file", type=Path)
    parser.add_argument("--user-prompt", required=True)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--preset-file", type=Path, default=DEFAULT_PRESET_FILE)
    parser.add_argument("--route", default="", help="Optional explicit route key, e.g. single_take, shot_driven, photo_to_video, magazine_broll.")
    parser.add_argument("--llm-model", default="gpt-5.5")
    parser.add_argument("--video-model", default=None)
    parser.add_argument("--target-duration", type=int, default=60)
    parser.add_argument("--shot-duration", type=int, default=0, help="Per-shot target, defaults to route/global suggestion.")
    parser.add_argument("--min-shot-duration", type=int, default=4)
    parser.add_argument("--max-shot-duration", type=int, default=16)
    parser.add_argument("--max-shots", type=int, default=0)
    parser.add_argument("--candidate-count", type=int, default=0, help="Candidates per shot (0 => infer from prompt, fallback 3).")
    parser.add_argument("--score-threshold", type=float, default=0.68)
    parser.add_argument("--selection-strategy", choices=["auto", "first", "manual"], default="auto")
    parser.add_argument("--selection-file", type=Path)
    parser.add_argument("--interactive", action="store_true", help="Enable per-shot interactive candidate selection.")
    parser.add_argument("--disable-llm-score", action="store_true", help="Use heuristic scoring only.")
    parser.add_argument("--require-pass", action="store_true", help="Only select candidates that pass the score threshold.")
    parser.add_argument("--max-pass-retry", type=int, default=0, help="Extra candidate attempts per shot when no candidate passes the threshold.")
    parser.add_argument("--duration", type=int, default=0)
    parser.add_argument("--fps", type=int, default=24)
    parser.add_argument("--aspect-ratio", default="")
    parser.add_argument("--response-format", default="url")
    parser.add_argument("--max-prompt-chars", type=int, default=1200)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--video-request-retries", type=int, default=2)
    parser.add_argument("--poll-attempts", type=int, default=8)
    parser.add_argument("--poll-delay", type=float, default=6.0)
    parser.add_argument("--send", action="store_true", help="Actually call video API.")
    parser.add_argument("--dry-run", action="store_true", help="Do not call remote APIs (request shaping only).")
    parser.add_argument("--print-only", action="store_true", help="Print planned payload summary only.")
    parser.add_argument("--no-assemble", action="store_true", help="Skip local final video assembly.")
    parser.add_argument("--ffmpeg-path", default="", help="Custom ffmpeg executable path.")
    parser.add_argument(
        "--assembly-timeout",
        type=int,
        default=DEFAULT_FFMPEG_TIMEOUT_SECONDS,
        help="Timeout for local ffmpeg operations (seconds).",
    )

    args = parser.parse_args()

    if args.candidate_count < 0:
        raise SystemExit("--candidate-count must be >= 0")
    if args.max_shots < 0:
        raise SystemExit("--max-shots must be >= 0")
    if args.candidate_count == 0:
        args.candidate_count = 3
    if args.candidate_count < 1:
        raise SystemExit("--candidate-count must be >= 1")

    args.out_dir = generate_video.ensure_writable_out_dir(args.out_dir)
    if args.duration > 0:
        args.target_duration = args.duration
    _normalize_inferred_params(args.user_prompt, args)

    if args.print_only:
        plan = {
            "mode": "print-only",
            "route": args.route,
            "target_duration": args.target_duration,
            "candidate_count": args.candidate_count,
            "max_pass_retry": args.max_pass_retry,
            "require_pass": args.require_pass,
            "selection_strategy": args.selection_strategy,
            "assemble": not args.no_assemble,
            "ffmpeg_path": args.ffmpeg_path or "(auto)",
            "assembly_timeout": args.assembly_timeout,
        }
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0

    video_env = _env(args.env_file)
    llm_env = _env(args.llm_env_file) if args.llm_env_file else video_env

    presets = _load_video_presets(args.preset_file)
    global_rules = presets.get("global_rules", {}) if isinstance(presets, dict) else {}

    route = _pick_route(args.user_prompt, args.route, presets)
    route_cfg = (presets.get("video_routes") or {}).get(route, {})
    if not isinstance(route_cfg, dict):
        route_cfg = {}

    defaults = global_rules.get("defaults", {}) if isinstance(global_rules, dict) else {}
    final_fps = args.fps or int(defaults.get("fps", 24) or 24)
    final_aspect = args.aspect_ratio or str(defaults.get("aspect_ratio", "16:9") or "16:9")
    args.fps = final_fps
    args.aspect_ratio = final_aspect

    shot_base = args.shot_duration or int(route_cfg.get("default_shot_duration") or defaults.get("default_shot_duration", 8) or 8)
    shot_min = max(2, _clamp_int(args.min_shot_duration, 2, 60))
    shot_max = _clamp_int(args.max_shot_duration, shot_min, 60)

    perform_send = bool(args.send)
    if not perform_send and not args.dry_run:
        print(
            "[INFO] video-story defaults to dry-run mode when --send is not provided."
            " add --send to call the video API.",
            flush=True,
        )
        args.dry_run = True
    storyboard_llm_env = llm_env if (perform_send and not args.dry_run and not args.disable_llm_score) else None
    storyboard, storyboard_meta, storyboard_mode = _build_storyboard(
        user_prompt=args.user_prompt,
        route=route,
        route_cfg=route_cfg,
        llm_env=storyboard_llm_env,
        llm_model=args.llm_model,
        target_duration=args.target_duration,
        max_shots=args.max_shots,
        min_shot=shot_min,
        max_shot=shot_max,
        shot_base=shot_base,
        timeout=args.timeout,
        retries=2,
    )

    (args.out_dir / "user_request.txt").write_text(args.user_prompt, encoding="utf-8")
    (args.out_dir / "video_route.json").write_text(json.dumps({"route": route, "config": route_cfg}, ensure_ascii=False, indent=2), encoding="utf-8")

    story_payload = {
        "mode": storyboard_mode,
        "route": route,
        "target_duration_seconds": args.target_duration,
        "shots": [asdict(x) for x in storyboard],
        "meta": storyboard_meta,
    }
    (args.out_dir / "story_plan.json").write_text(json.dumps(story_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    selection_override = _load_selection_map(args.selection_file, len(storyboard)) if args.selection_file else {}

    candidate_args = _compose_candidate_args(args)
    candidate_records: list[dict[str, Any]] = []
    selected_records: list[dict[str, Any]] = []

    candidate_args.send = perform_send
    candidate_args.dry_run = bool(args.dry_run) or (not perform_send)

    use_llm_score = (
        perform_send
        and (not args.dry_run)
        and (not args.disable_llm_score)
        and bool(llm_env)
    )

    pass_violations = 0
    for i, shot in enumerate(storyboard, start=1):
        shot_dir = args.out_dir / f"shot_{i:03d}"
        shot_dir.mkdir(parents=True, exist_ok=True)
        prior_goal = storyboard[i - 2].goal if i > 1 else None

        per_shot_candidates: list[dict[str, Any]] = []
        total_candidates_needed = args.candidate_count + (max(0, args.max_pass_retry) if args.require_pass else 0)

        for cand_idx in range(1, total_candidates_needed + 1):
            shot_prompt = _build_shot_prompt(
                user_prompt=args.user_prompt,
                route_cfg=route_cfg,
                shot=shot,
                shot_total=len(storyboard),
                previous_shot=prior_goal,
                final_total_seconds=args.target_duration,
                variant=cand_idx,
            )
            candidate_args.duration = shot.duration_seconds
            result = generate_video.run_video_once(
                env=video_env,
                out_dir=shot_dir / f"candidate_{cand_idx:03d}",
                user_prompt=shot_prompt,
                route=route,
                route_cfg=route_cfg,
                attempt=cand_idx,
                args=candidate_args,
            )
            candidate_record = _build_candidate_record(
                shot=shot,
            cand_idx=cand_idx,
            shot_prompt=shot_prompt,
            user_prompt=args.user_prompt,
            result=result,
            llm_env=llm_env if use_llm_score else None,
            llm_model=args.llm_model,
                timeout=args.timeout,
                use_llm_score=use_llm_score,
            )
            per_shot_candidates.append(candidate_record)

            if not args.require_pass:
                continue

            if cand_idx > args.candidate_count and _is_pass_candidate(candidate_record, args.score_threshold):
                break

            if cand_idx > args.candidate_count and any(
                _is_pass_candidate(c, args.score_threshold) for c in per_shot_candidates
            ):
                break
        if not per_shot_candidates:
            selected_records.append({
                "shot_index": shot.shot_index,
                "candidate_index": 1,
                "shot_title": shot.goal,
                "duration_seconds": shot.duration_seconds,
                "score": 0.0,
                "selected": False,
                "reason": "no candidate generated",
            })
            continue

        if args.interactive:
            chosen = _interactive_select_shot_candidates(shot, per_shot_candidates)
        elif shot.shot_index in selection_override:
            requested_index = selection_override[shot.shot_index]
            chosen = next((c for c in per_shot_candidates if c["candidate_index"] == requested_index), None)
            if chosen is None:
                chosen = _select_candidate(
                    per_shot_candidates,
                    args.score_threshold,
                    "auto",
                    require_pass=args.require_pass,
                )
        else:
            chosen = _select_candidate(
                per_shot_candidates,
                args.score_threshold,
                args.selection_strategy,
                require_pass=args.require_pass,
            )

        if not chosen:
            chosen = per_shot_candidates[0]

        chosen_url = None
        chosen_urls = chosen.get("urls")
        if isinstance(chosen_urls, list) and chosen_urls:
            chosen_url = chosen_urls[0]

        quality_ok = _is_pass_candidate(chosen, args.score_threshold)
        if (perform_send and not args.dry_run) and not quality_ok:
            pass_violations += 1

        chosen_sel = {
            "shot_index": shot.shot_index,
            "shot_title": shot.goal,
            "candidate_index": chosen.get("candidate_index"),
            "duration_seconds": int(chosen.get("duration_seconds") or shot.duration_seconds),
            "ok": bool(quality_ok),
            "score": chosen.get("score"),
            "selected_url": chosen_url,
            "selected_video_task_id": chosen.get("task_id"),
            "selection_reason": "interactive"
            if args.interactive
            else "selection_file"
            if shot.shot_index in selection_override
            else "auto_best_or_threshold",
            "selected": True,
            "quality_passed": quality_ok,
            "verdict": chosen.get("verdict"),
            "continuity": chosen.get("continuity"),
            "notes": chosen.get("notes"),
            "highlights": chosen.get("highlights"),
            "risks": chosen.get("risks"),
            "suggestions": chosen.get("suggestions"),
            "status": chosen.get("status"),
            "error": chosen.get("error"),
        }
        selected_records.append(chosen_sel)
        candidate_records.extend(per_shot_candidates)

        (shot_dir / "candidates.json").write_text(json.dumps(per_shot_candidates, ensure_ascii=False, indent=2), encoding="utf-8")

    (args.out_dir / "shot_candidates.json").write_text(json.dumps(candidate_records, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.out_dir / "shot_selection.json").write_text(json.dumps(selected_records, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_selection_template(args.out_dir, selected_records, candidate_records)

    assembly_plan = _build_assembly_plan(selected_records, args.target_duration, shot_min, shot_max, args.fps)
    (args.out_dir / "assembly_plan.json").write_text(json.dumps(assembly_plan, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.no_assemble:
        assembly_result = {
            "status": "skipped",
            "reason": "disabled by --no-assemble",
            "clips": [],
            "concat_file": str(args.out_dir / "assembly" / "concat_list.txt"),
            "assemble_script": str(args.out_dir / "assembly" / ("assemble_video.bat" if os.name == "nt" else "assemble_video.sh")),
            "final": str(args.out_dir / "assembly" / "final_video.mp4"),
            "ffmpeg": None,
            "timeline": assembly_plan.get("shots", []),
        }
    elif args.dry_run:
        assembly_result = {
            "status": "skipped",
            "reason": "dry-run mode; no remote video outputs were requested",
            "clips": [],
            "concat_file": str(args.out_dir / "assembly" / "concat_list.txt"),
            "assemble_script": str(args.out_dir / "assembly" / ("assemble_video.bat" if os.name == "nt" else "assemble_video.sh")),
            "final": str(args.out_dir / "assembly" / "final_video.mp4"),
            "ffmpeg": None,
            "timeline": assembly_plan.get("shots", []),
        }
    else:
        ffmpeg_bin = _find_ffmpeg(args.ffmpeg_path)
        assembly_result = _assemble_candidate_clips(
            selected_records,
            ffmpeg_bin,
            args.out_dir / "assembly",
            args.fps,
            shot_min,
            shot_max,
            args.target_duration,
            timeout=max(60, int(args.assembly_timeout)),
        )
        # keep a local copy for easier downstream reuse
        if isinstance(assembly_result.get("final"), str):
            final_path = Path(assembly_result["final"])
            if final_path.exists():
                assembly_result["final_size_bytes"] = final_path.stat().st_size

    summary = {
        "pipeline": "storyboard -> generate candidates -> score -> select -> assemble",
        "out_dir": str(args.out_dir),
        "user_prompt": args.user_prompt,
        "route": route,
        "target_duration_seconds": args.target_duration,
        "target_shots": storyboard_meta.get("shot_count_target", math.ceil(args.target_duration / max(1, shot_base))),
        "actual_shots": storyboard_meta.get("shot_count_actual", len(storyboard)),
        "target_shot_duration": shot_base,
        "selection_strategy": args.selection_strategy,
        "require_pass": args.require_pass,
        "max_pass_retry": args.max_pass_retry,
        "selection_file_used": str(args.selection_file) if args.selection_file else None,
        "candidate_count": args.candidate_count,
        "storyboard_mode": storyboard_mode,
        "storyboard_count": len(storyboard),
        "quality_gate_failed_shots": pass_violations,
        "quality_gate_blocked": args.require_pass and pass_violations > 0,
        "candidate_summary": _timestamped_summary(candidate_records),
        "selection_summary": _timestamped_summary(selected_records),
        "selection_summary_by_quality": {
            "total": len(selected_records),
            "passed": sum(1 for item in selected_records if item.get("quality_passed")),
        },
        "assembly": {
            "actual_total_seconds": assembly_plan.get("actual_total_seconds"),
            "shots": len(assembly_plan.get("shots", [])),
            "status": assembly_result.get("status"),
            "method": assembly_result.get("reason"),
            "result_file": str(args.out_dir / "assembly" / "assembly_result.json"),
        },
    }
    (args.out_dir / "assembly_result.json").write_text(json.dumps(assembly_result, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.out_dir / "video_story_final_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.require_pass and pass_violations > 0:
        return 2

    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

