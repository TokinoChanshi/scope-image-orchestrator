#!/usr/bin/env python3
"""Built-in SCOPE v2 preset regression batch for an image API.

Generates 6 categories x 6 variants: portrait, magazine, poster, cosplay, interior, product.
The batch is resumable: existing PNGs are skipped and contact sheets are rebuilt after each item.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import pathlib
import random
import re
import time
from typing import Any

import requests
from PIL import Image, ImageDraw, ImageFont

ROOT = pathlib.Path.cwd()
ENV_PATH = pathlib.Path(os.environ["SCOPE_IMAGE_ENV_FILE"]) if os.environ.get("SCOPE_IMAGE_ENV_FILE") else None
OUT_DIR = ROOT / "scope_runs" / "preset_regression_6x6"
MODEL = os.environ.get("SCOPE_IMAGE_MODEL", "gpt-image-2")
MAX_ATTEMPTS = int(os.environ.get("SCOPE_IMAGE_ATTEMPTS", "3"))
MAX_PROMPT_CHARS = int(os.environ.get("SCOPE_MAX_PROMPT_CHARS", "760"))
RESPONSE_FORMATS = ("url", "b64_json", "url")
INFRA_PAT = re.compile(r"RemoteDisconnected|SSLEOFError|origin_bad_gateway|Bad gateway|HTTP 502|TLS|基础连接", re.I)
INFRA_STREAK_LIMIT = int(os.environ.get("SCOPE_INFRA_STREAK_LIMIT", "3"))
FORCED_OVERWRITE = False
COSPLAY_REALISM_BOOSTER = (
    "practical real-world texture cues: subtle sensor grain, slight lens vignetting, natural micro-hand asymmetry, "
    "minor fabric stretching and micro creases, realistic body weight shifts and shoulder imbalance, natural skin microvariation."
)
MAGAZINE_TEXT_HARD_BOUNDS = (
    "masthead must stay fully readable, 22% clear space above forehead, short 2-4 line hierarchy, no text overlap on logo."
)


def load_env(path: pathlib.Path) -> dict[str, str]:
    env: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8-sig", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def compact(prompt: str, max_chars: int | None = None) -> str:
    if max_chars is None:
        max_chars = MAX_PROMPT_CHARS
    prompt = " ".join(prompt.split())
    if len(prompt) <= max_chars:
        return prompt
    cut = prompt[:max_chars]
    idx = max(cut.rfind(". "), cut.rfind("; "), cut.rfind(", "))
    return cut[: idx + 1].strip() if idx > 360 else cut.strip()


def api_base(env: dict[str, str]) -> str:
    base = env.get("SCOPE_IMAGE_BASE_URL")
    if not base:
        raise SystemExit("Missing SCOPE_IMAGE_BASE_URL")
    return base.rstrip("/")


def parse_categories(raw: str | None, all_prompts: dict[str, list[tuple[str, str]]]) -> list[str]:
    if not raw:
        return list(all_prompts.keys())
    categories = [item.strip() for item in raw.split(",") if item.strip()]
    unknown = [c for c in categories if c not in all_prompts]
    if unknown:
        raise SystemExit(f"Unknown categories in --categories: {unknown}; valid={sorted(all_prompts)}")
    return categories


def parse_variants(raw: str | None, all_prompts: dict[str, list[tuple[str, str]]], categories: list[str]) -> set[str]:
    if not raw:
        return set()
    normalized = set()
    for item in raw.split(","):
        key = item.strip()
        if not key:
            continue
        normalized.add(re.sub(r"^\d+_", "", key))
    known: set[str] = {name for cat in categories for name, _ in all_prompts[cat]}
    unknown = [name for name in normalized if name not in known]
    if unknown:
        raise SystemExit(f"Unknown variants in --variants: {unknown}; valid={sorted(known)}")
    return normalized


def headers(env: dict[str, str]) -> dict[str, str]:
    return {
        "Authorization": "Bearer " + env["SCOPE_IMAGE_API_KEY"],
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 SCOPE-Image-Orchestrator/1.0",
        "Connection": "close",
    }


def health_check(env: dict[str, str], attempts: int = 2) -> tuple[bool, str]:
    url = api_base(env) + "/v1/models"
    h = headers(env)
    h.pop("Content-Type", None)
    last = ""
    for attempt in range(1, attempts + 1):
        try:
            with requests.Session() as session:
                r = session.get(url, headers=h, timeout=(10, 35))
            if r.status_code == 200:
                return True, f"GET /v1/models OK bytes={len(r.content)}"
            last = f"HTTP {r.status_code}: {r.text[:240]}"
        except Exception as exc:
            last = repr(exc)
        print(f"[HEALTH] attempt {attempt}/{attempts} failed: {last}", flush=True)
        if attempt < attempts:
            time.sleep(45 + random.uniform(2, 8))
    return False, last


def retry_sleep(attempt: int) -> None:
    time.sleep(min(65, 18 * (1.55 ** max(0, attempt - 1))) + random.uniform(2, 6))


def download_image(url: str, out_path: pathlib.Path) -> bool:
    h = {"User-Agent": "Mozilla/5.0 SCOPE-Image-Orchestrator/1.0", "Connection": "close"}
    for attempt in range(1, 4):
        try:
            with requests.Session() as session:
                r = session.get(url, headers=h, timeout=(20, 120))
            if r.status_code == 200 and r.content:
                out_path.write_bytes(r.content)
                return True
            print(f"[WARN] download {attempt}/3 HTTP {r.status_code}: {r.text[:120]}", flush=True)
        except Exception as exc:
            print(f"[WARN] download {attempt}/3 failed: {repr(exc)}", flush=True)
        time.sleep(5 * attempt)
    return False


def prompts() -> dict[str, list[tuple[str, str]]]:
    neg_person = "Negative: no nudity, no lingerie, no transparent clothing, no explicit pose, no minors, no watermark."
    neg_text = "Negative: no random paragraphs, no repeated letters, no watermark, no plastic skin."
    cosplay_booster = (
        "practical mixed lighting, real fabric and metal texture, natural skin imperfections, asymmetric face, subtle pores, "
        "slight hand asymmetry, natural shoulder posture, visible fabric drape and tension, natural clothing stretch at elbows, "
        "minor lens imperfection, realistic body weight and micro pose sway, no volumetric haze."
    )
    cosplay_booster = f"{cosplay_booster} {COSPLAY_REALISM_BOOSTER}"
    return {
        "portrait": [
            ("tokyo_window_bob", "Photorealistic 2:3 editorial lifestyle portrait, adult East Asian woman, short black bob, oval face, ivory cotton blouse by a hotel window, ceramic cup in hand, 85mm lens, soft morning light, beige curtains, city blur, natural asymmetric face, pores, flyaway hairs, small fabric wrinkles, candid quiet mood. No typography. " + neg_person),
            ("cafe_curls", "Photorealistic 2:3 lifestyle portrait, adult Black woman with cropped natural curls and square face, rust knit dress in a quiet cafe corner, hands around coffee cup, 50mm lens, warm lamp, books, rainy window reflections, real skin texture, relaxed decisive moment, not catalogue posture. No typography. " + neg_person),
            ("balcony_blonde", "Photorealistic 2:3 city night balcony portrait, adult blonde woman in her late 30s, angular face, navy evening dress with tailored black jacket, neon bokeh, glass railing, wind-touched hair, low-key available light, realistic pores, soft under-eye detail, confident candid stance. No typography. " + neg_person),
            ("studio_south_asian", "Photorealistic 2:3 daylight studio portrait, adult South Asian woman, heart-shaped face, long dark hair tied low, white linen shirt and taupe trousers, canvas backdrop, stool, reflector card, 85mm lens, real fabric texture, natural hands in pockets, calm editorial realism. No typography. " + neg_person),
            ("garden_redhair", "Photorealistic 2:3 garden path portrait, adult woman with copper red hair, freckles, pale green cotton dress, 50mm lens, backlit leaves, stone path, natural walking pose, imperfect hand placement, skin tone variation, mild film grain, private summer mood. No typography. " + neg_person),
            ("apartment_latina", "Photorealistic 2:3 compact apartment portrait, adult Latina woman with messy bun and thin glasses, beige oversized cardigan over opaque lounge top and linen pants, sofa, books, warm table lamp, blanket, handheld framing, natural asymmetric face, flyaway hairs, intimate everyday realism. No typography. " + neg_person),
        ],
        "magazine": [
            ("luxe_coat", "Photorealistic 2:3 fashion magazine cover. Masthead LUXE, cover lines Modern Grace / New Silhouette, small badge ISSUE 47. Adult model with short black bob in cream wool coat and pearl earring, dark hotel interior, clean editorial grid, head overlaps masthead, crisp serif typography, warm contrast, real skin texture, visible wool fibers. " + neg_text),
            ("noir_suit", "Photorealistic 2:3 fashion magazine cover. Masthead NOIR, cover lines Sharp Lines / City Muse, small badge NIGHT. Adult model with silver-blonde pixie cut in black tailored suit, grey studio set, strong side light, clean negative space, head partly covers masthead, crisp cream serif text, fabric weave and pores visible. " + neg_text),
            ("atelier_linen", "Photorealistic 2:3 fashion magazine cover. Masthead ATELIER, cover lines Soft Power / Linen Notes, small badge 47. Adult model with auburn wavy hair in structured ivory linen dress, cream seamless studio, editorial grid, relaxed seated pose, readable serif text, soft shadows, natural skin and hair detail. " + neg_text),
            ("flora_green", "Photorealistic 2:3 fashion magazine cover. Masthead FLORA, cover lines Garden Issue / New Romance, small badge SPRING. Adult model with dark curly hair in emerald floral couture jacket, botanical set, clean left text column, subject angled slightly right with hair framed away from masthead, visible 22% masthead clearance zone above forehead. " + MAGAZINE_TEXT_HARD_BOUNDS + " " + neg_text),
            ("mode_silver", "Photorealistic 2:3 fashion magazine cover. Masthead MODE, cover lines Future Classics / Minimal Issue, small badge 26. Adult model with sharp bob in silver minimalist coat, grey cyclorama, restrained layout, large top masthead, tiny issue number, crisp white typography, cool studio light, real textile texture. " + neg_text),
            ("voyage_lobby", "Photorealistic 2:3 fashion magazine cover. Masthead VOYAGE, cover lines Hotel Stories / Quiet Luxury, small badge SUMMER. Adult model with long braided hair in sand linen suit, boutique hotel lobby, warm wood and stone, editorial grid, head overlaps masthead, readable serif type, natural skin detail. " + neg_text),
        ],
        "poster": [
            ("neon_protocol", "Cinematic 2:3 movie poster for NEON PROTOCOL. Adult female detective with cropped hair, wet trench coat, mechanical forearm, clear foreground silhouette. Midground police drone, background rainy neon alley and hovering traffic, cyan-magenta reflections. Title in lower third, short tagline at top, small credits block. High-budget film realism, dramatic rim light. Negative: no repeated title, no clutter, no watermark."),
            ("desert_signal", "Cinematic 2:3 movie poster for DESERT SIGNAL. Adult engineer in dusty survival suit holds a blue emergency flare before a desert radio tower. Orange dust storm background, cables and rover in midground, strong silhouette, readable face. Title lower third, tiny credits bottom, gritty sci-fi film color grade. Negative: no repeated title, no fake logos, no watermark."),
            ("ocean_archive", "Cinematic 2:3 movie poster for OCEAN ARCHIVE. Adult diver scientist in dark wetsuit stands inside a glass underwater lab. Bioluminescent blue-green ocean outside, cracked archive case in midground, layered depth, wet reflections, title lower third and small credits block. Negative: no extra limbs, no repeated text, no watermark."),
            ("winter_orbit", "Cinematic 2:3 movie poster for WINTER ORBIT. Adult astronaut without helmet in snowy launch site foreground, silver thermal suit, rocket gantry and aurora sky behind, orange work lights, breath mist, strong eye-line. Title lower third, short tagline at top, small credits. Negative: no repeated title, no clutter, no watermark."),
            ("red_station", "Cinematic 2:3 noir spy movie poster for RED STATION. Adult protagonist in long coat stands under red train-station lights with one suitcase. Steam haze, clock, platform lines, deep shadows, clear silhouette, title across lower third, credits at bottom. Negative: no fake logos, no repeated text, no watermark."),
            ("forest_gate", "Cinematic 2:3 fantasy mystery poster for FOREST GATE. Adult ranger with leather cloak and lantern faces a glowing ancient doorway in a dark forest. Moon rim light, fog layers, mossy stones, strong silhouette, title lower third, small credits block. Negative: no clutter, no repeated title, no watermark."),
        ],
        "cosplay": [
            ("plum_pyro", "Photorealistic 2:3 live-action character poster, adult cosplayer as an original pyro shrine heroine: dark twin tails, plum hair ornaments, red-black silk and leather costume, lantern prop, embroidered seams, metal charms, night lantern street, warm practical rim light, real pores and hair strands. Negative: no anime render, no plastic costume, no cheap cosplay, no random text, no nudity, no watermark. " + cosplay_booster),
            ("blue_archer", "Photorealistic 2:3 live-action character poster, adult cosplayer as original blue archer heroine: long navy hair, crescent silver hairpin, teal cloak, carved bow, layered fabric, leather bracers, mountain temple dawn, clear heroic silhouette, natural face texture. Negative: no anime render, no CGI skin, no cheap costume, no random text, no nudity, no watermark. " + cosplay_booster),
            ("cyber_idol", "Photorealistic 2:3 live-action character poster, adult cosplayer as original cyber idol: short pink hair, translucent acrylic visor, metallic cropped jacket over opaque stage outfit, glowing microphone prop, neon backstage, chrome and vinyl textures, candid performance stance. Negative: no anime render, no plastic skin, no cheap cosplay, no random text, no nudity, no watermark. " + cosplay_booster),
            ("forest_healer", "Photorealistic 2:3 live-action character poster, adult cosplayer as original forest healer: green braided hair, herb pouch, wooden staff, linen cloak, leather belt, mossy ruin background, soft green-gold light, real fabric weight and embroidery. Negative: no CGI, no cheap costume, no random text, no nudity, no watermark. " + cosplay_booster),
            (
                "crimson_knight",
                "Photorealistic 2:3 live-action character poster, adult male red knight cosplay in full ornate red-and-silver armor with metallic sheen and "
                "visible leather details, short dark hair, sharp jawline, holding a sword in a disciplined ready pose. "
                "Real garment folds, metal edge reflections, realistic fabric tension, realistic human proportions and natural skin imperfections with subtle pores. "
                "Subject carries a slight shoulder-forward shift and micro knee bend to show real body weight. "
                "Practical side key and fill lights with crisp shadow edge, no studio flatness. "
                f"{cosplay_booster} No CGI, no anime render, no plastic armor, no perfect symmetry, no smoke haze, no nudity, no watermark. "
                "Keep style photographic, not stylized CGI.",
            ),
            ("moon_witch", "Photorealistic 2:3 live-action character poster, adult cosplayer as original moon witch: silver hair, crescent hairpin, midnight velvet cloak, crystal lantern, star embroidery, blue observatory at night, practical candlelight, realistic pores and hair. Negative: no CGI skin, no cheap cosplay, no random text, no watermark. " + cosplay_booster),
        ],
        "interior": [
            ("oriental_living", "Photorealistic 16:9 modern oriental minimalist living room, eye-height 24mm lens, low beige sofa, stone coffee table, walnut wall panels, floor-to-ceiling sunset window, hidden LED strips, paper lamp, rug foreground, straight verticals, realistic scale, wood grain and stone veining. Negative: no warped furniture, no impossible perspective, no people, no watermark."),
            ("hotel_suite", "Photorealistic 16:9 boutique hotel suite bedroom, eye-height 24mm lens from doorway, linen bed, stone headboard, walnut nightstands, paper pendant lamp, city window, layered warm bedside lights, folded throw, realistic fabric weave and shadows. Negative: no extra windows, no warped bed, no people, no watermark."),
            ("japanese_bath", "Photorealistic 4:5 compact Japanese spa bathroom, eye-height 28mm lens, stone soaking tub, cream tiles, wood slat wall, frosted window, folded towels, glass shower edge, wet-dry material separation, soft steam and warm indirect light. Negative: no impossible plumbing, no warped tiles, no people, no watermark."),
            ("gallery_kitchen", "Photorealistic 16:9 open gallery kitchen, eye-height 24mm lens, travertine island, oak cabinetry, brushed metal faucet, breakfast stools, pendant lights, morning window light, ceramic bowls, straight vertical lines, realistic stone and wood textures. Negative: no warped cabinets, no extra doors, no people, no watermark."),
            ("creative_office", "Photorealistic 16:9 creative studio office, eye-height 24mm lens, long oak desk, ergonomic chairs, shelves, plants, acoustic panels, warm desk lamps, tidy cable management, rug foreground, realistic monitor scale and fabric texture. Negative: no melted chairs, no impossible perspective, no people, no watermark."),
            ("dark_lounge", "Photorealistic 16:9 dark luxury lounge, eye-height 28mm lens, black stone bar, amber backlit shelves, leather sofa, brass details, low evening lighting, reflective stone floor, bottles as blurred background shapes, clean geometry. Negative: no warped furniture, no fake text labels, no people, no watermark."),
        ],
        "product": [
            ("perfume_glass", "Photorealistic 4:5 commercial product photo, luxury perfume bottle as single hero on cream stone, transparent glass body, chrome cap, blank label, softbox gradient reflection, jasmine flowers, crisp edges, premium negative space. Negative: no duplicate bottle, no random label text, no warped glass, no watermark."),
            ("watch_macro", "Photorealistic 1:1 commercial macro product photo, mechanical wristwatch as single hero on black velvet, brushed steel case, leather strap grain, precise bezel, controlled rim light, crisp shadow, shallow depth only behind watch. Negative: no duplicate watch, no warped dial text, no clutter, no watermark."),
            ("iced_tea", "Photorealistic 4:5 beverage product photo, cold bottled iced tea as single hero, blank paper label, condensation droplets, acrylic ice, citrus slices, sunlit glass table, golden liquid glow, crisp silhouette. Negative: no random brand text, no duplicate bottle, no warped cap, no watermark."),
            ("white_sneaker", "Photorealistic 4:5 commercial product photo, white leather sneaker as single hero, three-quarter angle on concrete surface, leather grain, stitching, rubber sole texture, soft shadow, neutral grey background, clean negative space. Negative: no duplicate shoe, no warped laces, no fake logo, no watermark."),
            ("matcha_dessert", "Photorealistic 4:5 food product photo, matcha dessert as single hero on handmade ceramic plate, powder texture, small spoon, linen napkin, soft window light, shallow depth, natural crumbs, cream-green palette. Negative: no duplicate dessert, no messy clutter, no watermark."),
            ("headphones", "Photorealistic 1:1 commercial product photo, matte black wireless headphones as single hero on curved acrylic stand, brushed metal accents, dark gradient background, controlled reflections, crisp edges and soft shadow. Negative: no duplicate headphones, no warped logo, no clutter, no watermark."),
        ],
    }


def post_image(env: dict[str, str], prompt: str, category: str, idx: int, name: str) -> dict[str, Any]:
    cat_dir = OUT_DIR / category
    cat_dir.mkdir(parents=True, exist_ok=True)
    image_path = cat_dir / f"{idx:02d}_{name}.png"
    if (not FORCED_OVERWRITE) and image_path.exists() and image_path.stat().st_size > 1000:
        return {"ok": True, "category": category, "idx": idx, "name": name, "image_path": str(image_path), "skipped_existing": True}

    prompt = compact(prompt)
    (cat_dir / f"{idx:02d}_{name}.prompt.txt").write_text(prompt, encoding="utf-8")
    payload_base = {"model": MODEL, "prompt": prompt, "n": 1, "response_format": "url"}
    url = api_base(env) + "/v1/images/generations"
    last_error = None
    last_body: Any = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        payload = dict(payload_base)
        payload["response_format"] = RESPONSE_FORMATS[min(attempt - 1, len(RESPONSE_FORMATS) - 1)]
        if attempt == MAX_ATTEMPTS:
            payload["prompt"] = compact(prompt, 520)
        try:
            with requests.Session() as session:
                r = session.post(url, headers=headers(env), json=payload, timeout=(20, 260))
            try:
                body = r.json()
            except Exception:
                body = {"text": r.text[:1000]}
            last_body = body
            if r.status_code == 200:
                item = (body.get("data") or [{}])[0]
                if item.get("b64_json"):
                    image_path.write_bytes(base64.b64decode(item["b64_json"]))
                    return {"ok": True, "category": category, "idx": idx, "name": name, "image_path": str(image_path), "attempt": attempt, "format": payload["response_format"]}
                if item.get("url"):
                    if download_image(item["url"], image_path):
                        return {"ok": True, "category": category, "idx": idx, "name": name, "image_path": str(image_path), "attempt": attempt, "format": payload["response_format"], "image_url": item["url"]}
                    last_error = "generated URL but media download failed"
                else:
                    last_error = "200 response without image data"
            else:
                last_error = f"HTTP {r.status_code}: {str(body)[:500]}"
        except Exception as exc:
            last_error = repr(exc)
        print(f"[WARN] {category}/{name} attempt {attempt}/{MAX_ATTEMPTS} failed: {last_error}", flush=True)
        if attempt < MAX_ATTEMPTS:
            retry_sleep(attempt)
    return {"ok": False, "category": category, "idx": idx, "name": name, "error": last_error, "body": last_body}


def make_sheet(items: list[tuple[str, pathlib.Path]], out: pathlib.Path, cols: int = 6, thumb_w: int = 220, thumb_h: int = 330) -> str | None:
    items = [(label, path) for label, path in items if path.exists()]
    if not items:
        return None
    label_h, margin = 34, 12
    rows = (len(items) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * thumb_w + (cols + 1) * margin, rows * (thumb_h + label_h) + (rows + 1) * margin), (245, 245, 245))
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("arial.ttf", 14)
    except Exception:
        font = ImageFont.load_default()
    for i, (label, path) in enumerate(items):
        im = Image.open(path).convert("RGB")
        im.thumbnail((thumb_w, thumb_h), Image.LANCZOS)
        cell = Image.new("RGB", (thumb_w, thumb_h), (230, 230, 230))
        cell.paste(im, ((thumb_w - im.width) // 2, (thumb_h - im.height) // 2))
        x = margin + (i % cols) * (thumb_w + margin)
        y = margin + (i // cols) * (thumb_h + label_h + margin)
        sheet.paste(cell, (x, y))
        draw.text((x, y + thumb_h + 7), label[:28], fill=(30, 30, 30), font=font)
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    return str(out)


def build_sheets(all_prompts: dict[str, list[tuple[str, str]]]) -> dict[str, str | None]:
    sheets: dict[str, str | None] = {}
    overview: list[tuple[str, pathlib.Path]] = []
    for category in all_prompts:
        files = sorted(p for p in (OUT_DIR / category).glob("*.png") if p.name != "contact_sheet.png") if (OUT_DIR / category).exists() else []
        items = [(p.stem, p) for p in files]
        sheets[category] = make_sheet(items, OUT_DIR / category / "contact_sheet.png", cols=3, thumb_w=300, thumb_h=420)
        overview.extend((f"{category}/{p.stem[:2]}", p) for p in files)
    sheets["overview"] = make_sheet(overview, OUT_DIR / "overview_contact_sheet.png", cols=6, thumb_w=210, thumb_h=300)
    return sheets


def write_summary(all_prompts: dict[str, list[tuple[str, str]]], results: list[dict[str, Any]], stopped: str | None = None) -> dict[str, Any]:
    sheets = build_sheets(all_prompts)
    summary = {
        "out_dir": str(OUT_DIR),
        "stopped": stopped,
        "target_total": sum(len(v) for v in all_prompts.values()),
        "generated_this_run": sum(1 for r in results if r.get("ok") and not r.get("skipped_existing")),
        "by_category": {},
        "overview_contact_sheet": sheets.get("overview"),
        "results": [{k: r.get(k) for k in ["category", "idx", "name", "ok", "image_path", "error", "skipped_existing"]} for r in results],
    }
    for cat, variants in all_prompts.items():
        files = sorted(p for p in (OUT_DIR / cat).glob("*.png") if p.name != "contact_sheet.png") if (OUT_DIR / cat).exists() else []
        summary["by_category"][cat] = {"ok": len(files), "target": len(variants), "sheet": sheets.get(cat), "files": [str(p) for p in files]}
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> int:
    global ENV_PATH, OUT_DIR, MODEL, MAX_ATTEMPTS, MAX_PROMPT_CHARS, RESPONSE_FORMATS, FORCED_OVERWRITE, INFRA_STREAK_LIMIT

    parser = argparse.ArgumentParser(
        description="Generate the built-in 6x6 v2 SCOPE preset regression batch with resumable outputs."
    )
    parser.add_argument("--env-file", type=pathlib.Path, default=ENV_PATH, help="Local SCOPE image KEY=VALUE env file.")
    parser.add_argument("--out-dir", type=pathlib.Path, default=OUT_DIR, help="Output directory. Existing PNGs are skipped.")
    parser.add_argument("--image-model", default=MODEL)
    parser.add_argument("--max-attempts", type=int, default=MAX_ATTEMPTS)
    parser.add_argument("--max-prompt-chars", type=int, default=MAX_PROMPT_CHARS)
    parser.add_argument("--response-formats", default="url,b64_json,url", help="Comma-separated retry response formats.")
    parser.add_argument("--skip-health-check", action="store_true")
    parser.add_argument(
        "--infra-streak-limit",
        type=int,
        default=INFRA_STREAK_LIMIT,
        help="Stop when consecutive infrastructure failures reach this limit. 0 means never stop by streak.",
    )
    parser.add_argument("--categories", default="", help="Comma-separated subset of categories to run.")
    parser.add_argument("--force", action="store_true", help="Re-generate even if existing image files exist.")
    parser.add_argument("--variants", default="", help="Comma-separated variant names to run, e.g. 05_crimson_knight. Only works in selected categories.")
    parser.add_argument(
        "--order",
        default="product,interior,poster,cosplay,magazine,portrait",
        help="Comma-separated category generation order.",
    )
    args = parser.parse_args()

    if args.env_file is None:
        raise SystemExit("Missing --env-file or SCOPE_IMAGE_ENV_FILE")

    ENV_PATH = args.env_file
    OUT_DIR = args.out_dir
    MODEL = args.image_model
    MAX_ATTEMPTS = max(1, args.max_attempts)
    MAX_PROMPT_CHARS = max(260, args.max_prompt_chars)
    RESPONSE_FORMATS = tuple(x.strip() for x in args.response_formats.split(",") if x.strip()) or ("url", "b64_json", "url")
    INFRA_STREAK_LIMIT = max(0, args.infra_streak_limit)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    env = load_env(ENV_PATH)
    all_prompts = prompts()
    FORCED_OVERWRITE = args.force
    if not args.skip_health_check:
        ok, msg = health_check(env)
        (OUT_DIR / "health.txt").write_text(msg, encoding="utf-8")
        if not ok:
            summary = write_summary(all_prompts, [], stopped="health_check_failed: " + msg)
            print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
            return 2

    results: list[dict[str, Any]] = []
    fail_streak = 0
    stopped: str | None = None
    # Generate only the requested categories (default all), in the requested order.
    if args.categories:
        order = parse_categories(args.categories, all_prompts)
    else:
        order = parse_categories(args.order, all_prompts)
    active_prompts = {k: all_prompts[k] for k in order}
    selected_variants = parse_variants(args.variants, all_prompts, order)
    for category in order:
        print(f"\n=== CATEGORY {category} ===", flush=True)
        for idx, (name, prompt) in enumerate(all_prompts[category], start=1):
            if selected_variants and name not in selected_variants:
                continue
            print(f"[RUN] {category} {idx:02d} {name}", flush=True)
            result = post_image(env, prompt, category, idx, name)
            results.append(result)
            (OUT_DIR / category / f"{idx:02d}_{name}.result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            build_sheets(active_prompts)
            if result.get("ok"):
                fail_streak = 0
                cooldown = 1 if result.get("skipped_existing") else 18
            else:
                fail_streak = fail_streak + 1 if INFRA_PAT.search(str(result.get("error") or "")) else 0
                cooldown = 75
            if INFRA_STREAK_LIMIT and fail_streak >= INFRA_STREAK_LIMIT:
                stopped = f"infrastructure_failure_streak_{fail_streak}"
                print(f"[STOP] {stopped}", flush=True)
                summary = write_summary(active_prompts, results, stopped=stopped)
                print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
                return 3
            time.sleep(cooldown + random.uniform(0, 5))
    summary = write_summary(active_prompts, results, stopped=stopped)
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())



