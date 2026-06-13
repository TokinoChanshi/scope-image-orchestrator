---
name: scope-image-orchestrator
description: Use when an image-generation workflow needs SCOPE-style semantic decomposition, prompt optimization, API routing, visual verification, repair loops, batch regression, or when the user starts command mode with 生图优化.
---

# SCOPE Image Orchestrator

## Goal

SCOPE Image Orchestrator is an open-source friendly Codex skill for image-generation orchestration. It applies the SCOPE paper's core idea: preserve important user requirements as explicit semantic commitments, then keep generation, verification, and repair aligned to those commitments.

This skill is model-agnostic and endpoint-agnostic, but API wire formats must be explicit. Public examples should use official OpenAI and Google Gemini request shapes and should name models only, not private channels, relays, vendors, or deployment sources. Configure endpoints through environment variables or a task-local config file, and never commit real keys.

## Command Mode

`生图优化` is the human-facing activation command. When the user says it, enter command mode for the current thread. After that, short follow-up messages should be interpreted as image commands until the user says `退出生图优化`, `停止生图优化`, or clearly switches topics.

Command mode is natural-language first: infer the prompt, count, route, reference image, env files, and output directory from the current thread when safe. Ask only for missing critical items, such as an env file or reference image path.

| Command | Meaning | Default implementation |
| --- | --- | --- |
| `帮助` / `命令` | Show available command-mode aliases. | `python scripts/scope_commands.py commands` |
| `查看预设` | List all route presets from the unified library. | `python scripts/scope_commands.py list-presets --detail` |
| `查看预设 bathroom` | List one route preset. | `python scripts/scope_commands.py list-presets --route bathroom --detail` |
| `查看主题包` | List all image theme packs from the unified library. | `python scripts/scope_commands.py list-theme-packs --detail` |
| `查看主题包 mecha_tokusatsu` | List one image theme pack. | `python scripts/scope_commands.py list-theme-packs --theme-pack mecha_tokusatsu --detail` |
| `跑图 <prompt>` / `单张跑 <prompt>` | Generate one image with the v2 router. | `python scripts/generate_single_v2.py --env-file <env> --user-prompt "<prompt>" --out-dir <out>` |
| `批量跑 N 张 <prompt>` | Run the same prompt N times; count comes from the user. | `python scripts/scope_commands.py batch-run --count N --env-file <env> --user-prompt "<prompt>" --out-dir <out>` |
| `参考生图 <image> <prompt>` | Generate using a reference image for style/composition/identity/product guidance. | `python scripts/scope_commands.py reference-run --reference-image <image> --env-file <env> --user-prompt "<prompt>" --out-dir <out>` |
| `严格链路 <prompt>` | Use the paper-style decomposition/synthesis/coverage chain. | Use the strict SCOPE runner for decomposition, synthesis, coverage verification, generation, and repair. |
| `回归测试` / `预设回归` | Run route regression after preset or model changes. | `python scripts/run_v2_route_regression.py --env-file <env> --out-dir <out>` |
| `审核 <image_root>` | Run visual audit over generated images. | `python scripts/audit_generated_images_with_vision.py --env-file <vision.env> --image-root <image_root> --out-file <out.json>` |
| `三模型对比 <image_root> [--vision-models]` | Run one root against Gemini/Claude/GPT model list (comma-separated). | `python scripts/audit_generated_images_with_vision.py --env-file <vision.env> --image-root <image_root> --vision-models "gemini-3.5-flash,claude-3.5-sonnet,gpt-5.5" --out-file <out.json>` |

| `干跑 <command>` | Produce route/prompt/plan without image API spending. | Add `--dry-run`; for batch wrappers also add `--print-only` if only commands are needed. |
| `重跑失败` | Resume or rerun failed batch items. | Prefer `--resume` for regression or rerun failed item directories only. |
| `退出生图优化` | Leave command mode. | Stop interpreting short messages as image commands. |

Reference-image behavior:

- By default, `参考生图` uses a vision model to analyze the reference image, writes `reference_image.json`, injects a compact reference brief into the prompt, then uses the normal image generator. This works even when the image API is text-to-image only.
- For direct official reference-image calls, use `SCOPE_IMAGE_FORMAT=openai-responses-image` or `SCOPE_IMAGE_FORMAT=google-gemini-image`; the runner will attach the image using `input_image` or Gemini `inlineData`.
- The OpenAI Images API reference workflow uses `/v1/images/edits` multipart. Treat it as a separate implementation path, not the default JSON generation path.
- Use `--reference-mode style|composition|identity|character|product|auto` to control what the reference should influence.

## Paper Basis

This is a practical implementation inspired by the SCOPE paper, not an official reproduction of the authors' code.

Paper reference:

- **Title:** SCOPE: Structured Decomposition and Conditional Skill Orchestration for Complex Image Generation.
- **arXiv:** https://arxiv.org/abs/2605.08043
- **Project page:** https://nopnor.github.io/SCOPE/

Key ideas adapted here:

1. **Semantic commitments:** represent user requirements as persistent objects, attributes, relations, layout rules, text requirements, and factual constraints.
2. **Object-centric decomposition:** split a request into entities, constraints, and unknowns before prompting an image model.
3. **Conditional correction:** resolve only the missing or ambiguous pieces that matter for the current generation.
4. **Prompt synthesis from commitments:** synthesize a compact production prompt from the structured specification instead of relying on a flat prompt alone.
5. **Itemized verification:** verify generated outputs entity-by-entity and constraint-by-constraint; do not rely only on a holistic score.
6. **Targeted repair:** map failures to retrieval, prompt rewrite, regeneration, or image editing.
7. **Regression evaluation:** test routes and presets across multiple prompt families to detect prompt-library or model-routing regressions.

Model names mentioned by the original paper and this implementation may include `text-model`, `image-model`, `vision-model`, `text-model`, `image-model`, and `vision-model`. Public docs should list model names only and avoid private endpoint or relay names.

Read `references/scope-paper.md` for a longer paper-to-implementation mapping.

## Preset Library Notice

`references/scope-preset-library.json` is the single preset entrypoint. It contains runtime route presets, optimizer guides, and distilled prompt-pattern notes.

Most preset ideas were derived from public internet prompt libraries and prompt examples, then restructured, filtered, rewritten, and distilled into route-level controls. The preset library is not intended to be a verbatim copy of third-party prompts. Keep only compact patterns, route hints, material/camera/layout controls, negative constraints, and source/count metadata.

Current routes:

```text
portrait, magazine, poster, cosplay, interior, product, bathroom,
idiom_cinema, documentary, strategy_overhead, anime_cel
```

## Quick Workflow

1. **Create a run directory**, e.g. `scope_runs/<short-task-name>/`.
2. **Decompose the request** into:
   - `entities`: people, characters, objects, text blocks, places, styles, logos, UI elements.
   - `constraints`: atomic attribute, relation, layout, style, text, or factual requirements.
   - `unknowns`: missing facts or reference details tied to an entity, constraint, or prompt.
3. **Resolve unknowns only when needed** using retrieval, reasoning, or a vision/text model.
4. **Route the request** to a preset family: portrait, magazine, poster, cosplay, interior, product, bathroom, idiom_cinema, documentary, strategy_overhead, or anime_cel.
5. **Optimize the prompt** with a text model such as `text-model` or `vision-model`.
6. **Generate the image** with an image model such as `image-model`.
7. **Verify item by item** with a vision-capable model such as `vision-model`.
8. **Repair targeted failures** through prompt rewrite, regeneration, or image editing when available.
9. **Stop** when critical requirements pass or when additional attempts are unlikely to help.

## Model Roles

| Role | Example model names | Notes |
| --- | --- | --- |
| `decomposer` | `text-model`, `vision-model` | Convert user request into structured commitments. |
| `prompt_optimizer` | `text-model`, `vision-model` | Turn route + commitments into a compact generation prompt. |
| `retrieval_corrector` | `vision-model` | Clean factual/reference details when retrieval is available. |
| `image_generator` | `image-model`, `image-model` | Produce the image. |
| `verifier` | `vision-model`, `vision-model` | Inspect generated outputs item by item. |
| `repair_planner` | `text-model`, `vision-model` | Convert failures into prompt repairs or rerun strategy. |

## Environment Contract

Prefer generic `SCOPE_*` variables in open-source examples. Set the adapter format first:

```env
SCOPE_LLM_FORMAT=openai-responses
SCOPE_VISION_FORMAT=openai-responses
SCOPE_IMAGE_FORMAT=openai-images
```

Supported formats:

```text
openai-chat             -> OpenAI Chat Completions
openai-responses        -> OpenAI Responses
google-gemini           -> Gemini generateContent
openai-images           -> OpenAI Images API
openai-responses-image  -> OpenAI Responses image_generation tool
google-gemini-image     -> Gemini native image generation
generic-text-json       -> generic JSON text wrapper
generic-vision-json     -> generic JSON vision wrapper
generic-image-json      -> generic JSON image wrapper
openai-images-legacy    -> legacy OpenAI-compatible JSON image endpoints
```

Default OpenAI-style example:

```env
SCOPE_LLM_BASE_URL=https://api.openai.com/v1
SCOPE_LLM_API_KEY=your_key
SCOPE_LLM_MODEL=text-model

SCOPE_VISION_BASE_URL=https://api.openai.com/v1
SCOPE_VISION_API_KEY=your_key
SCOPE_VISION_MODEL=text-model

SCOPE_IMAGE_BASE_URL=https://api.openai.com/v1
SCOPE_IMAGE_API_KEY=your_key
SCOPE_IMAGE_MODEL=image-model
```

Gemini-style example:

```env
SCOPE_LLM_FORMAT=google-gemini
SCOPE_VISION_FORMAT=google-gemini
SCOPE_IMAGE_FORMAT=google-gemini-image
SCOPE_GOOGLE_API_KEY_AUTH=header
SCOPE_LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta
SCOPE_VISION_BASE_URL=https://generativelanguage.googleapis.com/v1beta
SCOPE_IMAGE_BASE_URL=https://generativelanguage.googleapis.com/v1beta
```

Read `references/api-providers.md` for exact request/response shapes.

Use generic adapters when the user has a custom wrapper endpoint:

```env
SCOPE_LLM_FORMAT=generic-text-json
SCOPE_LLM_ENDPOINT_URL=https://example.com/text
SCOPE_IMAGE_FORMAT=generic-image-json
SCOPE_IMAGE_ENDPOINT_URL=https://example.com/image
SCOPE_GENERIC_AUTH_MODE=bearer
```

Use `openai-images-legacy` when the user needs the previous image API format:

```env
SCOPE_LLM_FORMAT=openai-chat
SCOPE_VISION_FORMAT=openai-chat
SCOPE_IMAGE_FORMAT=openai-images-legacy
SCOPE_IMAGE_GENERATIONS_URL=https://example.com/v1/images/generations
SCOPE_RESPONSE_FORMATS=b64_json,url,b64_json,url
```

Legacy direct reference fields are allowed only when explicitly configured:

```env
SCOPE_SEND_REFERENCE_IMAGE=1
SCOPE_REFERENCE_IMAGE_FIELD=images
```

Do not commit real env files or generated private outputs.

## Output Artifacts

A serious run should persist compact artifacts:

```text
scope_runs/<task>/
  user_request.txt
  route.json
  optimized_prompt.json
  generation_prompt.txt
  generation_prompt.attempt_N.txt
  image_result.attempt_N.json
  visual_audit.attempt_N.json
  reference_image.json
  image.png
  final_summary.json
```

## Practical Commands

Dry-run a single request:

```bash
python scripts/generate_single_v2.py --env-file <env> --user-prompt "生活方式服饰室内场景室内生活方式" --out-dir scope_runs/single_bathroom --dry-run
```

Run one request with optimizer and visual audit:

```bash
python scripts/generate_single_v2.py --env-file <image.env> --llm-env-file <llm.env> --vision-env-file <vision.env> --llm-model text-model --vision-model vision-model --image-model image-model --user-prompt "cinematic poster concept" --out-dir scope_runs/single_poster --max-generation-attempts 2
```

Run a prompt multiple times:

```bash
python scripts/scope_commands.py batch-run --count 6 --env-file <image.env> --user-prompt "commercial product image" --out-dir scope_runs/batch_product
```

List presets:

```bash
python scripts/scope_commands.py list-presets --detail
```

## Validation

When changing presets, model routing, or retry logic:

```bash
python scripts/run_v2_route_regression.py --env-file <image.env> --llm-env-file <llm.env> --vision-env-file <vision.env> --out-dir scope_runs/scope_v2_regression
```

For quick smoke tests:

```bash
python scripts/run_v2_route_regression.py --env-file <image.env> --max-cases 3 --skip-vision --dry-run
```

Before publishing or changing API adapters, run the offline release gate:

```bash
python scripts/run_release_checks.py --out-dir tmp/scope_release_checks
```

Use the faster adapter/schema-only variant during iterative edits:

```bash
python scripts/run_release_checks.py --out-dir tmp/scope_release_checks --skip-dry-run
```

Release cases and checklist live in `references/release-test-cases.json` and `references/release-testing.md`.

