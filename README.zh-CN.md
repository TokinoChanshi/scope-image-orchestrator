[English](README.md) | [简体中文](README.zh-CN.md)

# SCOPE Image Orchestrator

SCOPE Image Orchestrator 是一套用于图像生成流程编排的 Codex skill。  
它将用户输入转成明确可执行的约束，按路由依次走“解析 → 提示词优化 → 生成 → 可选审核 → 定向修复”。

支持 OpenAI / Gemini / 自定义通用 JSON 适配，适合在本地或自有网关环境复用。

## 核心能力

- 结构化分解与条件编排
- 路由感知提示词优化（portrait / magazine / poster / cosplay / interior / product / bathroom）
- 多模型角色分离（文本模型、视觉模型、图像模型）
- 参考图分析与参考引导（含镜子自拍、场景参考等）
- 批量执行、命令入口与可复现 dry-run

## 论文映射

- **SCOPE: Structured Decomposition and Conditional Skill Orchestration for Complex Image Generation**
- arXiv: https://arxiv.org/abs/2605.08043
- HTML: https://arxiv.org/html/2605.08043v1
- Project: https://nopnor.github.io/SCOPE/

本仓库是论文思路的实践化版本（非官方实现）。

## 示例画廊

- [Sample gallery](docs/gallery.md)

## 快速开始

复制环境模板并填写你自己的 endpoint 与 key：

```bash
cp references/.env.example .env
```

Dry-run（不调用真实图像 API）：

```bash
python scripts/generate_single_v2.py \
  --env-file .env \
  --user-prompt "your image request" \
  --out-dir scope_runs/example \
  --dry-run
```

正式生成：

```bash
python scripts/generate_single_v2.py \
  --env-file .env \
  --user-prompt "your image request" \
  --out-dir scope_runs/example
```

查看命令：

```bash
python scripts/scope_commands.py commands
```

## 配置与适配

使用 `references/.env.example` 作为公开配置起点。

支持的适配器类型：

- OpenAI-compatible 文本 / 视觉 / 图像 API
- Google Gemini 文本 / 视觉 / 图像 API
- 通用 JSON 包装（generic-text-json / generic-vision-json / generic-image-json）

详细请求形状见：

- `references/api-providers.md`
- `references/provider-config.example.json`

## 统一预设库

全部路由统一维护在：

```
references/scope-preset-library.json
```

预设来源于公开提示词库和互联网案例，经过蒸馏后保留可执行控制项，故不直接复刻第三方原始长提示词。

## 发布前检查（离线）

默认不调用真实 API：

```bash
python scripts/run_release_checks.py --out-dir D:/tmp/scope_release_checks
```

快速变更可加速：

```bash
python scripts/run_release_checks.py --out-dir D:/tmp/scope_release_checks --skip-dry-run
```

如需绕过执行环境限制，可跳过编译检查：

```bash
python scripts/run_release_checks.py --out-dir D:/tmp/scope_release_checks --skip-compile
```

## 产物目录

```
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

