[English](README.md) | [中文](README.zh-CN.md)

# SCOPE Image Orchestrator

A Codex skill for structured image-generation orchestration.

It converts image requests into explicit constraints, route-aware optimization,
generation calls, optional visual checks, targeted repair loops, and reproducible artifacts.

This is an independent practical adaptation inspired by the SCOPE paper.

## Highlights

- Structured prompt decomposition.
- Route-aware prompt optimization.
- Multi-provider API adapter layer.
- Optional reference-image analysis.
- Optional visual audit and targeted repair loop.
- Batch and dry-run tooling for repeatable tests.

## Paper

- **SCOPE: Structured Decomposition and Conditional Skill Orchestration for Complex Image Generation**
- arXiv: https://arxiv.org/abs/2605.08043
- HTML: https://arxiv.org/html/2605.08043v1
- Project: https://nopnor.github.io/SCOPE/

## Quick start

Copy the environment template and fill in your own endpoint and key:

```bash
cp references/.env.example .env
```

Dry-run without calling an image API:

```bash
python scripts/generate_single_v2.py \
  --env-file .env \
  --user-prompt "your image request" \
  --out-dir scope_runs/example \
  --dry-run
```

Generate one image:

```bash
python scripts/generate_single_v2.py \
  --env-file .env \
  --user-prompt "your image request" \
  --out-dir scope_runs/example
```

List command helpers:

```bash
python scripts/scope_commands.py commands
```

## Configuration

Use `references/.env.example` as the public configuration template.

Supported adapter families:

- OpenAI-compatible text, vision, and image APIs.
- Google Gemini-compatible text, vision, and image APIs.
- Generic JSON wrapper endpoints.

For detailed request shapes, see:

- `references/api-providers.md`
- `references/provider-config.example.json`

### Quick model routing for this batch workflow

For **vision auditing/review** and **text-optimizer/repair** you can switch models in the same run:

```bash
# Gemini 3.5
python scripts/scope_commands.py audit-run \
  --env-file <vision.env> \
  --image-root scope_runs/<batch> \
  --vision-models "gemini-3.5-flash" \
  --limit 6 --out-file vision-gemini.json

# Claude-family (OpenAI-compatible endpoint)
python scripts/audit_generated_images_with_vision.py \
  --env-file <vision.env> \
  --image-root scope_runs/<batch> \
  --vision-models "claude-3.5-sonnet" \
  --limit 6 --out-file vision-claude.json

# GPT-family / Grok-family
python scripts/audit_generated_images_with_vision.py \
  --env-file <vision.env> \
  --image-root scope_runs/<batch> \
  --vision-models "gpt-5.5,gpt-4.20-auto,deepseek-ai/DeepSeek-V3.1,grok-4.3" \
  --limit 6 --out-file vision-gpt.json
```

## Presets

The unified preset library is:

```text
references/scope-preset-library.json
```

Preset ideas are distilled from public prompt examples and rewritten into compact
route-level controls. The repository is not intended to redistribute verbatim
third-party prompt bodies.

Current route families include:

```text
portrait, magazine, poster, cosplay, interior, product, bathroom,
idiom_cinema, documentary, strategy_overhead, anime_cel
```

## Validation

Run the offline release check before publishing changes:

```bash
python scripts/run_release_checks.py --out-dir ./tmp/scope_release_checks
```

This check is local only and does not call real APIs.

## Output artifacts

```text
scope_runs/<task>/
  user_request.txt
  route.json
  optimized_prompt.json
  generation_prompt.txt
  image_result.attempt_N.json
  visual_audit.attempt_N.json
  image.png
  final_summary.json
```

## Community

Friendly support: Linux Do Community

QQ group: `1107570994`

<img src="docs/assets/qq-group.png" alt="QQ group 1107570994" width="360">
