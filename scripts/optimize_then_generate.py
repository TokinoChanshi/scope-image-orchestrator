#!/usr/bin/env python3
"""Optimize an image prompt with an LLM, then optionally call an image API.

Default pipeline:
  user prompt -> GPT-5.5 prompt optimizer -> gpt-image-2 image generation

Example:
  python scripts/optimize_then_generate.py --env-file key.env --user-prompt "Hu Tao live-action cosplay magazine cover" --out-dir scope_runs/test --send --download
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import time
from pathlib import Path
from typing import Any

import requests

from api_adapters import build_image_request, build_text_request, extract_image_items, extract_text, normalize_adapter

SKILL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PRESET_LIBRARY_FILE = SKILL_ROOT / "references" / "scope-preset-library.json"

DEFAULT_SYSTEM = """
You are an advanced image prompt optimization engineer, visual director, photography art director,
character designer, and commercial poster planner.

Turn the user's rough idea into a high-quality, coherent production prompt for image generation.
Output JSON only with these fields:
- understanding_zh: short Chinese understanding
- optimized_prompt_zh: polished Chinese image prompt
- optimized_prompt_en: polished English prompt directly usable by image generation
- negative_prompt: concise negative constraints
- aspect_ratio: suggested aspect ratio
- notes: short practical notes

Rules:
- Prefer one natural production prompt, not keyword spam and not malformed JSON.
- If the user asks for real-person cosplay or anime-to-real, emphasize photorealistic live-action quality,
  natural skin texture, pores, believable facial anatomy, realistic hair, premium costume materials, and high-budget poster lighting.
- For magazine/poster requests, add typography as a design element, but warn that exact text may not be perfect.
- Keep sensual direction visually restrained and adult-only: adult 25+, no nudity, no lingerie, no see-through clothing, no explicit pose, no minors, no school uniform.
- Avoid cheap cosplay, plastic skin, doll face, anime/CGI look when realism is requested.
- Keep optimized_prompt_en around 160-280 words for API stability.
""".strip()

LEGACY_SYSTEM_SECTIONS = {
    "prompt-presets.md": "prompt_presets_md",
    "prompt-optimizer-compact.md": "prompt_optimizer_compact_md",
    "prompt-optimizer-engineering.md": "prompt_optimizer_engineering_md",
    "external-prompt-patterns.md": "external_prompt_patterns_md",
}


def load_env_file(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        if value:
            env[key.strip()] = value
            os.environ[key.strip()] = value
    return env


def read_text_if_exists(path: Path | None, section: str | None = None) -> str:
    if not path:
        return ""
    if not path.exists() and path.name in LEGACY_SYSTEM_SECTIONS:
        section = section or LEGACY_SYSTEM_SECTIONS[path.name]
        path = DEFAULT_PRESET_LIBRARY_FILE
    if not path.exists():
        raise SystemExit(f"System prompt file not found: {path}")
    if path.suffix.lower() == ".json":
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception as exc:  # noqa: BLE001
            raise SystemExit(f"System prompt JSON file could not be read: {path}: {exc}") from exc
        guides = data.get("optimizer_guides", {}) if isinstance(data, dict) else {}
        if isinstance(guides, dict):
            value = guides.get(section or "prompt_optimizer_engineering_md")
            if isinstance(value, str) and value.strip():
                return value[:12000]
        compact = {
            "global_rules": data.get("global_rules", {}) if isinstance(data, dict) else {},
            "routes": data.get("routes", {}) if isinstance(data, dict) else {},
        }
        return json.dumps(compact, ensure_ascii=False, indent=2)[:12000]
    text = path.read_text(encoding="utf-8-sig")
    # Keep the reference prompt compact enough for endpoints that reject huge payloads.
    return text[:12000]


def extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, flags=re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    return {"optimized_prompt_en": text, "raw": text}


def call_optimizer(env: dict[str, str], user_prompt: str, model: str, system_file: Path | None, timeout: int, retries: int) -> dict[str, Any]:
    base = (
        env.get("SCOPE_LLM_BASE_URL")
        or env.get("SCOPE_CHAT_BASE_URL")
        or env.get("SCOPE_LLM_ENDPOINT_URL")
        or env.get("SCOPE_CHAT_ENDPOINT_URL")
        or ""
    ).rstrip("/")
    if not base:
        raise SystemExit("Missing SCOPE_LLM_BASE_URL")
    api_key = env.get("SCOPE_LLM_API_KEY") or env.get("SCOPE_CHAT_API_KEY")
    if not api_key:
        raise SystemExit("Missing SCOPE_LLM_API_KEY")

    reference = read_text_if_exists(system_file, section="prompt_optimizer_engineering_md")
    system = DEFAULT_SYSTEM
    if reference:
        system += "\n\nUse this user-provided prompt engineering guide as additional policy/reference:\n" + reference

    adapter = normalize_adapter(env.get("SCOPE_LLM_FORMAT") or env.get("SCOPE_CHAT_FORMAT"), "openai-chat")
    url, headers, payload, adapter = build_text_request(
        adapter,
        base,
        api_key,
        model,
        system,
        user_prompt,
        env,
        temperature=0.35,
        json_object=True,
    )
    last_error: str | None = None
    for attempt in range(1, retries + 2):
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=timeout)
            body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {"text": r.text}
            if r.status_code == 200:
                content = extract_text(adapter, body)
                parsed = extract_json(content)
                return {"status": r.status_code, "model": model, "adapter": adapter, "parsed": parsed, "raw": body}
            last_error = f"HTTP {r.status_code}: {str(body)[:500]}"
            if r.status_code not in {429, 500, 502, 503, 504}:
                break
        except requests.RequestException as exc:
            last_error = str(exc)
        print(f"[WARN] optimizer attempt={attempt} failed: {last_error}", flush=True)
        if attempt <= retries:
            time.sleep(5 * attempt)
    return {"status": "error", "model": model, "error": last_error}


def call_image(env: dict[str, str], prompt: str, model: str, timeout: int, retries: int) -> dict[str, Any]:
    adapter = normalize_adapter(env.get("SCOPE_IMAGE_FORMAT"), "openai-images")
    base = (
        env.get("SCOPE_IMAGE_BASE_URL")
        or env.get("SCOPE_GOOGLE_BASE_URL")
        or env.get("SCOPE_IMAGE_ENDPOINT_URL")
        or ""
    ).rstrip("/")
    if not base:
        raise SystemExit("Missing SCOPE_IMAGE_BASE_URL")
    api_key = env.get("SCOPE_IMAGE_API_KEY") or env.get("SCOPE_GOOGLE_API_KEY")
    if not api_key:
        raise SystemExit("Missing SCOPE_IMAGE_API_KEY")
    endpoint_override = None
    if adapter in {"openai-images", "openai-images-legacy"}:
        endpoint_override = env.get("SCOPE_IMAGE_GENERATIONS_URL")
    elif adapter == "openai-responses-image":
        endpoint_override = env.get("SCOPE_IMAGE_RESPONSES_URL")
    elif adapter == "google-gemini-image":
        endpoint_override = env.get("SCOPE_GOOGLE_GENERATE_CONTENT_URL") or env.get("SCOPE_IMAGE_GENERATE_CONTENT_URL")
    elif adapter == "generic-image-json":
        endpoint_override = env.get("SCOPE_IMAGE_ENDPOINT_URL")
    url, headers, payload, adapter = build_image_request(
        adapter,
        base,
        api_key,
        model,
        prompt,
        env,
        endpoint_override=endpoint_override,
        response_format=env.get("SCOPE_OPENAI_IMAGES_RESPONSE_FORMAT") if adapter == "openai-images-legacy" else None,
    )
    last_error: str | None = None
    for attempt in range(1, retries + 2):
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=timeout)
            try:
                body: Any = r.json()
            except ValueError:
                body = {"text": r.text}
            if r.status_code == 200:
                return {"status": r.status_code, "body": body, "payload_redacted": redact_b64(payload), "adapter": adapter, "endpoint": url}
            last_error = f"HTTP {r.status_code}: {str(body)[:500]}"
            if r.status_code not in {429, 500, 502, 503, 504}:
                break
        except requests.RequestException as exc:
            last_error = str(exc)
        print(f"[WARN] image attempt={attempt} failed: {last_error}", flush=True)
        if attempt <= retries:
            time.sleep(8 * attempt)
    return {"status": "error", "error": last_error, "payload_redacted": redact_b64(payload), "adapter": adapter, "endpoint": url}


def redact_b64(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: (f"[base64 omitted len={len(v)}]" if k in {"b64_json", "result", "data"} and isinstance(v, str) and len(v) > 512 else redact_b64(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact_b64(v) for v in obj]
    return obj


def extract_first_url(body: Any) -> str | None:
    for item in extract_image_items(body):
        url = item.get("url")
        if isinstance(url, str) and url.startswith("http"):
            return url
    if isinstance(body, dict):
        data = body.get("data")
        if isinstance(data, list) and data:
            first = data[0]
            if isinstance(first, dict):
                for key in ("url", "image_url", "fileUrl", "file_url"):
                    value = first.get(key)
                    if isinstance(value, str) and value.startswith("http"):
                        return value
        for key in ("url", "image_url", "fileUrl", "file_url"):
            value = body.get(key)
            if isinstance(value, str) and value.startswith("http"):
                return value
    return None


def extract_first_b64(body: Any) -> str | None:
    for item in extract_image_items(body):
        b64 = item.get("b64")
        if isinstance(b64, str) and b64:
            return b64
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", required=True, type=Path)
    parser.add_argument("--user-prompt", required=True)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--optimizer-model", default="gpt-5.5")
    parser.add_argument("--image-model", default="gpt-image-2")
    parser.add_argument("--system-file", type=Path, default=DEFAULT_PRESET_LIBRARY_FILE)
    parser.add_argument("--timeout", default=300, type=int)
    parser.add_argument("--retries", default=2, type=int)
    parser.add_argument("--send", action="store_true")
    parser.add_argument("--download", action="store_true")
    args = parser.parse_args()

    env = load_env_file(args.env_file)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    opt = call_optimizer(env, args.user_prompt, args.optimizer_model, args.system_file, args.timeout, args.retries)
    (args.out_dir / "optimizer_result.json").write_text(json.dumps(opt, ensure_ascii=False, indent=2), encoding="utf-8")
    parsed = opt.get("parsed", {}) if isinstance(opt, dict) else {}
    optimized_prompt = parsed.get("optimized_prompt_en") or parsed.get("english_prompt") or parsed.get("prompt_en") or parsed.get("raw") or args.user_prompt
    (args.out_dir / "optimized_prompt.txt").write_text(str(optimized_prompt), encoding="utf-8")
    print("[OK] optimized prompt written", args.out_dir / "optimized_prompt.txt", flush=True)

    if not args.send:
        return 0
    image = call_image(env, str(optimized_prompt), args.image_model, args.timeout, args.retries)
    (args.out_dir / "image_result.json").write_text(json.dumps(redact_b64(image), ensure_ascii=False, indent=2), encoding="utf-8")
    url = extract_first_url(image.get("body"))
    b64 = extract_first_b64(image.get("body"))
    if b64:
        out = args.out_dir / "image.png"
        out.write_bytes(base64.b64decode(b64))
        print("[OK] image saved", out, flush=True)
    if url:
        (args.out_dir / "image_url.txt").write_text(url + "\n", encoding="utf-8")
        print("[OK] image url", url, flush=True)
        if args.download:
            try:
                r = requests.get(url, timeout=120, headers={"User-Agent": "Mozilla/5.0 SCOPE-Image-Orchestrator/1.0"})
                if r.status_code == 200 and r.content:
                    out = args.out_dir / "image.png"
                    out.write_bytes(r.content)
                    print("[OK] downloaded", out, flush=True)
            except requests.RequestException as exc:
                print("[WARN] download failed", exc, flush=True)
    else:
        print("[WARN] no image URL found", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

