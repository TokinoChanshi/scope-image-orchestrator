#!/usr/bin/env python3
"""Validate a SCOPE provider config.

Usage:
    python scripts/validate_provider_config.py references/provider-config.example.json
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

ALLOWED_ADAPTERS = {
    "openai-chat",
    "openai-responses",
    "openai-chat-completions",
    "openai-chat-completions-vision",
    "openai-images",
    "openai-images-generations",
    "openai-images-legacy",
    "openai-responses-image",
    "openai-videos",
    "openai-videos-legacy",
    "google-gemini",
    "google-gemini-image",
    "generic-text-json",
    "generic-vision-json",
    "generic-image-json",
    "generic-video-json",
    "custom-image-json",
    "custom-json",
}
ENV_RE = re.compile(r"^[A-Z_][A-Z0-9_]*$")


def fail(message: str) -> None:
    print(f"[FAIL] {message}")
    raise SystemExit(1)


def warn(message: str) -> None:
    print(f"[WARN] {message}")


def obj(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        fail(f"{name} must be an object")
    return value


def arr(value: Any, name: str) -> list[Any]:
    if not isinstance(value, list):
        fail(f"{name} must be a list")
    return value


def nonempty_str(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        fail(f"{name} must be a non-empty string")
    return value


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[1] in {"-h", "--help"}:
        print(__doc__.strip())
        return 0 if len(argv) == 2 and argv[1] in {"-h", "--help"} else 2

    path = Path(argv[1])
    try:
        cfg = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:  # noqa: BLE001
        fail(f"could not read JSON: {exc}")

    cfg = obj(cfg, "root")
    if cfg.get("version") != "scope-provider-config-v1":
        warn("version should be 'scope-provider-config-v1'")

    roles = obj(cfg.get("roles"), "roles")
    providers = obj(cfg.get("providers"), "providers")
    if not roles:
        fail("roles must not be empty")
    if not providers:
        fail("providers must not be empty")

    for provider_name, provider in providers.items():
        provider = obj(provider, f"providers.{provider_name}")
        adapter = nonempty_str(provider.get("adapter"), f"providers.{provider_name}.adapter")
        if adapter not in ALLOWED_ADAPTERS:
            fail(f"providers.{provider_name}.adapter must be one of {sorted(ALLOWED_ADAPTERS)}")

        has_base = bool(provider.get("base_url") or provider.get("base_url_env"))
        if not has_base:
            warn(f"providers.{provider_name} has no base_url/base_url_env")
        for key in ("api_key_env", "base_url_env"):
            value = provider.get(key)
            if value is not None and (not isinstance(value, str) or not ENV_RE.match(value)):
                fail(f"providers.{provider_name}.{key} must be an environment variable name")

        models = arr(provider.get("models", []), f"providers.{provider_name}.models")
        for model in models:
            nonempty_str(model, f"providers.{provider_name}.models[]")

        # custom-json/custom-image-json are accepted as aliases for the generic
        # JSON adapters; request_template remains optional for hand-written
        # wrapper tools.

    for role_name, route in roles.items():
        route = obj(route, f"roles.{role_name}")
        provider_name = nonempty_str(route.get("provider"), f"roles.{role_name}.provider")
        model = nonempty_str(route.get("model"), f"roles.{role_name}.model")
        if provider_name not in providers:
            fail(f"roles.{role_name} references unknown provider: {provider_name}")
        provider_models = providers[provider_name].get("models", [])
        if provider_models and model not in provider_models:
            warn(f"roles.{role_name} model '{model}' is not listed in providers.{provider_name}.models")

    print(f"[OK] {path}: {len(providers)} providers, {len(roles)} role routes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
