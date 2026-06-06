# Release Readiness Notes (2026-06-06)

- Repository: `https://github.com/TokinoChanshi/scope-image-orchestrator`
- Current branch: `main`
- Latest local commit: `456adc8`

## 1) Offline release checks

Executed:

```bash
python scripts/run_release_checks.py --out-dir D:\RH应用\scope_run_release_checks
```

Result:

- `[OK] compiled 14 scripts`
- `[OK] provider config validation`
- `[OK] rendered 12 provider roles`
- `[OK] sample SCOPE spec validation`
- `[OK] preset routes present: bathroom, cosplay, interior, magazine, portrait, poster, product`
- `[OK] adapter payload cases checked: 10`
- `[OK] response extraction cases checked: 6`
- `[OK] dry-run prompt cases checked: 7`
- `[OK] release checks passed`

## 2) Route regression (dry-run)

Executed:

```bash
python scripts/run_v2_route_regression.py --env-file .tmp_scope_publish_chatgpt2_live.env --out-dir D:\RH应用\scope_run_v2_regression --dry-run
```

Result:

- 42 cases selected
- `selected_cases.json` generated (dry-run only)

## 3) Real API call status

In the current local environment, image endpoints returned auth/quota errors (e.g., `invalid_api_key`, `no available image quota`) when trying quick live calls.  
Therefore, generated images cannot yet be published as reproducible "success samples" here.

## 4) Open-source publishing constraints kept

- No private endpoint URLs or API keys are committed.
- Only public model names and public request-shape compatibility are documented.
- Prompt source is explicitly documented as distilled from public public examples; raw third-party prompt bodies are not redistributed.
