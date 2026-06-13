#!/usr/bin/env python3
"""Run a stricter SCOPE-style image pipeline.

Pipeline:
  user_request
  -> decompose semantic commitments (entities/constraints/unknowns)
  -> resolve unknowns/reason about character facts when needed
  -> synthesize optimized generation prompt with prompt-engineering guide
  -> generate image with the configured image model
  -> text verifier checklist artifact (vision verifier can be plugged in)
  -> repair plan artifact

This is intentionally artifact-first: every stage is saved to disk so the chain is auditable.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import random
import re
import time
import tempfile
import unicodedata
from pathlib import Path
from typing import Any

import requests

from api_adapters import (
    build_image_request,
    build_text_request,
    extract_image_items,
    extract_text,
    generic_endpoint,
    generic_json_headers,
    google_auth_mode,
    google_generate_url,
    json_headers,
    normalize_adapter,
    openai_url as official_openai_url,
)

SKILL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PRESET_LIBRARY_FILE = SKILL_ROOT / "references" / "scope-preset-library.json"

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

LEGACY_REFERENCE_SECTIONS = {
    "prompt-presets.md": "prompt_presets_md",
    "prompt-optimizer-compact.md": "prompt_optimizer_compact_md",
    "prompt-optimizer-engineering.md": "prompt_optimizer_engineering_md",
    "external-prompt-patterns.md": "external_prompt_patterns_md",
}

DEFAULT_DECOMPOSER_SYSTEM = """
You are the Decomposer stage of the SCOPE image generation workflow.
Convert the user request into a strict JSON specification with version='scope-spec-v1'.
Return JSON only. Schema:
{
  "version":"scope-spec-v1",
  "prompt":"original request",
  "global_style":"short style summary",
  "entities":[{"id":"e1","name":"...","kind":"person|character|object|scene|text|style|other","priority":"critical|important|nice_to_have","description":"...","reference":{"type":"none|image|url|fact","value":""}}],
  "constraints":[{"id":"c1","type":"attribute|relation|layout|style|text|factual","text":"atomic requirement","depends_on":["e1"],"priority":"critical|important|nice_to_have","verification_hint":"..."}],
  "unknowns":[{"id":"u1","owner":"e1|c1|prompt","question":"...","resolution_method":"retrieval|reasoning|user|none","status":"open|resolved|deferred","answer":null,"evidence":[]}]
}
Rules:
- Preserve all user requirements as commitments.
- For cosplay/anime-to-real prompts, include commitments for real-human texture, character recognizability, premium costume material, non-cheap-cosplay quality, typography/layout if requested.
- Add safety constraints: adult 25+, no nudity, no lingerie, no see-through clothing, no explicit sexual pose, no minors.
- Split compound requirements into atomic constraints.
""".strip()

DEFAULT_RESOLVER_SYSTEM = """
You are the Resolve/Reason stage of SCOPE. Given a specification, resolve unknowns using internal reasoning only unless evidence is already present.
For named characters, fill concise visual facts useful for image generation, but mark them as style/reference facts, not guaranteed canon if uncertain.
Return the updated full JSON specification only.
""".strip()

DEFAULT_SYNTH_SYSTEM = """
You are the Synthesize stage of SCOPE and an advanced image prompt optimization engineer.
Input is a SCOPE specification. Create a production prompt for the configured image model that satisfies every critical entity and constraint.
Return JSON only:
{
  "optimized_prompt_en":"...",
  "optimized_prompt_zh":"...",
  "negative_prompt":"...",
  "aspect_ratio":"2:3",
  "commitment_map":{"c1":"phrase in prompt that addresses c1"}
}
Rules:
- Use a compact natural English production prompt, not broken JSON and not keyword spam.
- Keep optimized_prompt_en around 120-190 words and under 1200 characters for endpoint stability.
- For the final image API prompt, use clean ASCII English only; avoid literal Chinese/Japanese text, mojibake, smart quotes, and uncommon Unicode. Use romanized/English typography placeholders instead.
- For realism: photorealistic, RAW full-frame, real pores, skin texture, subsurface scattering, lifelike eyes, realistic hair, premium fabric.
- For cover/poster: typography as composition frame, elegant serif title, issue details, badge/grid layout, but exact text may be imperfect.
- Enforce adult and non-explicit safety constraints.
""".strip()

DEFAULT_VERIFY_SYSTEM = """
You are the Verifier planning stage of SCOPE. Given the specification and generated image metadata/URL, produce an itemized verification template.
If no vision input is available, mark visual judgments as 'needs_vision_check' and still list what must be checked.
Return JSON only with entities, constraints, overall, and repair_recommendations.
""".strip()

DEFAULT_PROMPT_COVERAGE_SYSTEM = """
You are the prompt-coverage verifier stage of SCOPE.
You cannot see the generated image. Instead, verify whether the synthesized prompt explicitly covers the SCOPE semantic commitments before image generation.
Return JSON only:
{
  "overall":"pass|needs_repair",
  "coverage":[{"id":"c1","verdict":"pass|missing|weak|conflicting","reason":"..."}],
  "repair_instructions":"short instructions for prompt repair"
}
Rules:
- Critical constraints must be explicit, not merely implied.
- Safety constraints must be explicit.
- If the prompt is too vague to preserve identity/style/material/layout, mark needs_repair.
""".strip()

DEFAULT_REPAIR_SYSTEM = """
You are the repair stage of SCOPE. Rewrite the image-generation prompt to fix failed or weak commitments while preserving passed requirements.
Return JSON only:
{
  "optimized_prompt_en":"repaired production prompt",
  "changes":["short list of changes"],
  "targeted_failures":["c1","c2"]
}
Rules:
- Keep the prompt concise enough for image generation, about 120-190 words and under 1200 characters.
- Use clean ASCII English only for the final image API prompt; avoid literal Chinese/Japanese text, mojibake, smart quotes, and uncommon Unicode.
- Do not remove critical safety constraints.
- Prefer targeted strengthening over adding keyword spam.
""".strip()

DEFAULT_GROK_VISION_VERIFY_TEXT = """
You are the visual verifier stage of the SCOPE image generation workflow.
You can inspect the generated image. Compare it against the SCOPE semantic commitments.
Return JSON only:
{
  "can_see_image": true,
  "overall": "pass|needs_repair|failed",
  "entities": [{"id":"e1","verdict":"pass|fail|uncertain","reason":"..."}],
  "constraints": [{"id":"c1","verdict":"pass|fail|blocked_by_entity|uncertain","reason":"..."}],
  "failed_ids": ["e1","c2"],
  "repair_instructions": "targeted prompt repair instructions",
  "risk_notes": "short notes"
}
Rules:
- Verify entities first. If a required entity is missing, mark dependent constraints blocked_by_entity.
- Be strict on critical identity, realism, composition, safety, and typography/layout commitments.
- If the image cannot be accessed or inspected, set can_see_image=false and overall=needs_repair.
- Do not invent success. Prefer uncertain/fail when evidence is weak.
""".strip()


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


def read_reference(path: Path | None, section: str | None = None) -> str:
    """Read a markdown guide or a section from the unified preset library.

    The skill now stores route presets and optimizer guides in
    references/scope-preset-library.json. Legacy markdown filenames are mapped
    back to that single file when they no longer exist.
    """
    if path and not path.exists() and path.name in LEGACY_REFERENCE_SECTIONS:
        section = section or LEGACY_REFERENCE_SECTIONS[path.name]
        path = DEFAULT_PRESET_LIBRARY_FILE
    if not path or not path.exists():
        return ""
    if path.suffix.lower() == ".json":
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception:  # noqa: BLE001
            return ""
        if section:
            guides = data.get("optimizer_guides", {})
            if isinstance(guides, dict):
                value = guides.get(section)
                if isinstance(value, str):
                    return value[:12000]
        compact = {
            "global_rules": data.get("global_rules", {}),
            "routes": data.get("routes", {}),
            "nano_banana_influence": data.get("nano_banana_influence", {}),
            "gpt_image2_influence": data.get("gpt_image2_influence", {}),
            "external_prompt_sources": data.get("external_prompt_sources", {}),
        }
        return json.dumps(compact, ensure_ascii=False, indent=2)[:12000]
    return path.read_text(encoding="utf-8-sig")[:12000]


def extract_json(text: str) -> Any:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, flags=re.S)
        if m:
            return json.loads(m.group(0))
    raise ValueError("No JSON object found in model output")


def ensure_writable_out_dir(requested: Path) -> Path:
    requested = requested.expanduser()
    candidates = [requested, (Path.cwd() / requested).resolve(), (Path("scope_runs") / requested).resolve(), (Path(tempfile.gettempdir()) / "scope_image_runs" / requested.name).resolve()]
    seen: set[str] = set()
    for candidate in candidates:
        normalized = candidate.resolve()
        if str(normalized) in seen:
            continue
        seen.add(str(normalized))
        try:
            normalized.mkdir(parents=True, exist_ok=True)
            return normalized
        except OSError:
            continue
    raise RuntimeError(f"cannot create writable output directory: {requested}")


def openai_compatible_url(base: str, path: str) -> str:
    base = base.rstrip("/")
    path = path.lstrip("/")
    if base.endswith("/v1"):
        return base + "/" + path.removeprefix("v1/")
    return base + "/v1/" + path.removeprefix("v1/")


def retry_sleep(attempt: int, base_seconds: float = 6.0, max_seconds: float = 75.0) -> None:
    """Backoff with jitter. Important for unstable Cloudflare/origin endpoints."""
    delay = min(max_seconds, base_seconds * (1.8 ** max(0, attempt - 1)))
    delay += random.uniform(0.5, 3.5)
    time.sleep(delay)


def is_transient_error(error: str | None) -> bool:
    if not error:
        return False
    return any(pattern in error for pattern in TRANSIENT_ERROR_PATTERNS)


def post_json_reliable(
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout: int,
    attempts: int,
    label: str,
    backoff_base: float = 6.0,
) -> tuple[int | str, Any, str | None]:
    """POST JSON with a fresh connection per attempt.

    Some endpoints can fail with SSL EOF, RemoteDisconnected, or transient 5xx
    while overloaded. Reusing keep-alive sockets can make this worse, so force
    Connection: close and recreate the connection.
    """
    request_headers = dict(headers)
    request_headers["Connection"] = "close"
    last_error: str | None = None
    for attempt in range(1, attempts + 1):
        try:
            with requests.Session() as session:
                r = session.post(url, headers=request_headers, json=payload, timeout=(20, timeout))
            try:
                body: Any = r.json()
            except ValueError:
                body = {"text": r.text[:1000]}
            if r.status_code == 200:
                return r.status_code, body, None
            last_error = f"HTTP {r.status_code}: {str(body)[:500]}"
            if r.status_code not in RETRYABLE_HTTP_STATUS:
                return r.status_code, body, last_error
        except Exception as exc:  # noqa: BLE001
            last_error = repr(exc)
            body = {"error": last_error}
            if not is_transient_error(last_error):
                return "error", body, last_error
        print(f"[WARN] {label} attempt={attempt}/{attempts} failed: {last_error}", flush=True)
        if attempt < attempts:
            retry_sleep(attempt, base_seconds=backoff_base)
    return "error", {"error": last_error}, last_error


def chat(env: dict[str, str], model: str, system: str, user: str, timeout: int, retries: int, temperature: float = 0.25) -> dict[str, Any]:
    base = (
        env.get("SCOPE_LLM_BASE_URL")
        or env.get("SCOPE_CHAT_BASE_URL")
        or env.get("SCOPE_LLM_ENDPOINT_URL")
        or env.get("SCOPE_CHAT_ENDPOINT_URL")
    )
    if not base:
        raise SystemExit("Missing SCOPE_LLM_BASE_URL")
    key = (
        env.get("SCOPE_LLM_API_KEY")
        or env.get("SCOPE_CHAT_API_KEY")
    )
    if not key:
        raise SystemExit("Missing SCOPE_LLM_API_KEY")
    adapter = normalize_adapter(env.get("SCOPE_LLM_FORMAT") or env.get("SCOPE_CHAT_FORMAT"), "openai-chat")
    url, headers, payload, adapter = build_text_request(
        adapter,
        base,
        key,
        model,
        system,
        user,
        env,
        temperature=temperature,
        json_object=True,
    )
    attempts = max(retries + 1, int(env.get("SCOPE_CHAT_ATTEMPTS", "4")))
    status, body, error = post_json_reliable(url, headers, payload, timeout, attempts, f"{adapter} chat {model}", backoff_base=5.0)
    if status == 200:
        content = extract_text(adapter, body)
        return {"status": status, "parsed": extract_json(content), "raw": body}
    raise RuntimeError(error or "chat failed")


def generate_image(env: dict[str, str], model: str, prompt: str, timeout: int, retries: int) -> dict[str, Any]:
    adapter = normalize_adapter(env.get("SCOPE_IMAGE_FORMAT"), "openai-images")
    base = (
        env.get("SCOPE_IMAGE_BASE_URL")
        or env.get("SCOPE_GOOGLE_BASE_URL")
        or env.get("SCOPE_IMAGE_ENDPOINT_URL")
        or ""
    ).rstrip("/")
    key = env.get("SCOPE_IMAGE_API_KEY") or env.get("SCOPE_GOOGLE_API_KEY")
    if not base:
        raise SystemExit("Missing SCOPE_IMAGE_BASE_URL")
    if not key:
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
    response_format = (
        env.get("SCOPE_OPENAI_IMAGES_RESPONSE_FORMAT")
        if adapter == "openai-images-legacy"
        else env.get("SCOPE_IMAGE_RESPONSE_FORMAT")
        if adapter == "generic-image-json"
        else None
    )
    url, headers, payload, used_adapter = build_image_request(
        adapter,
        base,
        key,
        model,
        prompt,
        env,
        endpoint_override=endpoint_override,
        response_format=response_format,
    )
    attempts = max(retries + 1, int(env.get("SCOPE_IMAGE_ATTEMPTS", "4")))
    last_error: str | None = None
    last_body: Any = None
    for attempt in range(1, attempts + 1):
        status, body, error = post_json_reliable(
            url,
            headers,
            payload,
            timeout,
            attempts=1,
            label=f"{used_adapter} image",
            backoff_base=8.0,
        )
        last_error = error
        last_body = body
        if status == 200:
            return {"status": status, "body": body, "payload_redacted": redact_image_b64(payload), "attempt": attempt, "adapter": used_adapter, "endpoint": url}
        if isinstance(status, int) and status not in RETRYABLE_HTTP_STATUS:
            break
        if attempt < attempts:
            retry_sleep(attempt, base_seconds=8.0, max_seconds=90.0)
    return {"status": "error", "error": last_error, "body": redact_image_b64(last_body), "payload_redacted": redact_image_b64(payload), "adapter": adapter, "endpoint": url}


def first_url(body: Any) -> str | None:
    for item in extract_image_items(body):
        url = item.get("url")
        if isinstance(url, str):
            return url
    return None


def first_b64(body: Any) -> str | None:
    for item in extract_image_items(body):
        b64 = item.get("b64")
        if isinstance(b64, str) and b64:
            return b64
    return None


def redact_image_b64(obj: Any) -> Any:
    """Return a JSON-serializable copy with large image base64 elided."""
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for key, value in obj.items():
            if key in {"b64_json", "result", "data"} and isinstance(value, str) and len(value) > 512:
                out[key] = f"[base64 omitted len={len(value)}]"
            else:
                out[key] = redact_image_b64(value)
        return out
    if isinstance(obj, list):
        return [redact_image_b64(item) for item in obj]
    return obj


def save_b64_image(out_dir: Path, b64: str, gen_round: int, suffix: str = "") -> Path:
    raw = base64.b64decode(b64)
    if suffix:
        image_name = f"image.{suffix}_{gen_round}.png"
    else:
        image_name = "image.png" if gen_round == 1 else f"image.attempt_{gen_round}.png"
    path = out_dir / image_name
    path.write_bytes(raw)
    return path


def write_json(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def sanitize_image_prompt(prompt: str, max_chars: int = 1200) -> str:
    """Make final image prompt safer for unstable endpoints."""
    replacements = {
        "鈥": "'",
        "檚": "'s",
        "淣": "N",
        "銆": "",
        "婇": "",
        "湏": "",
        "铏": "",
        "硅": "",
        "竟": "",
        "畣": "",
        "€": "",
    }
    for src, dst in replacements.items():
        prompt = prompt.replace(src, dst)
    prompt = unicodedata.normalize("NFKD", prompt)
    prompt = prompt.encode("ascii", "ignore").decode("ascii")
    prompt = re.sub(r"\s+", " ", prompt).strip()
    if len(prompt) <= max_chars:
        return prompt
    cut = prompt[:max_chars]
    # Prefer cutting at a sentence boundary.
    idx = max(cut.rfind(". "), cut.rfind("; "), cut.rfind(", "))
    if idx > 500:
        cut = cut[: idx + 1]
    return cut.strip()


def compact_spec_for_synthesis(spec: dict[str, Any], max_items: int = 18) -> dict[str, Any]:
    """Keep SCOPE commitments but avoid sending huge verbose JSON through unstable endpoints."""
    entities = []
    for ent in spec.get("entities", []):
        entities.append({
            "id": ent.get("id"),
            "name": ent.get("name"),
            "kind": ent.get("kind"),
            "priority": ent.get("priority"),
            "description": str(ent.get("description", ""))[:240],
        })
    constraints = []
    for con in spec.get("constraints", []):
        priority = con.get("priority")
        if priority in {"critical", "important"}:
            constraints.append({
                "id": con.get("id"),
                "type": con.get("type"),
                "text": str(con.get("text", ""))[:180],
                "depends_on": con.get("depends_on", []),
                "priority": priority,
            })
    unknowns = []
    for unk in spec.get("unknowns", []):
        if unk.get("status") == "resolved":
            unknowns.append({
                "id": unk.get("id"),
                "owner": unk.get("owner"),
                "answer": str(unk.get("answer", ""))[:220],
            })
    return {
        "version": spec.get("version", "scope-spec-v1"),
        "prompt": str(spec.get("prompt", ""))[:300],
        "global_style": str(spec.get("global_style", ""))[:300],
        "entities": entities[:max_items],
        "constraints": constraints[:max_items],
        "resolved_unknowns": unknowns[:8],
    }


def verify_prompt_coverage(env: dict[str, str], model: str, compact_spec: dict[str, Any], prompt: str, timeout: int, retries: int) -> dict[str, Any]:
    payload = {"specification": compact_spec, "prompt": prompt}
    return chat(env, model, DEFAULT_PROMPT_COVERAGE_SYSTEM, json.dumps(payload, ensure_ascii=False), timeout, retries, temperature=0.1)["parsed"]


def repair_prompt(env: dict[str, str], model: str, compact_spec: dict[str, Any], prompt: str, repair_context: Any, timeout: int, retries: int) -> dict[str, Any]:
    payload = {"specification": compact_spec, "current_prompt": prompt, "repair_context": repair_context}
    return chat(env, model, DEFAULT_REPAIR_SYSTEM, json.dumps(payload, ensure_ascii=False), timeout, retries, temperature=0.25)["parsed"]


def grok_vision_verify(
    grok_env: dict[str, str],
    model: str,
    compact_spec: dict[str, Any],
    image_url: str,
    timeout: int,
    retries: int,
) -> dict[str, Any]:
    base = (
        grok_env.get("SCOPE_VISION_BASE_URL")
        or grok_env.get("SCOPE_REASONER_BASE_URL")
        or grok_env.get("SCOPE_VISION_ENDPOINT_URL")
    )
    key = grok_env.get("SCOPE_VISION_API_KEY") or grok_env.get("SCOPE_REASONER_API_KEY")
    if not base:
        raise SystemExit("Missing SCOPE_VISION_BASE_URL")
    if not key:
        raise SystemExit("Missing SCOPE_VISION_API_KEY for vision verifier")
    user_text = DEFAULT_GROK_VISION_VERIFY_TEXT + "\n\nSCOPE compact specification:\n" + json.dumps(compact_spec, ensure_ascii=False)
    adapter = normalize_adapter(grok_env.get("SCOPE_VISION_FORMAT") or grok_env.get("SCOPE_LLM_FORMAT"), "openai-chat")
    if adapter == "openai-chat":
        url = official_openai_url(base, "chat/completions")
        headers = json_headers(key)
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_text},
                        {"type": "image_url", "image_url": {"url": image_url}},
                    ],
                }
            ],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
    elif adapter == "openai-responses":
        url = official_openai_url(base, "responses")
        headers = json_headers(key)
        payload = {
            "model": model,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": user_text},
                        {"type": "input_image", "image_url": image_url},
                    ],
                }
            ],
            "temperature": 0,
        }
    elif adapter == "google-gemini":
        if not image_url.startswith("data:") or ";base64," not in image_url:
            raise RuntimeError("google-gemini vision verifier requires a data URL or local b64 image artifact")
        mime = image_url.split(";", 1)[0].removeprefix("data:") or "image/png"
        b64 = image_url.split(";base64,", 1)[1]
        auth_mode = google_auth_mode(grok_env, "vision")
        url = google_generate_url(base, model, key, auth_mode)
        headers = json_headers(key, auth_mode)
        payload = {
            "contents": [{
                "role": "user",
                "parts": [
                    {"text": user_text},
                    {"inlineData": {"mimeType": mime, "data": b64}},
                ],
            }],
            "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
        }
    elif adapter == "generic-vision-json":
        url = generic_endpoint(grok_env, "vision", base, key)
        headers = generic_json_headers(key, grok_env, "vision")
        payload = {
            "model": model,
            "prompt": user_text,
            "images": [image_url],
            "image": image_url,
            "temperature": 0,
            "json": True,
            "response_format": {"type": "json_object"},
        }
    else:
        raise RuntimeError(f"unsupported vision adapter: {adapter}")
    attempts = max(retries + 1, int(grok_env.get("SCOPE_VISION_ATTEMPTS", "4")))
    status, body, last_error = post_json_reliable(
        url,
        headers,
        payload,
        timeout,
        attempts,
        f"{adapter} vision {model}",
        backoff_base=5.0,
    )
    if status == 200:
        content = extract_text(adapter, body)
        try:
            parsed = extract_json(content)
        except Exception:
            parsed = {
                "can_see_image": False,
                "overall": "needs_repair",
                "entities": [],
                "constraints": [],
                "failed_ids": [],
                "repair_instructions": (
                    f"Vision output could not be parsed as JSON: {str(content)[:300]}"
                    if content
                    else "Empty vision output"
                ),
                "risk_notes": "vision response format mismatch or model capability limit",
            }
        return {"status": status, "parsed": parsed, "raw": body}
    return {
        "status": "error",
        "parsed": {
            "can_see_image": False,
            "overall": "needs_repair",
            "entities": [],
            "constraints": [],
            "failed_ids": [],
            "repair_instructions": last_error or "vision verifier failed",
        },
        "error": last_error,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", required=True, type=Path)
    parser.add_argument("--llm-env-file", type=Path, help="Optional LLM env file for decomposition/synthesis/repair. Defaults to --env-file.")
    parser.add_argument("--user-prompt", required=True)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--llm-model", default="gpt-5.5")
    parser.add_argument("--image-model", default="gpt-image-2")
    parser.add_argument("--optimizer-guide", type=Path, default=DEFAULT_PRESET_LIBRARY_FILE)
    parser.add_argument("--preset-guide", type=Path, default=DEFAULT_PRESET_LIBRARY_FILE)
    parser.add_argument("--timeout", default=300, type=int)
    parser.add_argument("--retries", default=2, type=int)
    parser.add_argument("--max-prompt-repair-rounds", default=1, type=int)
    parser.add_argument("--vision-provider", choices=["none", "vision"], default="none")
    parser.add_argument("--vision-env-file", type=Path, help="Env file for the vision verifier.")
    parser.add_argument("--vision-model", default="grok-4.3")
    parser.add_argument("--max-generation-attempts", default=3, type=int)
    parser.add_argument("--visual-feedback-file", type=Path, help="Optional human/external-vision feedback file for post-generation repair.")
    parser.add_argument("--max-visual-repair-rounds", default=0, type=int)
    parser.add_argument("--download", action="store_true")
    args = parser.parse_args()

    env = load_env_file(args.env_file)
    llm_env = load_env_file(args.llm_env_file) if args.llm_env_file else env
    args.out_dir = ensure_writable_out_dir(args.out_dir)
    (args.out_dir / "user_request.txt").write_text(args.user_prompt, encoding="utf-8")

    print("[1/6] decompose", flush=True)
    decomp = chat(llm_env, args.llm_model, DEFAULT_DECOMPOSER_SYSTEM, args.user_prompt, args.timeout, args.retries)
    spec = decomp["parsed"]
    write_json(args.out_dir / "specification.raw.json", spec)

    print("[2/6] resolve unknowns / reason", flush=True)
    resolved = chat(llm_env, args.llm_model, DEFAULT_RESOLVER_SYSTEM, json.dumps(spec, ensure_ascii=False), args.timeout, args.retries)
    spec2 = resolved["parsed"]
    write_json(args.out_dir / "specification.json", spec2)

    print("[3/6] synthesize prompt with optimizer guide", flush=True)
    guide = read_reference(args.optimizer_guide, section="prompt_optimizer_compact_md")
    preset_guide = read_reference(args.preset_guide, section="prompt_presets_md")
    synth_system = DEFAULT_SYNTH_SYSTEM
    if guide:
        synth_system += "\n\nAdditional prompt engineering guide:\n" + guide
    if preset_guide:
        synth_system += "\n\nScene preset library:\n" + preset_guide
    synth_input = compact_spec_for_synthesis(spec2)
    write_json(args.out_dir / "synthesis_input.compact.json", synth_input)
    synth = chat(llm_env, args.llm_model, synth_system, json.dumps(synth_input, ensure_ascii=False), args.timeout, args.retries, temperature=0.35)
    synth_parsed = synth["parsed"]
    write_json(args.out_dir / "prompt_synthesis.json", synth_parsed)
    prompt = synth_parsed.get("optimized_prompt_en") or args.user_prompt

    print("[3b/6] prompt coverage verifier / repair gate", flush=True)
    prompt_repairs: list[dict[str, Any]] = []
    for round_idx in range(1, args.max_prompt_repair_rounds + 2):
        coverage = verify_prompt_coverage(llm_env, args.llm_model, synth_input, prompt, args.timeout, args.retries)
        write_json(args.out_dir / f"prompt_coverage_round_{round_idx}.json", coverage)
        if coverage.get("overall") == "pass" or round_idx > args.max_prompt_repair_rounds:
            break
        try:
            repaired = repair_prompt(llm_env, args.llm_model, synth_input, prompt, coverage, args.timeout, args.retries)
        except Exception as exc:  # noqa: BLE001
            repaired = {"error": str(exc), "optimized_prompt_en": prompt, "targeted_failures": []}
            write_json(args.out_dir / f"prompt_repair_round_{round_idx}.error.json", repaired)
            break
        prompt_repairs.append(repaired)
        write_json(args.out_dir / f"prompt_repair_round_{round_idx}.json", repaired)
        prompt = repaired.get("optimized_prompt_en") or prompt

    prompt = sanitize_image_prompt(prompt)
    (args.out_dir / "generation_prompt.txt").write_text(prompt, encoding="utf-8")

    print("[4/6] generate image + optional visual verifier", flush=True)
    grok_env = load_env_file(args.vision_env_file) if args.vision_provider != "none" and args.vision_env_file else {}
    image: dict[str, Any] = {}
    url: str | None = None
    image_file: str | None = None
    visual_verifications: list[dict[str, Any]] = []
    generation_repairs: list[dict[str, Any]] = []
    final_visual_overall = "not_run"

    for gen_round in range(1, max(1, args.max_generation_attempts) + 1):
        print(f"[4/{gen_round}] generate attempt {gen_round}", flush=True)
        image = generate_image(env, args.image_model, prompt, args.timeout, args.retries)
        image_for_artifact = redact_image_b64(image)
        write_json(args.out_dir / f"image_result.attempt_{gen_round}.json", image_for_artifact)
        if gen_round == 1:
            write_json(args.out_dir / "image_result.json", image_for_artifact)
        url = first_url(image.get("body"))
        b64 = first_b64(image.get("body"))
        visual_image_ref = url
        if b64:
            try:
                saved = save_b64_image(args.out_dir, b64, gen_round)
                image_file = str(saved)
                visual_image_ref = "data:image/png;base64," + b64
                print(f"[OK] saved local image {saved.name} from b64_json", flush=True)
            except Exception as exc:  # noqa: BLE001
                print("[WARN] b64 image save failed", exc, flush=True)
        if url:
            (args.out_dir / f"image_url.attempt_{gen_round}.txt").write_text(url + "\n", encoding="utf-8")
            (args.out_dir / "image_url.txt").write_text(url + "\n", encoding="utf-8")
            print("[OK] image url", url, flush=True)
            if args.download and not b64:
                try:
                    r = requests.get(url, timeout=120, headers={"User-Agent": "Mozilla/5.0 SCOPE-Image-Orchestrator/1.0"})
                    if r.status_code == 200 and r.content:
                        image_name = "image.png" if gen_round == 1 else f"image.attempt_{gen_round}.png"
                        saved = args.out_dir / image_name
                        saved.write_bytes(r.content)
                        image_file = str(saved)
                        print(f"[OK] downloaded {image_name}", flush=True)
                except Exception as exc:  # noqa: BLE001
                    print("[WARN] download failed", exc, flush=True)
        if not url and not b64:
            final_visual_overall = "image_generation_failed"
            continue

        if args.vision_provider != "none":
            print(f"[4v/{gen_round}] visual verifier", flush=True)
            vres = grok_vision_verify(grok_env, args.vision_model, synth_input, visual_image_ref or url, args.timeout, args.retries)
            visual_verifications.append(vres)
            write_json(args.out_dir / f"visual_verification.attempt_{gen_round}.json", vres)
            parsed_v = vres.get("parsed", {})
            final_visual_overall = parsed_v.get("overall", "needs_repair")
            if parsed_v.get("can_see_image") is True and final_visual_overall == "pass":
                break
            if gen_round < args.max_generation_attempts:
                repaired = repair_prompt(llm_env, args.llm_model, synth_input, prompt, parsed_v, args.timeout, args.retries)
                generation_repairs.append(repaired)
                write_json(args.out_dir / f"visual_prompt_repair.attempt_{gen_round}.json", repaired)
                prompt = sanitize_image_prompt(repaired.get("optimized_prompt_en") or prompt)
                (args.out_dir / f"generation_prompt.attempt_{gen_round + 1}.txt").write_text(prompt, encoding="utf-8")
        else:
            final_visual_overall = "not_run"
            break

    print("[5/6] verifier checklist", flush=True)
    verify_input = json.dumps(
        {"specification": spec2, "image_url": url, "image_file": image_file, "image_result": redact_image_b64(image)},
        ensure_ascii=False,
    )
    verify = chat(llm_env, args.llm_model, DEFAULT_VERIFY_SYSTEM, verify_input, args.timeout, args.retries)
    write_json(args.out_dir / "verification.json", verify["parsed"])

    visual_repairs: list[dict[str, Any]] = []
    final_url = url
    if args.visual_feedback_file and args.visual_feedback_file.exists() and args.max_visual_repair_rounds > 0:
        feedback = args.visual_feedback_file.read_text(encoding="utf-8-sig")
        for round_idx in range(1, args.max_visual_repair_rounds + 1):
            print(f"[5b/6] visual-feedback repair round {round_idx}", flush=True)
            repaired = repair_prompt(
                llm_env,
                args.llm_model,
                synth_input,
                prompt,
                {"image_url": final_url, "visual_feedback": feedback},
                args.timeout,
                args.retries,
            )
            visual_repairs.append(repaired)
            write_json(args.out_dir / f"visual_repair_round_{round_idx}.json", repaired)
            prompt = sanitize_image_prompt(repaired.get("optimized_prompt_en") or prompt)
            (args.out_dir / f"generation_prompt.visual_repair_{round_idx}.txt").write_text(prompt, encoding="utf-8")
            image = generate_image(env, args.image_model, prompt, args.timeout, args.retries)
            write_json(args.out_dir / f"image_result.visual_repair_{round_idx}.json", redact_image_b64(image))
            final_url = first_url(image.get("body")) or final_url
            b64 = first_b64(image.get("body"))
            if b64:
                try:
                    saved = save_b64_image(args.out_dir, b64, round_idx, suffix="visual_repair")
                    image_file = str(saved)
                    print(f"[OK] saved local image {saved.name} from b64_json", flush=True)
                except Exception as exc:  # noqa: BLE001
                    print("[WARN] visual repair b64 image save failed", exc, flush=True)
            if final_url:
                (args.out_dir / f"image_url.visual_repair_{round_idx}.txt").write_text(final_url + "\n", encoding="utf-8")
                if args.download and not b64:
                    try:
                        r = requests.get(final_url, timeout=120, headers={"User-Agent": "Mozilla/5.0 SCOPE-Image-Orchestrator/1.0"})
                        if r.status_code == 200 and r.content:
                            saved = args.out_dir / f"image.visual_repair_{round_idx}.png"
                            saved.write_bytes(r.content)
                            image_file = str(saved)
                    except Exception as exc:  # noqa: BLE001
                        print("[WARN] visual repair download failed", exc, flush=True)

    print("[6/6] final summary", flush=True)
    summary = {
        "pipeline": "SCOPE-style: decompose -> resolve -> synthesize -> generate -> verify checklist -> repair plan",
        "llm_model": args.llm_model,
        "image_model": args.image_model,
        "image_url": final_url,
        "image_file": image_file,
        "prompt_repair_rounds": len(prompt_repairs),
        "visual_repair_rounds": len(visual_repairs) + len(generation_repairs),
        "vision_provider": args.vision_provider,
        "vision_model": args.vision_model if args.vision_provider != "none" else None,
        "vision_verifier_available": args.vision_provider != "none",
        "vision_verifier_overall": final_visual_overall,
        "vision_verifier_note": "Use --vision-provider vision with a compatible vision model for post-generation visual verification.",
        "artifacts": [p.name for p in sorted(args.out_dir.iterdir())],
    }
    write_json(args.out_dir / "final_summary.json", summary)
    print("[OK] wrote", args.out_dir, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
