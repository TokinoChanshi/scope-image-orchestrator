# Structured Specification Schema

Use this schema to keep semantic commitments traceable through decomposition, retrieval, generation, verification, and repair.

## Minimal schema

```json
{
  "version": "scope-spec-v1",
  "prompt": "original user request",
  "global_style": "optional style summary",
  "entities": [
    {
      "id": "e1",
      "name": "main subject",
      "kind": "person|character|object|scene|text|style|other",
      "priority": "critical|important|nice_to_have",
      "description": "what must be visible",
      "reference": {"type": "none|image|url|fact", "value": "optional"}
    }
  ],
  "constraints": [
    {
      "id": "c1",
      "type": "attribute|relation|layout|style|text|factual",
      "text": "atomic requirement",
      "depends_on": ["e1"],
      "priority": "critical|important|nice_to_have",
      "verification_hint": "how to check this visually"
    }
  ],
  "unknowns": [
    {
      "id": "u1",
      "owner": "prompt|e1|c1",
      "question": "what must be resolved",
      "resolution_method": "retrieval|reasoning|user|none",
      "status": "open|resolved|deferred",
      "answer": null,
      "evidence": []
    }
  ]
}
```

## Decomposition checklist

- Split compound requirements into atomic constraints.
- Put exact visible text in `text` constraints with spelling preserved.
- Represent counts explicitly: e.g. "exactly three lanterns".
- Represent relative placement explicitly: left/right/foreground/background/center/top.
- Attach every constraint to prerequisite entities using `depends_on`.
- Mark priorities. Critical failures should trigger repair or regeneration.
- Put uncertain factual/reference details into `unknowns`; do not hallucinate.

## Good unknown ownership

```json
{"id": "u1", "owner": "e2", "question": "What does this character's canonical outfit look like?", "resolution_method": "retrieval"}
{"id": "u2", "owner": "c4", "question": "Which trophy design was used in the 2026 event?", "resolution_method": "retrieval"}
{"id": "u3", "owner": "prompt", "question": "What aspect ratio should be used if not specified?", "resolution_method": "reasoning", "status": "resolved", "answer": "Use 1:1 by default."}
```

## Common mistakes

- Do not use one giant constraint for a whole paragraph.
- Do not verify constraints if their prerequisite entity is missing.
- Do not bury exact text requirements in style prose.
- Do not delete failed commitments during repair; update their status and repair notes.
