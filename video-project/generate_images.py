#!/usr/bin/env python3
"""
千问文生图 + 图生视频 批量生成脚本

模式:
  images  — 文生图（千问 qwen-image-2.0-pro）
  videos  — 图生视频（FFmpeg Ken Burns / AI 接口）
  all     — 先文生图，再图生视频

环境变量:
  DASHSCOPE_API_KEY — 阿里云百炼 API Key（文生图需要）

用法:
  python generate_images.py --mode all                  # 全流程
  python generate_images.py --mode images               # 只生成图片
  python generate_images.py --mode videos               # 只生成视频
  python generate_images.py --mode videos --video-backend ai  # 用 AI 接口（暂未实现）
  python generate_images.py --shots S01 S02             # 只处理指定镜头
  python generate_images.py --skip-existing             # 跳过已有文件
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import http.client
import urllib.parse

PROJECT_DIR = Path(__file__).parent
PROMPTS_FILE = PROJECT_DIR / "prompts.json"
IMAGES_DIR = PROJECT_DIR / "images"
CLIPS_DIR = PROJECT_DIR / "clips"

IMAGES_DIR.mkdir(exist_ok=True)
CLIPS_DIR.mkdir(exist_ok=True)

API_URL = "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
MODEL = "qwen-image-2.0-pro"
IMAGE_SIZE = "1792*1024"

# Ken Burns 方向参数（5 种运动模式循环）
KB_DIRECTIONS = [
    ("iw", "ih"),       # 右下
    ("0", "0"),         # 左上
    ("iw*0.15", "0"),   # 右上
    ("0", "ih*0.15"),   # 左下
    ("iw*0.15", "ih*0.15"),  # 右下（短距）
]


# ═══════════════════════════════════════════
# 文生图
# ═══════════════════════════════════════════

def load_prompts() -> dict:
    with open(PROMPTS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _http_post_json(url: str, payload: dict, headers: dict, timeout: int = 120) -> tuple[int, dict]:
    """用 http.client 发送 POST JSON，返回 (status_code, json_dict)。"""
    parsed = urllib.parse.urlparse(url)
    host = parsed.hostname
    path = parsed.path or "/"
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    conn = http.client.HTTPSConnection(host, timeout=timeout)
    try:
        conn.request("POST", path, body=body, headers=headers)
        resp = conn.getresponse()
        data = json.loads(resp.read().decode("utf-8"))
        return resp.status, data
    finally:
        conn.close()


def _http_download(url: str, timeout: int = 60) -> bytes | None:
    """用 http.client 下载文件内容。"""
    parsed = urllib.parse.urlparse(url)
    host = parsed.hostname
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query

    conn = http.client.HTTPSConnection(host, timeout=timeout)
    try:
        conn.request("GET", path)
        resp = conn.getresponse()
        if resp.status != 200:
            print(f"  ❌ 下载 HTTP {resp.status}")
            return None
        return resp.read()
    except Exception as e:
        print(f"  ❌ 下载失败: {e}")
        return None
    finally:
        conn.close()


def generate_image(
    prompt: str,
    negative_prompt: str,
    output_path: Path,
    api_key: str,
    max_retries: int = 3,
) -> Path | None:
    """调用千问 API 生成单张图片。"""
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
            status_code, data = _http_post_json(API_URL, payload, headers, timeout=120)
        except Exception as e:
            print(f"  ❌ 网络错误: {e}")
            return None

        if status_code == 429:
            wait = 15 * (attempt + 1)
            print(f"  ⏳ 限流，等待 {wait}s 后重试 ({attempt + 1}/{max_retries})...")
            time.sleep(wait)
            continue

        if status_code != 200:
            print(f"  ❌ API 错误 (HTTP {status_code}): {json.dumps(data, ensure_ascii=False)[:300]}")
            return None
        break
    else:
        print(f"  ❌ 重试 {max_retries} 次后仍被限流")
        return None

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

    img_bytes = _http_download(image_url)
    if not img_bytes:
        return None

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(img_bytes)

    size_kb = output_path.stat().st_size / 1024
    print(f"  ✅ 已保存: {output_path.name} ({size_kb:.0f}KB)")
    return output_path


def generate_all_images(project: dict, api_key: str, skip_existing: bool = True) -> int:
    """批量文生图。返回失败数量。"""
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


# ═══════════════════════════════════════════
# 图生视频
# ═══════════════════════════════════════════

def generate_video_ffmpeg(
    image_path: Path,
    output_path: Path,
    duration: float,
    direction_index: int = 0,
) -> Path | None:
    """用 FFmpeg zoompan 把静态图转成 Ken Burns 动效视频。"""
    dx, dy = KB_DIRECTIONS[direction_index % len(KB_DIRECTIONS)]
    frames = int(duration * 25)

    zoom_filter = (
        f"scale=8000:-1,"
        f"zoompan=z='min(zoom+0.0003,1.5)':"
        f"x='{dx}':y='{dy}':"
        f"d={frames}:s=1792x1024:fps=25"
    )

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1",
        "-i", str(image_path),
        "-t", str(duration),
        "-vf", zoom_filter,
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-r", "25",
        str(output_path),
    ]

    print(f"  🎞️  生成视频: {output_path.name} ({duration}s, 方向={direction_index})")

    try:
        result = subprocess.run(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            timeout=300,
        )
        if result.returncode != 0:
            print(f"  ❌ FFmpeg 失败: {result.stderr[:300]}")
            return None
    except subprocess.TimeoutExpired:
        print(f"  ❌ FFmpeg 超时 (>{300}s)")
        return None
    except FileNotFoundError:
        print(f"  ❌ 找不到 ffmpeg，请先安装: brew install ffmpeg")
        sys.exit(1)

    size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"  ✅ 已保存: {output_path.name} ({size_mb:.1f}MB)")
    return output_path


def generate_video_ai(
    image_path: Path,
    output_path: Path,
    duration: float,
) -> Path | None:
    """调用 AI 接口生成视频（空实现，待接入具体 API）。"""
    print(f"  ⏳ AI 图生视频暂未实现: {output_path.name}")
    print(f"     可接入 Kling / Runway / Pika 等 API")
    return None


def generate_all_videos(
    project: dict,
    backend: str = "ffmpeg",
    skip_existing: bool = True,
) -> int:
    """批量图生视频。返回失败数量。"""
    total = len(project["shots"])
    failed = 0

    for i, shot in enumerate(project["shots"]):
        shot_id = shot["id"]
        duration = shot.get("duration_sec", 30)
        image_path = IMAGES_DIR / f"{shot_id}.png"
        output_path = CLIPS_DIR / f"{shot_id}.mp4"

        if not image_path.exists():
            print(f"  ⚠️  缺少图片: {image_path.name}，跳过")
            failed += 1
            continue

        if skip_existing and output_path.exists():
            print(f"  ⏭️  跳过已有: {output_path.name}")
            continue

        if backend == "ai":
            result = generate_video_ai(image_path, output_path, duration)
        else:
            result = generate_video_ffmpeg(image_path, output_path, duration, direction_index=i)

        if not result:
            failed += 1
            print(f"  ⚠️  {shot_id} 视频生成失败 ({failed} 失败 / {total} 总计)")

    succeeded = total - failed
    print(f"\n🎞️  视频生成完成: {succeeded}/{total} 成功，保存在: {CLIPS_DIR}/")

    if failed > 0 and succeeded == 0:
        print(f"❌ 全部 {total} 个镜头视频生成失败")
        sys.exit(1)

    return failed


# ═══════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="千问文生图 + 图生视频",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python generate_images.py --mode all              # 全流程：图片 + 视频
  python generate_images.py --mode images            # 只生成图片
  python generate_images.py --mode videos            # 只生成视频（需要已有图片）
  python generate_images.py --mode videos --video-backend ai  # AI 接口（暂未实现）
  python generate_images.py --shots S01 S03          # 只处理指定镜头
        """,
    )
    parser.add_argument(
        "--mode",
        choices=["images", "videos", "all"],
        default="all",
        help="运行模式: images=文生图, videos=图生视频, all=先图后视 (默认: all)",
    )
    parser.add_argument(
        "--video-backend",
        choices=["ffmpeg", "ai"],
        default="ffmpeg",
        help="图生视频后端: ffmpeg=Ken Burns 动效 (默认), ai=AI 接口 (暂未实现)",
    )
    parser.add_argument(
        "--shots", nargs="*", help="只处理指定镜头，如: --shots S01 S05"
    )
    parser.add_argument(
        "--skip-existing", action="store_true", default=True, help="跳过已有文件 (默认开启)"
    )
    parser.add_argument(
        "--no-skip", action="store_true", help="不跳过已有文件，强制重新生成"
    )
    args = parser.parse_args()

    project = load_prompts()

    if args.shots:
        project["shots"] = [s for s in project["shots"] if s["id"] in args.shots]
        print(f"🎯 指定镜头: {args.shots}")

    skip_existing = args.skip_existing and not args.no_skip

    mode_label = {"images": "文生图", "videos": "图生视频", "all": "全流程"}[args.mode]
    print(f"{'=' * 60}")
    print(f"镜头数: {len(project['shots'])}")
    print(f"模式: {mode_label}")
    if args.mode in ("videos", "all"):
        print(f"视频后端: {args.video_backend}")
    print(f"{'=' * 60}\n")

    # ── 文生图 ──
    if args.mode in ("images", "all"):
        api_key = os.environ.get("DASHSCOPE_API_KEY", "")
        if not api_key:
            print("⚠️  未设置 DASHSCOPE_API_KEY 环境变量")
            print("   export DASHSCOPE_API_KEY='sk-xxx'")
            print("   获取: https://bailian.console.aliyun.com/")
            sys.exit(1)

        print(f"🎨 文生图 (模型: {MODEL})\n")
        generate_all_images(project, api_key, skip_existing)

    # ── 图生视频 ──
    if args.mode in ("videos", "all"):
        print(f"\n🎞️  图生视频 (后端: {args.video_backend})\n")
        generate_all_videos(project, backend=args.video_backend, skip_existing=skip_existing)

    print(f"\n✅ 全部完成")


if __name__ == "__main__":
    main()
