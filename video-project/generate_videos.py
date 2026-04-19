#!/usr/bin/env python3
"""
新铁屋记 — AI视频批量生成脚本

支持的 API 后端:
  1. Kling (官方 / ModelsLab 代理)
  2. Runway
  3. Pika

用法:
  # 1. 先生成关键帧图片（可选，提升视频一致性）
  python generate_videos.py --mode images --backend kling

  # 2. 用关键帧图片生成视频片段
  python generate_videos.py --mode videos --backend kling

  # 3. 一键全流程（图片+视频）
  python generate_videos.py --mode all --backend kling

环境变量:
  KLING_API_KEY   — Kling API 密钥
  RUNWAY_API_KEY  — Runway API 密钥（如用 Runway）
  PIKA_API_KEY    — Pika API 密钥（如用 Pika）
"""

import argparse
import json
import os
import sys
import time
import base64
import jwt
import requests
from pathlib import Path
from datetime import datetime

# ──────────────────────────────────────────────
# 配置
# ──────────────────────────────────────────────

PROJECT_DIR = Path(__file__).parent
PROMPTS_FILE = PROJECT_DIR / "prompts.json"
CLIPS_DIR = PROJECT_DIR / "clips"
IMAGES_DIR = PROJECT_DIR / "images"

CLIPS_DIR.mkdir(exist_ok=True)
IMAGES_DIR.mkdir(exist_ok=True)


def load_prompts() -> dict:
    with open(PROMPTS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


# ──────────────────────────────────────────────
# Kling API Backend
# ──────────────────────────────────────────────


class KlingBackend:
    """Kling AI 视频生成后端

    支持两种模式:
      1. Kling 官方 API (JWT 认证) — 设置 KLING_ACCESS_KEY + KLING_SECRET_KEY
      2. ModelsLab 代理 API — 设置 KLING_API_KEY

    环境变量:
      KLING_ACCESS_KEY  — Kling 官方 Access Key
      KLING_SECRET_KEY  — Kling 官方 Secret Key
      KLING_API_KEY     — ModelsLab API Key (代理模式)
      KLING_USE_OFFICIAL=1 — 强制使用官方 API
      KLING_API_DOMAIN  — API 域名: "global"(默认) 或 "china"(api-beijing.klingai.com)
    """

    def __init__(self):
        self.access_key = os.environ.get("KLING_ACCESS_KEY", "")
        self.secret_key = os.environ.get("KLING_SECRET_KEY", "")
        self.api_key = os.environ.get("KLING_API_KEY", "")
        self.use_official = os.environ.get("KLING_USE_OFFICIAL", "0") == "1"

        # 自动检测: 如果有 access_key + secret_key, 默认用官方 API
        if self.access_key and self.secret_key:
            self.use_official = True

        if self.use_official:
            if not self.access_key or not self.secret_key:
                print("⚠️  Kling 官方 API 需要 KLING_ACCESS_KEY 和 KLING_SECRET_KEY")
                print("   export KLING_ACCESS_KEY='your-access-key'")
                print("   export KLING_SECRET_KEY='your-secret-key'")
                sys.exit(1)
            domain = os.environ.get("KLING_API_DOMAIN", "global")
            if domain == "china":
                self.base_url = "https://api-beijing.klingai.com/v1"
            else:
                self.base_url = "https://api.klingai.com/v1"
            self._token = None
            self._token_exp = 0
            print(f"📡 使用 Kling 官方 API ({domain})")
        else:
            if not self.api_key:
                print("⚠️  未设置 KLING_API_KEY 或 KLING_ACCESS_KEY+KLING_SECRET_KEY")
                print("   export KLING_API_KEY='your-modelslab-key'")
                print("   export KLING_ACCESS_KEY='your-kling-access-key'")
                print("   export KLING_SECRET_KEY='your-kling-secret-key'")
                sys.exit(1)
            self.base_url = "https://modelslab.com/api/v6/video"
            print("📡 使用 ModelsLab API (wan2.2)")

    def _generate_jwt(self) -> str:
        """生成 Kling 官方 API JWT Token (HS256)"""
        now = time.time()
        if self._token and now < self._token_exp - 60:
            return self._token
        headers = {"alg": "HS256", "typ": "JWT"}
        payload = {
            "iss": self.access_key,
            "exp": int(now) + 1800,
            "nbf": int(now) - 5,
        }
        self._token = jwt.encode(payload, self.secret_key, headers=headers)
        self._token_exp = now + 1800
        return self._token

    def _headers(self):
        if self.use_official:
            return {
                "Authorization": f"Bearer {self._generate_jwt()}",
                "Content-Type": "application/json",
            }
        return {"Content-Type": "application/json"}

    def generate_image(
        self, prompt: str, negative_prompt: str = "", output_path: Path = None
    ) -> Path:
        print(f"  🎨 生成图片: {output_path.name}")

        if self.use_official:
            url = f"{self.base_url}/images/generations"
            payload = {
                "model": "kling-v1",
                "prompt": prompt,
                "negative_prompt": negative_prompt,
                "aspect_ratio": "16:9",
                "n": 1,
            }
            headers = self._headers()
        else:
            url = "https://modelslab.com/api/v4/realtime/text2img"
            payload = {
                "key": self.api_key,
                "model_id": "flux",
                "prompt": prompt,
                "negative_prompt": negative_prompt,
                "width": 1344,
                "height": 768,
                "samples": 1,
                "num_inference_steps": 30,
                "guidance_scale": 7.5,
            }
            headers = {"Content-Type": "application/json"}

        resp = requests.post(url, json=payload, headers=headers, timeout=120)
        resp.raise_for_status()
        data = resp.json()

        if data.get("status") == "error":
            print(f"  ❌ 图片生成失败: {data.get('message', '')}")
            return None

        image_url = None
        if self.use_official:
            images = data.get("data", [])
            if images:
                image_url = images[0].get("url")
        else:
            output = data.get("output", [])
            if output:
                image_url = (
                    output[0]
                    if isinstance(output[0], str)
                    else output[0].get("url")
                    if isinstance(output[0], dict)
                    else None
                )

        if not image_url:
            print(
                f"  ❌ 图片生成失败: {json.dumps(data, indent=2, ensure_ascii=False)[:500]}"
            )
            return None

        img_resp = requests.get(image_url, timeout=60)
        img_resp.raise_for_status()

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(img_resp.content)

        print(f"  ✅ 图片已保存: {output_path}")
        return output_path

    def generate_video(
        self,
        prompt: str,
        negative_prompt: str = "",
        duration: int = 5,
        image_path: Path = None,
        output_path: Path = None,
    ) -> Path:
        print(f"  🎬 生成视频: {output_path.name}")
        print(
            f"     时长: {duration}s, 参考图: {image_path.name if image_path else '无'}"
        )

        if self.use_official:
            return self._generate_video_official(
                prompt, negative_prompt, duration, image_path, output_path
            )
        return self._generate_video_modelslab(
            prompt, negative_prompt, duration, image_path, output_path
        )

    def _generate_video_modelslab(
        self, prompt, negative_prompt, duration, image_path, output_path
    ):
        if image_path and image_path.exists():
            url = f"{self.base_url}/img2video"
            with open(image_path, "rb") as f:
                img_b64 = base64.b64encode(f.read()).decode("utf-8")
            payload = {
                "key": self.api_key,
                "model_id": "wan2.2",
                "init_image": f"data:image/png;base64,{img_b64}",
                "prompt": prompt,
                "negative_prompt": negative_prompt,
                "width": 512,
                "height": 512,
                "num_frames": 25,
                "num_inference_steps": 20,
                "output_type": "mp4",
            }
        else:
            url = f"{self.base_url}/text2video"
            payload = {
                "key": self.api_key,
                "model_id": "wan2.2",
                "prompt": prompt,
                "negative_prompt": negative_prompt,
                "width": 512,
                "height": 512,
                "num_frames": 25,
                "num_inference_steps": 20,
                "guidance_scale": 7,
                "output_type": "mp4",
                "upscale_width": 1024,
                "upscale_height": 640,
            }

        resp = requests.post(url, json=payload, headers=self._headers(), timeout=120)
        resp.raise_for_status()
        data = resp.json()

        if data.get("status") == "error":
            print(f"  ❌ 请求失败: {data.get('message', '')}")
            return None

        video_url = self._extract_video_url(data)
        if video_url:
            return self._download_video(video_url, output_path)

        request_id = data.get("id") or data.get("task_id") or data.get("request_id")
        if request_id:
            return self._poll_modelslab(request_id, output_path)

        future_links = data.get("future_links", [])
        if future_links:
            return self._poll_url(future_links[0], output_path)

        print(
            f"  ❌ 无法解析响应: {json.dumps(data, indent=2, ensure_ascii=False)[:500]}"
        )
        return None

    def _poll_modelslab(self, request_id, output_path, max_wait=600, interval=10):
        print(f"  ⏳ 等待生成 (id: {request_id})")
        start = time.time()
        fetch_url = f"{self.base_url}/fetch/{request_id}"

        while time.time() - start < max_wait:
            resp = requests.post(
                fetch_url,
                json={"key": self.api_key},
                headers=self._headers(),
                timeout=30,
            )
            data = resp.json()
            status = data.get("status", "")

            if status == "success":
                video_url = self._extract_video_url(data)
                if video_url:
                    return self._download_video(video_url, output_path)
                print(f"  ❌ success 但无视频 URL: {json.dumps(data)[:300]}")
                return None
            elif status == "failed":
                print(f"  ❌ 生成失败: {data.get('message', '')}")
                return None

            elapsed = int(time.time() - start)
            print(f"  ⏳ 状态: {status} (已等 {elapsed}s)")
            time.sleep(interval)

        print(f"  ❌ 超时 ({max_wait}s)")
        return None

    def _poll_url(self, url, output_path, max_wait=600, interval=10):
        print(f"  ⏳ 轮询 future_link...")
        start = time.time()
        while time.time() - start < max_wait:
            resp = requests.get(url, timeout=30, allow_redirects=True)
            if resp.status_code == 200 and "video" in resp.headers.get(
                "content-type", ""
            ):
                output_path.parent.mkdir(parents=True, exist_ok=True)
                with open(output_path, "wb") as f:
                    f.write(resp.content)
                size_mb = output_path.stat().st_size / 1024 / 1024
                print(f"  ✅ 视频已保存: {output_path} ({size_mb:.1f}MB)")
                return output_path
            time.sleep(interval)
        print(f"  ❌ 超时")
        return None

    def _generate_video_official(
        self, prompt, negative_prompt, duration, image_path, output_path
    ):
        if image_path and image_path.exists():
            upload_url = f"{self.base_url}/images/upload"
            with open(image_path, "rb") as f:
                upload_resp = requests.post(
                    upload_url,
                    headers=self._headers(),
                    files={"file": f},
                    timeout=60,
                )
            upload_data = upload_resp.json()
            image_url = upload_data["data"]["url"]

            url = f"{self.base_url}/videos/image2video"
            payload = {
                "model": "kling-v2-master",
                "image": image_url,
                "prompt": prompt,
                "negative_prompt": negative_prompt,
                "duration": "5" if duration <= 5 else "10",
                "mode": "std",
                "aspect_ratio": "16:9",
            }
        else:
            url = f"{self.base_url}/videos/text2video"
            payload = {
                "model": "kling-v2-master",
                "prompt": prompt,
                "negative_prompt": negative_prompt,
                "duration": "5" if duration <= 5 else "10",
                "mode": "std",
                "aspect_ratio": "16:9",
            }

        try:
            resp = requests.post(
                url, json=payload, headers=self._headers(), timeout=120
            )
            resp.raise_for_status()
            data = resp.json()
        except requests.exceptions.HTTPError as e:
            error_body = resp.text[:300] if resp else str(e)
            print(f"  ❌ API 请求失败 (HTTP {resp.status_code}): {error_body}")
            if resp.status_code == 429:
                print("  ⚠️  账户余额不足，请充值后重试。")
            return None

        task_id = data.get("data", {}).get("task_id") or data.get("data", {}).get("id")
        if task_id:
            return self._poll_official(task_id, image_path is not None, output_path)

        code = data.get("code")
        if code and code != 0:
            print(f"  ❌ API 错误 (code={code}): {data.get('message', '')}")
            return None

        print(f"  ❌ 无法解析: {json.dumps(data, indent=2, ensure_ascii=False)[:500]}")
        return None

    def _poll_official(
        self, task_id, is_image2video, output_path, max_wait=600, interval=10
    ):
        endpoint = "image2video" if is_image2video else "text2video"
        print(f"  ⏳ 等待 Kling 官方生成 (task: {task_id[:16]}...)")
        start = time.time()
        while time.time() - start < max_wait:
            status_url = f"{self.base_url}/videos/{endpoint}/{task_id}"
            resp = requests.get(status_url, headers=self._headers(), timeout=30)
            data = resp.json()
            status = data.get("data", {}).get("task_status", "")
            if status == "succeed":
                videos = data["data"]["task_result"]["videos"]
                if videos:
                    return self._download_video(videos[0]["url"], output_path)
                print(f"  ❌ succeed 但无视频: {json.dumps(data)[:300]}")
                return None
            elif status == "failed":
                print(f"  ❌ 生成失败: {data}")
                return None
            elapsed = int(time.time() - start)
            print(f"  ⏳ 状态: {status} (已等 {elapsed}s)")
            time.sleep(interval)
        print(f"  ❌ 超时")
        return None

    def _extract_video_url(self, data: dict) -> str | None:
        output = data.get("output", [])
        if output:
            item = output[0]
            if isinstance(item, str):
                return item
            if isinstance(item, dict):
                return item.get("url")
        for key in ("video_url", "url", "video", "download_url"):
            if key in data:
                return data[key]
        return None

    def _download_video(self, url: str, output_path: Path) -> Path:
        print(f"  ⬇️  下载视频...")
        resp = requests.get(url, timeout=120, stream=True)
        resp.raise_for_status()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
        size_mb = output_path.stat().st_size / 1024 / 1024
        print(f"  ✅ 视频已保存: {output_path} ({size_mb:.1f}MB)")
        return output_path


# ──────────────────────────────────────────────
# Runway API Backend (备选)
# ──────────────────────────────────────────────


class RunwayBackend:
    """Runway Gen-4 API

    文档: https://docs.runwayml.com/
    """

    def __init__(self):
        self.api_key = os.environ.get("RUNWAY_API_KEY", "")
        if not self.api_key:
            print("⚠️  未设置 RUNWAY_API_KEY 环境变量")
            sys.exit(1)
        self.base_url = "https://api.runwayml.com/v1"
        print("📡 使用 Runway API")

    def _headers(self):
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "X-Runway-Version": "2024-11-06",
        }

    def generate_image(self, prompt, negative_prompt="", output_path=None):
        """Runway 暂无原生图片生成，跳过"""
        print("  ⚠️  Runway 暂不支持图片生成，跳过关键帧步骤")
        return None

    def generate_video(
        self, prompt, negative_prompt="", duration=5, image_path=None, output_path=None
    ):
        url = (
            f"{self.base_url}/image_to_video"
            if image_path
            else f"{self.base_url}/text_to_video"
        )
        payload = {
            "promptText": prompt,
            "model": "gen3a_turbo",
            "duration": min(duration, 10),
            "ratio": "16:9",
        }

        if image_path and image_path.exists():
            with open(image_path, "rb") as f:
                import base64

                img_b64 = base64.b64encode(f.read()).decode()
            payload["promptImage"] = f"data:image/png;base64,{img_b64}"

        resp = requests.post(url, json=payload, headers=self._headers(), timeout=120)
        resp.raise_for_status()
        data = resp.json()
        task_id = data.get("id")

        if not task_id:
            print(f"  ❌ 无法获取任务 ID: {data}")
            return None

        # 轮询
        print(f"  ⏳ 等待生成 (task: {task_id[:16]}...)")
        start = time.time()
        while time.time() - start < 600:
            status_resp = requests.get(
                f"{self.base_url}/tasks/{task_id}",
                headers=self._headers(),
                timeout=30,
            )
            status_data = status_resp.json()
            status = status_data.get("status", "")

            if status == "SUCCEEDED":
                video_url = status_data.get("output", [""])[0]
                if video_url:
                    resp = requests.get(video_url, timeout=120, stream=True)
                    resp.raise_for_status()
                    with open(output_path, "wb") as f:
                        for chunk in resp.iter_content(8192):
                            f.write(chunk)
                    size_mb = output_path.stat().st_size / 1024 / 1024
                    print(f"  ✅ 视频已保存: {output_path} ({size_mb:.1f}MB)")
                    return output_path
            elif status == "FAILED":
                print(f"  ❌ 生成失败: {status_data}")
                return None

            time.sleep(10)

        print(f"  ❌ 超时")
        return None


# ──────────────────────────────────────────────
# Pika API Backend (备选)
# ──────────────────────────────────────────────


class PikaBackend:
    """Pika 2.5 API"""

    def __init__(self):
        self.api_key = os.environ.get("PIKA_API_KEY", "")
        if not self.api_key:
            print("⚠️  未设置 PIKA_API_KEY 环境变量")
            sys.exit(1)
        self.base_url = "https://api.pika.art/v1"
        print("📡 使用 Pika API")

    def generate_image(self, prompt, negative_prompt="", output_path=None):
        print("  ⚠️  Pika 暂不支持图片生成，跳过关键帧步骤")
        return None

    def generate_video(
        self, prompt, negative_prompt="", duration=5, image_path=None, output_path=None
    ):
        url = f"{self.base_url}/generate"
        payload = {
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "duration": min(duration, 10),
            "resolution": "1080p",
            "aspect_ratio": "16:9",
        }

        if image_path and image_path.exists():
            with open(image_path, "rb") as f:
                import base64

                img_b64 = base64.b64encode(f.read()).decode()
            payload["image"] = f"data:image/png;base64,{img_b64}"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        resp = requests.post(url, json=payload, headers=headers, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        task_id = data.get("id")

        if not task_id:
            video_url = data.get("url") or data.get("video_url")
            if video_url:
                resp = requests.get(video_url, timeout=120, stream=True)
                resp.raise_for_status()
                with open(output_path, "wb") as f:
                    for chunk in resp.iter_content(8192):
                        f.write(chunk)
                print(f"  ✅ 视频已保存: {output_path}")
                return output_path
            print(f"  ❌ 无法解析: {data}")
            return None

        # 轮询
        print(f"  ⏳ 等待生成 (task: {task_id[:16]}...)")
        start = time.time()
        while time.time() - start < 600:
            r = requests.get(
                f"{self.base_url}/status/{task_id}", headers=headers, timeout=30
            )
            d = r.json()
            if d.get("status") in ("completed", "done"):
                video_url = d.get("url") or d.get("video_url")
                if video_url:
                    resp = requests.get(video_url, timeout=120, stream=True)
                    resp.raise_for_status()
                    with open(output_path, "wb") as f:
                        for chunk in resp.iter_content(8192):
                            f.write(chunk)
                    print(f"  ✅ 视频已保存: {output_path}")
                    return output_path
            elif d.get("status") == "failed":
                print(f"  ❌ 失败: {d}")
                return None
            time.sleep(10)

        print(f"  ❌ 超时")
        return None


# ──────────────────────────────────────────────
# 主流程
# ──────────────────────────────────────────────

BACKENDS = {
    "kling": KlingBackend,
    "runway": RunwayBackend,
    "pika": PikaBackend,
}


def generate_images(project: dict, backend):
    """为每个分镜生成关键帧图片"""
    for shot in project["shots"]:
        shot_id = shot["id"]
        prompt = shot["prompt"]
        negative = shot.get("negative_prompt", "")

        output_path = IMAGES_DIR / f"{shot_id}_keyframe.png"

        if output_path.exists():
            print(f"  ⏭️  跳过已有图片: {output_path.name}")
            continue

        result = backend.generate_image(
            prompt=f"Editorial illustration, ink wash painting style. {prompt} Single frame, cinematic composition, 16:9 aspect ratio, high contrast black and white with cold blue-grey tones.",
            negative_prompt=f"photorealistic, 3D render, cartoon, anime. {negative}",
            output_path=output_path,
        )

        if not result:
            print(f"  ⚠️  {shot_id} 图片生成失败，将使用纯文本模式生成视频")

        # 限流: 避免触发 API rate limit
        time.sleep(3)

    print(f"\n🎨 关键帧图片生成完成，保存在: {IMAGES_DIR}/")


def generate_videos(project: dict, backend):
    """为每个分镜批量生成视频片段"""
    total_clips = sum(s["clips_needed"] for s in project["shots"])
    current = 0

    for shot in project["shots"]:
        shot_id = shot["id"]
        clips_needed = shot["clips_needed"]
        prompt = shot["prompt"]
        negative = shot.get("negative_prompt", "")

        print(f"\n{'=' * 60}")
        print(f"📹 {shot_id} | {shot['timestamp']} | 需要 {clips_needed} 个片段")
        print(f"{'=' * 60}")

        # 检查参考图片
        keyframe = IMAGES_DIR / f"{shot_id}_keyframe.png"

        for clip_idx in range(clips_needed):
            current += 1
            clip_name = f"{shot_id}_clip{clip_idx + 1:02d}.mp4"
            output_path = CLIPS_DIR / clip_name

            if output_path.exists():
                print(f"  [{current}/{total_clips}] ⏭️  跳过已有: {clip_name}")
                continue

            print(f"\n  [{current}/{total_clips}] 生成 {clip_name}")

            # 第一个片段用参考图片（如有），后续片段纯文本
            use_image = keyframe if (clip_idx == 0 and keyframe.exists()) else None

            result = backend.generate_video(
                prompt=f"Cinematic slow camera movement. {prompt} Ink wash painting aesthetic, editorial illustration style, atmospheric, moody lighting.",
                negative_prompt=f"photorealistic, 3D render, cartoon. {negative}",
                duration=5,
                image_path=use_image,
                output_path=output_path,
            )

            if not result:
                print(f"  ❌ {clip_name} 生成失败，将跳过")

            # 限流
            time.sleep(5)

    print(f"\n\n🎬 全部视频片段生成完成！保存在: {CLIPS_DIR}/")
    print(f"   总计: {total_clips} 个片段")

    # 生成 ffmpeg concat 文件列表
    generate_concat_file(project)


def generate_videos_ffmpeg(project: dict, skip_existing: bool = True):
    """用 ffmpeg zoompan 将静态图片生成视频（慢速推近效果）

    从 prompts.json 的 default_params 读取视频参数:
      - resolution: "1080p" / "720p" / "480p"
      - fps: 帧率
      - aspect_ratio: "16:9" / "4:3" / "1:1"
    """
    import subprocess
    import math

    dp = project.get("default_params", {})
    fps = dp.get("fps", 24)
    aspect = dp.get("aspect_ratio", "16:9")

    resolution_map = {
        ("1080p", "16:9"): (1920, 1080),
        ("1080p", "4:3"):  (1440, 1080),
        ("720p",  "16:9"): (1280, 720),
        ("720p",  "4:3"):  (960, 720),
        ("480p",  "16:9"): (854, 480),
        ("480p",  "4:3"):  (640, 480),
    }
    res_name = dp.get("resolution", "1080p")
    width, height = resolution_map.get((res_name, aspect), (1920, 1080))

    print(f"📹 ffmpeg 模式 | 分辨率: {width}x{height} | FPS: {fps} | 比例: {aspect}")

    total = len(project["shots"])

    for idx, shot in enumerate(project["shots"], 1):
        shot_id = shot["id"]
        duration = shot["duration_sec"]
        total_frames = int(duration * fps)

        image_path = IMAGES_DIR / f"{shot_id}.png"
        output_path = CLIPS_DIR / f"{shot_id}.mp4"

        print(f"\n{'─' * 50}")
        print(f"  [{idx}/{total}] {shot_id} | {shot['timestamp']} | {duration:.1f}s ({total_frames} frames)")

        if not image_path.exists():
            alt_path = IMAGES_DIR / f"{shot_id}_keyframe.png"
            if alt_path.exists():
                image_path = alt_path
            else:
                print(f"  ⚠️  缺少图片: {image_path.name}，跳过")
                continue

        if skip_existing and output_path.exists():
            size_mb = output_path.stat().st_size / 1024 / 1024
            print(f"  ⏭️  跳过已有: {output_path.name} ({size_mb:.1f}MB)")
            continue

        # scale 到 2x 目标分辨率（crop 居中裁切），zoompan 操作后再 scale 回来
        # 2x 分辨率让 zoompan 整数取整误差 < 0.5 物理像素，消除抖动
        max_zoom = 1.2
        zoom_speed = (max_zoom - 1.0) / total_frames if total_frames > 0 else 0.001
        iw, ih = width * 2, height * 2
        vf = (
            f"scale={iw}:{ih}:force_original_aspect_ratio=increase,"
            f"crop={iw}:{ih},"
            f"zoompan=z='min(zoom+{zoom_speed:.6f},{max_zoom})'"
            f":x='iw/2-(iw/zoom)/2':y='ih/2-(ih/zoom)/2'"
            f":d={total_frames}:s={iw}x{ih}:fps={fps},"
            f"scale={width}:{height}"
        )

        cmd = [
            "ffmpeg", "-y",
            "-loop", "1",
            "-i", str(image_path),
            "-vf", vf,
            "-t", str(duration),
            "-c:v", "libx264",
            "-preset", "medium",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            str(output_path),
        ]

        print(f"  🎬 生成中...")
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=300
        )

        if result.returncode != 0:
            print(f"  ❌ ffmpeg 失败:")
            print(f"     {result.stderr[-300:]}")
            continue

        size_mb = output_path.stat().st_size / 1024 / 1024
        print(f"  ✅ {output_path.name} ({size_mb:.1f}MB)")

    print(f"\n\n🎬 ffmpeg 视频生成完成！保存在: {CLIPS_DIR}/")
    generate_concat_file(project, mode="ffmpeg")


def generate_concat_file(project: dict, mode: str = "api"):
    """生成 ffmpeg concat 需要的文件列表

    mode="api":    按 clips_needed 拆分 (S01_clip01.mp4, S01_clip02.mp4, ...)
    mode="ffmpeg": 每个 shot 一个视频 (S01.mp4, S02.mp4, ...)
    """
    concat_path = PROJECT_DIR / "concat_list.txt"

    with open(concat_path, "w", encoding="utf-8") as f:
        for shot in project["shots"]:
            shot_id = shot["id"]
            if mode == "ffmpeg":
                clip_path = CLIPS_DIR / f"{shot_id}.mp4"
                if clip_path.exists():
                    f.write(f"file '{clip_path}'\n")
                else:
                    print(f"  ⚠️  缺少片段: {shot_id}.mp4")
            else:
                clips_needed = shot["clips_needed"]
                for clip_idx in range(clips_needed):
                    clip_name = f"{shot_id}_clip{clip_idx + 1:02d}.mp4"
                    clip_path = CLIPS_DIR / clip_name
                    if clip_path.exists():
                        f.write(f"file '{clip_path}'\n")
                    else:
                        print(f"  ⚠️  缺少片段: {clip_name}")

    print(f"\n📝 ffmpeg concat 列表已生成: {concat_path}")


def main():
    parser = argparse.ArgumentParser(
        description="doc2video — AI视频批量生成",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # ffmpeg 模式：静态图推近生成视频（零成本，无需 API）
  python generate_videos.py --mode ffmpeg

  # 生成关键帧图片 + 视频片段（全流程，需 API）
  python generate_videos.py --mode all --backend kling

  # 只生成视频片段（如果已有图片，需 API）
  python generate_videos.py --mode videos --backend kling

  # 只生成特定镜头
  python generate_videos.py --mode ffmpeg --shots S01 S02 S03

  # 使用 Runway
  python generate_videos.py --mode all --backend runway
        """,
    )
    parser.add_argument(
        "--mode",
        choices=["images", "videos", "ffmpeg", "all"],
        default="all",
        help="生成模式: images(只生成图片), videos(API视频), ffmpeg(本地推近), all(图片+API视频)",
    )
    parser.add_argument(
        "--backend",
        choices=list(BACKENDS.keys()),
        default="kling",
        help="API 后端 (ffmpeg 模式忽略此参数)",
    )
    parser.add_argument(
        "--shots",
        nargs="*",
        help="只生成指定镜头，如: --shots S01 S05 S14",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        default=True,
        help="跳过已存在的视频文件 (默认开启)",
    )

    args = parser.parse_args()

    project = load_prompts()

    if args.shots:
        project["shots"] = [s for s in project["shots"] if s["id"] in args.shots]
        print(f"🎯 指定镜头: {args.shots}")

    dp = project.get("default_params", {})
    print(f"{'=' * 60}")
    print(f"doc2video — 视频批量生成")
    print(f"项目: {project.get('project', 'N/A')}")
    print(f"镜头数: {len(project['shots'])}")
    print(f"模式: {args.mode}")
    if args.mode != "ffmpeg":
        print(f"后端: {args.backend}")
    print(f"参数: {dp.get('resolution', 'N/A')} / {dp.get('fps', 'N/A')}fps / {dp.get('aspect_ratio', 'N/A')}")
    print(f"{'=' * 60}\n")

    if args.mode == "ffmpeg":
        generate_videos_ffmpeg(project, skip_existing=args.skip_existing)
    else:
        backend = BACKENDS[args.backend]()

        if args.mode in ("images", "all"):
            generate_images(project, backend)

        if args.mode in ("videos", "all"):
            generate_videos(project, backend)

    print("\n✅ 完成！下一步:")
    print("   bash assemble.sh  # 拼接视频 + 叠加音频")


if __name__ == "__main__":
    main()
