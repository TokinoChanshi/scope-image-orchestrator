#!/usr/bin/env python3
"""Run the v2 SCOPE route regression matrix.

This is the reusable version of the 42-case smoke/regression batch used when
prompt presets, external prompt libraries, model routing, or endpoint reliability
logic changes.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent
WORKSPACE_ROOT = SKILL_ROOT.parent.parent.parent
RUNNER = SCRIPT_DIR / "generate_single_v2.py"

COSPLAY_BOOST = (
    "Practical mixed light, natural lens imperfection, subtle hand asymmetry, "
    "realistic fabric drape and slight body weight shift, micro imperfections in skin, "
    "natural anatomy, visible cloth seams, embroidery, and metal reflections; no CGI look."
)

CASES: list[tuple[str, str, str]] = [
    ("portrait", "01_europe_casual", "Photorealistic 2:3 editorial lifestyle portrait, adult woman in a city hotel room, 2:3 vertical, window light, real skin texture with subtle pores, soft asymmetry, natural imperfect pose, practical setting details."),
    ("portrait", "02_afro_boss", "Photorealistic 2:3 editorial portrait of an adult Black woman in a modern coffee corner, natural curls, 85mm candid framing, visible pores, slight under-eye shadow, one hand holding a cup, relaxed posture, real fabric texture."),
    ("portrait", "03_urban_blond", "Photorealistic 2:3 urban evening portrait, adult blonde woman with angular features, windy hair, 50mm lens, warm street glow, realistic skin texture and natural hand placement."),
    ("portrait", "04_southasian_prof", "Photorealistic 2:3 editorial portrait of an adult South-Asian woman in beige linen top, studio corner, neutral background, realistic shoulder/neck weight, subtle skin variation, candid practical mood."),
    ("portrait", "05_garden_redhead", "Photorealistic 2:3 garden portrait, adult woman with copper red hair and freckles on a garden path, stone path and foliage anchors, soft film grain, lifelike skin microvariation."),
    ("portrait", "06_latina_evening", "Photorealistic 2:3 compact apartment portrait, adult Latina woman with messy bun and thin-frame glasses, soft lamp light, candid half-body composition, visible fabric folds and natural hand occlusion."),
    ("magazine", "01_luxe_cover", "Photorealistic high-fashion 2:3 magazine cover. Masthead LUXE, three lines: Private Interview, New Silhouette, Modern Rhythm. Adult model with cream ivory knit, city evening mood, clean editorial grid, head overlaps masthead, readable serif text."),
    ("magazine", "02_noir_cover", "Photorealistic high-fashion 2:3 noir editorial cover with minimal palette, short clean cover lines, 2 short subtitles, one circular badge, subject angled to side of masthead, strong print-like contrast."),
    ("magazine", "03_linen_cover", "Photorealistic 2:3 linen couture magazine cover, adult model in ivory coat, elegant serif masthead LINEA, short left-side cover lines, small issue badge, controlled text spacing."),
    ("magazine", "04_garden_issue", "Photorealistic 2:3 fashion cover in emerald botanical scene. Adult model in tailored green-gold coat, clean editorial structure, 3 readable lines only, one issue badge, crisp text spacing."),
    ("magazine", "05_minimal_issue", "Photorealistic 2:3 minimal monochrome fashion cover. Cool silver outfit, large masthead MINIMAL, short three-line editorial copy, circular issue mark, strong composition and readable spacing."),
    ("magazine", "06_hotel_issue", "Photorealistic 2:3 boutique-hotel inspired fashion cover with linen suit, woven wood stone interior, masthead HOTEL, short issue copy, calm high-end editorial layout and clean typography."),
    ("poster", "01_neon_protocol", "Cinematic 2:3 movie poster, female protagonist in rainy neon alley, practical rain slick light, readable title in lower third, one short tagline, minimal credits."),
    ("poster", "02_desert_signal", "Cinematic sci-fi 2:3 poster, engineer holding flare at desert radio mast, dusty wind atmosphere, practical light, title and short subtitle with readable credit strip."),
    ("poster", "03_ocean_archive", "Cinematic 2:3 underwater archive key art, diver scientist in glass capsule, emotional gaze, wet reflective surfaces, clear title + short subtitle, clean credits strip."),
    ("poster", "04_winter_orbit", "Cinematic 2:3 astronaut at snowy launch site, breath fog, aurora background, title across lower third, short genre note, compact credits panel."),
    ("poster", "05_red_station", "Cinematic noir 2:3 spy poster, coat silhouette under red station lamps, suitcase in hand, title + short subtitle + compact credits, clear readable layout. Keep one hero focus and practical depth with one hard shadow source."),
    ("poster", "06_forest_gate", "Cinematic 2:3 fantasy poster, ranger and lantern at ancient gate, layered fog and trees, one title and tiny credits block."),
    ("cosplay", "01_pyro_hero", "Photorealistic vertical 2:3 live-action cosplay poster, adult cosplayer inspired by a crimson shrine flame heroine: dark twin tails, plum ornaments, red-black fantasy costume, lantern prop, metal trim and silk edges, practical night street background. Real human face, lifelike eyes, subtle pores, realistic hair strands and jawline. Costume translates into premium real materials with seams, weight, embroidery, and believable tension. " + COSPLAY_BOOST),
    ("cosplay", "02_bow_archer", "Photorealistic vertical 2:3 live-action character poster, adult cosplayer inspired by a blue archer heroine: long navy hair, crescent silver pin, teal cloak, carved bow, carved fabric and leather bracers, mountain shrine dawn. Natural hero stance and shoulder-forward body balance. Real human face and skin microdetail. " + COSPLAY_BOOST),
    ("cosplay", "03_cyber_star", "Photorealistic vertical 2:3 live-action cyber idol cosplay with translucent visor, stage utility belt, backstage console lights and practical LED sources. Realistic microphone prop, reflective vinyl jacket, one hero action with natural hand asymmetry and body weight shift. Adult model with short hair, realistic skin texture and subtle jawline asymmetry. " + COSPLAY_BOOST),
    ("cosplay", "04_forest_healer", "Photorealistic vertical 2:3 live-action fantasy healer cosplay: green braided hair, herb pouch, linen cloak, wooden staff, mossy ruin background, natural key light shafts. Real fabric seams, weave, embroidery and body-weight shift. " + COSPLAY_BOOST),
    ("cosplay", "05_crimson_knight", "Photorealistic vertical 2:3 live-action crimson knight cosplay, mature male model in ornate red and silver armor with visible stitch, leather, and steel edges; short dark hair and sharp jawline. One disciplined ready pose with natural shoulder imbalance and subtle knee bend. " + COSPLAY_BOOST),
    ("cosplay", "06_moon_witch", "Photorealistic vertical 2:3 live-action moon witch cosplay with velvet cloak, crystal lantern, silver crescent hairpin, observatory night scenery and practical candle/cool lamp mix. Real pores, eyelashes and hair strands; realistic cloth folds and shoulder line."),
    ("interior", "01_oriental_living", "Photorealistic architectural interior 16:9 modern oriental living room, eye-height 24mm, beige sofa, walnut wall panels, straight verticals, realistic materials and practical daylight."),
    ("interior", "02_hotel_suite", "Photorealistic boutique hotel bedroom, linen bed, stone headboard, clean circulation path, doorway perspective, walnut tableware, realistic fabric weave and practical lamp glow, true room scale and physical materials."),
    ("interior", "03_japanese_bath", "Photorealistic compact Japanese spa bathroom, cream tiles, glass shower edge, wood slat wall, steam traces, hidden lighting, realistic towel and wet-dry separation."),
    ("interior", "04_gallery_kitchen", "Photorealistic open gallery kitchen, travertine island, oak cabinetry, brushed metal fixtures, pendant lights, breakfast stools, plants, realistic dishware and practical geometry."),
    ("interior", "05_creative_office", "Photorealistic creative office at eye-level, long oak desk and ergonomic chairs, shelves, plants, acoustic panels, warm desk lamps, tidy cable management, rugged monitor scale, realistic fabric texture."),
    ("interior", "06_dark_lounge", "Photorealistic luxury lounge at night, stone floor, amber backlight, bar counter, brass details, reflective geometry, clear circulation and realistic material scale."),
    ("product", "01_perfume", "Photorealistic commercial still life of a luxury perfume bottle on matte cream stone pedestal, chrome cap, transparent glass, controlled reflections, clean negative space."),
    ("product", "02_watch_macro", "Photorealistic macro watch product photo, brushed steel case and leather strap on dark neutral textile, precise dial details and crisp macro edges."),
    ("product", "03_iced_tea", "Photorealistic beverage hero of bottled iced tea with condensation and ice, clean label blank, side lighting, practical table surface."),
    ("product", "04_white_sneaker", "Photorealistic commercial sneaker still life, white leather shoe on concrete, stitching and sole detail, soft shadow and realistic reflections."),
    ("product", "05_matcha_dessert", "Photorealistic matcha dessert food still life on handmade ceramic, powder texture and crumbs, linen napkin, natural garnish and controlled composition."),
    ("product", "06_headphones", "Photorealistic commercial still life of matte black headphones on acrylic stand, brushed metal highlights, clean negative space and controlled contrast."),
    ("bathroom", "01_hotel_bathroom_mirror", "Photorealistic 9:16 real smartphone bathroom mirror selfie in a boutique hotel bathroom, black phone partly covers one cheek, uneven handheld mirror crop, warm vanity bulbs, cream ceramic tiles, glass shower edge, folded towels, chrome faucet, skincare bottles, natural skin texture."),
    ("bathroom", "02_white_shirt_selfie", "Photorealistic 9:16 mirror selfie in a hotel bathroom, messy bun, thin-frame glasses, oversized white Oxford shirt with rolled sleeves, slight 26mm phone-lens edge distortion, realistic shirt hem and collar."),
    ("bathroom", "03_private_lifestyle", "Photorealistic 9:16 mirror selfie in compact apartment bathroom, natural side angle, half-body framing, sink and folded towels in mirror, mild grain and realistic indoor reflections."),
    ("bathroom", "04_partner_pov", "Photorealistic 9:16 girlfriend POV bathroom mirror selfie, black phone partly covering one cheek, soft private-room mood, minimal makeup, realistic pores and hair strands, natural mirror highlights."),
    ("bathroom", "05_no_showy_text", "Photorealistic 9:16 mirror selfie with private lifestyle mood, folded towel and skincare bottles visible, subtle realistic wetness-free skin, candid pose, no cover-style typography."),
    ("bathroom", "06_soft_bathroom", "Photorealistic 9:16 private bathroom mirror selfie, natural cross-leg lean and hand placement, warm neutral interior light, chrome faucet and stone tile edges, imperfect smartphone framing."),
]


def split_csv(value: str | None) -> set[str]:
    return {x.strip() for x in (value or "").replace(";", ",").split(",") if x.strip()}


def run_one(args: argparse.Namespace, category: str, code: str, prompt: str, out_root: Path) -> dict[str, Any]:
    out_dir = out_root / category / code
    out_dir.mkdir(parents=True, exist_ok=True)
    final_summary = out_dir / "final_summary.json"
    if args.resume and final_summary.exists():
        try:
            cached = json.loads(final_summary.read_text(encoding="utf-8"))
            if cached.get("final_overall") == "pass":
                return {"case": code, "category": category, "out_dir": str(out_dir), "returncode": 0, "elapsed_sec": 0, "cached": True, "final_summary": cached}
        except Exception:
            pass

    cmd = [
        sys.executable,
        str(RUNNER),
        "--user-prompt",
        prompt,
        "--env-file",
        str(args.env_file),
        "--llm-env-file",
        str(args.llm_env_file or args.env_file),
        "--out-dir",
        str(out_dir),
        "--route",
        category,
        "--llm-model",
        args.llm_model,
        "--image-model",
        args.image_model,
        "--max-generation-attempts",
        str(args.max_generation_attempts),
        "--image-retries",
        str(args.image_retries),
        "--timeout",
        str(args.timeout),
        "--max-prompt-chars",
        str(args.max_prompt_chars),
        "--response-formats",
        args.response_formats,
    ]
    if args.vision_env_file and not args.skip_vision:
        cmd.extend(["--vision-env-file", str(args.vision_env_file), "--vision-model", args.vision_model])

    started = time.time()
    proc = subprocess.run(cmd, cwd=str(WORKSPACE_ROOT), text=True, capture_output=True, encoding="utf-8", errors="replace")
    elapsed = round(time.time() - started, 1)
    (out_dir / "run.log").write_text((proc.stdout or "") + "\n" + (proc.stderr or ""), encoding="utf-8")

    summary: dict[str, Any] = {"case": code, "category": category, "out_dir": str(out_dir), "returncode": proc.returncode, "elapsed_sec": elapsed}
    if final_summary.exists():
        try:
            summary["final_summary"] = json.loads(final_summary.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            summary["final_summary_error"] = repr(exc)
    if proc.returncode != 0:
        summary["stderr_tail"] = (proc.stderr or "")[-2000:]
    return summary


def write_batch_summary(out_root: Path, results: list[dict[str, Any]]) -> dict[str, Any]:
    categories = [c for c in dict.fromkeys(category for category, _, _ in CASES)]
    by_category: dict[str, dict[str, Any]] = {cat: {"requested": 0, "passed": 0, "results": []} for cat in categories}
    requested_pairs = {(r["category"], r["case"]) for r in results}
    for category, code, _ in CASES:
        if (category, code) not in requested_pairs:
            continue
        by_category[category]["requested"] += 1
        by_category[category]["results"].append(str(out_root / category / code))
    for entry in results:
        fs = entry.get("final_summary") or {}
        if isinstance(fs, dict) and fs.get("final_overall") == "pass":
            by_category[entry["category"]]["passed"] += 1

    summary = {"out_root": str(out_root), "total_cases": len(results), "categories": categories, "by_category": by_category, "results": results}
    (out_root / "batch_final_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run SCOPE v2 route regression batch.")
    parser.add_argument("--env-file", required=True, type=Path, help="Image provider env file.")
    parser.add_argument("--llm-env-file", type=Path, help="Prompt optimizer env. Defaults to --env-file.")
    parser.add_argument("--vision-env-file", type=Path, help="Vision verifier env.")
    parser.add_argument("--out-dir", type=Path, default=WORKSPACE_ROOT / "scope_runs" / datetime.now().strftime("scope_v2_regression_%Y%m%d_%H%M%S"))
    parser.add_argument("--llm-model", default="gpt-5.5")
    parser.add_argument("--vision-model", default="grok-4.3")
    parser.add_argument("--image-model", default="gpt-image-2")
    parser.add_argument("--max-generation-attempts", type=int, default=4)
    parser.add_argument("--image-retries", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=340)
    parser.add_argument("--max-prompt-chars", type=int, default=840)
    parser.add_argument("--response-formats", default="url,b64_json")
    parser.add_argument("--only-categories", help="Comma-separated categories to run.")
    parser.add_argument("--only-cases", help="Comma-separated case codes to run.")
    parser.add_argument("--max-cases", type=int, help="Run only the first N selected cases.")
    parser.add_argument("--skip-vision", action="store_true")
    parser.add_argument("--resume", action="store_true", help="Skip existing cases whose final_summary is pass.")
    parser.add_argument("--dry-run", action="store_true", help="Write selected_cases.json and exit without API calls.")
    parser.add_argument("--delay", type=float, default=3.8)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.env_file.exists():
        raise SystemExit(f"missing --env-file: {args.env_file}")
    args.out_dir.mkdir(parents=True, exist_ok=True)

    cats = split_csv(args.only_categories)
    cases = split_csv(args.only_cases)
    selected = [(cat, code, prompt) for cat, code, prompt in CASES if (not cats or cat in cats) and (not cases or code in cases)]
    if args.max_cases:
        selected = selected[: args.max_cases]

    print(f"[INFO] out: {args.out_dir}")
    print(f"[INFO] image env: {args.env_file}")
    print(f"[INFO] llm env: {args.llm_env_file or args.env_file}")
    print(f"[INFO] vision env: {args.vision_env_file if args.vision_env_file and not args.skip_vision else 'disabled'}")
    print(f"[INFO] selected: {len(selected)}")
    if args.dry_run:
        payload = {"out_root": str(args.out_dir), "selected": [{"category": c, "case": k, "prompt": p} for c, k, p in selected]}
        (args.out_dir / "selected_cases.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print("[DRY-RUN] wrote", args.out_dir / "selected_cases.json")
        return 0

    results: list[dict[str, Any]] = []
    for idx, (category, code, prompt) in enumerate(selected, start=1):
        print(f"[RUN] {idx:02d}/{len(selected)} {category}/{code}", flush=True)
        results.append(run_one(args, category, code, prompt, args.out_dir))
        write_batch_summary(args.out_dir, results)
        if idx < len(selected):
            time.sleep(args.delay)

    summary = write_batch_summary(args.out_dir, results)
    passed = sum(1 for r in results if (r.get("final_summary") or {}).get("final_overall") == "pass")
    print(f"[DONE] pass {passed}/{len(results)}")
    print(args.out_dir / "batch_final_summary.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
