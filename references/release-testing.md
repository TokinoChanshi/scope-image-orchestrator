# Release testing

This document defines the publish-time checks for SCOPE Image Orchestrator.

The release gate is offline by default and does not call real APIs.

## Run the release gate

```bash
python scripts/run_release_checks.py --out-dir ./tmp/scope_release_checks
```

Fast mode (skip dry-run prompts):

```bash
python scripts/run_release_checks.py --out-dir ./tmp/scope_release_checks --skip-dry-run
```

If the environment blocks compile output, use:

```bash
python scripts/run_release_checks.py --out-dir ./tmp/scope_release_checks --skip-compile
```

Expected success line:

```text
[OK] release checks passed
```

## Coverage

The gate validates:

1. Python script syntax/buildability (or compile skip mode).
2. `references/provider-config.example.json` validity.
3. Provider role payload rendering across all adapter families.
4. `validate_scope_spec.py` against a sample scope spec.
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
7. Response extraction for common response shapes:
   - OpenAI: `data[].b64_json` / `data[].url`
   - Generic: `images[].base64`, `image`, `output[].result`
   - Gemini: `candidates[].content.parts[].inlineData.data`
8. Dry-run routing for representative routes:
   - `portrait`
   - `bathroom`
   - `poster`
   - `product`
   - `interior`
   - `magazine`
   - `cosplay`
   - `documentary`
   - `strategy_overhead`
   - `idiom_cinema`
   - `anime_cel`

Test case definitions are in:

```text
references/release-test-cases.json
```

## Optional live smoke tests

Live tests are intentionally separate from the offline gate:

```bash
python scripts/generate_single_v2.py \
  --env-file <image.env> \
  --llm-env-file <llm.env> \
  --vision-env-file <vision.env> \
  --user-prompt "commercial product packshot, clean background, soft realistic shadow" \
  --out-dir scope_runs/live_product_smoke \
  --max-generation-attempts 1
```

Reference-image smoke test:

```bash
python scripts/scope_commands.py reference-run \
  --env-file <image.env> \
  --vision-env-file <vision.env> \
  --reference-image <reference.png> \
  --reference-mode style \
  --user-prompt "lifestyle mirror-selfie prompt: realistic skin, warm vanity light, private bedroom bathroom, candid composition" \
  --out-dir scope_runs/live_reference_smoke
```

### Optional live smoke example

Use one clean output dir per route. Representative command:

```bash
python scripts/generate_single_v2.py --env-file <image.env> --llm-model gpt-5.5 --vision-model grok-4.3 --image-model gpt-image-2 --user-prompt "<route prompt>" --out-dir scope_runs/<route>_test --max-generation-attempts 2
```

For a reproducible dry-run matrix, you can run:

```bash
python scripts/run_v2_route_regression.py --env-file <env> --llm-env-file <env> --out-dir scope_release_checks/<tag> --only-cases 01_europe_casual,01_luxe_cover,01_neon_protocol,01_pyro_hero,01_oriental_living,01_perfume,01_hotel_bathroom_mirror --dry-run
```

This dry-run result is used as an additional regression seed for route mapping and
preset/negative-constraint coverage (no API calls).

Live endpoints are tested separately and are intentionally not included in the
offline release gate because credentials and service availability vary by user environment.

## Pre-publish checklist

- [ ] `python scripts/run_release_checks.py --out-dir ./tmp/scope_release_checks` passes.
- [ ] `README.md` and `README.zh-CN.md` samples are still valid.
- [ ] `SKILL.md` remains a short usage guide and points to reference docs.
- [ ] `references/provider-config.example.json` contains no real endpoints or keys.
- [ ] `references/.env.example` contains placeholders only.
- [ ] `references/scope-preset-library.json` contains distilled controls, not verbatim prompt libraries.
- [ ] No private credentials, private outputs, `.env`, or raw cache artifacts are committed.
