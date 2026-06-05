#!/usr/bin/env python3
"""Audit generated images with a configured vision model.

The script is intentionally provider-light: it sends each image as a data URL to
The current helper uses Chat Completions-style vision and asks for JSON verdicts. Use it after
preset_regression_batch.py or run_scope_pipeline.py to create repair queues.
"""
from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import pathlib
import random
import time
from typing import Any

import requests

AUDIT_SYSTEM = """
You are a strict visual QA verifier for SCOPE image generation.
Return JSON only:
{
  "overall":"pass|needs_repair|failed",
  "category":"portrait|magazine|poster|cosplay|interior|product|unknown",
  "scores":{"route_fit":0-10,"realism":0-10,"composition":0-10,"text_quality":0-10,"diversity_anchor":0-10},
  "failures":["short concrete issue"],
  "repair_prompt":"one concise English repair instruction, empty if pass"
}
Rules:
- Pass means the image clearly fits the expected category and has no major artifact.
- For magazine/poster, inspect text hierarchy and repeated/gibberish text.
- For people, inspect same-face/generic AI face risk, hands, anatomy, hair, fabric, and non-explicit adult-safe presentation.
- For interior/product, inspect geometry, scale, warped objects, duplicate hero objects, and material realism.
- Be concise and actionable.
""".strip()

CATEGORY_HINTS = {
    "portrait": "Expected route: editorial lifestyle portrait, no typography, distinct real-person face and setting.",
    "magazine": "Expected route: high-fashion magazine cover with short crisp masthead/cover lines and clean editorial grid.",
    "poster": "Expected route: cinematic movie poster with title zone, hero silhouette, atmosphere, credits block.",
    "cosplay": "Expected route: live-action character/cosplay poster, real materials, iconic anchors, not anime render.",
    "interior": "Expected route: photorealistic architectural interior visualization, straight lines, realistic scale.",
    "product": "Expected route: commercial still life with one hero product, crisp material detail, minimal props.",
}

RETRYABLE_HTTP_STATUS = {408, 409, 425, 429, 500, 502, 503, 504, 520, 521, 522, 523, 524}
TRANSIENT_ERROR_PATTERNS = (
    "RemoteDisconnected",
    "SSLEOFError",
    "EOF occurred in violation of protocol",
    "Connection aborted",
    "Read timed out",
    "ConnectTimeout",
    "Connection reset",
    "origin_bad_gateway",
)


def load_env_file(path: pathlib.Path) -> dict[str, str]:
    env: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8-sig", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def image_to_data_url(path: pathlib.Path) -> str:
    mime = mimetypes.guess_type(str(path))[0] or "image/png"
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def infer_category(path: pathlib.Path, root: pathlib.Path) -> str:
    try:
        rel = path.relative_to(root)
        if len(rel.parts) >= 2:
            return rel.parts[0]
    except Exception:
        pass
    stem = path.stem.lower()
    for cat in CATEGORY_HINTS:
        if cat in stem:
            return cat
    return "unknown"


def extract_json(text: str) -> Any:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.removeprefix("json").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        raise


def is_transient_error(error: str | None) -> bool:
    if not error:
        return False
    return any(pattern in error for pattern in TRANSIENT_ERROR_PATTERNS)


def post_json_reliable(url: str, headers: dict[str, str], payload: dict[str, Any], timeout: int, attempts: int, label: str) -> tuple[bool, Any, str | None]:
    request_headers = dict(headers)
    request_headers["Connection"] = "close"
    last_error: str | None = None
    for attempt in range(1, attempts + 1):
        try:
            with requests.Session() as session:
                r = session.post(url, headers=request_headers, json=payload, timeout=(20, timeout))
            try:
                body = r.json()
            except Exception:
                body = {"text": r.text[:1000]}
            if r.status_code == 200:
                return True, body, None
            last_error = f"HTTP {r.status_code}: {str(body)[:500]}"
            if r.status_code not in RETRYABLE_HTTP_STATUS:
                return False, body, last_error
        except Exception as exc:  # noqa: BLE001
            last_error = repr(exc)
            body = {"error": last_error}
            if not is_transient_error(last_error):
                return False, body, last_error
        print(f"[WARN] {label} attempt={attempt}/{attempts} failed: {last_error}", flush=True)
        if attempt < attempts:
            delay = min(70, 8 * (1.7 ** (attempt - 1))) + random.uniform(0.5, 2.5)
            time.sleep(delay)
    return False, {"error": last_error}, last_error


def audit_one(env: dict[str, str], model: str, image_path: pathlib.Path, category: str, timeout: int) -> dict[str, Any]:
    base = (env.get("SCOPE_VISION_BASE_URL") or env.get("SCOPE_REASONER_BASE_URL") or env.get("SCOPE_LLM_BASE_URL") or "").rstrip("/")
    key = env.get("SCOPE_VISION_API_KEY") or env.get("SCOPE_REASONER_API_KEY") or env.get("SCOPE_LLM_API_KEY")
    if not base:
        raise SystemExit("Missing SCOPE_VISION_BASE_URL / SCOPE_REASONER_BASE_URL / SCOPE_LLM_BASE_URL")
    if not key:
        raise SystemExit("Missing SCOPE_VISION_API_KEY / SCOPE_REASONER_API_KEY / SCOPE_LLM_API_KEY")
    url = base + "/chat/completions"
    user_text = f"Image file: {image_path.name}\nExpected category: {category}\n{CATEGORY_HINTS.get(category, '')}"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": AUDIT_SYSTEM},
            {"role": "user", "content": [
                {"type": "text", "text": user_text},
                {"type": "image_url", "image_url": {"url": image_to_data_url(image_path)}},
            ]},
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": "Bearer " + key,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Connection": "close",
        "User-Agent": "Mozilla/5.0 SCOPE-Image-Orchestrator/1.0",
    }
    ok, body, error = post_json_reliable(url, headers, payload, timeout, attempts=5, label=f"audit {image_path.name}")
    if not ok:
        return {"image": str(image_path), "category": category, "ok": False, "error": error or "audit failed", "body": body}
    content = body.get("choices", [{}])[0].get("message", {}).get("content", "{}")
    try:
        parsed = extract_json(content)
    except Exception as exc:  # noqa: BLE001
        return {"image": str(image_path), "category": category, "ok": False, "error": f"JSONDecodeError: {repr(exc)}", "body": body}
    return {"image": str(image_path), "category": category, "ok": True, "audit": parsed}


def collect_images(root: pathlib.Path, pattern: str) -> list[pathlib.Path]:
    if root.is_file():
        return [root]
    return sorted(
        p for p in root.rglob(pattern)
        if p.is_file() and p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
        and p.name not in {"contact_sheet.png", "overview_contact_sheet.png"}
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", required=True, type=pathlib.Path)
    parser.add_argument("--image-root", required=True, type=pathlib.Path)
    parser.add_argument("--out-file", type=pathlib.Path)
    parser.add_argument("--model", default="grok-4.3")
    parser.add_argument("--pattern", default="*.png")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--delay", type=float, default=2.0)
    args = parser.parse_args()

    env = load_env_file(args.env_file)
    images = collect_images(args.image_root, args.pattern)
    if args.limit > 0:
        images = images[: args.limit]
    out_file = args.out_file or (args.image_root if args.image_root.is_dir() else args.image_root.parent) / "grok_visual_audit.json"

    results: list[dict[str, Any]] = []
    for i, image in enumerate(images, start=1):
        category = infer_category(image, args.image_root if args.image_root.is_dir() else args.image_root.parent)
        print(f"[AUDIT] {i}/{len(images)} {category} {image.name}", flush=True)
        try:
            result = audit_one(env, args.model, image, category, args.timeout)
        except Exception as exc:  # noqa: BLE001
            result = {"image": str(image), "category": category, "ok": False, "error": repr(exc)}
        results.append(result)
        out_file.write_text(json.dumps({"count": len(results), "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
        time.sleep(args.delay)

    needs_repair = [r for r in results if r.get("ok") and r.get("audit", {}).get("overall") != "pass"]
    infra_failures = [r for r in results if not r.get("ok")]
    summary = {
        "count": len(results),
        "needs_repair_count": len(needs_repair),
        "infra_failure_count": len(infra_failures),
        "infra_failure_examples": [r.get("image") for r in infra_failures][:8],
        "results": results,
    }
    out_file.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
