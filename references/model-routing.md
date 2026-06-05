# Model Routing

Route by role, not by endpoint source. Public docs should keep only model names and generic API shapes.

## Recommended roles

| Role | Example model names | Why |
| --- | --- | --- |
| `decomposer` | `gpt-5.5`, `grok-4.3` | Stable structured decomposition. |
| `reasoner` | `gpt-5.5`, `grok-4.3` | Implicit constraints, contradictions, repair planning. |
| `retrieval_corrector` | `grok-4.3` | Evidence cleanup when retrieval is available. |
| `prompt_optimizer` | `gpt-5.5`, `grok-4.3` | Compact production prompts from commitments. |
| `verifier` | `grok-4.3`, `Gemini 3-Pro` | Itemized visual inspection. |
| `image_generator` | `gpt-image-2`, `Nano Banana Pro` | Final image generation. |
| `image_editor` | edit-capable image model | Localized repair when supported. |

## Custom model support

Add any model by registering a role in a task-local config:

```json
{
  "roles": {
    "reasoner": {"provider": "llm", "model": "gpt-5.5"},
    "verifier": {"provider": "vision", "model": "grok-4.3"},
    "image_generator": {"provider": "image", "model": "gpt-image-2"}
  }
}
```

## Comparison policy

Do not assume one model is globally best. Test each route on representative prompts and compare:

1. Entity pass rate.
2. Constraint pass rate.
3. Text rendering.
4. Reference preservation.
5. Factual grounding quality.
6. Latency and cost.
7. Repair convergence.

For most workflows, use a strong text model for decomposition/optimization, an image model for generation, and a vision-capable model for audit/repair.
