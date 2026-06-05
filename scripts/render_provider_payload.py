#!/usr/bin/env python3
"""Render a provider request payload for a SCOPE role without sending it.

Usage examples:
    python scripts/render_provider_payload.py --config references/provider-config.example.json --role reasoner --prompt "test"
    python scripts/render_provider_payload.py --config references/provider-config.example.json --role image_generator --prompt "a cat" --size 1024x1024
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from api_adapters import normalize_adapter, openai_url


def load_config(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def replace_template(value: Any, mapping: dict[str, str]) -> Any:
    if isinstance(value, str):
        for key, val in mapping.items():
            value = value.replace("{{" + key + "}}", val)
        return value
    if isinstance(value, list):
        return [replace_template(item, mapping) for item in value]
    if isinstance(value, dict):
        return {k: replace_template(v, mapping) for k, v in value.items()}
    return value


def render_openai_endpoint(base_url: str, path: str) -> str:
    path = path.lstrip("/").removeprefix("v1/")
    if base_url.startswith("${"):
        return base_url.rstrip("/") + "/" + path
    return openai_url(base_url, path)


def render(cfg: dict[str, Any], role: str, prompt: str, system: str, size: str, n: int) -> dict[str, Any]:
    route = cfg["roles"][role]
    provider_name = route["provider"]
    model = route["model"]
    provider = cfg["providers"][provider_name]
    adapter = normalize_adapter(provider["adapter"], provider["adapter"])
    defaults = provider.get("default_options", {})

    base_url = provider.get("base_url") or "${" + provider.get("base_url_env", "BASE_URL") + "}"
    auth = "Bearer ${" + provider.get("api_key_env", "API_KEY") + "}"

    if adapter == "openai-responses":
        payload = {
            "model": model,
            "input": [
                {"role": "developer", "content": [{"type": "input_text", "text": system}]},
                {"role": "user", "content": [{"type": "input_text", "text": prompt}]},
            ],
            **defaults,
        }
        endpoint = render_openai_endpoint(base_url, "responses")
    elif adapter == "openai-chat":
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            **defaults,
        }
        endpoint = render_openai_endpoint(base_url, "chat/completions")
    elif adapter in {"openai-images", "openai-images-legacy"}:
        payload = {
            "model": model,
            "prompt": prompt,
            **defaults,
        }
        if adapter == "openai-images-legacy":
            payload.setdefault("n", n or 1)
            payload.setdefault("response_format", "b64_json")
        endpoint = provider.get("generations_url") or "${" + provider.get("generations_url_env", "SCOPE_IMAGE_GENERATIONS_URL") + "}"
        if endpoint.startswith("${"):
            endpoint = render_openai_endpoint(base_url, "images/generations")
    elif adapter == "openai-responses-image":
        payload = {
            "model": model,
            "input": prompt,
            "tools": [{"type": "image_generation"}],
            **defaults,
        }
        endpoint = render_openai_endpoint(base_url, "responses")
    elif adapter == "google-gemini":
        payload = {
            "contents": [{"role": "user", "parts": [{"text": system + "\n\n" + prompt}]}],
            **defaults,
        }
        endpoint = base_url.rstrip("/") + "/models/" + model + ":generateContent"
        auth = "${" + provider.get("api_key_env", "GEMINI_API_KEY") + "}"
    elif adapter == "google-gemini-image":
        payload = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]},
            **defaults,
        }
        endpoint = base_url.rstrip("/") + "/models/" + model + ":generateContent"
        auth = "${" + provider.get("api_key_env", "GEMINI_API_KEY") + "}"
    elif adapter == "generic-text-json":
        payload = {
            "model": model,
            "system": system,
            "prompt": prompt,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "json": True,
            **defaults,
        }
        endpoint = provider.get("endpoint_url") or base_url
    elif adapter == "generic-vision-json":
        payload = {
            "model": model,
            "system": system,
            "prompt": prompt,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "images": ["data:image/png;base64,..."],
            "image": "data:image/png;base64,...",
            "json": True,
            **defaults,
        }
        endpoint = provider.get("endpoint_url") or base_url
    elif adapter == "generic-image-json":
        payload = {
            "model": model,
            "prompt": prompt,
            "n": n or defaults.get("n", 1),
            "size": size or defaults.get("size", "1024x1024"),
            **defaults,
        }
        endpoint = provider.get("endpoint_url") or base_url
    elif adapter == "custom-image-json":
        payload = {
            "model": model,
            "prompt": prompt,
            "size": size or defaults.get("size", "1024x1024"),
            "n": n or defaults.get("n", 1),
            "metadata": {"scope_role": role},
        }
        endpoint = base_url
    elif adapter == "custom-json":
        payload = replace_template(
            provider.get("request_template", {}),
            {"model": model, "prompt": prompt, "system": system, "role": role},
        )
        endpoint = base_url
    else:
        raise ValueError(f"Unsupported adapter: {adapter}")

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "SCOPE-Image-Orchestrator/1.0",
    }
    if auth.startswith("Bearer "):
        headers["Authorization"] = auth
    else:
        headers["x-goog-api-key"] = auth

    return {
        "role": role,
        "provider": provider_name,
        "adapter": adapter,
        "endpoint": endpoint,
        "headers": headers,
        "payload": payload,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--role", required=True)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--system", default="You are executing one stage of the SCOPE image orchestration workflow. Return concise structured output.")
    parser.add_argument("--size", default="1024x1024")
    parser.add_argument("--n", default=1, type=int)
    args = parser.parse_args()

    cfg = load_config(args.config)
    if args.role not in cfg.get("roles", {}):
        raise SystemExit(f"Unknown role: {args.role}")
    print(json.dumps(render(cfg, args.role, args.prompt, args.system, args.size, args.n), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
