[English](README.md) | [中文](README.zh-CN.md)

# SCOPE Image Orchestrator

这是一个用于图像生成协同流程的开源 Skill：

- 对请求进行路由到专用场景（portrait、magazine、poster、cosplay、interior、product、bathroom）
- 将请求映射为可执行的提示词控制项（人物、场景、镜头、材质、灯光、否定约束）
- 调用 LLM 做提示词优化（可选）
- 发送图像生成请求（可配置多种适配器）
- 可选视觉审核与失败修复重试
- 支持批量与回归测试

本项目基于 **SCOPE** 论文思想实现，目标是：用结构化路由与约束控制，减少“拍脑袋提示词”带来的波动。

## 特性

- 路由驱动的提示词优化
- 多适配器兼容（OpenAI/Gemini/通用 JSON）
- 可选参考图分析（参考图风格/构图/身份/产品特征）
- 可选视觉审核 + 针对性修复
- 批量调用、干跑与回归测试

## 论文信息

- **SCOPE: Structured Decomposition and Conditional Skill Orchestration for Complex Image Generation**
- arXiv: https://arxiv.org/abs/2605.08043
- HTML: https://arxiv.org/html/2605.08043v1
- 项目页: https://nopnor.github.io/SCOPE/

## 快速开始

复制环境模板并填写你自己的 Key / Endpoint：

```bash
cp references/.env.example .env
```

不调用图像接口的干跑：

```bash
python scripts/generate_single_v2.py \
  --env-file .env \
  --user-prompt "你的图像需求" \
  --out-dir scope_runs/example \
  --dry-run
```

实际生成一张：

```bash
python scripts/generate_single_v2.py \
  --env-file .env \
  --user-prompt "你的图像需求" \
  --out-dir scope_runs/example
```

查看命令模式：

```bash
python scripts/scope_commands.py commands
```

## 配置

使用 `references/.env.example`。支持的通道格式：

- OpenAI-compatible text / vision / image
- Google Gemini text / vision / image
- 通用 JSON 封装（custom wrapper）

详细请求示例见：

- `references/api-providers.md`
- `references/provider-config.example.json`

## 预设库

统一预设入口：

```text
references/scope-preset-library.json
```

预设与风格来源说明：

- 本仓库中的提示词思路来自公开可见的互联网创作模板进行蒸馏与重构，
- 仅保留场景-镜头-材质-构图等可执行控制项，
- 不在仓库中原样分发第三方完整提示词。

## 验证

发布前请执行离线发布检查（不调用真实图像 API）：

```bash
python scripts/run_release_checks.py --out-dir ./.codex_tmp/scope_release_checks
```

如需快速检查：

```bash
python scripts/run_release_checks.py --out-dir ./.codex_tmp/scope_release_checks --skip-dry-run
```

发布可复现性证据：

- [release-readiness-2026-06-06.md](docs/release-readiness-2026-06-06.md)

## 输出产物

```text
scope_runs/<task>/
  user_request.txt
  route.json
  optimized_prompt.json
  generation_prompt.txt
  image_result.attempt_N.json
  visual_audit.attempt_N.json
  image.png
  final_summary.json
```

## 社区

QQ 群：`1107570994`

<img src="docs/assets/qq-group.png" alt="QQ group 1107570994" width="360">
