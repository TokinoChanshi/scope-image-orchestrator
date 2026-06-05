# Repair Routing

Use verification results to decide the smallest useful repair.

## Decision table

| Failure type | Signal | Action |
| --- | --- | --- |
| `unresolved_unknown` | Verifier says the image cannot be judged or a fact/reference is missing. | Retrieve or reason, then update the spec before another generation. |
| `prompt_expression_gap` | Spec contains the requirement, but generation prompt omitted or weakened it. | Rewrite prompt; keep image provider unchanged. |
| `visual_realization_gap` | Prompt clearly states the requirement, but output misses it. | Use image edit for local defects; regenerate for broad failures. |
| `blocked_by_entity` | Required entity is missing or wrong, so dependent constraints cannot be checked. | Repair/regenerate the entity first; do not overfit dependent constraints yet. |
| `overconstrained_or_conflicting` | Requirements conflict or exceed likely model capability. | Simplify, prioritize critical constraints, or ask user if tradeoff is needed. |

## Prompt rewrite

Use when many failures are caused by weak prompt expression. Include:

- A compact scene overview.
- Critical entities first.
- Exact counts/text/positions.
- Negative constraints only when necessary.
- Avoid long rationale or JSON unless the image model benefits from it.

## Image edit

Use when the base image is good and the failure is localized:

- Missing small object.
- Wrong text on a sign/poster.
- Color/detail correction.
- Minor layout adjustment.

Edit prompt should name target failure IDs:

```text
Edit only these issues: c3 and c5. Preserve all passed entities and constraints. Add exactly two red ribbons on the left side of e2; replace the poster text with "OPEN 24 HOURS" in readable uppercase letters.
```

## Regeneration

Use when failures are broad or entangled:

- Wrong main entity identity.
- Incorrect scene structure.
- Multiple critical layout failures.
- Style and content both drifted.

Regeneration prompt should explicitly preserve all resolved unknowns and prioritize critical constraints.

## Stop criteria

Stop when:

- All critical entities and constraints pass.
- Remaining failures are nice-to-have and user asked for speed.
- Two repair attempts repeat the same failure, suggesting provider limitation.
- Further repair risks damaging more passed constraints than it fixes.
