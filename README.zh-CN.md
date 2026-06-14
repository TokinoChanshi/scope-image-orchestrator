# SCOPE Image Orchestrator

这是一个开源的图像/视频生成流程封装项目，聚焦“可复现”与“可追踪”的生产逻辑：

1) 解析用户意图（路线、风格、限制）
2) 路由到预设
3) 预处理/优化提示词
4) 调用文本/图像/视频模型
5) 结果校验与打分
6) 回传修正（多次重跑）

本仓库实现受 arXiv 论文《SCOPE》的启发（论文参考见 `references/scope-paper.md`），不复现其官方代码。

## 快速开始

```bash
cp references/.env.example .env
python scripts/generate_single_v2.py --env-file .env --user-prompt "高端生活场景照片" --out-dir scope_runs/example --dry-run
python scripts/scope_commands.py commands
```

## 命令入口

常用命令示例：

```bash
python scripts/scope_commands.py list-presets --detail
python scripts/scope_commands.py video-run --env-file .env --user-prompt "高端生活片段" --out-dir scope_runs/video --dry-run
python scripts/scope_commands.py video-story --env-file .env --user-prompt "创建一个60秒分镜故事" --out-dir scope_runs/story --target-duration 60 --shot-duration 10 --candidate-count 3
python scripts/run_v2_route_regression.py --env-file .env --max-cases 1 --skip-vision --dry-run --out-dir scope_runs/regression
python scripts/scope_commands.py video-skill-check --env-file .env --out-dir scope_runs/video_skill_check
```

## 视觉模型/视频自然语言入口

支持一句话直接驱动分镜与候选生成（推荐）：

```bash
python scripts/run_video_skill.py \
  --env-file .env \
  --user-input "创作一个3分钟的高端生活片，每10秒一个镜头，每镜3个备选" \
  --out-dir scope_runs/story_mode
```

- 默认不开启 `--send`，脚本进入干跑（dry-run）；
- 可自动解析 `3分钟`、`每10秒`、`每镜3个` 等；
- 支持 `--send`、`--interactive`、`--selection-strategy`、`--max-shots`、`--no-assemble`。

### 兼容模型与格式

文档与示例只列出模型名称，不包含私有端点和密钥信息。支持模型形态：

- OpenAI 兼容接口（文本/图像/视频）
- Google Gemini 接口
- 通用 JSON 包装接口（可用于自定义代理）

更多适配说明见 `references/api-providers.md`。

## 社区

Linux Do 社区  
QQ 群：`1107570994`

<img src="docs/assets/qq-group.png" alt="QQ group 1107570994" width="360">
