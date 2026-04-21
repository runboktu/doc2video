#!/usr/bin/env python3
"""
千问文生图批量生成脚本

使用阿里云百炼平台 qwen-image-2.0-pro 模型，为分镜生成插画。

环境变量:
  DASHSCOPE_API_KEY — 阿里云百炼 API Key

用法:
  python generate_images.py              # 生成全部图片
  python generate_images.py --skip-existing  # 跳过已有图片
  python generate_images.py --shots S01 S02  # 只生成指定镜头
"""

import argparse
import json
import os
import sys
import time
import requests
from pathlib import Path

PROJECT_DIR = Path(__file__).parent
PROMPTS_FILE = PROJECT_DIR / "prompts.json"
IMAGES_DIR = PROJECT_DIR / "images"

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

    total = len(project["shots"])
    failed = 0

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
            failed += 1
            print(f"  ⚠️  {shot_id} 生成失败 ({failed} 失败 / {total} 总计)")

        time.sleep(5)

    succeeded = total - failed
    print(f"\n🎨 图片生成完成: {succeeded}/{total} 成功，保存在: {IMAGES_DIR}/")

    if failed > 0 and succeeded == 0:
        print(f"❌ 全部 {total} 个镜头生成失败，无法继续")
        sys.exit(1)
    elif failed > total // 2:
        print(f"⚠️  超过一半镜头 ({failed}/{total}) 生成失败，结果可能不理想")
        print(f"   可用 --no-skip 重试，或检查 API 配额和网络")

    return failed


def main():
    parser = argparse.ArgumentParser(description="千问文生图")
    parser.add_argument(
        "--shots", nargs="*", help="只生成指定镜头，如: --shots S01 S05"
    )
    parser.add_argument(
        "--skip-existing", action="store_true", default=True, help="跳过已有图片"
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

    api_key = os.environ.get("DASHSCOPE_API_KEY", "")
    if not api_key:
        print("⚠️  未设置 DASHSCOPE_API_KEY 环境变量")
        print("   export DASHSCOPE_API_KEY='sk-xxx'")
        print("   获取: https://bailian.console.aliyun.com/")
        sys.exit(1)

    print(f"{'=' * 60}")
    print(f"千问文生图")
    print(f"镜头数: {len(project['shots'])}")
    print(f"模型: {MODEL}")
    print(f"{'=' * 60}\n")

    generate_all_images(project, api_key, skip_existing)


if __name__ == "__main__":
    main()
