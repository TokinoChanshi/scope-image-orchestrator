#!/usr/bin/env python3
"""Video generation entrypoint for SCOPE skill extension.

The current stage focuses on a reproducible request/response pipeline:
1) build a compact video plan
2) call a configured text->video API
3) persist request/response and extract result URLs/ids
4) produce a stable final summary artifact
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import time
from pathlib import Path
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from api_adapters import build_video_request, extract_video_items

SCRIPT_ROOT = Path(__file__).resolve().parent
DEFAULT_PRESET_FILE = SCRIPT_ROOT.parent / "references" / "scope-video-presets.json"

RETRYABLE_HTTP_STATUS = {408, 409, 425, 429, 500, 502, 503, 504, 520, 521, 522, 523, 524, 530}


def _env_str(name: str, default: str) -> str:
    return os.getenv(name, "").strip() or default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "").strip() or str(default))
    except Exception:
        return default


def load_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        raise SystemExit(f"env file not found: {path}")
    env: dict[str, str] = {}
    for lineno, raw_line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise SystemExit(f"invalid env line {path}:{lineno}: expected KEY=VALUE")
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if not re.match(r"^[A-Z_][A-Z0-9_]*$", key):
            raise SystemExit(f"invalid env key {path}:{lineno}: {key}")
        env[key] = value
        os.environ[key] = value
    return env


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

    candidates: list[Path] = [requested]
    if not candidates[0].is_absolute():
        candidates.append((Path.cwd() / requested).resolve())
        candidates.append(Path("scope_runs") / requested)
    fallback = Path("scope_runs") / candidates[0].name
    candidates.append(fallback)

    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate.resolve())
        if key in seen:
            continue
        seen.add(key)
        try:
            if can_write_dir(candidate):
                return candidate.resolve()
        except OSError:
            continue
    raise RuntimeError(f"cannot create writable directory: {requested}")


def _load_video_presets(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"video preset file not found: {path}")
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(raw, dict):
        raise SystemExit("video preset file format invalid")
    return raw


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
        for keyword in cfg.get("keywords", []) or []:
            if not isinstance(keyword, str):
                continue
            if keyword.lower() in text:
                hits += 1
        if hits:
            ranked.append((hits, route_name))
    if not ranked:
        return "single_take"
    ranked.sort(key=lambda x: (-x[0], x[1]))
    return ranked[0][1]


def _build_video_prompt(user_prompt: str, route_cfg: dict[str, Any], duration: int, aspect_ratio: str, fps: int) -> str:
    route_hint = route_cfg.get("route_hint", "")
    planning = route_cfg.get("planning_template", "")
    shot_design = route_cfg.get("shot_design", "")
    boosters = route_cfg.get("booster_lines", []) or []
    negatives = route_cfg.get("negative", "") if route_cfg.get("negative") else "Negative: no random glitches, no repeated artifacts, no fake subtitles." 
    lines = [
        f"video production request: {user_prompt}",
        f"route: {route_hint}",
        planning,
        shot_design,
        f"duration_seconds: {duration}",
        f"aspect_ratio: {aspect_ratio}",
        f"fps: {fps}",
    ]
    if boosters:
        lines.extend(f"enhance: {line}" for line in boosters if isinstance(line, str))
    if negatives:
        lines.append(negatives)
    return " \n".join(x for x in lines if x)


def _safe_length(prompt: str, max_chars: int) -> str:
    if len(prompt) <= max_chars:
        return prompt
    return prompt[: max_chars - 3].rstrip() + "..."


def _build_request_session(timeout: int) -> requests.Session:
    retry = Retry(total=1, status=3, allowed_methods=frozenset(["POST", "GET"]), backoff_factor=0.5, status_forcelist=RETRYABLE_HTTP_STATUS)
    adapter = HTTPAdapter(max_retries=retry)
    session = requests.Session()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({"User-Agent": "SCOPE-Video-Skill/1.0"})
    session.request = session.request  # type: ignore[attr-defined]
    return session


def request_json_with_retries(
    session: requests.Session,
    method: str,
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any] | None,
    timeout: int,
    attempts: int,
    label: str,
) -> tuple[int | str, Any, str]:
    last_error: str | None = None
    for attempt in range(1, attempts + 1):
        try:
            response = session.request(method=method, url=url, headers=headers, json=payload, timeout=timeout)
            status = response.status_code
            try:
                body: Any = response.json()
            except ValueError:
                body = response.text
            if status in RETRYABLE_HTTP_STATUS and attempt < attempts:
                wait = min(20, (2 ** attempt) + random.uniform(0.5, 1.5))
                print(f"[WARN] {label} HTTP {status} attempt={attempt}; retrying in {wait:.1f}s", flush=True)
                time.sleep(wait)
                continue
            return status, body, ""
        except requests.RequestException as exc:
            last_error = str(exc)
            if attempt < attempts:
                wait = min(12, (2 ** attempt) + random.uniform(0.5, 1.2))
                print(f"[WARN] {label} request error attempt={attempt}: {last_error}", flush=True)
                time.sleep(wait)
                continue
            return "error", {"error": last_error}, last_error
    return "error", {"error": last_error}, str(last_error)


def post_json_with_retries(session: requests.Session, url: str, headers: dict[str, str], payload: dict[str, Any], timeout: int, attempts: int, label: str) -> tuple[int | str, Any, str]:
    return request_json_with_retries(session, "POST", url, headers, payload, timeout, attempts, label)


def get_json_with_retries(session: requests.Session, url: str, headers: dict[str, str], timeout: int, attempts: int, label: str) -> tuple[int | str, Any, str]:
    return request_json_with_retries(session, "GET", url, headers, None, timeout, attempts, label)


def _build_status_url(task_id: str, env: dict[str, str], base_url: str) -> str | None:
    template = env.get("SCOPE_VIDEO_TASK_STATUS_URL")
    if template:
        if "{task_id}" in template:
            return template.format(task_id=task_id)
        if template.rstrip("/").endswith("videos"):
            return template.rstrip("/") + "/" + task_id
        return template + task_id

    base = base_url.rstrip("/")
    if base:
        return f"{base}/v1/videos/{task_id}"
    return None


def poll_video_task(session: requests.Session, task_url: str, headers: dict[str, str], timeout: int, attempts: int, delay: float) -> tuple[bool, Any]:
    for attempt in range(1, attempts + 1):
        status, body, _ = get_json_with_retries(session, task_url, headers=headers, timeout=timeout, attempts=1, label=f"video task {task_url}")
        if status == "error":
            continue
        if status in {200, 201, 202}:
            state = None
            if isinstance(body, dict):
                state = (body.get("status") or body.get("state") or body.get("stage") or "").lower()
                if state in {"completed", "succeeded", "done", "finished"}:
                    return True, body
                if state in {"failed", "error", "canceled", "cancelled", "rejected"}:
                    return False, body
            if extract_video_items(body):
                return True, body
        if attempt < attempts:
            time.sleep(delay)
    return False, {"error": "video task timeout or no completed status"}


def run_video_once(
    env: dict[str, str],
    out_dir: Path,
    user_prompt: str,
    route: str,
    route_cfg: dict[str, Any],
    attempt: int,
    args: argparse.Namespace,
) -> dict[str, Any]:
    duration = int(args.duration)
    fps = int(args.fps)
    aspect_ratio = args.aspect_ratio or route_cfg.get("default_aspect_ratio") or "16:9"
    max_chars = int(args.max_prompt_chars)

    out_dir.mkdir(parents=True, exist_ok=True)

    video_model = args.video_model or env.get("SCOPE_VIDEO_MODEL") or "video-model"
    base_url = env.get("SCOPE_VIDEO_BASE_URL") or env.get("SCOPE_VIDEO_ENDPOINT_URL") or env.get("SCOPE_VIDEO_GENERATIONS_URL")
    api_key = env.get("SCOPE_VIDEO_API_KEY") or env.get("SCOPE_VIDEO_KEY")
    if args.dry_run:
        if not base_url:
            base_url = "https://api.openai.com/v1"
        if not api_key:
            api_key = "dry-run-token"
    else:
        if not base_url:
            raise RuntimeError("missing SCOPE_VIDEO_BASE_URL or SCOPE_VIDEO_ENDPOINT_URL or SCOPE_VIDEO_GENERATIONS_URL")
        if not api_key:
            raise RuntimeError("missing SCOPE_VIDEO_API_KEY / SCOPE_VIDEO_KEY")

    raw_prompt = _build_video_prompt(user_prompt, route_cfg, duration, aspect_ratio, fps)
    final_prompt = _safe_length(raw_prompt, max_chars)
    request_payload_file = out_dir / f"video_request.attempt_{attempt}.json"
    response_file = out_dir / f"video_response.attempt_{attempt}.json"
    (out_dir / "video_prompt.txt").write_text(final_prompt, encoding="utf-8")

    adapter = env.get("SCOPE_VIDEO_FORMAT", "openai-videos")
    status_url = env.get("SCOPE_VIDEO_STATUS_URL")
    task_url_template = env.get("SCOPE_VIDEO_TASK_STATUS_URL")

    endpoint_override = env.get("SCOPE_VIDEO_GENERATIONS_URL")
    target_url, headers, payload, adapter_name = build_video_request(
        adapter,
        base_url,
        api_key,
        video_model,
        final_prompt,
        env,
        duration_seconds=duration,
        fps=fps,
        aspect_ratio=aspect_ratio,
        n=1,
        response_format=args.response_format,
        endpoint_override=endpoint_override,
    )

    if args.dry_run:
        request_payload_file.write_text(
            json.dumps(
                {
                    "adapter": adapter_name,
                    "url": target_url,
                    "headers": headers,
                    "payload": payload,
                    "env_template": {
                        "SCOPE_VIDEO_FORMAT": adapter,
                        "SCOPE_VIDEO_BASE_URL": base_url,
                        "SCOPE_VIDEO_MODEL": video_model,
                    },
                    "status_url": status_url,
                    "task_url_template": task_url_template,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return {
            "attempt": attempt,
            "route": route,
            "dry_run": True,
            "payload": payload,
            "url": target_url,
        }

    session = _build_request_session(args.timeout)
    status, body, error = post_json_with_retries(
        session,
        target_url,
        headers=headers,
        payload=payload,
        timeout=args.timeout,
        attempts=args.video_request_retries,
        label=f"video generation attempt={attempt}",
    )
    if status == "error":
        return {
            "attempt": attempt,
            "route": route,
            "ok": False,
            "error": error,
            "request": payload,
            "status": status,
        }

    response_file.write_text(json.dumps({"status": status, "body": body}, ensure_ascii=False, indent=2), encoding="utf-8")
    items = extract_video_items(body)
    if not items:
        task_id = body.get("task_id") if isinstance(body, dict) else None
        if task_id:
            poll_url = _build_status_url(str(task_id), env, base_url)
            if poll_url:
                ok, poll_body = poll_video_task(
                    session,
                    poll_url,
                    headers=headers,
                    timeout=args.timeout,
                    attempts=args.poll_attempts,
                    delay=args.poll_delay,
                )
                items = extract_video_items(poll_body)
                if not ok and not items:
                    return {
                        "attempt": attempt,
                        "route": route,
                        "ok": False,
                        "error": "video task did not reach completion",
                        "task_id": str(task_id),
                        "poll_body": poll_body,
                    }
            else:
                return {
                    "attempt": attempt,
                    "route": route,
                    "ok": False,
                    "error": "task accepted but no poll url configured",
                    "task_id": str(task_id),
                    "body": body,
                }

    if not items:
        return {
            "attempt": attempt,
            "route": route,
            "ok": False,
            "status": status,
            "error": "no video output field in response",
            "response": body,
        }

    video_records = [
        {
            "url": item.get("url") or "",
            "source": item.get("source") or "body",
            "task_id": item.get("task_id") if isinstance(item, dict) else None,
        }
        for item in items
        if item.get("url")
    ]
    if not video_records:
        return {
            "attempt": attempt,
            "route": route,
            "ok": False,
            "error": "video response detected but no usable url",
            "response": body,
        }

    out_file = out_dir / f"video_urls.attempt_{attempt}.json"
    out_file.write_text(json.dumps(video_records, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "attempt": attempt,
        "route": route,
        "ok": True,
        "status": status,
        "videos": video_records,
        "request": payload,
        "status_task": body.get("status") if isinstance(body, dict) else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="SCOPE video runner.")
    parser.add_argument("--env-file", required=True, type=Path)
    parser.add_argument("--user-prompt", required=True)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--preset-file", type=Path, default=DEFAULT_PRESET_FILE)
    parser.add_argument("--route", default="")
    parser.add_argument("--count", type=int, default=1)
    parser.add_argument("--video-model", default=None)
    parser.add_argument("--duration", type=int, default=8)
    parser.add_argument("--fps", type=int, default=24)
    parser.add_argument("--aspect-ratio", default="")
    parser.add_argument("--response-format", default="url")
    parser.add_argument("--max-prompt-chars", type=int, default=1200)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--video-request-retries", type=int, default=2)
    parser.add_argument("--poll-attempts", type=int, default=8)
    parser.add_argument("--poll-delay", type=float, default=6.0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--send", action="store_true")
    args = parser.parse_args()
    if not args.send:
        args.dry_run = True

    if not args.send:
        print("[INFO] default dry-run mode. add --send to actually call video API.")

    out_dir = ensure_writable_out_dir(args.out_dir)
    env = load_env_file(args.env_file)
    presets = _load_video_presets(args.preset_file)
    defaults = presets.get("global_rules", {}) if isinstance(presets, dict) else {}
    args.duration = max(1, args.duration or _env_int("SCOPE_VIDEO_DURATION", int(defaults.get("defaults", {}).get("duration_seconds", 8) or 8)))
    args.fps = max(1, args.fps or _env_int("SCOPE_VIDEO_FPS", int(defaults.get("defaults", {}).get("fps", 24) or 24)))
    if not args.aspect_ratio:
        args.aspect_ratio = _env_str("SCOPE_VIDEO_ASPECT_RATIO", str(defaults.get("defaults", {}).get("aspect_ratio", "16:9") or "16:9"))
    if not args.max_prompt_chars:
        args.max_prompt_chars = int(defaults.get("defaults", {}).get("max_prompt_chars", 1200) or 1200)

    (out_dir / "user_prompt.txt").write_text(args.user_prompt, encoding="utf-8")

    route = _pick_route(args.user_prompt, args.route, presets)
    route_cfg = (presets.get("video_routes") or {}).get(route, {})
    if not isinstance(route_cfg, dict):
        route_cfg = {}
    (out_dir / "video_route.json").write_text(json.dumps({"route": route, "config": route_cfg}, ensure_ascii=False, indent=2), encoding="utf-8")

    records: list[dict[str, Any]] = []
    summary: dict[str, Any] = {
        "route": route,
        "send": args.send,
        "dry_run": not args.send,
        "attempts": [],
        "preset_file": str(args.preset_file),
        "out_dir": str(out_dir),
    }

    if args.send:
        for i in range(1, max(1, args.count) + 1):
            res = run_video_once(env, out_dir / f"attempt_{i:03d}", args.user_prompt, route, route_cfg, i, args)
            records.append(res)
            summary["attempts"].append(res)
            if res.get("ok"):
                continue
    else:
        res = run_video_once(env, out_dir / "attempt_001", args.user_prompt, route, route_cfg, 1, args)
        records.append(res)
        summary["attempts"].append(res)

    summary["final"] = records[-1] if records else {}
    summary["artifact_count"] = len(list(out_dir.rglob("*")))
    summary_file = out_dir / "video_final_summary.json"
    summary_file.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    # flatten all URLs for quick review
    urls: list[dict[str, str]] = []
    for r in records:
        for item in r.get("videos", []) or []:
            url = item.get("url")
            if isinstance(url, str):
                urls.append({"attempt": str(r.get("attempt", "")), "url": url, "source": item.get("source", "")})
    (out_dir / "video_urls_all.json").write_text(json.dumps(urls, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
