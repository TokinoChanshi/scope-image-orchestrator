[中文（主）](README.md) | [English](README.en.md) | [中文镜像](README.zh-CN.md)

# SCOPE Image Orchestrator

`README.md` 为主中文说明；本文件保留为中文镜像与兼容入口，便于历史链接继续可用。

## 快速入口

- 主说明：`README.md`
- 英文说明：`README.en.md`
- Skill 说明：`SKILL.md`
- 图集：`docs/gallery.md`
- 预设库：`references/scope-preset-library.json`
- 接口说明：`references/api-providers.md`

## 项目概述

这是一个面向图像生成协同流程的开源 Skill。  
核心目标是把“自然语言需求 → 结构化约束 → 路由 → 优化 → 生图 → 审核 → 修复”做成一条可复现链路。

## 论文来源

- **SCOPE: Structured Decomposition and Conditional Skill Orchestration for Complex Image Generation**
- arXiv: https://arxiv.org/abs/2605.08043
- HTML: https://arxiv.org/html/2605.08043v1
- Project: https://nopnor.github.io/SCOPE/

## 常用命令

```bash
python scripts/scope_commands.py commands
python scripts/scope_commands.py list-presets --detail
python scripts/generate_single_v2.py --env-file .env --user-prompt "你的图像需求" --out-dir scope_runs/example --dry-run
```

## 说明

- 中文优先以 `README.md` 为准
- 公开文档仅展示模型名与通用兼容格式
- 不提交真实 key、私有 endpoint、私有输出

## 社区

友情支持：Linux Do 社区

QQ 群：`1107570994`

<img src="docs/assets/qq-group.png" alt="QQ group 1107570994" width="360">
