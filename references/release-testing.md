# Release testing

This file describes the publish-time test matrix for SCOPE Image Orchestrator.

The default release checks are **offline**. They do not call real APIs and do
not require real API keys.

## Run the release gate

From the skill root:

```bash
python scripts/run_release_checks.py --out-dir .codex_tmp/scope_release_checks
```

Fast variant without prompt dry-runs:

```bash
python scripts/run_release_checks.py --out-dir .codex_tmp/scope_release_checks --skip-dry-run
```

Expected final line:

```text
[OK] release checks passed
```

## What is covered

The release gate checks:

1. Python syntax for every script in `scripts/`.
2. `references/provider-config.example.json` structure.
3. Provider-role payload rendering for every configured role.
4. A sample SCOPE specification with `validate_scope_spec.py`.
5. Required preset routes in `references/scope-preset-library.json`.
6. Adapter payload construction for:
   - `openai-chat`
   - `openai-responses`
   - `google-gemini`
   - `openai-images`
   - `openai-responses-image`
   - `google-gemini-image`
   - `generic-text-json`
   - `generic-vision-json`
   - `generic-image-json`
   - `openai-images-legacy`
7. Response extraction for common image response shapes:
   - OpenAI `data[].b64_json`
   - OpenAI `data[].url`
   - generic `images[].base64`
   - generic `image` data URL
   - Responses `output[].result`
   - Gemini `inlineData.data`
8. Dry-run prompt cases for:
   - portrait
   - bathroom
   - poster
   - product
   - interior
   - magazine
   - cosplay

The concrete cases live in:

```text
references/release-test-cases.json
```

## Optional live smoke tests

Live smoke tests are intentionally separate from the release gate because they
spend API quota and require private credentials.

Before publishing a new adapter or model-routing change, optionally run:

```bash
python scripts/generate_single_v2.py \
  --env-file <image.env> \
  --llm-env-file <llm.env> \
  --vision-env-file <vision.env> \
  --user-prompt "commercial product packshot, clean background, soft realistic shadow" \
  --out-dir scope_runs/live_product_smoke \
  --max-generation-attempts 1
```

Also test one reference-image request if the release changed reference handling:

```bash
python scripts/scope_commands.py reference-run \
  --env-file <image.env> \
  --vision-env-file <vision.env> \
  --reference-image <reference.png> \
  --reference-mode style \
  --user-prompt "参考图片氛围，生成现代浴室室内生活方式人像摄影" \
  --out-dir scope_runs/live_reference_smoke
```

Do not commit real env files, private output images, or private endpoint URLs.

## Pre-publish checklist

- [ ] `python scripts/run_release_checks.py --out-dir .codex_tmp/scope_release_checks` passes.
- [ ] `README.md` examples still match the supported adapters.
- [ ] `SKILL.md` stays concise and points to reference files for details.
- [ ] `references/provider-config.example.json` contains no real endpoints or keys.
- [ ] `references/.env.example` contains placeholders only.
- [ ] `references/scope-preset-library.json` avoids verbatim third-party prompt bodies.
- [ ] Generated outputs, `.env` files, `.codex_tmp/`, `__pycache__/`, and `*.pyc` are not committed.
