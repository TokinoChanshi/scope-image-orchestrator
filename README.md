[中文（主）](README.md) | [English](README.en.md) | [中文镜像](README.zh-CN.md)

# SCOPE Image Orchestrator

一个面向图像生成工作流的开源 Codex Skill。

它把“自然语言需求 → 结构化约束 → 场景路由 → 提示词优化 → 生图调用 → 视觉审核 → 定向修复”整理成一条可复现链路，尽量减少只靠单段 prompt 反复试错带来的波动。

本项目是对 **SCOPE** 论文思路的工程化改造与实用化实现，并非论文作者官方代码。

## 这是什么

适合以下场景：

- 人像、杂志、海报、 Cosplay、室内、产品、浴室自拍等常见生图任务
- 批量跑图、回归测试、主题包 / 预设迭代
- 接入不同文本模型、视觉模型、生图模型
- 希望把“失败后继续修”纳入工作流，而不是只做一次性出图

## 核心链路

```text
用户请求
  -> 语义拆解
  -> route 选择
  -> 预设 / 主题包注入
  -> LLM 提示词优化
  -> 图像生成
  -> 视觉审核（可选）
  -> 定向修复 / 重跑（可选）
  -> 输出可复盘产物
```

与论文一致的关键思想：

1. 先拆需求，再生成，而不是把整句需求直接扔给生图模型。
2. 用结构化约束组织 prompt，而不是完全依赖“灵感式 prompt”。
3. 审核失败时只修失败项，而不是整条链路盲目重来。

## 主要能力

- **结构化拆解**：抽取人物、物体、关系、构图、材质、灯光、文本要求等约束
- **路由驱动优化**：不同场景走不同 route / preset，而不是一套模板通吃
- **多适配器兼容**：支持 OpenAI-compatible、Gemini-compatible、Generic JSON wrapper
- **参考图分析**：可选分析参考图的风格、构图、身份、产品特征
- **视觉审核与修复**：可选让视觉模型检查结果，并给出定向修复建议
- **批量与回归测试**：适合持续优化预设库、主题包与模型路由

## 论文来源

- **SCOPE: Structured Decomposition and Conditional Skill Orchestration for Complex Image Generation**
- arXiv: https://arxiv.org/abs/2605.08043
- HTML: https://arxiv.org/html/2605.08043v1
- Project: https://nopnor.github.io/SCOPE/

## 快速开始

复制环境模板并填写你自己的 Key / Endpoint：

```bash
cp references/.env.example .env
```

先做干跑，不调用真实图像接口：

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

## 命令模式

人类触发词：

```text
生图优化
```

常用命令：

| 命令 | 作用 |
| --- | --- |
| `帮助` / `命令` | 查看命令模式说明 |
| `查看预设` | 列出全部 route 预设 |
| `查看主题包` | 列出全部 theme pack |
| `跑图 <prompt>` | 生成单张 |
| `批量跑 N 张 <prompt>` | 同 prompt 批量生成 |
| `参考生图 <image> <prompt>` | 带参考图生成 |
| `严格链路 <prompt>` | 启用更接近论文式的严格拆解 / 校验链路 |
| `审核 <image_root>` | 对结果图做视觉审核 |
| `回归测试` | 运行 route / preset 回归 |
| `退出生图优化` | 离开命令模式 |

## 配置与兼容格式

公开示例优先使用通用 `SCOPE_*` 环境变量。

支持的接口格式：

- OpenAI-compatible text / vision / image
- Google Gemini text / vision / image
- Generic JSON wrapper

详细示例见：

- `references/.env.example`
- `references/api-providers.md`
- `references/provider-config.example.json`

## 模型角色

同一条链路里通常会有这些角色：

- `decomposer`：把请求拆成结构化约束
- `prompt_optimizer`：把 route + constraints 合成为最终 prompt
- `image_generator`：实际出图
- `verifier`：视觉检查是否满足约束
- `repair_planner`：将失败项转成下一轮修复动作

也就是说，你可以按自己的环境替换不同模型，只要请求格式兼容即可。

## 预设库

统一预设入口：

```text
references/scope-preset-library.json
```

当前主要 route：

```text
portrait, magazine, poster, cosplay, interior, product, bathroom,
idiom_cinema, documentary, strategy_overhead, anime_cel
```

来源说明：

- 大部分预设思路来自公开互联网提示词示例与社区经验
- 经过蒸馏、重构、压缩后，仅保留可执行控制项
- 不原样分发第三方完整提示词正文

## 输出产物

每次严肃跑图建议保留这些产物：

```text
scope_runs/<task>/
  user_request.txt
  route.json
  optimized_prompt.json
  generation_prompt.txt
  image_result.attempt_N.json
  visual_audit.attempt_N.json
  reference_image.json
  image.png
  final_summary.json
```

## 相关文档

- Skill 说明：`SKILL.md`
- 图集：`docs/gallery.md`
- 预设库：`references/scope-preset-library.json`

## 开源说明

- 文档中仅保留真实**模型名称**与**通用兼容格式**
- 不公开真实 key、私有 endpoint、私有输出
- 预设库以“蒸馏后的控制项”为主，不以搬运第三方完整 prompt 为目标

## 社区

友情支持：Linux Do 社区

QQ 群：`1107570994`

<img src="docs/assets/qq-group.png" alt="QQ group 1107570994" width="360">
