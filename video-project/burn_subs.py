#!/usr/bin/env python3
"""Burn SRT subtitles into video using PIL + ffmpeg overlay."""

import re
import os
import sys
import subprocess
import tempfile
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

SRT_PATH = sys.argv[1] if len(sys.argv) > 1 else "新铁屋记.srt"
VIDEO_PATH = sys.argv[2] if len(sys.argv) > 2 else "新铁屋记.mp4"
OUTPUT_PATH = sys.argv[3] if len(sys.argv) > 3 else "新铁屋记-字幕版.mp4"

FONT_PATH = "/System/Library/Fonts/STHeiti Light.ttc"
FONT_SIZE = 50
VIDEO_W, VIDEO_H = 1920, 1080
MAX_CHARS_PER_LINE = 28
MARGIN_BOTTOM = 80
BG_PADDING = 12
BG_ALPHA = 160

def parse_srt(path):
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    blocks = re.split(r"\n\n+", content.strip())
    subs = []
    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) < 3:
            continue
        time_match = re.match(
            r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[,.](\d{3})",
            lines[1].strip(),
        )
        if not time_match:
            continue
        g = time_match.groups()
        start = int(g[0]) * 3600 + int(g[1]) * 60 + int(g[2]) + int(g[3]) / 1000
        end = int(g[4]) * 3600 + int(g[5]) * 60 + int(g[6]) + int(g[7]) / 1000
        text = "\n".join(lines[2:]).strip()
        if text:
            subs.append((start, end, text))
    return subs

def wrap_text(text, font, max_width, draw):
    lines = []
    for paragraph in text.split("\n"):
        if not paragraph:
            lines.append("")
            continue
        current = ""
        for char in paragraph:
            test = current + char
            bbox = draw.textbbox((0, 0), test, font=font)
            if bbox[2] - bbox[0] > max_width:
                if current:
                    lines.append(current)
                current = char
            else:
                current = test
        if current:
            lines.append(current)
    return lines

def render_subtitle(text, font, video_w, video_h):
    tmp = Image.new("RGBA", (video_w, video_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(tmp)
    max_w = video_w - 200
    lines = wrap_text(text, font, max_w, draw)

    line_spacing = FONT_SIZE + 12
    total_h = len(lines) * line_spacing

    y_start = video_h - MARGIN_BOTTOM - total_h - BG_PADDING * 2

    line_bboxes = []
    for line in lines:
        line_bboxes.append(draw.textbbox((0, 0), line, font=font))

    max_line_w = max(bb[2] - bb[0] for bb in line_bboxes)
    total_h = len(lines) * line_spacing

    y_start = video_h - MARGIN_BOTTOM - total_h - BG_PADDING * 2

    if not lines:
        return None

    bg_x1 = (video_w - max_line_w) // 2 - BG_PADDING
    bg_y1 = y_start
    bg_x2 = (video_w + max_line_w) // 2 + BG_PADDING
    bg_y2 = y_start + total_h + BG_PADDING * 2
    draw.rounded_rectangle(
        [bg_x1, bg_y1, bg_x2, bg_y2],
        radius=8,
        fill=(0, 0, 0, BG_ALPHA),
    )

    for i, line in enumerate(lines):
        lw = line_bboxes[i][2] - line_bboxes[i][0]
        lx = (video_w - lw) // 2
        draw.text((lx, y_start + BG_PADDING + i * line_spacing), line, fill=(255, 255, 255, 255), font=font)

    img = Image.new("RGBA", (video_w, video_h), (0, 0, 0, 0))
    img.paste(tmp)
    return img

def fmt_time(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"

def main():
    project_dir = Path(__file__).parent if "__file__" in dir() else Path(".")
    srt_path = Path(SRT_PATH)
    if not srt_path.is_absolute():
        srt_path = project_dir / srt_path
    video_path = Path(VIDEO_PATH)
    if not video_path.is_absolute():
        video_path = project_dir / video_path
    output_path = Path(OUTPUT_PATH)
    if not output_path.is_absolute():
        output_path = project_dir / output_path

    subs = parse_srt(str(srt_path))
    print(f"Parsed {len(subs)} subtitle entries")

    font = ImageFont.truetype(FONT_PATH, FONT_SIZE)

    tmpdir = tempfile.mkdtemp(prefix="subs_")
    print(f"Rendering subtitles to {tmpdir}")

    filter_parts = []
    for i, (start, end, text) in enumerate(subs):
        img = render_subtitle(text, font, VIDEO_W, VIDEO_H)
        if img is None:
            continue
        png_path = os.path.join(tmpdir, f"sub_{i:04d}.png")
        img.save(png_path)

        start_str = fmt_time(start)
        end_str = fmt_time(end)
        enable = f"between(t,{start:.3f},{end:.3f})"
        filter_parts.append(
            f"[0:v][{i + 1}:v]overlay=0:0:enable='{enable}'"
        )

    print(f"Building ffmpeg filter chain with {len(filter_parts)} overlays...")

    overlay_inputs = []
    for i in range(len(subs)):
        png_path = os.path.join(tmpdir, f"sub_{i:04d}.png")
        if os.path.exists(png_path):
            overlay_inputs.extend(["-i", png_path])

    filter_complex = ""
    current = "[0:v]"
    for i, part in enumerate(filter_parts):
        if i < len(filter_parts) - 1:
            out_label = f"[v{i}]"
            part_modified = part.replace("[0:v]", current, 1)
            filter_complex += f"{part_modified}{out_label};"
            current = out_label
        else:
            part_modified = part.replace("[0:v]", current, 1)
            filter_complex += f"{part_modified}[vout]"

    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
    ] + overlay_inputs + [
        "-filter_complex", filter_complex,
        "-map", "[vout]",
        "-map", "0:a",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-c:a", "copy",
        "-movflags", "+faststart",
        str(output_path),
    ]

    print(f"Running ffmpeg (filter chain: {len(filter_parts)} overlays)...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"ffmpeg failed:\n{result.stderr[-2000:]}")
        sys.exit(1)

    print(f"Cleaning up {tmpdir}")
    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)
    print(f"\n✅ Done: {output_path}")

if __name__ == "__main__":
    main()
