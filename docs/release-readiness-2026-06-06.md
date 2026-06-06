# Release Readiness Notes (2026-06-06)

- Repository: `https://github.com/TokinoChanshi/scope-image-orchestrator`
- Current branch: `main`
- Latest local commit before this validation round: `456adc8`

## 1) Offline release checks

Executed:

```bash
python scripts/run_release_checks.py --out-dir C:/Users/12562/AppData/Local/Temp/scope_release_checks_distill_v3 --skip-compile
```

Result:

- `[OK] script compilation check skipped`
- `[OK] provider config validation`
- `[OK] rendered 12 provider roles`
- `[OK] sample SCOPE spec validation`
- `[OK] preset routes present: anime_cel, bathroom, cosplay, documentary, idiom_cinema, interior, magazine, portrait, poster, product, strategy_overhead`
- `[OK] adapter payload cases checked: 10`
- `[OK] response extraction cases checked: 6`
- `[OK] dry-run prompt cases checked: 11`
- `[OK] release checks passed`

## 2) Route regression (dry-run)

Executed:

```bash
python scripts/run_v2_route_regression.py --env-file ./.codex_tmp/scope_publish_chatgpt2_live.env --out-dir C:/Users/12562/AppData/Local/Temp/scope_run_v2_regression --max-cases 1 --dry-run
python scripts/run_v2_route_regression.py --env-file ./.codex_tmp/scope_publish_chatgpt2_live.env --out-dir C:/Users/12562/AppData/Local/Temp/scope_reg_new_routes_0606 --only-categories documentary,strategy_overhead,idiom_cinema,anime_cel --max-cases 8 --dry-run
```

Result:

- base matrix dry-run still works
- 8 additional dry-run regression cases were selected for the newly distilled routes:
  - `documentary`
  - `strategy_overhead`
  - `idiom_cinema`
  - `anime_cel`

## 2.5) Command-mode wrapper smoke (print-only)

Executed:

```bash
python scripts/scope_commands.py batch-run --count 2 --env-file .\.codex_tmp\scope_publish_chatgpt2_live.env --user-prompt "product packshot" --out-dir scope_runs/test_batch --print-only
python scripts/scope_commands.py strict-run --env-file .\.codex_tmp\scope_publish_chatgpt2_live.env --user-prompt "magazine cover" --out-dir scope_runs/test_strict --print-only
python scripts/scope_commands.py regression-run --env-file .\.codex_tmp\scope_publish_chatgpt2_live.env --out-dir scope_runs/test_regression --max-cases 1 --dry-run --print-only
python scripts/scope_commands.py audit-run --env-file .\.codex_tmp\scope_publish_chatgpt2_live.env --image-root scope_runs --print-only
```

Result:

- All wrappers emit expected child command lines.
- Output directory fallback to writable temporary paths works consistently (`...\\Temp\\scope_image_runs\\...`).
- No remote calls executed in these print-only smoke runs.

## 3) Prompt routing smoke with real user-style prompts

Dry-run probes using distilled prompts from the SSS0625 corpus now route as expected:

- idiom-style cinematic prompt → `idiom_cinema`
- BBC archaeology documentary prompt → `documentary`
- top-down RTS / god-view prompt → `strategy_overhead`
- cel-shaded anime character concept prompt → `anime_cel`

## 4) Real API smoke status

Executed:

```bash
python scripts/generate_single_v2.py --env-file C:/Users/12562/AppData/Local/Temp/scope_publish_image_only.env --user-prompt "BBC纪录片质感，一个考古的毛刷在土堆中发现了一个机器人，普通相机拍摄，自然光，冷色调，不要文字" --out-dir C:/Users/12562/AppData/Local/Temp/scope_live_doc_0606 --route documentary --max-generation-attempts 1 --timeout 240
python scripts/generate_single_v2.py --env-file C:/Users/12562/AppData/Local/Temp/scope_publish_image_only.env --user-prompt "虚幻引擎5光线追踪质感，PS5游戏大作，远距离上帝俯视视角的即时战略游戏，微缩视角，两个坦克攻击村庄，不要UI和界面" --out-dir C:/Users/12562/AppData/Local/Temp/scope_live_rts_0606 --route strategy_overhead --max-generation-attempts 1 --timeout 240
python scripts/generate_single_v2.py --env-file C:/Users/12562/AppData/Local/Temp/scope_publish_image_only.env --user-prompt "一个京剧中的武生，结构设计留白，不要复杂纹理，不要文字，而是赛璐璐平涂风格的日本动画风格" --out-dir C:/Users/12562/AppData/Local/Temp/scope_live_anime_0606 --route anime_cel --max-generation-attempts 1 --timeout 240
```

Result:

- `documentary` produced a usable archaeology discovery image (`image.png`) with believable brush/soil/robot storytelling on manual local review.
- `strategy_overhead` produced a usable top-down tank attack image (`image.png`) with readable terrain and no UI/HUD artifacts on manual local review.
- `anime_cel` produced a usable cel-shaded Beijing-opera warrior image (`image.png`) and the built-in visual audit could actually inspect it, returning `route_fit=7`, `composition=8`, and one targeted costume/headgear refinement note.
- The bundled vision-audit chain is still inconsistent in this environment: it returned `can_see_image=false` for the documentary and strategy smokes, while the anime smoke was inspectable. Final judgment therefore still relied on direct local image inspection plus available audit output.

## 5) Open-source publishing constraints kept

- No private endpoint URLs or API keys are committed.
- Only public model names and public request-shape compatibility are documented.
- Prompt source is explicitly documented as distilled from public examples plus user-supplied prompt corpora abstractions; raw third-party prompt bodies are not redistributed.
