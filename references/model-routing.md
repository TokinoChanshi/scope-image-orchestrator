# Model Routing

Route by role, not by endpoint source. Public docs should keep only model names and generic API shapes.

## Recommended roles

| Role | Example model names | Why |
| --- | --- | --- |
| `decomposer` | `text-model`, `vision-model` | Stable structured decomposition. |
| `reasoner` | `text-model`, `vision-model` | Implicit constraints, contradictions, repair planning. |
| `retrieval_corrector` | `vision-model` | Evidence cleanup when retrieval is available. |
| `prompt_optimizer` | `text-model`, `vision-model` | Compact production prompts from commitments. |
| `verifier` | `vision-model`, `vision-model` | Itemized visual inspection. |
| `image_generator` | `image-model`, `image-model` | Final image generation. |
| `image_editor` | edit-capable image model | Localized repair when supported. |

## Custom model support

Add any model by registering a role in a task-local config:

```json
{
  "roles": {
    "reasoner": {"provider": "llm", "model": "text-model"},
    "verifier": {"provider": "vision", "model": "vision-model"},
    "image_generator": {"provider": "image", "model": "image-model"}
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
