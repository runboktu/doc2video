#!/usr/bin/env python3
"""
月夜-赏析记 — 千问文生图批量生成脚本

使用阿里云百炼平台 qwen-image-2.0-pro 模型，为17个分镜生成插画。
然后将图片与音频合并为最终视频。

环境变量:
  DASHSCOPE_API_KEY — 阿里云百炼 API Key

用法:
  python generate_images.py              # 生成全部图片
  python generate_images.py --shots S01 S02  # 只生成指定镜头
  python generate_images.py --skip-existing  # 跳过已有图片
  python generate_images.py --assemble       # 只执行合并（不生成图片）
"""

import argparse
import json
import os
import subprocess
import sys
import time
import requests
from pathlib import Path

PROJECT_DIR = Path(__file__).parent
PROMPTS_FILE = PROJECT_DIR / "prompts.json"
IMAGES_DIR = PROJECT_DIR / "images"
AUDIO_FILE = PROJECT_DIR.parent / "月夜-赏析.wav"
OUTPUT_VIDEO = PROJECT_DIR / "月夜-赏析.mp4"

IMAGES_DIR.mkdir(exist_ok=True)

API_URL = "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
MODEL = "qwen-image-2.0-pro"
IMAGE_SIZE = "1792*1024"


def load_prompts() -> dict:
    with open(PROMPTS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def generate_image(
    prompt: str,
    negative_prompt: str,
    output_path: Path,
    api_key: str,
    max_retries: int = 3,
) -> Path | None:
    print(f"  🎨 生成图片: {output_path.name}")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": MODEL,
        "input": {
            "messages": [
                {
                    "role": "user",
                    "content": [{"text": prompt}],
                }
            ]
        },
        "parameters": {
            "size": IMAGE_SIZE,
            "n": 1,
            "prompt_extend": True,
            "watermark": False,
        },
    }
    if negative_prompt:
        payload["parameters"]["negative_prompt"] = negative_prompt

    for attempt in range(max_retries):
        try:
            resp = requests.post(API_URL, json=payload, headers=headers, timeout=120)
        except requests.exceptions.RequestException as e:
            print(f"  ❌ 网络错误: {e}")
            return None

        if resp.status_code == 429:
            wait = 15 * (attempt + 1)
            print(f"  ⏳ 限流，等待 {wait}s 后重试 ({attempt + 1}/{max_retries})...")
            time.sleep(wait)
            continue

        if resp.status_code != 200:
            print(f"  ❌ API 错误 (HTTP {resp.status_code}): {resp.text[:300]}")
            return None
        break
    else:
        print(f"  ❌ 重试 {max_retries} 次后仍被限流")
        return None

    data = resp.json()

    image_url = None
    choices = data.get("output", {}).get("choices", [])
    if choices:
        content = choices[0].get("message", {}).get("content", [])
        for item in content:
            if "image" in item:
                image_url = item["image"]
                break

    if not image_url:
        print(f"  ❌ 无法提取图片 URL: {json.dumps(data, ensure_ascii=False)[:300]}")
        return None

    try:
        img_resp = requests.get(image_url, timeout=60)
        img_resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"  ❌ 下载失败: {e}")
        return None

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(img_resp.content)

    size_kb = output_path.stat().st_size / 1024
    print(f"  ✅ 已保存: {output_path.name} ({size_kb:.0f}KB)")
    return output_path


def generate_all_images(project: dict, api_key: str, skip_existing: bool = True):
    style_prefix = "黑白水墨画风格插画，冷灰色调，素描质感。"
    style_suffix = " 编辑插画风格，电影感构图，16:9横版。"
    neg_common = "照片级写实, 3D渲染, 卡通, 动漫, 亮丽色彩, 鲜艳"

    for shot in project["shots"]:
        shot_id = shot["id"]
        output_path = IMAGES_DIR / f"{shot_id}.png"

        if skip_existing and output_path.exists():
            print(f"  ⏭️  跳过已有: {output_path.name}")
            continue

        prompt = style_prefix + shot["prompt"] + style_suffix
        negative = f"{neg_common}, {shot.get('negative_prompt', '')}"

        result = generate_image(prompt, negative, output_path, api_key)
        if not result:
            print(f"  ⚠️  {shot_id} 生成失败，稍后重试")

        time.sleep(5)

    print(f"\n🎨 图片生成完成，保存在: {IMAGES_DIR}/")


def assemble_video(project: dict):
    if not AUDIO_FILE.exists():
        print(f"❌ 音频文件不存在: {AUDIO_FILE}")
        sys.exit(1)

    total_duration = project["total_duration_sec"]
    print(f"\n🎬 合并视频...")
    print(f"   音频: {AUDIO_FILE}")
    print(f"   总时长: {total_duration}s")
    print(f"   镜头数: {len(project['shots'])}")

    shots_data = []
    for shot in project["shots"]:
        img_path = IMAGES_DIR / f"{shot['id']}.png"
        if not img_path.exists():
            print(f"  ⚠️  缺少图片: {shot['id']}.png，跳过")
            continue
        shots_data.append(
            {
                "id": shot["id"],
                "image": str(img_path),
                "duration": shot["duration_sec"],
                "timestamp": shot["timestamp"],
            }
        )

    if not shots_data:
        print("❌ 没有可用的图片")
        sys.exit(1)

    clips_dir = PROJECT_DIR / "clips"
    clips_dir.mkdir(exist_ok=True)

    clip_files = []
    for i, shot in enumerate(shots_data):
        clip_path = clips_dir / f"{shot['id']}.mp4"
        clip_files.append(str(clip_path))

        if clip_path.exists():
            print(f"  ⏭️  跳过已有片段: {clip_path.name}")
            continue

        duration = shot["duration"]
        img = shot["image"]
        directions = [
            ("iw", "ih", "(iw*1.15)", "(ih*1.15)"),
            ("0", "0", "(iw*0.85)", "(ih*0.85)"),
            ("iw*0.15", "0", "iw", "(ih*0.85)"),
            ("0", "ih*0.15", "(iw*0.85)", "ih"),
            ("iw*0.15", "ih*0.15", "iw", "ih"),
        ]
        d = directions[i % len(directions)]
        zoom_filter = (
            f"scale=8000:-1,"
            f"zoompan=z='min(zoom+0.0003,1.5)':"
            f"x='{d[0]}':y='{d[1]}':"
            f"d={int(duration * 25)}:s=1792x1024:fps=25"
        )

    if not shots_data:
        print("❌ 没有可用的图片")
        sys.exit(1)

    # 为每个镜头生成带 Ken Burns 效果的视频片段
    clips_dir = PROJECT_DIR / "clips"
    clips_dir.mkdir(exist_ok=True)

    clip_files = []
    for i, shot in enumerate(shots_data):
        clip_path = clips_dir / f"{shot['id']}.mp4"
        clip_files.append(str(clip_path))

        if clip_path.exists():
            print(f"  ⏭️  跳过已有片段: {clip_path.name}")
            continue

        duration = shot["duration"]
        img = shot["image"]

        # Ken Burns: 从 100% 缓慢放大到 115%，轻微平移
        # 每个镜头用不同的运动方向
        directions = [
            ("iw", "ih", "(iw*1.15)", "(ih*1.15)"),  # zoom in center
            ("0", "0", "(iw*0.85)", "(ih*0.85)"),  # zoom out from top-left
            ("iw*0.15", "0", "iw", "(ih*0.85)"),  # zoom out from top-right
            ("0", "ih*0.15", "(iw*0.85)", "ih"),  # zoom out from bottom-left
            ("iw*0.15", "ih*0.15", "iw", "ih"),  # zoom out from bottom-right
        ]
        d = directions[i % len(directions)]
        zoom_filter = (
            f"scale=8000:-1,"
            f"zoompan=z='min(zoom+0.0003,1.5)':"
            f"x='{d[0]}':y='{d[1]}':"
            f"d={int(duration * 25)}:s=1792x1024:fps=25"
        )

        cmd = [
            "ffmpeg",
            "-y",
            "-loop",
            "1",
            "-i",
            img,
            "-t",
            str(duration),
            "-vf",
            zoom_filter,
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "23",
            "-pix_fmt",
            "yuv420p",
            "-r",
            "25",
            str(clip_path),
        ]
        print(f"  🎞️  生成片段: {clip_path.name} ({duration}s)")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"  ❌ ffmpeg 失败: {result.stderr[:200]}")
            sys.exit(1)

    concat_file = PROJECT_DIR / "concat_list.txt"
    with open(concat_file, "w", encoding="utf-8") as f:
        for clip in clip_files:
            f.write(f"file '{clip}'\n")

    concat_video = PROJECT_DIR / "concat_video.mp4"
    print(f"\n🔗 拼接 {len(clip_files)} 个片段...")
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_file),
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        str(concat_video),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ❌ 拼接失败: {result.stderr[:200]}")
        sys.exit(1)

    print(f"🎵 叠加音频...")
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(concat_video),
        "-i",
        str(AUDIO_FILE),
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-shortest",
        str(OUTPUT_VIDEO),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ❌ 叠加音频失败: {result.stderr[:200]}")
        sys.exit(1)

    concat_video.unlink(missing_ok=True)

    size_mb = OUTPUT_VIDEO.stat().st_size / 1024 / 1024
    print(f"\n✅ 视频生成完成！")
    print(f"   📁 {OUTPUT_VIDEO}")
    print(f"   📦 {size_mb:.1f}MB")


def main():
    parser = argparse.ArgumentParser(description="月夜-赏析 — 千问文生图 + 视频合并")
    parser.add_argument(
        "--shots", nargs="*", help="只生成指定镜头，如: --shots S01 S05"
    )
    parser.add_argument(
        "--skip-existing", action="store_true", default=True, help="跳过已有图片"
    )
    parser.add_argument(
        "--assemble", action="store_true", help="只执行视频合并（不生成图片）"
    )
    parser.add_argument(
        "--no-skip", action="store_true", help="不跳过已有图片，强制重新生成"
    )
    args = parser.parse_args()

    project = load_prompts()

    if args.shots:
        project["shots"] = [s for s in project["shots"] if s["id"] in args.shots]
        print(f"🎯 指定镜头: {args.shots}")

    skip_existing = args.skip_existing and not args.no_skip

    print(f"{'=' * 60}")
    print(f"月夜-赏析 — 千问文生图")
    print(f"镜头数: {len(project['shots'])}")
    print(f"模型: {MODEL}")
    print(f"{'=' * 60}\n")

    if not args.assemble:
        api_key = os.environ.get("DASHSCOPE_API_KEY", "")
        if not api_key:
            print("⚠️  未设置 DASHSCOPE_API_KEY 环境变量")
            print("   export DASHSCOPE_API_KEY='sk-xxx'")
            print("   获取: https://bailian.console.aliyun.com/")
            sys.exit(1)
        generate_all_images(project, api_key, skip_existing)

    assemble_video(project)


if __name__ == "__main__":
    main()
