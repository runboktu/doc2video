# 新铁屋记 — AI视频生成项目

鲁迅风格杂文 → 分镜脚本 → AI生成视频片段 → 最终成片

## 项目结构

```
video-project/
├── prompts.json           # 17个分镜的英文 prompt（核心配置）
├── generate_videos.py     # 批量调用 API 生成视频片段
├── assemble.sh            # ffmpeg 拼接视频 + 叠加音频
├── images/                # 关键帧图片（可选，提升视频一致性）
└── clips/                 # 生成的视频片段
```

## 快速开始

### 1. 设置 API Key

```bash
# Kling (推荐，性价比最高)
export KLING_API_KEY="your-key-here"

# 或使用 Kling 官方 API（需国内手机号注册）
export KLING_API_KEY="your-key-here"
export KLING_USE_OFFICIAL=1

# 或使用 Runway（质量最高，价格贵）
# export RUNWAY_API_KEY="your-key-here"

# 或使用 Pika（速度最快）
# export PIKA_API_KEY="your-key-here"
```

### 2. 生成视频

```bash
cd video-project

# 全流程：先生成关键帧图片 → 再生成视频片段
python generate_videos.py --mode all --backend kling

# 只生成视频（跳过图片）
python generate_videos.py --mode videos --backend kling

# 只生成特定镜头
python generate_videos.py --mode videos --backend kling --shots S01 S05 S14
```

### 3. 拼接成片

```bash
# 完整流程：标准化 → 拼接 → 速度匹配 → 叠加音频
bash assemble.sh

# 跳过标准化（已标准化过）
bash assemble.sh --skip-normalize

# 只叠加音频（视频已拼接好）
bash assemble.sh --audio-only
```

最终输出: `新铁屋记.mp4`（在上级目录）

## API 获取方式

| 平台 | 注册地址 | 免费额度 | 单视频成本 |
|------|---------|---------|-----------|
| Kling (ModelsLab) | https://modelslab.com | 有 | ~$0.05-0.15 |
| Kling (官方) | https://klingai.com | 66 credits/天 | ~$0.035/秒 |
| Runway | https://runwayml.com | 125 credits一次性 | ~$0.50/秒 |
| Pika | https://pika.art | 80 credits/月 | ~$0.20/秒 |

## 自定义 Prompt

编辑 `prompts.json` 中每个 shot 的 `prompt` 和 `negative_prompt` 字段。
全局风格设置在 `style_guide` 字段中。
