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

## Validation

```bash
python scripts/run_release_checks.py --out-dir ./tmp/scope_release_checks
python scripts/run_release_checks.py --out-dir ./tmp/scope_release_checks --skip-dry-run
```

The release gate is offline by default and does not call real APIs.

## Related docs

- `SKILL.md`
- `docs/gallery.md`
- `references/release-testing.md`

## Community

Friendly support: Linux Do Community

QQ group: `1107570994`

<img src="docs/assets/qq-group.png" alt="QQ group 1107570994" width="360">
