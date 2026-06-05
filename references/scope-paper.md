# SCOPE Paper Notes

This skill is inspired by the paper:

- **SCOPE: Structured Decomposition and Conditional Skill Orchestration for Complex Image Generation**
- arXiv: https://arxiv.org/abs/2605.08043
- HTML: https://arxiv.org/html/2605.08043v1
- Project page: https://nopnor.github.io/SCOPE/

This repository is an independent practical adaptation. It is not the official implementation and does not claim to reproduce all paper experiments.

## Problem described by the paper

The paper studies complex text-to-image prompts where models often fail to preserve all requirements at once. It describes a **Conceptual Rift**: the gap between a user's intended semantic specification and what a flat text prompt/image model actually realizes.

Typical failures include:

- missing entities;
- wrong count or attributes;
- broken object relations;
- inconsistent layout;
- weak factual grounding;
- prompt details being dropped during generation;
- global image quality looking acceptable while specific requirements fail.

## Core SCOPE idea

SCOPE treats image generation as an orchestration problem instead of a single prompt problem.

The high-level chain is:

```text
user prompt
-> structured decomposition
-> conditional retrieval/reasoning
-> prompt synthesis
-> image generation
-> itemized verification
-> targeted repair
```

The important part is that the system keeps semantic commitments alive across the whole chain rather than letting them disappear inside one long prompt.

## Structured decomposition

The paper-style decomposition can be mapped into three practical object groups:

```text
entities: required people, objects, characters, places, visible text, style blocks
constraints: atomic attributes, relations, layouts, text requirements, factual commitments
unknowns: facts or references that must be resolved only if they matter
```

This implementation writes these ideas into artifacts such as:

```text
specification.raw.json
specification.json
synthesis_input.compact.json
prompt_synthesis.json
generation_prompt.txt
verification.json
final_summary.json
```

## Conditional skill orchestration

The paper's orchestration idea is conditional: do not call every tool for every request. Use the stage that fixes the current gap.

Examples:

| Gap | Skill/stage |
| --- | --- |
| Unknown factual detail | retrieval or reasoner |
| Weak prompt expression | prompt optimizer |
| Missing entity in image | regeneration or stronger prompt |
| Local visual defect | image edit if available |
| Broken text/layout | prompt simplification or route-specific template |
| Ambiguous user intent | ask user only when the system cannot infer safely |

## Verification philosophy

The paper emphasizes that a good-looking image can still fail the prompt. Verification should therefore be itemized:

1. Check critical entities first.
2. Check attributes and relations only after their dependent entities exist.
3. Mark blocked constraints explicitly instead of hallucinating a verdict.
4. Create repair instructions from concrete failed commitments.

This implementation follows the same spirit with visual audit JSON fields such as:

```json
{
  "overall": "pass | needs_repair | failed",
  "scores": {
    "route_fit": 0,
    "realism": 0,
    "composition": 0,
    "text_quality": 0
  },
  "failures": [],
  "repair_prompt": ""
}
```

## Evaluation and regression

The paper discusses complex-image evaluation rather than only single image quality. This implementation turns that into route regression:

```text
portrait
magazine
poster
cosplay
interior
product
bathroom
```

Each route has multiple prompt cases. Regression is used to catch preset drift, repeated same-face outputs, broken typography, weak realism, object duplication, perspective errors, or visual-audit failure loops.

## Model names

Open-source docs should name model strings only and avoid private endpoint/channel names. Depending on availability, the workflow can use model names such as:

```text
gpt-5.5
gpt-image-2
grok-4.3
GPT-5.4
Nano Banana Pro
Gemini 3-Pro
```

The role assignment is more important than the exact model:

```text
text model -> decomposition / prompt optimization / repair
image model -> generation
vision model -> visual audit / reference-image analysis
```

## Prompt preset provenance

Most route presets in this project were distilled from public internet prompt libraries and examples. The project intentionally stores route-level controls rather than verbatim third-party prompts:

```text
layout controls
camera/capture controls
material and lighting controls
route-specific negative constraints
quality controls
source/count metadata
```

The unified library is:

```text
references/scope-preset-library.json
```

## What is adapted vs. original

Adapted from the paper:

- semantic commitments;
- structured decomposition;
- conditional retrieval/reasoning;
- synthesis from structured state;
- entity-gated verification;
- repair loops;
- regression-style evaluation.

Implementation-specific additions:

- Chinese command mode using `生图优化`;
- unified preset library;
- route presets for portrait/magazine/poster/cosplay/interior/product/bathroom;
- reference-image analysis path;
- explicit OpenAI and Google Gemini API-shape adapters;
- batch and dry-run utilities.
