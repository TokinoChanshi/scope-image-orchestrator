#!/usr/bin/env python3
"""Official API-shape adapters for SCOPE image orchestration.

The skill keeps model routing provider-neutral, but request payloads should be
explicit about the wire format.  This module supports:

- OpenAI Chat Completions for JSON text / vision analysis.
- OpenAI Responses for JSON text / vision analysis and image-generation tool.
- OpenAI Images API for text-to-image generation.
- Gemini generateContent for text / vision and native image generation.
- Generic JSON adapters for simple provider wrappers.
"""
from __future__ import annotations

import base64
import mimetypes
from pathlib import Path
from typing import Any
from urllib.parse import urlencode


ADAPTER_ALIASES = {
    "openai-compatible": "openai-chat",
    "openai-compatible-chat": "openai-chat",
    "openai-compatible-vision": "openai-chat",
    "openai-compatible-image": "openai-images-legacy",
    "openai-compatible-images": "openai-images-legacy",
    "openai-compatible-image-json": "openai-images-legacy",
    "legacy": "openai-images-legacy",
    "legacy-image": "openai-images-legacy",
    "legacy-image-json": "openai-images-legacy",
    "legacy-openai-compatible": "openai-images-legacy",
    "legacy-openai-compatible-image": "openai-images-legacy",
    "legacy-chat": "openai-chat",
    "legacy-vision": "openai-chat",
    "openai-chat-completions": "openai-chat",
    "openai-chat-completions-vision": "openai-chat",
    "openai-chat-vision": "openai-chat",
    "openai-responses-vision": "openai-responses",
    "openai-image": "openai-images",
    "openai-images-generations": "openai-images",
    "openai-images-generation": "openai-images",
    "openai-image-generation": "openai-images",
    "openai-images-legacy-json": "openai-images-legacy",
    "openai-video": "openai-videos",
    "openai-videos": "openai-videos",
    "openai-videos-generations": "openai-videos-legacy",
    "openai-video-generation": "openai-videos",
    "openai-videos-legacy": "openai-videos-legacy",
    "openai-responses-image-generation": "openai-responses-image",
    "gemini": "google-gemini",
    "google": "google-gemini",
    "google-gemini-vision": "google-gemini",
    "gemini-image": "google-gemini-image",
    "google-image": "google-gemini-image",
    "google-gemini-native-image": "google-gemini-image",
    "generic": "generic-text-json",
    "generic-text": "generic-text-json",
    "generic-chat": "generic-text-json",
    "generic-chat-json": "generic-text-json",
    "generic-vision": "generic-vision-json",
    "generic-image": "generic-image-json",
    "generic-video": "generic-video-json",
    "generic-video-json": "generic-video-json",
    "custom-json": "generic-text-json",
    "custom-text-json": "generic-text-json",
    "custom-vision-json": "generic-vision-json",
    "custom-image-json": "generic-image-json",
}


def normalize_adapter(raw: str | None, default: str) -> str:
    value = (raw or default).strip().lower().replace("_", "-")
    return ADAPTER_ALIASES.get(value, value)


def openai_url(base: str, path: str) -> str:
    base = base.rstrip("/")
    path = path.lstrip("/")
    if base.endswith("/v1"):
        return base + "/" + path.removeprefix("v1/")
    return base + "/v1/" + path.removeprefix("v1/")


def google_generate_url(base: str, model: str, api_key: str = "", auth_mode: str = "header") -> str:
    base = base.rstrip("/")
    if base.endswith(":generateContent"):
        url = base
    else:
        model_path = model if model.startswith("models/") else f"models/{model}"
        url = f"{base}/{model_path}:generateContent"
    if auth_mode == "query" and api_key:
        sep = "&" if "?" in url else "?"
        url += sep + urlencode({"key": api_key})
    return url


def json_headers(api_key: str, auth_mode: str = "bearer") -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "SCOPE-Image-Orchestrator/1.0",
        "Connection": "close",
    }
    if api_key:
        if auth_mode in {"google-header", "header", "x-goog-api-key"}:
            headers["x-goog-api-key"] = api_key
        elif auth_mode == "query":
            pass
        else:
            headers["Authorization"] = "Bearer " + api_key
    return headers


def data_url(path: Path) -> str:
    mime = mimetypes.guess_type(str(path))[0] or "image/png"
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def google_inline_data(path: Path) -> dict[str, Any]:
    mime = mimetypes.guess_type(str(path))[0] or "image/png"
    return {
        "inlineData": {
            "mimeType": mime,
            "data": base64.b64encode(path.read_bytes()).decode("ascii"),
        }
    }


def google_auth_mode(env: dict[str, str], role: str = "") -> str:
    role_key = f"SCOPE_{role.upper()}_GOOGLE_API_KEY_AUTH" if role else ""
    return (
        (env.get(role_key) if role_key else None)
        or env.get("SCOPE_GOOGLE_API_KEY_AUTH")
        or "header"
    ).strip().lower()


def generic_endpoint(env: dict[str, str], role: str, base_url: str, api_key: str = "") -> str:
    role_upper = role.upper()
    url = (
        env.get(f"SCOPE_{role_upper}_ENDPOINT_URL")
        or env.get(f"SCOPE_{role_upper}_URL")
        or env.get("SCOPE_GENERIC_ENDPOINT_URL")
        or base_url
    ).rstrip("/")
    if generic_auth_mode(env, role) == "query" and api_key:
        sep = "&" if "?" in url else "?"
        key_name = env.get(f"SCOPE_{role_upper}_API_KEY_QUERY_PARAM") or env.get("SCOPE_GENERIC_API_KEY_QUERY_PARAM") or "key"
        url += sep + urlencode({key_name: api_key})
    return url


def generic_auth_mode(env: dict[str, str], role: str) -> str:
    role_upper = role.upper()
    return (
        env.get(f"SCOPE_{role_upper}_AUTH_MODE")
        or env.get("SCOPE_GENERIC_AUTH_MODE")
        or "bearer"
    ).strip().lower()


def generic_payload_style(env: dict[str, str], role: str, default: str = "both") -> str:
    role_upper = role.upper()
    return (
        env.get(f"SCOPE_{role_upper}_PAYLOAD_STYLE")
        or env.get("SCOPE_GENERIC_PAYLOAD_STYLE")
        or default
    ).strip().lower()


def generic_json_headers(api_key: str, env: dict[str, str], role: str) -> dict[str, str]:
    """Headers for generic wrappers.

    Supported auth modes:
      bearer       -> Authorization: Bearer <key>
      api-key      -> X-API-Key: <key>
      header       -> custom header from SCOPE_<ROLE>_AUTH_HEADER or SCOPE_GENERIC_AUTH_HEADER
      query/none   -> no auth header
    """
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "SCOPE-Image-Orchestrator/1.0",
        "Connection": "close",
    }
    if not api_key:
        return headers
    mode = generic_auth_mode(env, role)
    role_upper = role.upper()
    if mode in {"none", "query"}:
        return headers
    if mode in {"bearer", "authorization"}:
        headers["Authorization"] = "Bearer " + api_key
    elif mode == "basic":
        headers["Authorization"] = "Basic " + api_key
    elif mode in {"api-key", "x-api-key"}:
        headers["X-API-Key"] = api_key
    elif mode.startswith("header:"):
        headers[mode.split(":", 1)[1].strip() or "X-API-Key"] = api_key
    else:
        header_name = env.get(f"SCOPE_{role_upper}_AUTH_HEADER") or env.get("SCOPE_GENERIC_AUTH_HEADER") or "X-API-Key"
        headers[header_name] = api_key
    return headers


def generic_text_payload(
    model: str,
    system: str,
    user: str,
    *,
    temperature: float,
    json_object: bool,
    style: str,
) -> dict[str, Any]:
    if style == "messages":
        payload: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": temperature,
        }
    elif style == "prompt":
        payload = {
            "model": model,
            "system": system,
            "prompt": user,
            "temperature": temperature,
        }
    else:
        payload = {
            "model": model,
            "system": system,
            "prompt": user,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": temperature,
        }
    if json_object:
        payload["json"] = True
        payload["response_format"] = {"type": "json_object"}
    return payload


def truthy_env(env: dict[str, str], name: str, default: bool = False) -> bool:
    raw = env.get(name)
    if raw is None or raw == "":
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on", "y"}


def add_legacy_reference_image(payload: dict[str, Any], reference_image: Path | None, env: dict[str, str]) -> bool:
    """Attach reference image using the older JSON field style.

    This is intentionally limited to legacy/generic adapters. Official OpenAI
    Responses and Gemini adapters use their own `input_image` / `inlineData`
    shapes instead.
    """
    if not reference_image or not truthy_env(env, "SCOPE_SEND_REFERENCE_IMAGE", False):
        return False
    ref = data_url(reference_image)
    field = (env.get("SCOPE_REFERENCE_IMAGE_FIELD") or "images").strip() or "images"
    if field in {"images", "reference_images", "input_images"}:
        payload[field] = [ref]
    else:
        payload[field] = ref
    return True


def build_text_request(
    adapter_raw: str,
    base_url: str,
    api_key: str,
    model: str,
    system: str,
    user: str,
    env: dict[str, str] | None = None,
    *,
    temperature: float = 0.25,
    json_object: bool = True,
) -> tuple[str, dict[str, str], dict[str, Any], str]:
    env = env or {}
    adapter = normalize_adapter(adapter_raw, "openai-chat")
    if adapter == "openai-chat":
        payload: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
        }
        if json_object:
            payload["response_format"] = {"type": "json_object"}
        return openai_url(base_url, "chat/completions"), json_headers(api_key), payload, adapter

    if adapter == "openai-responses":
        instruction = system
        if json_object:
            instruction = instruction.rstrip() + "\nReturn one valid JSON object only."
        payload = {
            "model": model,
            "input": [
                {
                    "role": "developer",
                    "content": [{"type": "input_text", "text": instruction}],
                },
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": user}],
                },
            ],
            "temperature": temperature,
        }
        return openai_url(base_url, "responses"), json_headers(api_key), payload, adapter

    if adapter == "google-gemini":
        auth_mode = google_auth_mode(env, "llm")
        instruction = system
        if json_object:
            instruction = instruction.rstrip() + "\nReturn one valid JSON object only."
        payload = {
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "systemInstruction": {"parts": [{"text": instruction}]},
            "generationConfig": {"temperature": temperature},
        }
        if json_object:
            payload["generationConfig"]["responseMimeType"] = "application/json"
        return google_generate_url(base_url, model, api_key, auth_mode), json_headers(api_key, auth_mode), payload, adapter

    if adapter == "generic-text-json":
        auth_mode = generic_auth_mode(env, "llm")
        payload = generic_text_payload(
            model,
            system,
            user,
            temperature=temperature,
            json_object=json_object,
            style=generic_payload_style(env, "llm", "both"),
        )
        return generic_endpoint(env, "llm", base_url, api_key), generic_json_headers(api_key, env, "llm"), payload, adapter

    raise ValueError(f"unsupported text adapter: {adapter_raw}")


def build_vision_request(
    adapter_raw: str,
    base_url: str,
    api_key: str,
    model: str,
    system: str,
    text: str,
    image_paths: list[Path],
    env: dict[str, str] | None = None,
    *,
    temperature: float = 0.0,
    json_object: bool = True,
) -> tuple[str, dict[str, str], dict[str, Any], str]:
    env = env or {}
    adapter = normalize_adapter(adapter_raw, "openai-chat")
    if adapter == "openai-chat":
        content: list[dict[str, Any]] = [{"type": "text", "text": text}]
        content.extend({"type": "image_url", "image_url": {"url": data_url(p)}} for p in image_paths)
        payload: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": content},
            ],
            "temperature": temperature,
        }
        if json_object:
            payload["response_format"] = {"type": "json_object"}
        return openai_url(base_url, "chat/completions"), json_headers(api_key), payload, adapter

    if adapter == "openai-responses":
        instruction = system
        if json_object:
            instruction = instruction.rstrip() + "\nReturn one valid JSON object only."
        content = [{"type": "input_text", "text": text}]
        content.extend({"type": "input_image", "image_url": data_url(p)} for p in image_paths)
        payload = {
            "model": model,
            "input": [
                {
                    "role": "developer",
                    "content": [{"type": "input_text", "text": instruction}],
                },
                {"role": "user", "content": content},
            ],
            "temperature": temperature,
        }
        return openai_url(base_url, "responses"), json_headers(api_key), payload, adapter

    if adapter == "google-gemini":
        auth_mode = google_auth_mode(env, "vision")
        instruction = system
        if json_object:
            instruction = instruction.rstrip() + "\nReturn one valid JSON object only."
        parts: list[dict[str, Any]] = [{"text": text}]
        parts.extend(google_inline_data(p) for p in image_paths)
        payload = {
            "contents": [{"role": "user", "parts": parts}],
            "systemInstruction": {"parts": [{"text": instruction}]},
            "generationConfig": {"temperature": temperature},
        }
        if json_object:
            payload["generationConfig"]["responseMimeType"] = "application/json"
        return google_generate_url(base_url, model, api_key, auth_mode), json_headers(api_key, auth_mode), payload, adapter

    if adapter == "generic-vision-json":
        auth_mode = generic_auth_mode(env, "vision")
        image_data_urls = [data_url(p) for p in image_paths]
        payload = generic_text_payload(
            model,
            system,
            text,
            temperature=temperature,
            json_object=json_object,
            style=generic_payload_style(env, "vision", "both"),
        )
        payload["images"] = image_data_urls
        payload["image"] = image_data_urls[0] if image_data_urls else None
        return generic_endpoint(env, "vision", base_url, api_key), generic_json_headers(api_key, env, "vision"), payload, adapter

    raise ValueError(f"unsupported vision adapter: {adapter_raw}")


def _copy_openai_image_options(payload: dict[str, Any], env: dict[str, str]) -> None:
    mapping = {
        "SCOPE_IMAGE_N": ("n", int),
        "SCOPE_IMAGE_SIZE": ("size", str),
        "SCOPE_IMAGE_QUALITY": ("quality", str),
        "SCOPE_IMAGE_OUTPUT_FORMAT": ("output_format", str),
        "SCOPE_IMAGE_OUTPUT_COMPRESSION": ("output_compression", int),
        "SCOPE_IMAGE_BACKGROUND": ("background", str),
        "SCOPE_IMAGE_MODERATION": ("moderation", str),
        "SCOPE_IMAGE_PARTIAL_IMAGES": ("partial_images", int),
    }
    for env_key, (field, cast) in mapping.items():
        raw = env.get(env_key)
        if raw is None or raw == "":
            continue
        try:
            payload[field] = cast(raw)
        except ValueError:
            payload[field] = raw


def build_image_request(
    adapter_raw: str,
    base_url: str,
    api_key: str,
    model: str,
    prompt: str,
    env: dict[str, str] | None = None,
    *,
    reference_image: Path | None = None,
    endpoint_override: str | None = None,
    response_format: str | None = None,
) -> tuple[str, dict[str, str], dict[str, Any], str]:
    env = env or {}
    adapter = normalize_adapter(adapter_raw, "openai-images")
    if adapter in {"openai-images", "openai-images-legacy"}:
        payload: dict[str, Any] = {"model": model, "prompt": prompt}
        if env.get("SCOPE_IMAGE_N"):
            try:
                payload["n"] = int(env["SCOPE_IMAGE_N"])
            except ValueError:
                payload["n"] = env["SCOPE_IMAGE_N"]
        elif adapter == "openai-images-legacy":
            payload["n"] = 1
        _copy_openai_image_options(payload, env)
        # Current GPT Image API returns b64_json by default.  Only legacy
        # OpenAI-compatible endpoints should receive a response_format field.
        legacy_response_format = (
            response_format
            or env.get("SCOPE_OPENAI_IMAGES_RESPONSE_FORMAT")
            or env.get("SCOPE_IMAGE_RESPONSE_FORMAT")
        )
        if adapter == "openai-images-legacy" and legacy_response_format:
            payload["response_format"] = legacy_response_format
        if adapter == "openai-images-legacy":
            add_legacy_reference_image(payload, reference_image, env)
        url = endpoint_override or openai_url(base_url, "images/generations")
        return url, json_headers(api_key), payload, adapter

    if adapter == "openai-responses-image":
        tool: dict[str, Any] = {"type": "image_generation"}
        action = env.get("SCOPE_IMAGE_ACTION")
        if action:
            tool["action"] = action
        for env_key, field in {
            "SCOPE_IMAGE_QUALITY": "quality",
            "SCOPE_IMAGE_SIZE": "size",
            "SCOPE_IMAGE_OUTPUT_FORMAT": "output_format",
            "SCOPE_IMAGE_BACKGROUND": "background",
            "SCOPE_IMAGE_PARTIAL_IMAGES": "partial_images",
        }.items():
            if env.get(env_key):
                tool[field] = env[env_key]
        if reference_image:
            input_value: Any = [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt},
                        {"type": "input_image", "image_url": data_url(reference_image)},
                    ],
                }
            ]
        else:
            input_value = prompt
        payload = {"model": model, "input": input_value, "tools": [tool]}
        return endpoint_override or openai_url(base_url, "responses"), json_headers(api_key), payload, adapter

    if adapter == "google-gemini-image":
        auth_mode = google_auth_mode(env, "image")
        parts: list[dict[str, Any]] = [{"text": prompt}]
        if reference_image:
            parts.append(google_inline_data(reference_image))
        payload = {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {
                "responseModalities": ["TEXT", "IMAGE"],
            },
        }
        if env.get("SCOPE_IMAGE_ASPECT_RATIO"):
            payload["generationConfig"]["aspectRatio"] = env["SCOPE_IMAGE_ASPECT_RATIO"]
        return (
            endpoint_override or google_generate_url(base_url, model, api_key, auth_mode),
            json_headers(api_key, auth_mode),
            payload,
            adapter,
        )

    if adapter == "generic-image-json":
        auth_mode = generic_auth_mode(env, "image")
        payload: dict[str, Any] = {"model": model, "prompt": prompt}
        if env.get("SCOPE_IMAGE_N"):
            try:
                payload["n"] = int(env["SCOPE_IMAGE_N"])
            except ValueError:
                payload["n"] = env["SCOPE_IMAGE_N"]
        else:
            payload["n"] = 1
        _copy_openai_image_options(payload, env)
        if response_format or env.get("SCOPE_IMAGE_RESPONSE_FORMAT"):
            payload["response_format"] = response_format or env.get("SCOPE_IMAGE_RESPONSE_FORMAT")
        if reference_image:
            ref = data_url(reference_image)
            payload["images"] = [ref]
            payload["image"] = ref
        url = endpoint_override or generic_endpoint(env, "image", base_url, api_key)
        return url, generic_json_headers(api_key, env, "image"), payload, adapter

    raise ValueError(f"unsupported image adapter: {adapter_raw}")


def build_video_request(
    adapter_raw: str,
    base_url: str,
    api_key: str,
    model: str,
    prompt: str,
    env: dict[str, str] | None = None,
    *,
    duration_seconds: int = 8,
    fps: int = 24,
    aspect_ratio: str | None = None,
    n: int = 1,
    response_format: str | None = None,
    endpoint_override: str | None = None,
) -> tuple[str, dict[str, str], dict[str, Any], str]:
    env = env or {}
    adapter = normalize_adapter(adapter_raw, "openai-videos")

    if adapter in {"openai-videos", "openai-videos-legacy"}:
        payload: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "n": int(n),
            "duration_seconds": int(duration_seconds),
            "fps": int(fps),
        }
        if aspect_ratio:
            payload["aspect_ratio"] = aspect_ratio
        if response_format or env.get("SCOPE_VIDEO_RESPONSE_FORMAT"):
            payload["response_format"] = response_format or env.get("SCOPE_VIDEO_RESPONSE_FORMAT")
        return endpoint_override or openai_url(base_url, "videos/generations"), json_headers(api_key), payload, adapter

    if adapter == "generic-video-json":
        payload: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "n": int(n),
            "duration_seconds": int(duration_seconds),
            "fps": int(fps),
        }
        if aspect_ratio:
            payload["aspect_ratio"] = aspect_ratio
        if response_format or env.get("SCOPE_VIDEO_RESPONSE_FORMAT"):
            payload["response_format"] = response_format or env.get("SCOPE_VIDEO_RESPONSE_FORMAT")
        return endpoint_override or generic_endpoint(env, "video", base_url, api_key), generic_json_headers(api_key, env, "video"), payload, adapter

    raise ValueError(f"unsupported video adapter: {adapter_raw}")


def extract_video_items(body: Any) -> list[dict[str, Any]]:
    """Return video candidates as {url, format, source} dictionaries."""
    items: list[dict[str, Any]] = []
    if not isinstance(body, dict):
        return items

    def add_candidate(value: Any, source: str) -> None:
        if not isinstance(value, str) or not value:
            return
        if value.startswith("http://") or value.startswith("https://"):
            items.append({"url": value, "source": source})

    for key in ("video_url", "url", "fileUrl", "file_url", "output_url", "result_url"):
        add_candidate(body.get(key), f"body.{key}")

    for item in body.get("data") or []:
        if not isinstance(item, dict):
            continue
        for key in ("video_url", "url", "fileUrl", "file_url", "output_url", "result_url"):
            add_candidate(item.get(key), f"data.{key}")

    for output in body.get("output") or []:
        if not isinstance(output, dict):
            continue
        for key in ("video", "result", "url", "fileUrl", "file_url"):
            value = output.get(key)
            if isinstance(value, str):
                add_candidate(value, f"output.{key}")

    for key in ("task_id",):
        value = body.get(key)
        if value is not None:
            items.append({"task_id": str(value), "source": "body.task_id"})
    return items


def extract_text(adapter_raw: str, body: Any) -> str:
    adapter = normalize_adapter(adapter_raw, "openai-chat")
    if not isinstance(body, dict):
        return ""
    if adapter == "openai-chat":
        # Some OpenAI-compatible gateways route specific upstreams through an
        # Anthropic-like response envelope even when the request shape is
        # /chat/completions.  Accept that envelope so custom model pools can be
        # used without writing a provider-specific adapter.
        content = body.get("content")
        if isinstance(content, list):
            chunks = []
            for part in content:
                if isinstance(part, dict):
                    chunks.append(str(part.get("text") or ""))
                elif isinstance(part, str):
                    chunks.append(part)
            text = "\n".join(x for x in chunks if x)
            if text:
                return text
        elif isinstance(content, str):
            return content
        if isinstance(body.get("message"), dict):
            message_content = body["message"].get("content")
            if isinstance(message_content, str):
                return message_content
        choice = (body.get("choices") or [{}])[0]
        return str((choice.get("message") or {}).get("content") or "")
    if adapter == "openai-responses":
        if body.get("output_text"):
            return str(body["output_text"])
        chunks: list[str] = []
        for output in body.get("output") or []:
            if isinstance(output, dict) and output.get("type") == "message":
                for part in output.get("content") or []:
                    if isinstance(part, dict):
                        chunks.append(str(part.get("text") or part.get("output_text") or ""))
            elif isinstance(output, dict):
                chunks.append(str(output.get("text") or ""))
        return "\n".join(x for x in chunks if x)
    if adapter == "google-gemini":
        chunks = []
        for cand in body.get("candidates") or []:
            for part in ((cand.get("content") or {}).get("parts") or []):
                if isinstance(part, dict) and part.get("text"):
                    chunks.append(str(part["text"]))
        return "\n".join(chunks)
    if adapter in {"generic-text-json", "generic-vision-json"}:
        for key in ("text", "content", "output_text", "response", "result", "message"):
            value = body.get(key)
            if isinstance(value, str):
                return value
            if isinstance(value, dict):
                nested = extract_text("generic-text-json", value)
                if nested:
                    return nested
        output = body.get("output")
        if isinstance(output, str):
            return output
        if isinstance(output, list):
            chunks = []
            for item in output:
                if isinstance(item, str):
                    chunks.append(item)
                elif isinstance(item, dict):
                    nested = extract_text("generic-text-json", item)
                    if nested:
                        chunks.append(nested)
            return "\n".join(chunks)
        choice = (body.get("choices") or [{}])[0]
        if isinstance(choice, dict):
            return str((choice.get("message") or {}).get("content") or choice.get("text") or "")
    return ""


def extract_image_items(body: Any) -> list[dict[str, Any]]:
    """Return image candidates as {b64|url, mime, source} dictionaries."""
    items: list[dict[str, Any]] = []
    if not isinstance(body, dict):
        return items

    def add_candidate(value: Any, source: str, mime: str = "image/png", force_b64: bool = False) -> None:
        if not isinstance(value, str) or not value:
            return
        if value.startswith("data:image/") and ";base64," in value:
            head, b64 = value.split(";base64,", 1)
            items.append({"b64": b64, "mime": head.removeprefix("data:") or mime, "source": source})
        elif value.startswith("http://") or value.startswith("https://"):
            items.append({"url": value, "source": source})
        elif force_b64 or (len(value) > 200 and " " not in value and "\n" not in value):
            items.append({"b64": value, "mime": mime, "source": source})

    for key in ("b64_json", "base64", "image_base64"):
        add_candidate(body.get(key), key, str(body.get("mime_type") or body.get("mimeType") or "image/png"), force_b64=True)
    for key in ("image", "result_image", "url", "image_url", "fileUrl", "file_url"):
        add_candidate(body.get(key), key, str(body.get("mime_type") or body.get("mimeType") or "image/png"))

    for item in body.get("data") or []:
        if isinstance(item, str):
            add_candidate(item, "data[]")
            continue
        if not isinstance(item, dict):
            continue
        mime = item.get("mime_type") or item.get("mimeType") or "image/png"
        for key in ("b64_json", "base64", "image_base64"):
            add_candidate(item.get(key), f"data.{key}", str(mime), force_b64=True)
        for key in ("image", "url", "image_url", "fileUrl", "file_url"):
            add_candidate(item.get(key), f"data.{key}", str(mime))

    for item in body.get("images") or []:
        if isinstance(item, str):
            add_candidate(item, "images[]")
        elif isinstance(item, dict):
            mime = item.get("mime_type") or item.get("mimeType") or "image/png"
            for key in ("b64_json", "base64", "image_base64"):
                add_candidate(item.get(key), f"images.{key}", str(mime), force_b64=True)
            for key in ("image", "url", "image_url", "fileUrl", "file_url"):
                add_candidate(item.get(key), f"images.{key}", str(mime))

    for output in body.get("output") or []:
        if not isinstance(output, dict):
            continue
        if output.get("type") == "image_generation_call" and output.get("result"):
            items.append({"b64": output["result"], "mime": output.get("mime_type") or "image/png", "source": "output.image_generation_call.result"})
        for part in output.get("content") or []:
            if isinstance(part, dict) and part.get("image_url"):
                items.append({"url": part["image_url"], "source": "output.content.image_url"})

    for cand in body.get("candidates") or []:
        for part in ((cand.get("content") or {}).get("parts") or []):
            if not isinstance(part, dict):
                continue
            inline = part.get("inlineData") or part.get("inline_data")
            if isinstance(inline, dict) and inline.get("data"):
                items.append(
                    {
                        "b64": inline["data"],
                        "mime": inline.get("mimeType") or inline.get("mime_type") or "image/png",
                        "source": "candidates.content.parts.inlineData",
                    }
                )
    return items
