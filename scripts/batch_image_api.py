#!/usr/bin/env python3
"""Batch-generate safe adult fashion/glamour portraits with an image API.

The script never prints API keys. It loads a local KEY=VALUE env file and writes
prompts/results under --out-dir.

Example:
    python scripts/batch_image_api.py --env-file path/to/key.env --out-dir scope_runs/test --nationalities Chinese,Japanese,Korean,French,American,Brazilian --n-per 4 --send
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

import requests

SAFE_SUFFIX = (
    "Adult fashion glamour portrait, clearly age 25+, elegant designer dress, "
    "cinematic studio lighting, high-end magazine photography, medium shot, realistic skin texture. "
    "No nudity, no lingerie, no sheer clothing, no explicit sexual pose, no minors, no school uniform, no stereotypes."
)

VARIATIONS = [
    "warm golden-hour studio backdrop, 85mm portrait lens, soft rim light",
    "minimal black-and-white editorial set, dramatic side lighting, film grain",
    "luxury hotel lounge atmosphere, refined evening styling, shallow depth of field",
    "clean modern studio with silk backdrop, softbox lighting, elegant cinematic color grade",
]


def load_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        raise SystemExit(f"Env file not found: {path}")
    env: dict[str, str] = {}
    for lineno, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise SystemExit(f"Invalid env line {path}:{lineno}: expected KEY=VALUE")
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if value:
            env[key] = value
            os.environ[key] = value
    return env


def make_prompt(nationality: str, variation: str) -> str:
    return (
        f"Beautiful adult woman from {nationality} nationality. "
        f"{variation}. "
        f"{SAFE_SUFFIX}"
    )


def make_cosplay_cover_prompt(subject: str, romaji: str, environment: str) -> str:
    return (
        "Photorealistic vertical 2:3 cinematic cosplay magazine cover. "
        f"Adult 25+ female cosplayer inspired by {subject}: real human face, iconic hairstyle and accessories, "
        "luxury fantasy couture costume faithfully translated into real fabric. "
        "High-end glossy fashion cover, commercial photography, RAW full-frame photo realism, 85mm lens, "
        "shallow depth of field, real pores, fine skin texture, subtle subsurface scattering, natural skin oil sheen, "
        "glassy lips, eye catchlights. Confident refined fashion pose, elegant collarbone and neck line, "
        f"{environment}, warm bokeh, light mist, organized rich background details. "
        "Teal cool ambient light plus warm skin key light, strong hair rim light, glossy highlights. "
        f"Editorial typography frame: Japanese title, Romanized name {romaji}, small English tagline, circular seal, JERLIN 2026. "
        "No anime, no CGI, no plastic skin, no nudity, no lingerie, no see-through clothing, no minor, no school uniform, "
        "no explicit pose, no repeated text."
    )


def post_generation(url: str, api_key: str, model: str, prompt: str, n: int, timeout: int) -> dict[str, Any]:
    payload = {
        "model": model,
        "prompt": prompt,
        "n": n,
        "response_format": "url",
    }
    headers = {
        "Authorization": "Bearer " + api_key,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 SCOPE-Image-Orchestrator/1.0",
    }
    response = requests.post(url, headers=headers, json=payload, timeout=timeout)
    try:
        body: Any = response.json()
    except ValueError:
        body = response.text
    return {"status": response.status_code, "body": body, "payload_redacted": {**payload, "prompt": prompt}}


def post_generation_with_retries(
    url: str,
    api_key: str,
    model: str,
    prompt: str,
    n: int,
    timeout: int,
    retries: int,
    retry_delay: float,
) -> dict[str, Any]:
    last_error: str | None = None
    for attempt in range(1, retries + 2):
        try:
            result = post_generation(url, api_key, model, prompt, n, timeout)
            if result.get("status") in {429, 500, 502, 503, 504} and attempt <= retries:
                print(f"[WARN] HTTP {result.get('status')} attempt={attempt}; retrying", flush=True)
                time.sleep(retry_delay)
                continue
            return result
        except requests.RequestException as exc:
            last_error = str(exc)
            print(f"[WARN] request failed attempt={attempt}: {last_error}", flush=True)
            if attempt <= retries:
                time.sleep(retry_delay)
    return {"status": "request_error", "body": {"error": last_error}, "payload_redacted": {"model": model, "prompt": prompt, "n": n, "response_format": "url"}}


def write_outputs(out_dir: Path, plan: list[dict[str, Any]], results: list[dict[str, Any]], all_urls: list[dict[str, str]]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# image batch results", ""]
    for item in all_urls:
        lines.append(f"- {item['nationality']} #{item['index']}: {item['url']}")
    (out_dir / "image_urls.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def extract_urls(body: Any) -> list[str]:
    urls: list[str] = []
    if isinstance(body, dict):
        data = body.get("data")
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    for key in ("url", "image_url", "fileUrl", "file_url"):
                        value = item.get(key)
                        if isinstance(value, str) and value.startswith("http"):
                            urls.append(value)
        for key in ("url", "image_url", "fileUrl", "file_url"):
            value = body.get(key)
            if isinstance(value, str) and value.startswith("http"):
                urls.append(value)
        images = body.get("images")
        if isinstance(images, list):
            for item in images:
                if isinstance(item, dict):
                    value = item.get("url") or item.get("image_url")
                    if isinstance(value, str) and value.startswith("http"):
                        urls.append(value)
    return urls


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--nationalities", default="Chinese,Japanese,Korean,French,American,Brazilian")
    parser.add_argument("--n-per", default=4, type=int)
    parser.add_argument("--template", choices=["glamour", "cosplay-cover"], default="glamour")
    parser.add_argument("--subject", default="Hu Tao")
    parser.add_argument("--romaji", default="HUTAO")
    parser.add_argument("--environment", default="mysterious Liyue-style night set with lanterns")
    parser.add_argument("--model", default=None)
    parser.add_argument("--timeout", default=240, type=int)
    parser.add_argument("--delay", default=1.0, type=float)
    parser.add_argument("--retries", default=2, type=int)
    parser.add_argument("--retry-delay", default=5.0, type=float)
    parser.add_argument("--combine-n", action="store_true", help="Use one API request with n=n_per. Default sends n=1 repeatedly for stability.")
    parser.add_argument("--send", action="store_true", help="Actually call the API. Default writes only prompts/plan.")
    args = parser.parse_args()

    env = load_env_file(args.env_file)
    api_key = env.get("SCOPE_IMAGE_API_KEY")
    if args.send and not api_key:
        raise SystemExit("Missing SCOPE_IMAGE_API_KEY in env file")
    base = (env.get("SCOPE_IMAGE_BASE_URL") or "").rstrip("/")
    url = env.get("SCOPE_IMAGE_GENERATIONS_URL") or (base + "/v1/images/generations" if base else "")
    if args.send and not url:
        raise SystemExit("Missing SCOPE_IMAGE_GENERATIONS_URL or SCOPE_IMAGE_BASE_URL")
    model = args.model or env.get("SCOPE_IMAGE_MODEL") or "gpt-image-2"

    nationalities = [x.strip() for x in args.nationalities.split(",") if x.strip()]
    args.out_dir.mkdir(parents=True, exist_ok=True)

    plan: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    all_urls: list[dict[str, str]] = []

    for nationality in nationalities:
        prompt = make_cosplay_cover_prompt(args.subject, args.romaji, args.environment) if args.template == "cosplay-cover" else make_prompt(nationality, VARIATIONS[0])
        record = {"nationality": nationality, "n": args.n_per, "model": model, "prompt": prompt, "combine_n": args.combine_n}
        plan.append(record)
        if not args.send:
            continue
        print(f"[RUN] {nationality} x {args.n_per}", flush=True)
        if args.combine_n:
            result = post_generation_with_retries(url, api_key or "", model, prompt, args.n_per, args.timeout, args.retries, args.retry_delay)
            result_record = {**record, "response": result}
            results.append(result_record)
            urls = extract_urls(result.get("body"))
            for idx, image_url in enumerate(urls, start=1):
                all_urls.append({"nationality": nationality, "index": str(idx), "url": image_url})
            print(f"[DONE] {nationality}: status={result['status']} urls={len(urls)}", flush=True)
            time.sleep(args.delay)
        else:
            for idx in range(1, args.n_per + 1):
                if args.template == "cosplay-cover":
                    prompt_i = make_cosplay_cover_prompt(args.subject, args.romaji, args.environment)
                else:
                    prompt_i = make_prompt(nationality, VARIATIONS[(idx - 1) % len(VARIATIONS)])
                print(f"[RUN] {nationality} #{idx}", flush=True)
                result = post_generation_with_retries(url, api_key or "", model, prompt_i, 1, args.timeout, args.retries, args.retry_delay)
                result_record = {**record, "index": idx, "prompt": prompt_i, "response": result}
                results.append(result_record)
                urls = extract_urls(result.get("body"))
                for url_idx, image_url in enumerate(urls, start=1):
                    all_urls.append({"nationality": nationality, "index": str(idx if len(urls) == 1 else f"{idx}.{url_idx}"), "url": image_url})
                print(f"[DONE] {nationality} #{idx}: status={result['status']} urls={len(urls)}", flush=True)
                write_outputs(args.out_dir, plan, results, all_urls)
                time.sleep(args.delay)

    write_outputs(args.out_dir, plan, results, all_urls)
    print(f"[OK] wrote {args.out_dir}")
    print(f"[OK] total urls: {len(all_urls)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

