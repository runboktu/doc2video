# doc2video

**Automated document-to-video generation pipeline.** Transform Markdown articles into narrated videos with AI-generated visuals and burned-in subtitles.

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-3.9+-blue.svg)
![Rust](https://img.shields.io/badge/rust-1.70+-orange.svg)

## 🎯 What It Does

```
Markdown Article → TTS Audio → Storyboard → AI Images → Video Assembly → Final Video
```

1. **TTS Generation**: Uses `edge-tts` to generate natural-sounding Chinese narration with synchronized SRT subtitles
2. **Storyboard Creation**: DeepSeek LLM analyzes the article and SRT to create detailed shot-by-shot visual prompts
3. **AI Image Generation**: Alibaba DashScope/Qwen generates images for each shot based on prompts
4. **Video Assembly**: FFmpeg assembles clips, adjusts timing, and overlays audio
5. **Subtitle Burning**: PIL renders CJK-friendly subtitles as PNG overlays, FFmpeg burns them into the video

## 🚀 Quick Start

### Prerequisites

```bash
# Python 3.9+
brew install python@3.9

# Rust (for flow-run engine)
curl --proto '=https' --sh https://sh.rustup.rs -sSf | sh

# FFmpeg
brew install ffmpeg

# edge-tts
pip3 install edge-tts
```

### Install flow-run Engine

```bash
cd /path/to/flow-run
cargo build --release
export PATH=$PATH:/path/to/flow-run/target/release
```

### Run Your First Video

```bash
cd doc2video

# Run the complete workflow
DASHSCOPE_API_KEY=sk-xxx flow-run run doc-to-video.yaml \
  --input markdown_file=月夜-赏析.md

# Output: 月夜-赏析.mp4 (no subtitles)
#         月夜-赏析 -字幕版.mp4 (with burned subtitles)
```

## 📋 Configuration

### Workflow Inputs

| Parameter | Default | Description |
|-----------|---------|-------------|
| `markdown_file` | (required) | Path to input Markdown article |
| `voice` | `zh-CN-YunyangNeural` | edge-tts voice (e.g., `zh-TW-YunyangNeural`) |
| `rate` | `-10%` | Speech rate adjustment (e.g., `-10%`, `+20%`) |
| `pitch` | `-2Hz` | Pitch adjustment (e.g., `-2Hz`, `+5Hz`) |
| `max_shots` | `20` | Maximum number of shots/storyboards |
| `style` | `ink_wash` | Visual style: `ink_wash`, `modern`, `sketch` |
| `dashscope_api_key` | (required) | Alibaba DashScope API key for image generation |

### Visual Styles

| Style | Description |
|-------|-------------|
| `ink_wash` | Black-white ink wash painting, cold gray/dark blue tones, occasional striking red |
| `modern` | Modern flat vector, cold tones, geometric composition, tech feel |
| `sketch` | Pencil sketch texture, sepia tones, hand-drawn feel, vintage |

## 📁 Project Structure

```
doc2video/
├── doc-to-video.yaml      # Flow-run workflow definition (core)
├── burn_subs.py           # Subtitle burning script (PIL + FFmpeg)
├── video-project/
│   ├── generate_images.py # AI image generation via DashScope
│   ├── assemble.sh        # Video assembly and audio overlay
│   ├── prompts.json       # Generated storyboard prompts
│   ├── images/            # AI-generated images (S01.png, S02.png...)
│   └── clips/             # Video clips for each shot
├── lu-xun/                # Sample source materials (Lu Xun essays)
└── 月夜 -赏析.md           # Example input article
```

## 🔧 Workflow Steps

The pipeline executes 10 steps in 8 batches (parallel where possible):

```
Batch 1: setup                 → Initialize directories and paths
Batch 2: tts + read_md         → Generate audio/SRT + read article (parallel)
Batch 3: get_duration + read_srt → Get audio duration + read SRT (parallel)
Batch 4: generate_prompts      → DeepSeek generates storyboard JSON
Batch 5: write_prompts         → Validate and save prompts.json
Batch 6: gen_images            → DashScope generates images for all shots
Batch 7: assemble              → FFmpeg assembles clips + overlays audio
Batch 8: burn_subs             → Burn subtitles into final video
```

## 🛠️ Custom Scripts

### burn_subs.py

Burns SRT subtitles into video using PIL for CJK-friendly text rendering:

```bash
python3 burn_subs.py input.srt input.mp4 output.mp4
```

Features:
- Custom font support (Noto Sans CJK, Source Han Sans)
- Shadow effect for better readability
- Automatic positioning (bottom 15% of frame)
- Handles multi-line subtitles

### generate_images.py

Batch generates images using DashScope/Qwen API:

```bash
cd video-project
DASHSCOPE_API_KEY=sk-xxx python3 generate_images.py --skip-existing
```

### assemble.sh

Assembles video clips and overlays audio:

```bash
cd video-project
bash assemble.sh --skip-normalize
```

## 💰 API Costs

| Service | Provider | Cost | Notes |
|---------|----------|------|-------|
| TTS | edge-tts | Free | Microsoft Edge service |
| LLM | DeepSeek | ~$0.14/1M tokens | Storyboard generation |
| Images | DashScope/Qwen | ~$0.04/image | 1080p generation |
| Video | (optional) | Varies | If using AI video instead of images |

**Estimated cost per 5-minute video**: ~$2-5 (image generation only)

## 🔒 .gitignore

Media files are excluded by default:

- `*.mp3`, `*.wav`, `*.mp4` — Generated audio/video
- `.DS_Store` — macOS metadata
- `video-project/clips/` — Intermediate video clips
- `video-project/images/` — Generated images

Commit only source files: workflows, scripts, prompts, and Markdown articles.

## 📝 Example Input

```markdown
# 月夜 - 赏析

月光如流水一般，静静地泻在这一片叶子和花上...
```

The workflow extracts the article text, generates natural TTS narration, creates matching visuals, and produces a complete video.

## 🚨 Troubleshooting

### UTF-8 Encoding Issues

The flow-run engine has been patched for Chinese output. If you encounter encoding errors:

```bash
# Rebuild with UTF-8 fix
cd flow-run
cargo build --release
```

### DeepSeek JSON Output

DeepSeek may output Chinese explanations instead of pure JSON. The workflow uses a direct Python API call (bypassing flow-run's agent type) to ensure clean JSON output.

### FFmpeg Codec Issues

System FFmpeg may lack certain filters. The workflow uses PNG overlay method for subtitle burning, which works with vanilla FFmpeg.

## 📄 License

MIT License — see LICENSE file for details.

## 🙏 Acknowledgments

- [edge-tts](https://github.com/rany2/edge-tts) — Free TTS with Azure voices
- [FlowRun](https://github.com/runboktu/FlowRun) — DAG workflow engine
- [DeepSeek](https://deepseek.com/) — LLM for storyboard generation
- [DashScope](https://dashscope.aliyuncs.com/) — Alibaba AI image generation
