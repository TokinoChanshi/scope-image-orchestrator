#!/usr/bin/env python3
"""Call a configured SCOPE provider role, or dry-run the request.

Dry-run is default and never sends secrets:
    python scripts/call_provider.py --config references/provider-config.example.json --role reasoner --prompt "hello"

Send only after environment variables are set:
    python scripts/call_provider.py --config scope.provider.json --role reasoner --prompt "hello" --send

Or load local secrets from an env file:
    python scripts/call_provider.py --env-file scope.local.env --config scope.provider.json --role reasoner --prompt "hello" --send
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from render_provider_payload import load_config, render  # noqa: E402

ENV_PATTERN = re.compile(r"^\$\{([A-Z_][A-Z0-9_]*)\}$")
BEARER_ENV_PATTERN = re.compile(r"^Bearer \$\{([A-Z_][A-Z0-9_]*)\}$")


def load_env_file(path: Path) -> None:
    """Load KEY=VALUE lines into os.environ without printing secrets."""
    if not path.exists():
        raise SystemExit(f"Env file not found: {path}")
    for lineno, raw_line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise SystemExit(f"Invalid env line {path}:{lineno}: expected KEY=VALUE")
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if not re.match(r"^[A-Z_][A-Z0-9_]*$", key):
            raise SystemExit(f"Invalid env key {path}:{lineno}: {key}")
        if value:
            os.environ[key] = value


def resolve_env_string(value: str) -> str:
    m = ENV_PATTERN.match(value)
    if m:
        env_name = m.group(1)
        env_value = os.getenv(env_name)
        if not env_value:
            raise SystemExit(f"Missing environment variable: {env_name}")
        return env_value
    return value


def resolve_request(req: dict[str, Any]) -> dict[str, Any]:
    req = json.loads(json.dumps(req))
    req["endpoint"] = resolve_env_string(req["endpoint"])
    auth = req.get("headers", {}).get("Authorization", "")
    m = BEARER_ENV_PATTERN.match(auth)
    if m:
        env_name = m.group(1)
        env_value = os.getenv(env_name)
        if not env_value:
            raise SystemExit(f"Missing environment variable: {env_name}")
        req["headers"]["Authorization"] = "Bearer " + env_value
    return req


def redacted(req: dict[str, Any]) -> dict[str, Any]:
    req = json.loads(json.dumps(req))
    if "Authorization" in req.get("headers", {}):
        req["headers"]["Authorization"] = "Bearer <redacted>"
    return req


def post_json(req: dict[str, Any], timeout: int) -> dict[str, Any]:
    try:
        import requests  # type: ignore

        response = requests.post(
            req["endpoint"],
            headers=req["headers"],
            json=req["payload"],
            timeout=timeout,
        )
        try:
            body: Any = response.json()
        except ValueError:
            body = response.text
        return {"status": response.status_code, "headers": dict(response.headers), "body": body}
    except ImportError:
        pass
    except Exception as exc:  # noqa: BLE001 - CLI utility should surface provider/network errors
        return {"status": "request_error", "error": str(exc)}

    data = json.dumps(req["payload"]).encode("utf-8")
    request = urllib.request.Request(req["endpoint"], data=data, headers=req["headers"], method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - user-configured endpoint
            body = response.read().decode("utf-8", errors="replace")
            try:
                parsed: Any = json.loads(body)
            except json.JSONDecodeError:
                parsed = body
            return {"status": response.status, "headers": dict(response.headers), "body": parsed}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return {"status": exc.code, "error": body}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--role", required=True)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--system", default="You are executing one stage of the SCOPE image orchestration workflow. Return concise structured output.")
    parser.add_argument("--size", default="1024x1024")
    parser.add_argument("--n", default=1, type=int)
    parser.add_argument("--timeout", default=120, type=int)
    parser.add_argument("--env-file", type=Path, help="Load KEY=VALUE secrets from a local env file before sending.")
    parser.add_argument("--send", action="store_true", help="Actually POST the request. Default is dry-run.")
    args = parser.parse_args()

    if args.env_file:
        load_env_file(args.env_file)

    cfg = load_config(args.config)
    req = render(cfg, args.role, args.prompt, args.system, args.size, args.n)
    if not args.send:
        print(json.dumps(redacted(req), ensure_ascii=False, indent=2))
        return 0

    resolved = resolve_request(req)
    result = post_json(resolved, args.timeout)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
