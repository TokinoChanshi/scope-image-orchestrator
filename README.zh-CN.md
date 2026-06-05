[English](README.md) | [简体中文](README.zh-CN.md)

# SCOPE Image Orchestrator

一个用于 SCOPE 风格图像生成编排的 Codex skill。

它会把用户的图像请求转化为结构化语义承诺，优化提示词，调用图像模型，用视觉模型审核结果，并在失败时通过定向修复重新生成。

> 这是一个受 SCOPE 论文启发的独立实践改造版本，不是论文作者的官方实现。

## 社区交流

QQ 群：`1107570994`

扫码加入：

<img src="docs/assets/qq-group.png" alt="QQ 群 1107570994" width="360">

## 论文来源

- **SCOPE: Structured Decomposition and Conditional Skill Orchestration for Complex Image Generation**
- arXiv: https://arxiv.org/abs/2605.08043
- HTML: https://arxiv.org/html/2605.08043v1
- Project: https://nopnor.github.io/SCOPE/

论文到实现的映射见 `references/scope-paper.md`。

## 功能概览

```text
用户请求
-> 路由识别
-> 语义拆解 / 提示词优化
-> 图像生成
-> 视觉审核
-> 定向修复
-> 可复现产物
```

核心思路是把关键需求显式保存下来，而不是把所有内容都藏在一条超长提示词里。

## 生成样例

查看生成样例图库：

- [样例图库](docs/gallery.md)

预览：

![生成样例总览](docs/assets/gallery/overview-contact-sheet.jpg)

## 命令模式

用下面的命令启动命令模式：

```text
生图优化
```

启动后可以使用短命令：

```text
查看预设
查看预设 bathroom
跑图 <prompt>
单张跑 <prompt>
批量跑 N 张 <prompt>
参考生图 <image> <prompt>
严格链路 <prompt>
回归测试
审核 <image_root>
干跑 <command>
重跑失败
退出生图优化
```

查看辅助命令列表：

```bash
python scripts/scope_commands.py commands
```

## 模型与 API 格式

开源文档只保留模型名称字符串。工作流本身不绑定具体 endpoint，但 API 请求格式必须显式配置。

支持的公开 adapter：

```text
openai-chat             -> OpenAI Chat Completions
openai-responses        -> OpenAI Responses
google-gemini           -> Gemini generateContent
openai-images           -> OpenAI Images API
openai-responses-image  -> OpenAI Responses image_generation tool
google-gemini-image     -> Gemini 原生图像生成
generic-text-json       -> 通用 JSON 文本包装器
generic-vision-json     -> 通用 JSON 视觉包装器
generic-image-json      -> 通用 JSON 图像包装器
openai-images-legacy    -> 带 response_format 的旧 OpenAI-compatible 图像 JSON 格式
```

常见角色：

| 角色 | 示例模型名称 |
| --- | --- |
| 提示词优化 / 语义拆解 | `gpt-5.5`, `grok-4.3` |
| 图像生成 | `gpt-image-2`, `Nano Banana Pro` |
| 视觉审核 / 参考图分析 | `grok-4.3`, `Gemini 3-Pro` |

## 环境配置

复制 `references/.env.example` 到本地 env 文件，然后填入自己的 endpoint 与 key。

```env
SCOPE_LLM_FORMAT=openai-responses
SCOPE_VISION_FORMAT=openai-responses
SCOPE_IMAGE_FORMAT=openai-images

SCOPE_LLM_BASE_URL=https://api.openai.com/v1
SCOPE_LLM_API_KEY=your_key
SCOPE_LLM_MODEL=gpt-5.5

SCOPE_VISION_BASE_URL=https://api.openai.com/v1
SCOPE_VISION_API_KEY=your_key
SCOPE_VISION_MODEL=gpt-5.5

SCOPE_IMAGE_BASE_URL=https://api.openai.com/v1
SCOPE_IMAGE_API_KEY=your_key
SCOPE_IMAGE_MODEL=gpt-image-2
```

如果使用 Gemini，把对应角色格式设置为 `google-gemini` 或 `google-gemini-image`，base URL 可使用 `https://generativelanguage.googleapis.com/v1beta`，并配置 `SCOPE_GOOGLE_API_KEY_AUTH=header` 或 `query`。

如果使用非 OpenAI / 非 Gemini 的自定义包装接口，可使用通用 adapter：

```env
SCOPE_LLM_FORMAT=generic-text-json
SCOPE_LLM_ENDPOINT_URL=https://example.com/text
SCOPE_IMAGE_FORMAT=generic-image-json
SCOPE_IMAGE_ENDPOINT_URL=https://example.com/image
SCOPE_GENERIC_AUTH_MODE=bearer
```

如果需要旧版 OpenAI-compatible 图像格式：

```env
SCOPE_LLM_FORMAT=openai-chat
SCOPE_VISION_FORMAT=openai-chat
SCOPE_IMAGE_FORMAT=openai-images-legacy
SCOPE_IMAGE_GENERATIONS_URL=https://example.com/v1/images/generations
SCOPE_RESPONSE_FORMATS=b64_json,url,b64_json,url
```

不要提交真实 `.env` 文件或私有生成结果。

## 预设库

统一预设文件：

```text
references/scope-preset-library.json
```

当前路由：

```text
portrait, magazine, poster, cosplay, interior, product, bathroom
```

### 预设来源说明

大部分预设思路来自公开互联网提示词库与示例。它们经过筛选、重写、标准化与蒸馏，最终整理成路由级控制项。本项目希望保存的是：

```text
路由提示
相机 / 拍摄控制
构图控制
材质与灯光控制
负面约束
质量控制
来源 / 数量元数据
```

本项目不打算分发第三方提示词原文。

## 快速开始

不消耗图像 API 调用的 dry-run：

```bash
python scripts/generate_single_v2.py \
  --env-file <env> \
  --user-prompt "白衬衫酒店浴室镜前自拍" \
  --out-dir scope_runs/single_bathroom \
  --dry-run
```

生成一张图：

```bash
python scripts/generate_single_v2.py \
  --env-file <image.env> \
  --llm-env-file <llm.env> \
  --vision-env-file <vision.env> \
  --llm-model gpt-5.5 \
  --vision-model grok-4.3 \
  --image-model gpt-image-2 \
  --user-prompt "赛博朋克电影海报，雨夜女侦探" \
  --out-dir scope_runs/single_poster \
  --max-generation-attempts 2
```

批量生成 N 张：

```bash
python scripts/scope_commands.py batch-run \
  --count 6 \
  --env-file <image.env> \
  --user-prompt "产品图，香水瓶" \
  --out-dir scope_runs/batch_product
```

参考图生成：

```bash
python scripts/scope_commands.py reference-run \
  --env-file <image.env> \
  --vision-env-file <vision.env> \
  --reference-image <image.png> \
  --reference-mode style \
  --user-prompt "参考这张图的浴室氛围，生成白衬衫镜前自拍" \
  --out-dir scope_runs/reference_test
```

列出预设：

```bash
python scripts/scope_commands.py list-presets --detail
```

运行小规模 dry-run 回归：

```bash
python scripts/run_v2_route_regression.py \
  --env-file <image.env> \
  --max-cases 3 \
  --skip-vision \
  --dry-run
```

## 发布检查

发布 skill 前运行离线发布检查：

```bash
python scripts/run_release_checks.py --out-dir .codex_tmp/scope_release_checks
```

快速 adapter / schema 检查：

```bash
python scripts/run_release_checks.py --out-dir .codex_tmp/scope_release_checks --skip-dry-run
```

发布检查不会调用真实 API。它会检查脚本语法、provider config、API payload 形状、图像响应解析、预设路由、SCOPE spec 校验，以及代表性 dry-run prompt。

发布测试用例位于：

```text
references/release-test-cases.json
```

详细发布 checklist：

```text
references/release-testing.md
```

## 输出产物

典型输出目录：

```text
scope_runs/<task>/
  user_request.txt
  route.json
  optimized_prompt.json
  generation_prompt.txt
  generation_prompt.attempt_N.txt
  image_result.attempt_N.json
  visual_audit.attempt_N.json
  reference_image.json
  image.png
  final_summary.json
```

## 开源卫生

推荐 `.gitignore`：

```gitignore
*.env
.local-keys/
scope_runs/
.codex_tmp/
__pycache__/
*.pyc
```

不要提交：

```text
真实 API key
私有 endpoint URL
私有生成图片
包含第三方提示词原文的本地缓存
个人账号数据
```
