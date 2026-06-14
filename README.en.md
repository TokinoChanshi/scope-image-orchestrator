[中文（Primary）](README.md) | [English](README.en.md) | [中文镜像](README.zh-CN.md)

# SCOPE Image Orchestrator

An open-source Codex skill for structured image-generation orchestration.

This repository turns a free-form image request into a reproducible workflow:

```text
request
  -> semantic decomposition
  -> route selection
  -> preset / theme-pack injection
  -> LLM prompt optimization
  -> image generation
  -> optional visual audit
  -> targeted repair / rerun
  -> persisted artifacts
```

It is a practical engineering adaptation inspired by the **SCOPE** paper, not the authors' official implementation.

## What it is for

- Portrait, magazine, poster, cosplay, interior, product, bathroom selfie, and similar routes
- Batch generation and regression testing
- Swappable text / vision / image models
- Repair-oriented workflows instead of one-shot prompting only

## Highlights

- Structured prompt decomposition
- Route-aware prompt optimization
- Multi-provider adapter layer
- Optional reference-image analysis
- Optional visual audit and targeted repair
- Batch and regression tooling

## Paper

- **SCOPE: Structured Decomposition and Conditional Skill Orchestration for Complex Image Generation**
- arXiv: https://arxiv.org/abs/2605.08043
- HTML: https://arxiv.org/html/2605.08043v1
- Project: https://nopnor.github.io/SCOPE/

## Quick start

```bash
cp references/.env.example .env
python scripts/generate_single_v2.py --env-file .env --user-prompt "your image request" --out-dir scope_runs/example --dry-run
python scripts/generate_single_v2.py --env-file .env --user-prompt "your image request" --out-dir scope_runs/example
python scripts/scope_commands.py commands
```

## Command mode

Activation phrase:

```text
生图优化
```

Common commands:

- `帮助` / `命令`
- `查看预设`
- `查看主题包`
- `跑图 <prompt>`
- `批量跑 N 张 <prompt>`
- `参考生图 <image> <prompt>`
- `严格链路 <prompt>`
- `审核 <image_root>`
- `回归测试`
- `退出生图优化`

## Configuration

Public examples use generic `SCOPE_*` environment variables.

Supported adapter families:

- OpenAI-compatible text / vision / image
- Google Gemini text / vision / image
- Generic JSON wrapper

See:

- `references/.env.example`
- `references/api-providers.md`
- `references/provider-config.example.json`

## Preset library

Unified entry:

```text
references/scope-preset-library.json
```

Current route families:

```text
portrait, magazine, poster, cosplay, interior, product, bathroom,
idiom_cinema, documentary, strategy_overhead, anime_cel
```

Most preset ideas are distilled from public prompt examples and community practices. The library keeps route-level controls rather than redistributing verbatim third-party prompt bodies.

## Smoke test matrix (dry-run)

```bash
# 1) Image workflow smoke (single)
python scripts/generate_single_v2.py --env-file .env --user-prompt "cinematic product photo, warm indoor light" --out-dir scope_runs/smoke_image --dry-run

# 2) Video generation smoke (single route build)
python scripts/scope_commands.py video-run --env-file .env --user-prompt "high-end lifestyle montage" --out-dir scope_runs/smoke_video

# 3) Video storyboard smoke (multi-shot + candidates)
python scripts/scope_commands.py video-story --env-file .env --user-prompt "create a 60-second premium lifestyle story" --out-dir scope_runs/smoke_story --target-duration 60 --shot-duration 10 --candidate-count 3

# 4) Route-regression smoke
python scripts/run_v2_route_regression.py --env-file .env --max-cases 1 --skip-vision --dry-run --out-dir scope_runs/smoke_regression

# 5) Video one-shot parser + smoke chain
python scripts/scope_commands.py video-skill-check --env-file .env --out-dir scope_runs/smoke_video_skill_check
```

## 自然语言视频入口（建议日常）

如果你更习惯一句话描述目标时长，可以直接调用：

```bash
python scripts/run_video_skill.py \
  --env-file .env \
  --user-input "创作一个3分钟高端生活片，每10秒一个镜头，每镜3个备选" \
  --out-dir scope_runs/story_mode \
  --send
```

说明：

- 脚本会自动解析 `3分钟`、`每10秒`、`每镜3个` 等信息并映射到 `video-story` 的参数；
- 未加 `--send` 时默认干跑（`--dry-run`）；
- 你可以通过 `--candidate-count / --shot-duration / --target-duration / --route` 覆盖推断结果；
- 支持 `--interactive`、`--max-shots`、`--no-assemble` 等同 `video-story` 的常用参数。

## Related docs

- `SKILL.md`
- `docs/gallery.md`

## Community

Linux Do Community

QQ group: `1107570994`

<img src="docs/assets/qq-group.png" alt="QQ group 1107570994" width="360">
