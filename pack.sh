#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# pack.sh — 收尾打包脚本
#
# 用法：
#   bash pack.sh <markdown文件>
#   bash pack.sh doc2video-intro.md
#
# 功能：
#   1. 以 markdown 文件名（去扩展名）创建目录
#   2. 将生成的文本、音频、图片、mp4 全部 mv 到该目录
#   3. 置空 concat_list.txt 和 prompts.json
# ═══════════════════════════════════════════════════════════════

set -euo pipefail

# ── 参数检查 ──
if [ $# -lt 1 ]; then
  echo "用法: bash pack.sh <markdown文件>"
  echo "示例: bash pack.sh doc2video-intro.md"
  exit 1
fi

MD_FILE="$1"
MD_FILE="$(cd "$(dirname "$MD_FILE")" && pwd)/$(basename "$MD_FILE")"
BASE_NAME="$(basename "$MD_FILE")"
BASE_NAME="${BASE_NAME%.*}"
WORK_DIR="$(dirname "$MD_FILE")"
VIDEO_DIR="$WORK_DIR/video-project"

if [ ! -f "$MD_FILE" ]; then
  echo "❌ 找不到文件: $MD_FILE"
  exit 1
fi

PACK_DIR="$WORK_DIR/$BASE_NAME"
mkdir -p "$PACK_DIR/images"
echo "📁 打包目录: $PACK_DIR"

CLEAN_FILE="$WORK_DIR/${BASE_NAME}-clean.txt"
if [ -f "$CLEAN_FILE" ]; then
  mv "$CLEAN_FILE" "$PACK_DIR/"
  echo "✅ 文本: ${BASE_NAME}-clean.txt"
fi

for ext in wav mp3; do
  AUDIO="$WORK_DIR/${BASE_NAME}.${ext}"
  [ -f "$AUDIO" ] && mv "$AUDIO" "$PACK_DIR/" && echo "✅ 音频: ${BASE_NAME}.${ext}"
done

for srt in "$WORK_DIR/${BASE_NAME}.srt" "$WORK_DIR/${BASE_NAME}"-*-final.srt; do
  [ -f "$srt" ] && mv "$srt" "$PACK_DIR/" && echo "✅ 字幕: $(basename "$srt")"
done

for mp4 in "$WORK_DIR/${BASE_NAME}"*.mp4; do
  [ -f "$mp4" ] && mv "$mp4" "$PACK_DIR/" && echo "✅ 视频: $(basename "$mp4")"
done

# ── 移动图片 ──
if ls "$VIDEO_DIR/images/"*.png 1>/dev/null 2>&1; then
  mv "$VIDEO_DIR/images/"*.png "$PACK_DIR/images/"
  COUNT=$(ls "$PACK_DIR/images/"*.png 2>/dev/null | wc -l | tr -d ' ')
  echo "✅ 图片: ${COUNT} 张 → images/"
fi

# ── 移动 prompts.json（保留一份到打包目录） ──
if [ -f "$VIDEO_DIR/prompts.json" ]; then
  mv "$VIDEO_DIR/prompts.json" "$PACK_DIR/"
  echo "✅ 分镜脚本: prompts.json"
fi

# ── 置空中间文件 ──
> "$VIDEO_DIR/concat_list.txt"
echo "🧹 已置空: concat_list.txt"

echo '{}' > "$VIDEO_DIR/prompts.json"
echo "🧹 已置空: prompts.json"

# ── 清理 clips ──
if [ -d "$VIDEO_DIR/clips" ]; then
  rm -f "$VIDEO_DIR/clips/"*.mp4
  echo "🧹 已清理: clips/"
fi

# ── 清理 video-project 中的中间 mp4 ──
for f in "$VIDEO_DIR"/merged_raw.mp4 "$VIDEO_DIR"/merged_speed_adjusted.mp4; do
  [ -f "$f" ] && rm -f "$f" && echo "🧹 已删除: $(basename "$f")"
done

echo ""
echo "🎉 打包完成！所有产物已归档到: $PACK_DIR"
ls -lh "$PACK_DIR/"
