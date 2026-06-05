[English](README.md) | [简体中文](README.zh-CN.md)

# SCOPE Image Orchestrator

A Codex skill for SCOPE-style image generation orchestration.

It turns an image request into structured semantic commitments, optimizes the prompt, calls an image model, audits the result with a vision model, and repairs failures through targeted reruns.

> This is an independent practical adaptation inspired by the SCOPE paper. It is not the official implementation.

## Paper

- **SCOPE: Structured Decomposition and Conditional Skill Orchestration for Complex Image Generation**
- arXiv: https://arxiv.org/abs/2605.08043
- HTML: https://arxiv.org/html/2605.08043v1
- Project: https://nopnor.github.io/SCOPE/

See `references/scope-paper.md` for the paper-to-implementation mapping.

## What it does

```text
user request
-> route detection
-> semantic decomposition / prompt optimization
-> image generation
-> visual audit
-> targeted repair
-> reproducible artifacts
```

The design keeps requirements explicit instead of hiding everything inside one long prompt.

## Generated samples

See the generated sample gallery:

- [Sample gallery](docs/gallery.md)

Preview:

| Poster | Product | Interior |
| --- | --- | --- |
| ![poster sample](docs/assets/gallery/poster-neon-protocol.jpg) | ![product sample](docs/assets/gallery/product-perfume.jpg) | ![interior sample](docs/assets/gallery/interior-oriental-living.jpg) |

## Command mode

Start command mode with:

```text
生图优化
```

Then use short commands:

```text
查看预设
查看预设 bathroom
跑图 <prompt>
单张跑 <prompt>
批量跑 N 张 <prompt>
参考生图 <image> <prompt>
严格链路 <prompt>
回归测试
审核 <image_root>
干跑 <command>
重跑失败
退出生图优化
```

Helper command list:

```bash
python scripts/scope_commands.py commands
```

## Models and API formats

Open-source docs name model strings only. The workflow is endpoint-agnostic, but
wire formats are explicit.

Supported public adapters:

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
openai-images-legacy    -> previous OpenAI-compatible image JSON with response_format
```

Typical roles:

| Role | Example model names |
| --- | --- |
| Prompt optimization / decomposition | `gpt-5.5`, `grok-4.3` |
| Image generation | `gpt-image-2`, `Nano Banana Pro` |
| Vision audit / reference analysis | `grok-4.3`, `Gemini 3-Pro` |

## Environment

Copy `references/.env.example` to a local file and fill your own endpoints and keys.

```env
SCOPE_LLM_FORMAT=openai-responses
SCOPE_VISION_FORMAT=openai-responses
SCOPE_IMAGE_FORMAT=openai-images

SCOPE_LLM_BASE_URL=https://api.openai.com/v1
SCOPE_LLM_API_KEY=your_key
SCOPE_LLM_MODEL=gpt-5.5

SCOPE_VISION_BASE_URL=https://api.openai.com/v1
SCOPE_VISION_API_KEY=your_key
SCOPE_VISION_MODEL=gpt-5.5

SCOPE_IMAGE_BASE_URL=https://api.openai.com/v1
SCOPE_IMAGE_API_KEY=your_key
SCOPE_IMAGE_MODEL=gpt-image-2
```

For Gemini, set the corresponding role format to `google-gemini` or
`google-gemini-image`, use a Gemini API base such as
`https://generativelanguage.googleapis.com/v1beta`, and set
`SCOPE_GOOGLE_API_KEY_AUTH=header` or `query`.

For non-OpenAI/non-Gemini wrappers, use the generic adapters:

```env
SCOPE_LLM_FORMAT=generic-text-json
SCOPE_LLM_ENDPOINT_URL=https://example.com/text
SCOPE_IMAGE_FORMAT=generic-image-json
SCOPE_IMAGE_ENDPOINT_URL=https://example.com/image
SCOPE_GENERIC_AUTH_MODE=bearer
```

For the previous OpenAI-compatible image format, use:

```env
SCOPE_LLM_FORMAT=openai-chat
SCOPE_VISION_FORMAT=openai-chat
SCOPE_IMAGE_FORMAT=openai-images-legacy
SCOPE_IMAGE_GENERATIONS_URL=https://example.com/v1/images/generations
SCOPE_RESPONSE_FORMATS=b64_json,url,b64_json,url
```

Never commit real `.env` files or generated private outputs.

## Preset library

The unified preset file is:

```text
references/scope-preset-library.json
```

Routes:

```text
portrait, magazine, poster, cosplay, interior, product, bathroom
```

### Preset provenance

Most preset ideas come from public internet prompt libraries and examples. They were filtered, rewritten, normalized, and distilled into route-level controls. The project aims to store:

```text
route hints
camera/capture controls
composition controls
material and lighting controls
negative constraints
quality controls
source/count metadata
```

It is not intended to distribute verbatim third-party prompt bodies.

## Quick start

Dry-run a prompt without spending image calls:

```bash
python scripts/generate_single_v2.py \
  --env-file <env> \
  --user-prompt "白衬衫酒店浴室镜前自拍" \
  --out-dir scope_runs/single_bathroom \
  --dry-run
```

Generate one image:

```bash
python scripts/generate_single_v2.py \
  --env-file <image.env> \
  --llm-env-file <llm.env> \
  --vision-env-file <vision.env> \
  --llm-model gpt-5.5 \
  --vision-model grok-4.3 \
  --image-model gpt-image-2 \
  --user-prompt "赛博朋克电影海报，雨夜女侦探" \
  --out-dir scope_runs/single_poster \
  --max-generation-attempts 2
```

Batch run N images:

```bash
python scripts/scope_commands.py batch-run \
  --count 6 \
  --env-file <image.env> \
  --user-prompt "产品图，香水瓶" \
  --out-dir scope_runs/batch_product
```

Reference-image generation:

```bash
python scripts/scope_commands.py reference-run \
  --env-file <image.env> \
  --vision-env-file <vision.env> \
  --reference-image <image.png> \
  --reference-mode style \
  --user-prompt "参考这张图的浴室氛围，生成白衬衫镜前自拍" \
  --out-dir scope_runs/reference_test
```

List presets:

```bash
python scripts/scope_commands.py list-presets --detail
```

Run a small regression dry-run:

```bash
python scripts/run_v2_route_regression.py \
  --env-file <image.env> \
  --max-cases 3 \
  --skip-vision \
  --dry-run
```

## Release checks

Before publishing the skill, run the offline release gate:

```bash
python scripts/run_release_checks.py --out-dir .codex_tmp/scope_release_checks
```

Fast adapter/schema-only variant:

```bash
python scripts/run_release_checks.py --out-dir .codex_tmp/scope_release_checks --skip-dry-run
```

The release gate does not call real APIs. It checks script syntax, provider
config, API payload shapes, image response extraction, preset routes, SCOPE spec
validation, and representative dry-run prompts.

Release test cases live in:

```text
references/release-test-cases.json
```

Detailed publish checklist:

```text
references/release-testing.md
```

## Output artifacts

Typical output directory:

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

## Open-source hygiene

Recommended `.gitignore`:

```gitignore
*.env
.local-keys/
scope_runs/
.codex_tmp/
__pycache__/
*.pyc
```

Do not commit:

```text
real API keys
private endpoint URLs
private generated images
local caches with third-party prompt bodies
personal account data
```

## Community

QQ group: `1107570994`

Scan to join:

<img src="docs/assets/qq-group.png" alt="QQ group 1107570994" width="360">
