[English](README.md) | [简体中文](README.zh-CN.md)

# SCOPE Image Orchestrator

一个用于结构化图像生成编排的 Codex skill。

它可以把图像请求转化为明确需求、优化后的提示词、生成调用、视觉检查、修复尝试和可复现产物。

> 本项目是受 SCOPE 论文启发的独立实践改造版本，不是论文作者的官方实现。

## 特性

- 结构化提示词拆解。
- 按场景路由的提示词优化。
- 多 Provider API adapter 层。
- 可选参考图分析。
- 可选视觉审核与定向修复循环。
- 支持批量运行与 dry-run 测试。

## 论文

- **SCOPE: Structured Decomposition and Conditional Skill Orchestration for Complex Image Generation**
- arXiv: https://arxiv.org/abs/2605.08043
- HTML: https://arxiv.org/html/2605.08043v1
- Project: https://nopnor.github.io/SCOPE/

## 样例

查看生成样例图库：

- [样例图库](docs/gallery.md)

| 海报 | 产品 | 室内 |
| --- | --- | --- |
| ![海报样例](docs/assets/gallery/poster-neon-protocol.jpg) | ![产品样例](docs/assets/gallery/product-perfume.jpg) | ![室内样例](docs/assets/gallery/interior-oriental-living.jpg) |

## 快速开始

复制环境变量模板，并填写自己的 endpoint 和 key：

```bash
cp references/.env.example .env
```

不调用图像 API 的 dry-run：

```bash
python scripts/generate_single_v2.py \
  --env-file .env \
  --user-prompt "your image request" \
  --out-dir scope_runs/example \
  --dry-run
```

生成一张图：

```bash
python scripts/generate_single_v2.py \
  --env-file .env \
  --user-prompt "your image request" \
  --out-dir scope_runs/example
```

查看命令帮助：

```bash
python scripts/scope_commands.py commands
```

## 配置

使用 `references/.env.example` 作为公开配置模板。

支持的 adapter 类型：

- OpenAI-compatible 文本与图像 API。
- Google Gemini-compatible 文本、视觉与图像 API。
- 通用 JSON 包装接口。
- 旧版 OpenAI-compatible 图像 JSON 接口。

详细请求格式见：

- `references/api-providers.md`
- `references/provider-config.example.json`

## 预设

统一预设库：

```text
references/scope-preset-library.json
```

预设思路来自公开提示词示例，并经过重写与蒸馏，整理成紧凑的路由级控制项。本项目不用于分发第三方提示词原文。

## 验证

发布修改前运行离线检查：

```bash
python scripts/run_release_checks.py --out-dir .codex_tmp/scope_release_checks
```

该检查只在本地运行，不会调用真实 API。

## 输出产物

典型输出：

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

## 社区交流

QQ 群：`1107570994`

扫码加入：

<img src="docs/assets/qq-group.png" alt="QQ 群 1107570994" width="360">
