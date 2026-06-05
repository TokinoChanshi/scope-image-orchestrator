#!/usr/bin/env python3
"""Single-request v2 router for SCOPE image generation.

Flow:
  user request -> deterministic/LLM route -> v2 optimized prompt -> image model
  -> optional vision audit -> targeted repair/retry -> final artifacts.

The runtime is provider-neutral but the wire format is explicit.  Supported
adapters include OpenAI Chat Completions, OpenAI Responses, OpenAI Images API,
and Google Gemini generateContent. It does not print API keys.
"""
from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import pathlib
import random
import re
import shutil
import time
import unicodedata
from typing import Any
from requests.adapters import HTTPAdapter

import requests
from urllib3.util.retry import Retry

from api_adapters import (
    build_image_request,
    build_text_request,
    build_vision_request,
    extract_image_items,
    extract_text,
    normalize_adapter,
)

SCRIPT_ROOT = pathlib.Path(__file__).resolve().parent
DEFAULT_PRESET_FILE = SCRIPT_ROOT.parent / "references" / "scope-preset-library.json"

PEOPLE_NEG = "Negative: no nudity, no lingerie, no transparent clothing, no sexual poses, no minors, no watermark."
TEXT_NEG = "Negative: no random paragraphs, no repeated letters, no watermark, no plastic skin."
RETRYABLE_HTTP_STATUS = {408, 409, 425, 429, 500, 502, 503, 504, 520, 521, 522, 523, 524, 530}
TRANSIENT_ERROR_PATTERNS = (
    "RemoteDisconnected",
    "SSLEOFError",
    "EOF occurred in violation of protocol",
    "Connection aborted",
    "Read timed out",
    "ConnectTimeout",
    "Connection reset",
    "origin_bad_gateway",
    "NO_AVAILABLE_UPSTREAM",
    "server returned",
)

VISION_UNSTABLE_MARK = "vision_unstable"

DEFAULT_PRESET_LIBRARY = {
    "schema_version": "scope-inline-preset-v1",
    "global_rules": {
        "negative_anchor": PEOPLE_NEG,
    "text_principles": [
            "Prefer concrete camera/light/material terms before style adjectives.",
            "Keep negative boundaries concise and direct.",
            "Use one distinct scene noun cluster per variant.",
        ],
    },
    "routes": {
        "portrait": {
            "route_hint": "editorial lifestyle portrait, no typography, distinct real face, concrete setting, real skin/hair/fabric details",
            "route_keywords": [
                "美女写真",
                "美女",
                "生活写真",
                "日系写真",
                "女性写真",
                "lifestyle portrait",
                "editorial portrait",
                "portrait",
                "girlfriend photo",
            ],
            "fallback_prompt": "Photorealistic 2:3 vertical editorial lifestyle portrait, adult subject, based on: {subject}. {camera_phrase}. Natural asymmetry, soft under-eye detail, subtle skin tone variation, realistic pores, tiny flyaway hairs, natural neck and shoulder anatomy. Real fabric texture, relaxed unforced pose, practical scene details, no text overlays unless requested.",
            "camera_phrase": "85mm portrait lens, practical indoor/window light, mild natural roll-off",
            "aspect_ratio": "2:3",
            "negative": "Negative: no typography, no plastic skin, no beauty-filter face, no random repeated text, no watermark.",
            "booster_lines": [
                "distinct face geometry and hair profile per variant",
                "small body asymmetry and imperfect hand placement",
            ],
        },
        "magazine": {
            "route_hint": "high-fashion magazine cover, short masthead, 2-3 cover lines, one badge, clean grid, crisp typography",
            "route_keywords": [
                "杂志封面",
                "fashion cover",
                "editorial cover",
                "magazine cover",
                "luxe",
                "high-end cover",
                "Vogue-like",
                "fashion cover",
            ],
            "fallback_prompt": "Photorealistic 2:3 high-fashion magazine cover, adult model, based on: {subject}. Clean editorial grid with masthead, short cover lines, one badge, one issue number. {light_phrase}. Layout and typography first, then subject/scene detail.",
            "camera_phrase": "85mm portrait look, practical studio/window blend, controlled contrast",
            "light_phrase": "cool ambient plus warm key, print-quality edge control",
            "aspect_ratio": "2:3",
            "negative": "Negative: no random paragraphs, no repeated letters, no unreadable text, no random gibberish blocks, no watermark.",
        },
        "poster": {
            "route_hint": "cinematic movie poster, hero silhouette, title zone, tagline/credits, layered foreground-midground-background",
            "route_keywords": [
                "电影海报",
                "poster",
                "movie poster",
                "cinematic poster",
                "cyberpunk poster",
                "key art",
                "one-sheet",
            ],
            "fallback_prompt": "Cinematic 2:3 movie poster key art based on: {subject}. Hero silhouette first, one core prop in midground, readable title zone, short tagline, compact credits block, layered composition. Realistic atmosphere and practical light logic.",
            "camera_phrase": "cinematic composition, layered foreground-midground-background",
            "aspect_ratio": "2:3",
            "negative": "Negative: no repeated title, no fake logos unless requested, no unreadable clutter, no watermark.",
        },
        "cosplay": {
            "route_hint": "live-action character/cosplay poster, real human texture with natural skin imperfections, iconic anchors, premium costume materials, practical lighting, not anime render",
            "route_keywords": [
                "真人cos",
                "cosplay",
                "角色",
                "character poster",
                "anime to real",
                "二次元转真人",
                "游戏角色",
                "live-action character",
            ],
            "fallback_prompt": "Photorealistic 2:3 live-action character/cosplay poster, adult-inspired, preserve iconic anchors from: {subject}. Real fabrics and materials, visible seams, embroidery, leather and metal tension, practical mixed lighting, realistic hair and skin micro-detail, natural hand asymmetry.",
            "camera_phrase": "practical mixed real-world lighting, visible body sway and subtle pose imperfection",
            "aspect_ratio": "2:3",
            "negative": "Negative: no anime render, no CGI skin, no cheap cosplay, no random text, no sexual poses, no watermark.",
            "booster_lines": [
                "keep one clear character anchor: hairstyle, palette, accessory",
                "use character materials instead of literal costume plastics",
            ],
        },
        "interior": {
            "route_hint": "architectural interior visualization, room layout, camera position, real scale, material texture, straight verticals",
            "route_keywords": [
                "室内",
                "室内效果图",
                "interior",
                "室内设计",
                "客厅",
                "卧室",
                "厨房",
                "architecture",
                "interior render",
            ],
            "fallback_prompt": "Photorealistic architectural interior visualization, {subject}. Eye-height layout from practical camera position, 24mm/28mm interior lens, clear circulation, straight verticals, realistic furniture scale. Material realism includes wood grain, fabric weave, stone veining, metal reflections. Light: {light_phrase}.",
            "camera_phrase": "human eye-height 24mm/28mm interior lens",
            "light_phrase": "natural or warm artificial practical lighting with gentle bounce",
            "aspect_ratio": "16:9",
            "negative": "Negative: no warped furniture, no impossible perspective, no melted objects, no extra doors/windows, no people unless requested, no watermark.",
        },
        "product": {
            "route_hint": "commercial product still life, one hero object, material behavior, controlled reflections, minimal props",
            "route_keywords": [
                "产品图",
                "产品",
                "product photo",
                "commercial still",
                "product",
                "香水",
                "手表",
                "耳机",
                "饮料",
                "食品",
                "food",
            ],
            "fallback_prompt": "Photorealistic commercial product still life, hero product: {subject}. Clean commercial background, controlled reflections, realistic shadow, premium material detail and geometric composition.",
            "camera_phrase": "single-product focus, eye-level controlled angle",
            "aspect_ratio": "4:5",
            "negative": "Negative: no duplicate hero object, no warped logo/label, no random label text, no clutter, no watermark.",
        },
        "bathroom": {
            "route_hint": "real smartphone bathroom mirror selfie, private lifestyle photo, phone visible, compact hotel/apartment bathroom",
            "route_keywords": [
                "浴室自拍",
                "镜前自拍",
                "镜子自拍",
                "bathroom selfie",
                "白衬衫写真",
                "酒店浴室写真",
                "生活感性感自拍",
                "私房写真",
                "恋人视角自拍",
                "眼镜自拍",
                "轻私房写真",
                "酒店浴室",
                "private room selfie",
                "mirror selfie",
                "white shirt selfie",
                "白衬衫",
            ],
            "fallback_prompt": "Photorealistic 9:16 real smartphone mirror selfie, adult woman in a compact hotel or apartment bathroom, based on: {subject}. Handheld smartphone perspective with slight edge distortion, imperfect mirror crop, mirror reflections and real indoor light. Shirt, towel, sink, chrome faucet, glass shower edge, skincare bottles, tiled details.",
            "camera_phrase": "26mm equivalent smartphone lens behavior, slight handheld asymmetry",
            "style_blocks": [
                "boutique hotel or compact apartment bathroom",
                "warm vanity bulb practical light, soft natural ambient light",
                "natural everyday intimacy, quiet girlfriend POV",
            ],
            "aspect_ratio": "9:16",
            "negative": "Negative: no wet shirt, no transparent shirt, no influencer pose, no commercial cover look, no watermark, no minors, no sexual poses.",
            "booster_lines": [
                "less stock photo, more private smartphone realism",
                "small mirror edge and phone crop asymmetry",
                "tiny fabric wrinkles, shoulder shift, realistic skin texture",
            ],
        },
    },
}

ROUTE_KEYS: tuple[str, ...] = tuple(DEFAULT_PRESET_LIBRARY["routes"].keys())
ROUTE_HINTS = {route: cfg["route_hint"] for route, cfg in DEFAULT_PRESET_LIBRARY["routes"].items()}


def route_keys_from_presets(presets: dict[str, Any] | None = None) -> tuple[str, ...]:
    routes = presets.get("routes", {}) if presets else DEFAULT_PRESET_LIBRARY["routes"]
    if isinstance(routes, dict) and routes:
        return tuple(routes.keys())
    return ROUTE_KEYS

ROUTER_SYSTEM = """
You are the v2 SCOPE prompt router and optimizer. Convert the user's request into a compact English production prompt.
Return JSON only:
{
  "route":"route key from configured preset routes",
  "optimized_prompt_en":"...",
  "negative_prompt":"...",
  "aspect_ratio":"...",
  "reason":"short"
}
Rules:
- Keep optimized_prompt_en under 900 characters for unstable endpoints.
- Use natural English, not broken JSON, not keyword spam.
- Put hard boundaries in the negative_prompt.
- For people, use adult presentation and realistic skin/hair/fabric details; avoid same-face by specifying face/hair/setting anchors.
- For magazine/poster, keep text short and hierarchical.
- For interior/product, avoid portrait language and focus on scale/material/light.
""".strip()

VISION_AUDIT_SYSTEM = """
You are the visual verifier for a SCOPE image generation run. Inspect the image against the user's request and expected route.
Return JSON only:
{
  "can_see_image": true,
  "overall":"pass|needs_repair|failed",
  "scores":{"route_fit":0-10,"realism":0-10,"composition":0-10,"text_quality":0-10},
  "failures":["short concrete issue"],
  "repair_prompt":"concise English repair instruction, empty if pass"
}
Rules:
- Pass only when the image clearly follows the route and user intent.
- For magazine/poster, check text hierarchy, repeated/gibberish text, and layout.
- For people/cosplay, check face, hands/anatomy, hair, fabric, identity anchors, and overall realism.
- For interior/product, check geometry, scale, duplicated objects, warped objects, and material realism.
""".strip()

REFERENCE_ANALYSIS_SYSTEM = """
You analyze a reference image for a SCOPE image generation run.
Return JSON only:
{
  "reference_brief":"compact English visual brief usable by an image-generation prompt",
  "preserve":["specific visual attribute to preserve"],
  "adapt":["how to adapt it to the user's request"],
  "avoid":["what should not be copied or overfit"]
}
Rules:
- Describe only visible visual properties: composition, camera, lighting, materials, pose, palette, subject identity anchors, room/product geometry, typography/layout.
- Do not infer private identity or sensitive attributes.
- Keep the reference_brief under 420 characters.
- If the user asks for style/composition/product reference, focus on that; if identity reference is requested, preserve non-sensitive visual anchors only.
""".strip()

REPAIR_SYSTEM = """
You repair an image generation prompt after visual QA. Return JSON only:
{"optimized_prompt_en":"...", "changes":["..."]}
Rules:
- Preserve the original user intent and route.
- Apply the visual repair instructions directly.
- Keep the prompt under 900 characters.
- Use concise English and do not remove hard negative constraints.
""".strip()


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "").strip() or str(default))
    except Exception:
        return default


def _env_str(name: str, default: str) -> str:
    return os.getenv(name, "").strip() or default


def _env_bool(name: str, default: bool) -> bool:
    v = os.getenv(name, "").strip().lower()
    if not v:
        return default
    if v in {"1", "true", "yes", "on", "y"}:
        return True
    if v in {"0", "false", "off", "no", "n"}:
        return False
    return default


def is_transient_error(error: str | None) -> bool:
    if not error:
        return False
    return any(pattern in error for pattern in TRANSIENT_ERROR_PATTERNS)


def _merge_dict(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_dict(merged[key], value)
        elif value is not None:
            merged[key] = value
    return merged


def _as_str_list(items: Any) -> list[str]:
    out: list[str] = []
    if isinstance(items, list):
        for item in items:
            if isinstance(item, str):
                stripped = item.strip()
                if stripped:
                    out.append(stripped)
    return out


def load_prompt_presets(path: pathlib.Path | None) -> dict[str, Any]:
    presets: dict[str, Any] = json.loads(json.dumps(DEFAULT_PRESET_LIBRARY))
    if not path:
        return presets
    if not path.exists():
        print(f"[WARN] preset file missing, fallback to inline preset: {path}", flush=True)
        return presets
    try:
        raw = path.read_text(encoding="utf-8-sig", errors="ignore")
        loaded = json.loads(raw)
        if isinstance(loaded, dict):
            runtime_presets = loaded.get("runtime_presets")
            if isinstance(runtime_presets, dict):
                presets = _merge_dict(presets, runtime_presets)
            presets = _merge_dict(presets, loaded)
    except Exception as exc:  # noqa: BLE001
        print(f"[WARN] preset file load failed ({path}): {repr(exc)}", flush=True)
    return presets


def _route_preset(route: str, presets: dict[str, Any] | None = None) -> dict[str, Any]:
    if not presets:
        return DEFAULT_PRESET_LIBRARY["routes"].get(route, {})
    cfg = presets.get("routes", {}).get(route)
    return cfg if isinstance(cfg, dict) else {}


def route_hint_text(route: str, presets: dict[str, Any] | None = None) -> str:
    cfg = _route_preset(route, presets)
    return str(cfg.get("route_hint") or ROUTE_HINTS.get(route, route))


def preset_brief_for_llm(route: str, presets: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return a compact route preset brief for prompt optimization.

    Keep this small: it is injected into the chat optimizer request so external
    prompt-library distillations in `scope-preset-library.json` actually affect
    the LLM stage instead of only the local fallback stage.
    """
    cfg = _route_preset(route, presets)
    if not cfg:
        return {}
    out: dict[str, Any] = {}
    for key in ("camera_phrase", "light_phrase", "aspect_ratio", "negative"):
        value = cfg.get(key)
        if isinstance(value, str) and value.strip():
            out[key] = sanitize_prompt(value, 240)
    for key in ("style_blocks", "booster_lines", "external_patterns", "composition_patterns", "quality_controls"):
        values = _as_str_list(cfg.get(key))
        if values:
            out[key] = [sanitize_prompt(v, 180) for v in values[:8]]
    return out


def _global_rules(presets: dict[str, Any] | None = None) -> dict[str, Any]:
    source = presets.get("global_rules", {}) if presets else {}
    return dict(source) if isinstance(source, dict) else {}


def route_negative_anchor(route: str, presets: dict[str, Any] | None = None) -> str:
    cfg = _route_preset(route, presets)
    negative = str(cfg.get("negative", "").strip())
    if negative:
        return negative
    return str(_global_rules(presets).get("negative_anchor", PEOPLE_NEG))


def render_preset_fallback(route: str, subject: str, max_chars: int, presets: dict[str, Any] | None = None) -> dict[str, str]:
    cfg = _route_preset(route, presets)
    fallback = cfg.get("fallback_prompt")
    if not isinstance(fallback, str) or not fallback.strip():
        return {}

    context = {
        "subject": subject,
        "camera_phrase": str(cfg.get("camera_phrase", "")).strip(),
        "light_phrase": str(cfg.get("light_phrase", "")).strip(),
        "style_blocks": ", ".join(_as_str_list(cfg.get("style_blocks"))),
    }
    prompt = fallback
    for key, value in context.items():
        prompt = prompt.replace(f"{{{key}}}", value)
    prompt = re.sub(r"{[^{}]+}", "", prompt)
    prompt = prompt.replace("  ", " ").replace(" ,", ",").strip()
    if cfg.get("booster_lines"):
        boosters = ", ".join(_as_str_list(cfg.get("booster_lines")))
        if boosters:
            prompt = f"{prompt} {boosters}"
    return {
        "optimized_prompt_en": sanitize_prompt(prompt, max_chars),
        "negative_prompt": sanitize_prompt(route_negative_anchor(route, presets), max_chars=240),
        "aspect_ratio": str(cfg.get("aspect_ratio", "2:3")),
    }


def build_subject_hint(user_prompt: str) -> str:
    trimmed = sanitize_prompt(user_prompt, 240)
    return trimmed.strip().strip(",;。；，").strip()


def post_json_with_retries(
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout: int,
    attempts: int,
    label: str,
    backoff_base: float = 8.0,
    verify: bool = True,
) -> tuple[int | str, Any, str | None]:
    """POST JSON with per-attempt new connection and bounded retries.

    Image and chat endpoints can be observed to be unstable (connection close, SSL EOF,
    transient 5xx). For better success rate we force Connection: close each attempt
    and apply jittered backoff between attempts.
    """
    last_error: str | None = None
    request_headers = dict(headers)
    request_headers["Connection"] = "close"
    for attempt in range(1, attempts + 1):
        try:
            with build_retry_session() as session:
                response = session.post(url, headers=request_headers, json=payload, timeout=(20, timeout), verify=verify)
            try:
                body: Any = response.json()
            except ValueError:
                body = {"text": response.text[:1000]}
            if response.status_code == 200:
                return response.status_code, body, None
            last_error = f"HTTP {response.status_code}: {str(body)[:500]}"
            if response.status_code not in RETRYABLE_HTTP_STATUS:
                return response.status_code, body, last_error
        except Exception as exc:  # noqa: BLE001
            last_error = repr(exc)
            body = {"error": last_error}
            if not is_transient_error(last_error):
                return "error", body, last_error
        print(f"[WARN] {label} attempt {attempt}/{attempts} failed: {last_error}", flush=True)
        if attempt < attempts:
            time.sleep(min(90, backoff_base * (1.7 ** (attempt - 1))) + random.uniform(0.8, 3.0))
    return "error", {"error": last_error}, last_error


def load_env_file(path: pathlib.Path | None) -> dict[str, str]:
    if not path:
        return {}
    env: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8-sig", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def openai_url(base: str, path: str) -> str:
    base = base.rstrip("/")
    path = path.lstrip("/")
    if base.endswith("/v1"):
        return base + "/" + path.removeprefix("v1/")
    return base + "/v1/" + path.removeprefix("v1/")


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
    raise ValueError("No JSON object found")


def sanitize_prompt(prompt: str, max_chars: int) -> str:
    prompt = unicodedata.normalize("NFKD", prompt)
    prompt = prompt.encode("ascii", "ignore").decode("ascii")
    prompt = re.sub(r"\s+", " ", prompt).strip()
    if len(prompt) <= max_chars:
        return prompt
    cut = prompt[:max_chars]
    idx = max(cut.rfind(". "), cut.rfind("; "), cut.rfind(", "))
    return cut[: idx + 1].strip() if idx > 350 else cut.strip()


def build_retry_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=4,
        connect=4,
        read=4,
        status=2,
        status_forcelist=RETRYABLE_HTTP_STATUS,
        allowed_methods=frozenset({"GET", "POST"}),
        backoff_factor=0.75,
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_maxsize=4)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def parse_image_models(raw: str) -> list[str]:
    models = []
    for m in raw.replace(";", ",").replace(" ", ",").split(","):
        model = m.strip()
        if model:
            models.append(model)
    deduped = list(dict.fromkeys(models))
    if deduped:
        return deduped
    return models if models else ["gpt-image-2"]


def infer_route(user_prompt: str, forced: str = "auto", presets: dict[str, Any] | None = None) -> str:
    route_keys = route_keys_from_presets(presets)
    if forced != "auto":
        forced_key = forced.lower().strip()
        return forced_key if forced_key in route_keys else "portrait"

    raw = user_prompt
    prompt = user_prompt.lower()
    route_candidates = []
    for route in route_keys:
        cfg = _route_preset(route, presets)
        keywords = _as_str_list(cfg.get("route_keywords"))
        if not keywords:
            continue
        weighted = []
        for trig in keywords:
            trig_clean = trig.strip()
            if not trig_clean:
                continue
            weighted.append(trig_clean)
            weighted.append(trig_clean.lower())
        route_candidates.append((route, weighted))

    for route, keyword_list in route_candidates:
        if any((keyword in raw) or (keyword.lower() in prompt) for keyword in keyword_list):
            return route
    return "portrait"


def local_prompt_hint(user_prompt: str, route: str, presets: dict[str, Any] | None = None) -> str:
    """Small offline CN/EN hint extractor for dry-run or no-LLM mode.

    The final image prompt is ASCII English for endpoint stability. Without this
    mapper, Chinese-only requests would be stripped by sanitize_prompt().
    """
    cfg = _route_preset(route, presets)
    keyword_map = {
        "白衬衫": "white light-balance shirt with visible texture",
        "白衬衫写真": "white-shirt mirror selfie",
        "镜前自拍": "smartphone mirror selfie",
        "镜子自拍": "smartphone mirror selfie",
        "短发": "short hair",
        "丸子头": "messy bun or ponytail",
        "一边卷发": "loose ponytail",
        "眼镜": "thin-frame glasses",
        "酒店浴室": "boutique hotel bathroom",
        "客厅": "living room scene",
        "卧室": "bedroom scene",
        "厨房": "kitchen scene",
        "室内": "interior scene",
        "产品": "commercial subject",
        "产品图": "commercial product shot",
        "香水": "luxury perfume bottle",
        "手表": "watch macro",
        "耳机": "headphone still life",
        "杂志封面": "high-fashion magazine cover",
        "封面": "cover layout scene",
        "电影海报": "cinematic key art poster",
        "海报": "poster key art",
        "真人cos": "live-action character adaptation",
        "角色": "character-driven portrayal",
        "胡桃": "character anchor profile",
        "美女写真": "editorial lifestyle portrait",
        "写真": "lifestyle portrait",
        "美女": "adult portrait subject",
        "爱情": "intimate lifestyle mood",
    }

    prompt_lower = user_prompt.lower()
    subject = build_subject_hint(user_prompt)
    hints: list[str] = []
    if subject:
        hints.append(subject)

    for zh, en in keyword_map.items():
        if zh in user_prompt or zh.lower() in prompt_lower:
            if en:
                hints.append(en)

    if not hints:
        return f"the user's requested {route} scene"
    deduped = list(dict.fromkeys(hints))
    return ", ".join(deduped)


def looks_like_production_prompt(user_prompt: str) -> bool:
    stripped = user_prompt.strip()
    if len(stripped) < 40:
        return False
    ascii_ratio = sum(1 for ch in stripped if ord(ch) < 128) / max(1, len(stripped))
    if ascii_ratio < 0.82:
        return False
    lowered = stripped.lower()
    return any(
        marker in lowered
        for marker in (
            "photorealistic",
            "cinematic",
            "editorial",
            "magazine cover",
            "movie poster",
            "commercial",
            "architectural",
            "mirror selfie",
            "live-action",
        )
    )


def fallback_prompt(user_prompt: str, route: str, max_chars: int, presets: dict[str, Any] | None = None) -> dict[str, str]:
    cfg = _route_preset(route, presets)
    if looks_like_production_prompt(user_prompt):
        boosters = ", ".join(_as_str_list(cfg.get("booster_lines"))[:4])
        prompt = user_prompt.strip()
        if boosters:
            prompt = f"{prompt} {boosters}."
        return {
            "route": route,
            "optimized_prompt_en": sanitize_prompt(prompt, max_chars),
            "negative_prompt": route_negative_anchor(route, presets),
            "aspect_ratio": str(cfg.get("aspect_ratio", "2:3")),
            "reason": "production prompt fallback",
        }
    subject_hint = local_prompt_hint(user_prompt, route, presets)
    fallback = render_preset_fallback(route, subject_hint, max_chars, presets)
    if fallback:
        fallback["route"] = route
        fallback.setdefault("reason", "preset fallback")
        return fallback

    subject = build_subject_hint(user_prompt)
    prompt = f"Photorealistic {route} scene based on: {subject}. {route_hint_text(route, presets)}"
    return {
        "route": route,
        "optimized_prompt_en": sanitize_prompt(prompt, max_chars),
        "negative_prompt": route_negative_anchor(route, presets),
        "aspect_ratio": "2:3",
        "reason": "preset fallback",
    }


def mandatory_negative_for_route(route: str, presets: dict[str, Any] | None = None) -> str:
    return route_negative_anchor(route, presets)


def merge_negative(route: str, model_negative: str | None, presets: dict[str, Any] | None = None) -> str:
    """Always preserve hard route boundaries even when the LLM returns weak negatives."""
    mandatory = mandatory_negative_for_route(route, presets)
    if not model_negative:
        return mandatory
    merged = mandatory + " " + model_negative
    # Deduplicate rough clauses while preserving order.
    parts = [p.strip() for p in re.split(r"[.;]", merged) if p.strip()]
    seen: set[str] = set()
    out: list[str] = []
    for part in parts:
        normalized = part.removeprefix("Negative:").strip()
        key = normalized.lower()
        if any(key.startswith(old) or old.startswith(key) for old in seen):
            continue
        if key not in seen:
            seen.add(key)
            out.append(normalized)
    return "Negative: " + "; ".join(out) + "."


def assemble_generation_prompt(prompt: str, negative: str, max_chars: int) -> str:
    """Compact the positive prompt while preserving hard negative constraints."""
    negative_clean = sanitize_prompt(negative or "", 240)
    if not negative_clean:
        return sanitize_prompt(prompt, max_chars)
    reserve = min(max(160, len(negative_clean) + 1), max(180, max_chars // 3))
    positive_budget = max(240, max_chars - reserve)
    positive_clean = sanitize_prompt(prompt, positive_budget)
    combined = (positive_clean + " " + negative_clean).strip()
    if len(combined) <= max_chars:
        return combined
    # Last-resort compaction: keep the negative intact and trim the positive.
    positive_budget = max(120, max_chars - len(negative_clean) - 1)
    return (sanitize_prompt(prompt, positive_budget) + " " + negative_clean).strip()


def chat_json(env: dict[str, str], model: str, system: str, user: str, timeout: int, attempts: int | None = None) -> dict[str, Any]:
    if attempts is None:
        attempts = _env_int("SCOPE_CHAT_ATTEMPTS", 4)
    base = (
        env.get("SCOPE_LLM_BASE_URL")
        or env.get("SCOPE_CHAT_BASE_URL")
        or env.get("SCOPE_LLM_ENDPOINT_URL")
        or env.get("SCOPE_CHAT_ENDPOINT_URL")
    )
    key = (
        env.get("SCOPE_LLM_API_KEY")
        or env.get("SCOPE_CHAT_API_KEY")
    )
    if not base or not key:
        raise RuntimeError("missing LLM/chat base/key")
    adapter = normalize_adapter(env.get("SCOPE_LLM_FORMAT") or env.get("SCOPE_CHAT_FORMAT"), "openai-chat")
    url, headers, payload, adapter = build_text_request(
        adapter,
        base,
        key,
        model,
        system,
        user,
        env,
        temperature=0.25,
        json_object=True,
    )
    status, body, last = post_json_with_retries(url, headers, payload, timeout, attempts, f"{adapter} chat {model}", backoff_base=7.0)
    if status == 200:
        content = extract_text(adapter, body) or "{}"
        return extract_json(content)
    raise RuntimeError(last or "chat failed")


def optimize_prompt(
    user_prompt: str,
    route: str,
    llm_env: dict[str, str],
    llm_model: str,
    max_chars: int,
    timeout: int,
    presets: dict[str, Any] | None = None,
) -> dict[str, str]:
    fallback = fallback_prompt(user_prompt, route, max_chars, presets)
    if not llm_env:
        return fallback

    user = json.dumps(
        {
            "user_request": user_prompt,
            "initial_route": route,
            "route_hint": route_hint_text(route, presets),
            "route_preset_brief": preset_brief_for_llm(route, presets),
            "route_keys": route_keys_from_presets(presets),
        },
        ensure_ascii=False,
    )
    try:
        result = chat_json(llm_env, llm_model, ROUTER_SYSTEM, user, timeout)
        valid_routes = set(route_keys_from_presets(presets))
        out_route = result.get("route") if result.get("route") in valid_routes else route
        routed_fallback = fallback_prompt(user_prompt, out_route, max_chars, presets)
        prompt = result.get("optimized_prompt_en") or fallback["optimized_prompt_en"]
        result["route"] = out_route
        result["optimized_prompt_en"] = sanitize_prompt(prompt, max_chars)
        negative = result.get("negative_prompt")
        if not isinstance(negative, str) or not negative.strip():
            negative = routed_fallback["negative_prompt"]
        aspect = result.get("aspect_ratio")
        if not isinstance(aspect, str) or not aspect.strip():
            aspect = routed_fallback["aspect_ratio"]
        result["negative_prompt"] = negative
        result["aspect_ratio"] = aspect
        return result
    except Exception as exc:  # noqa: BLE001
        fallback["llm_error"] = repr(exc)
        return fallback


def image_to_data_url(path: pathlib.Path) -> str:
    mime = mimetypes.guess_type(str(path))[0] or "image/png"
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def download_image(url: str, out_path: pathlib.Path) -> bool:
    last_error = None
    for attempt in range(1, 4):
        try:
            with build_retry_session() as session:
                r = session.get(
                    url,
                    headers={"User-Agent": "Mozilla/5.0", "Connection": "close"},
                    timeout=(20, 120),
                )
                if r.status_code == 200 and r.content:
                    out_path.write_bytes(r.content)
                    return True
                print(f"[WARN] media download {attempt}/3 HTTP {r.status_code}: {r.text[:120]}", flush=True)
                last_error = f"HTTP {r.status_code}: {r.text[:180]}"
        except Exception as exc:  # noqa: BLE001
            last_error = repr(exc)
            print(f"[WARN] media download {attempt}/3 failed: {last_error}", flush=True)
        time.sleep(5 * attempt + random.uniform(0.5, 2.5))
    if last_error:
        print(f"[WARN] media download exhausted, last error: {last_error}", flush=True)
    return False


def image_suffix_from_mime(mime: str | None) -> str:
    value = (mime or "image/png").lower()
    if "jpeg" in value or "jpg" in value:
        return ".jpg"
    if "webp" in value:
        return ".webp"
    if "gif" in value:
        return ".gif"
    return ".png"


def generate_image(
    env: dict[str, str],
    model: str,
    prompt: str,
    out_dir: pathlib.Path,
    attempt: int,
    response_formats: list[str],
    timeout: int,
    image_retries: int,
    reference_image: pathlib.Path | None = None,
) -> dict[str, Any]:
    adapter = normalize_adapter(env.get("SCOPE_IMAGE_FORMAT"), "openai-images")
    base = (
        env.get("SCOPE_IMAGE_BASE_URL")
        or env.get("SCOPE_OPENAI_IMAGE_BASE_URL")
        or env.get("SCOPE_GOOGLE_BASE_URL")
        or ""
    ).rstrip("/")
    key = env.get("SCOPE_IMAGE_API_KEY") or env.get("SCOPE_OPENAI_IMAGE_API_KEY") or env.get("SCOPE_GOOGLE_API_KEY")
    if not key:
        raise SystemExit("Missing SCOPE_IMAGE_API_KEY")
    if not base and not any(
        env.get(k)
        for k in (
            "SCOPE_IMAGE_ENDPOINT_URL",
            "SCOPE_IMAGE_GENERATIONS_URL",
            "SCOPE_IMAGE_RESPONSES_URL",
            "SCOPE_GOOGLE_GENERATE_CONTENT_URL",
        )
    ):
        raise SystemExit("Missing SCOPE_IMAGE_BASE_URL or adapter-specific endpoint URL")

    endpoint_overrides: list[str | None] = [None]
    if adapter in {"openai-images", "openai-images-legacy"}:
        urls = [
            u.strip()
            for u in [
                env.get("SCOPE_IMAGE_GENERATIONS_URL"),
                env.get("SCOPE_IMAGES_GENERATIONS_URL"),
            ]
            if u
        ]
        alt_urls = env.get("SCOPE_IMAGE_GENERATIONS_ALT_URL") or env.get("SCOPE_IMAGES_ENDPOINTS")
        if alt_urls:
            urls.extend([u.strip() for u in alt_urls.replace(";", ",").split(",") if u.strip()])
        if urls:
            endpoint_overrides = list(dict.fromkeys(urls))
    elif adapter == "openai-responses-image":
        endpoint_overrides = [env.get("SCOPE_IMAGE_RESPONSES_URL") or None]
    elif adapter == "google-gemini-image":
        endpoint_overrides = [env.get("SCOPE_GOOGLE_GENERATE_CONTENT_URL") or env.get("SCOPE_IMAGE_GENERATE_CONTENT_URL") or None]
    elif adapter == "generic-image-json":
        endpoint_overrides = [env.get("SCOPE_IMAGE_ENDPOINT_URL") or None]

    model_sequence = parse_image_models(model)
    env_models = env.get("SCOPE_IMAGE_MODEL_LIST")
    if env_models:
        extra = parse_image_models(env_models)
        model_sequence = list(dict.fromkeys(extra + model_sequence))
    if not model_sequence:
        model_sequence = ["gpt-image-2"]
    last = None
    # Current OpenAI / Gemini official adapters do not need response_format
    # retries.  Keep the old retry field only for explicitly selected legacy
    # OpenAI-compatible image endpoints.
    format_sequence = response_formats if adapter == "openai-images-legacy" else [""]
    for image_url_idx, endpoint_override in enumerate(endpoint_overrides, start=1):
        for image_model in model_sequence:
            model_index = model_sequence.index(image_model) + 1
            for i, fmt in enumerate(format_sequence, start=1):
                reference_supported = adapter in {
                    "openai-responses-image",
                    "google-gemini-image",
                    "generic-image-json",
                    "openai-images-legacy",
                }
                try:
                    image_url, headers, payload, used_adapter = build_image_request(
                        adapter,
                        base,
                        key,
                        image_model,
                        prompt,
                        env,
                        reference_image=reference_image if reference_supported else None,
                        endpoint_override=endpoint_override,
                        response_format=fmt or None,
                    )
                except Exception as exc:  # noqa: BLE001
                    return {"ok": False, "error": repr(exc), "adapter": adapter}
                reference_sent = bool(reference_image and reference_supported)
                status, body, error = post_json_with_retries(
                    image_url,
                    headers,
                    payload,
                    timeout,
                    image_retries,
                    f"{used_adapter} image {image_model} ({image_url_idx}/{len(endpoint_overrides)})",
                    backoff_base=6.0,
                )
                if status == 200:
                    items = extract_image_items(body)
                    image_path: pathlib.Path | None = None
                    for item_index, item in enumerate(items, start=1):
                        suffix = image_suffix_from_mime(item.get("mime"))
                        image_path = out_dir / (
                            f"image{suffix}"
                            if attempt == 1 and image_model == model_sequence[0] and item_index == 1
                            else f"image.attempt_{attempt}.{item_index}{suffix}"
                        )
                        if item.get("b64"):
                            try:
                                image_path.write_bytes(base64.b64decode(item["b64"]))
                                return {
                                    "ok": True,
                                    "image_path": str(image_path),
                                    "format": fmt or "default",
                                    "sub_attempt": i,
                                    "body": redact_b64(body),
                                    "model": image_model,
                                    "endpoint": image_url,
                                    "adapter": used_adapter,
                                    "attempt_path_index": image_url_idx,
                                    "reference_image_sent": reference_sent,
                                    "image_source": item.get("source"),
                                }
                            except Exception as exc:  # noqa: BLE001
                                last = f"b64 decode failed: {repr(exc)}"
                                continue
                        if item.get("url"):
                            if download_image(item["url"], image_path):
                                return {
                                    "ok": True,
                                    "image_path": str(image_path),
                                    "image_url": item["url"],
                                    "format": fmt or "default",
                                    "sub_attempt": i,
                                    "body": redact_b64(body),
                                    "model": image_model,
                                    "endpoint": image_url,
                                    "adapter": used_adapter,
                                    "attempt_path_index": image_url_idx,
                                    "reference_image_sent": reference_sent,
                                    "image_source": item.get("source"),
                                }
                            last = "generated URL but download failed"
                    if not items:
                        last = "200 without image data"
                else:
                    last = f"{status}: {error}"
                print(
                    f"[WARN] image attempt {attempt}.{image_url_idx}.{model_index}.{i}/{len(format_sequence)} "
                    f"{image_model} via {adapter} failed: {last}",
                    flush=True,
                )
                if i < len(format_sequence):
                    time.sleep(min(75, 10 * (1.7 ** (i - 1))) + random.uniform(1, 4))
    return {"ok": False, "error": last or "all image endpoints/models failed", "adapter": adapter}


def redact_b64(obj: Any) -> Any:
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in {"b64_json", "result", "data"} and isinstance(v, str) and len(v) > 512:
                out[k] = f"[base64 omitted len={len(v)}]"
            else:
                out[k] = redact_b64(v)
        return out
    if isinstance(obj, list):
        return [redact_b64(v) for v in obj]
    return obj


def analyze_reference_image(
    vision_env: dict[str, str],
    model: str,
    reference_image: pathlib.Path,
    user_prompt: str,
    reference_mode: str,
    timeout: int,
) -> dict[str, Any]:
    user_text = (
        f"User request: {user_prompt}\n"
        f"Reference mode: {reference_mode}\n"
        "Create a concise visual reference brief for downstream image generation."
    )
    base = (
        vision_env.get("SCOPE_VISION_BASE_URL")
        or vision_env.get("SCOPE_LLM_BASE_URL")
        or vision_env.get("SCOPE_REASONER_BASE_URL")
        or vision_env.get("SCOPE_VISION_ENDPOINT_URL")
        or vision_env.get("SCOPE_LLM_ENDPOINT_URL")
    )
    key = (
        vision_env.get("SCOPE_VISION_API_KEY")
        or vision_env.get("SCOPE_LLM_API_KEY")
        or vision_env.get("SCOPE_REASONER_API_KEY")
    )
    if not base or not key:
        raise RuntimeError("missing vision base/key for reference analysis")
    adapter = normalize_adapter(vision_env.get("SCOPE_VISION_FORMAT") or vision_env.get("SCOPE_LLM_FORMAT"), "openai-chat")
    url, headers, payload, adapter = build_vision_request(
        adapter,
        base,
        key,
        model,
        REFERENCE_ANALYSIS_SYSTEM,
        user_text,
        [reference_image],
        vision_env,
        temperature=0,
        json_object=True,
    )
    attempts = max(1, _env_int("SCOPE_VISION_ATTEMPTS", 4))
    status, body, last = post_json_with_retries(url, headers, payload, timeout, attempts, f"{adapter} reference vision {model}", backoff_base=4.5)
    if status == 200:
        content = extract_text(adapter, body) or "{}"
        parsed = extract_json(content)
        return parsed if isinstance(parsed, dict) else {"reference_brief": str(parsed)}
    raise RuntimeError(last or f"reference analysis failed: {status}")


def vision_audit(
    vision_env: dict[str, str],
    model: str,
    image_path: pathlib.Path,
    user_prompt: str,
    route: str,
    timeout: int,
    presets: dict[str, Any] | None = None,
) -> dict[str, Any]:
    user_text = f"User request: {user_prompt}\nExpected route: {route}\nRoute hint: {route_hint_text(route, presets)}"
    base = (
        vision_env.get("SCOPE_VISION_BASE_URL")
        or vision_env.get("SCOPE_LLM_BASE_URL")
        or vision_env.get("SCOPE_REASONER_BASE_URL")
        or vision_env.get("SCOPE_VISION_ENDPOINT_URL")
        or vision_env.get("SCOPE_LLM_ENDPOINT_URL")
    )
    key = (
        vision_env.get("SCOPE_VISION_API_KEY")
        or vision_env.get("SCOPE_LLM_API_KEY")
        or vision_env.get("SCOPE_REASONER_API_KEY")
    )
    if not base or not key:
        raise RuntimeError("missing vision base/key")
    adapter = normalize_adapter(vision_env.get("SCOPE_VISION_FORMAT") or vision_env.get("SCOPE_LLM_FORMAT"), "openai-chat")
    url, headers, payload, adapter = build_vision_request(
        adapter,
        base,
        key,
        model,
        VISION_AUDIT_SYSTEM,
        user_text,
        [image_path],
        vision_env,
        temperature=0,
        json_object=True,
    )
    max_attempts = max(1, _env_int("SCOPE_VISION_ATTEMPTS", 4))
    attempts_by_status: list[bool] = []
    last: str | None = None
    transient_only = True
    for attempt in range(1, max_attempts + 1):
        status, body, last = post_json_with_retries(
            url,
            headers,
            payload,
            timeout,
            attempts=max_attempts,
            label=f"{adapter} vision {model}",
            backoff_base=4.5,
        )
        if status == 200:
            content = extract_text(adapter, body) or "{}"
            return extract_json(content)
        attempts_by_status.append(not is_transient_error(last))
        if status != "error":
            transient_only = transient_only and (status in RETRYABLE_HTTP_STATUS)
            if status not in RETRYABLE_HTTP_STATUS:
                return {"can_see_image": False, "overall": "needs_repair", "failures": [f"vision HTTP {status}: {str(body)[:300]}"], "repair_prompt": str(body)[:300]}
        if attempt < max_attempts:
            time.sleep(min(50, 6 * (1.5 ** (attempt - 1))) + random.uniform(0.5, 2.5))
    if transient_only and attempts_by_status:
        return {
            "can_see_image": False,
            "overall": VISION_UNSTABLE_MARK,
            "failures": [last or "vision service unstable"],
            "repair_prompt": "vision service unstable; proceed with generated image for now and retry later",
        }
    return {"can_see_image": False, "overall": "needs_repair", "failures": [last], "repair_prompt": "vision service unstable; retry with clearer prompt"}


def repair_prompt(current_prompt: str, audit: dict[str, Any], user_prompt: str, route: str, llm_env: dict[str, str], llm_model: str, max_chars: int, timeout: int) -> str:
    repair_instruction = audit.get("repair_prompt") or "; ".join(audit.get("failures", []))
    if not repair_instruction:
        return current_prompt
    if llm_env:
        try:
            payload = {"user_request": user_prompt, "route": route, "current_prompt": current_prompt, "visual_audit": audit}
            repaired = chat_json(llm_env, llm_model, REPAIR_SYSTEM, json.dumps(payload, ensure_ascii=False), timeout)
            return sanitize_prompt(repaired.get("optimized_prompt_en") or current_prompt, max_chars)
        except Exception as exc:  # noqa: BLE001
            print(f"[WARN] LLM repair failed: {repr(exc)}", flush=True)
    return sanitize_prompt(current_prompt + " Repair focus: " + repair_instruction, max_chars)


def main() -> int:
    parser = argparse.ArgumentParser(description="Single-request v2 SCOPE router/generator with optional vision repair.")
    parser.add_argument("--user-prompt", required=True)
    parser.add_argument("--env-file", required=True, type=pathlib.Path, help="Image endpoint env file.")
    parser.add_argument("--out-dir", required=True, type=pathlib.Path)
    parser.add_argument("--route", default="auto")
    parser.add_argument(
        "--preset-file",
        type=pathlib.Path,
        default=DEFAULT_PRESET_FILE,
        help="Prompt preset JSON file for route/prompt rules.",
    )
    parser.add_argument(
        "--image-model",
        default=_env_str("SCOPE_IMAGE_MODEL", "gpt-image-2"),
    )
    parser.add_argument("--llm-env-file", type=pathlib.Path, help="LLM env file.")
    parser.add_argument("--llm-model", default="grok-4.3")
    parser.add_argument("--vision-env-file", type=pathlib.Path, help="Vision model env file.")
    parser.add_argument("--vision-model", default="grok-4.3")
    parser.add_argument("--reference-image", type=pathlib.Path, help="Optional reference image for style/composition/identity/product-guided generation.")
    parser.add_argument("--reference-mode", default="auto", choices=["auto", "style", "composition", "identity", "character", "product"], help="How to use --reference-image.")
    parser.add_argument("--max-generation-attempts", type=int, default=_env_int("SCOPE_IMAGE_ATTEMPTS", 4))
    parser.add_argument("--response-formats", default=_env_str("SCOPE_RESPONSE_FORMATS", "b64_json,url,b64_json,url"))
    parser.add_argument("--image-retries", type=int, default=_env_int("SCOPE_IMAGE_RETRIES", 1), help="Per-format image API retry count when generating")
    parser.add_argument("--max-prompt-chars", type=int, default=900)
    parser.add_argument("--timeout", type=int, default=260)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "user_request.txt").write_text(args.user_prompt, encoding="utf-8")

    args.route = str(args.route).strip().lower()
    presets = load_prompt_presets(args.preset_file)
    route_keys = route_keys_from_presets(presets)
    if args.route != "auto" and args.route not in route_keys:
        parser.error(f"unsupported --route value: {args.route}. Allowed: {', '.join(route_keys)}")

    image_env = load_env_file(args.env_file)
    llm_env = load_env_file(args.llm_env_file) if args.llm_env_file else {}
    vision_env = load_env_file(args.vision_env_file) if args.vision_env_file else {}
    reference_image: pathlib.Path | None = None
    working_prompt = args.user_prompt
    if args.reference_image:
        if not args.reference_image.exists():
            parser.error(f"--reference-image not found: {args.reference_image}")
        reference_image = args.reference_image.resolve()
        ref_mime = mimetypes.guess_type(str(reference_image))[0] or ""
        if not ref_mime.startswith("image/"):
            parser.error(f"--reference-image must be an image file, got {reference_image}")
        ref_copy = args.out_dir / ("reference_image" + reference_image.suffix.lower())
        try:
            shutil.copyfile(reference_image, ref_copy)
        except Exception:  # noqa: BLE001
            ref_copy = reference_image
        reference_meta: dict[str, Any] = {
            "source": str(reference_image),
            "saved_copy": str(ref_copy),
            "mode": args.reference_mode,
            "direct_reference_payload_enabled": (
                normalize_adapter(image_env.get("SCOPE_IMAGE_FORMAT"), "openai-images")
                in {"openai-responses-image", "google-gemini-image", "generic-image-json"}
                or (
                    normalize_adapter(image_env.get("SCOPE_IMAGE_FORMAT"), "openai-images") == "openai-images-legacy"
                    and image_env.get("SCOPE_SEND_REFERENCE_IMAGE", "").strip().lower()
                    in {"1", "true", "yes", "on", "y"}
                )
            ),
        }
        reference_hint = (
            f"Reference image mode: {args.reference_mode}. Use the supplied reference image as visual guidance; "
            "preserve only relevant non-sensitive visual anchors and adapt them to the user's request."
        )
        if vision_env:
            try:
                reference_analysis = analyze_reference_image(
                    vision_env,
                    args.vision_model,
                    reference_image,
                    args.user_prompt,
                    args.reference_mode,
                    args.timeout,
                )
                reference_meta["analysis"] = reference_analysis
                brief = reference_analysis.get("reference_brief") if isinstance(reference_analysis, dict) else ""
                preserve = reference_analysis.get("preserve") if isinstance(reference_analysis, dict) else []
                adapt = reference_analysis.get("adapt") if isinstance(reference_analysis, dict) else []
                avoid = reference_analysis.get("avoid") if isinstance(reference_analysis, dict) else []
                reference_hint = (
                    f"Reference image mode: {args.reference_mode}. Reference brief: {brief}. "
                    f"Preserve: {preserve}. Adapt: {adapt}. Avoid copying: {avoid}."
                )
            except Exception as exc:  # noqa: BLE001
                reference_meta["analysis_error"] = repr(exc)
        (args.out_dir / "reference_image.json").write_text(json.dumps(reference_meta, ensure_ascii=False, indent=2), encoding="utf-8")
        working_prompt = args.user_prompt + "\n\n" + reference_hint
        (args.out_dir / "reference_prompt_input.txt").write_text(working_prompt, encoding="utf-8")

    route = infer_route(working_prompt, args.route, presets=presets)
    route_info = {
        "route": route,
        "route_hint": route_hint_text(route, presets),
        "forced": args.route != "auto",
        "preset_file": str(args.preset_file),
        "reference_image": str(reference_image) if reference_image else None,
    }
    (args.out_dir / "route.json").write_text(json.dumps(route_info, ensure_ascii=False, indent=2), encoding="utf-8")

    optimized = optimize_prompt(
        working_prompt,
        route,
        llm_env,
        args.llm_model,
        args.max_prompt_chars,
        args.timeout,
        presets=presets,
    )
    route = optimized.get("route", route)
    prompt = sanitize_prompt(optimized.get("optimized_prompt_en", working_prompt), args.max_prompt_chars)
    negative = merge_negative(route, optimized.get("negative_prompt"), presets=presets)
    final_prompt = assemble_generation_prompt(prompt, negative, args.max_prompt_chars)
    (args.out_dir / "optimized_prompt.json").write_text(json.dumps(optimized, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.out_dir / "generation_prompt.txt").write_text(final_prompt, encoding="utf-8")

    if args.dry_run:
        summary = {
            "dry_run": True,
            "route": route,
            "prompt": final_prompt,
            "out_dir": str(args.out_dir),
            "reference_image": str(reference_image) if reference_image else None,
        }
        (args.out_dir / "final_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
        return 0

    response_formats = [x.strip() for x in args.response_formats.split(",") if x.strip()]
    image_retries = max(1, args.image_retries)
    audits: list[dict[str, Any]] = []
    generations: list[dict[str, Any]] = []
    current_prompt = final_prompt
    final_image: str | None = None
    final_overall = "not_run"
    vision_status: list[str] = []

    for attempt in range(1, max(1, args.max_generation_attempts) + 1):
        (args.out_dir / f"generation_prompt.attempt_{attempt}.txt").write_text(current_prompt, encoding="utf-8")
        gen = generate_image(
            image_env,
            args.image_model,
            current_prompt,
            args.out_dir,
            attempt,
            response_formats,
            args.timeout,
            image_retries,
            reference_image=reference_image,
        )
        generations.append(gen)
        (args.out_dir / f"image_result.attempt_{attempt}.json").write_text(json.dumps(gen, ensure_ascii=False, indent=2), encoding="utf-8")
        if not gen.get("ok"):
            final_overall = "image_generation_failed"
            continue
        image_path = pathlib.Path(gen["image_path"])
        final_image = str(image_path)
        if image_path.name != "image.png":
            shutil.copyfile(image_path, args.out_dir / "image.png")
            final_image = str(args.out_dir / "image.png")
        if not vision_env:
            final_overall = "vision_not_run"
            break
        try:
            audit = vision_audit(
                vision_env,
                args.vision_model,
                image_path,
                working_prompt,
                route,
                args.timeout,
                presets=presets,
            )
        except Exception as exc:  # noqa: BLE001
            audit = {"can_see_image": False, "overall": "needs_repair", "failures": [repr(exc)], "repair_prompt": "vision audit failed; retry with clearer route and simpler composition"}
        audits.append(audit)
        (args.out_dir / f"visual_audit.attempt_{attempt}.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
        final_overall = audit.get("overall", "needs_repair")
        if final_overall == VISION_UNSTABLE_MARK:
            vision_status.append("vision_unstable")
            final_overall = "pass"
            break
        if final_overall == "pass":
            break
        vision_status.append(final_overall)
        if attempt < args.max_generation_attempts:
            current_prompt = repair_prompt(current_prompt, audit, working_prompt, route, llm_env or vision_env, args.llm_model, args.max_prompt_chars, args.timeout)

    summary = {
        "route": route,
        "image_model": args.image_model,
        "image_models": parse_image_models(args.image_model),
        "llm_model": args.llm_model if llm_env else None,
        "vision_model": args.vision_model if vision_env else None,
        "final_overall": final_overall,
        "final_image": final_image,
        "reference_image": str(reference_image) if reference_image else None,
        "generation_attempts": len(generations),
        "vision_status": vision_status,
        "response_formats": response_formats,
        "visual_audits": audits,
        "artifacts": sorted(p.name for p in args.out_dir.iterdir()),
    }
    (args.out_dir / "final_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
