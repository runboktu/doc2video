#!/bin/bash
# 新铁屋记 — 视频拼接 + 音频叠加脚本
#
# 用法:
#   bash assemble.sh                  # 完整流程
#   bash assemble.sh --skip-normalize # 跳过片段标准化（已标准化过）
#   bash assemble.sh --audio-only     # 只叠加音频（已拼接好视频）

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
CLIPS_DIR="$SCRIPT_DIR/clips"
AUDIO_FILE="$PROJECT_DIR/xin-tie-wu-man-0.9x.wav"

CONCAT_LIST="$SCRIPT_DIR/concat_list.txt"
MERGED_RAW="$SCRIPT_DIR/merged_raw.mp4"
MERGED_NORMALIZED="$SCRIPT_DIR/merged_normalized.mp4"
FINAL_OUTPUT="$PROJECT_DIR/新铁屋记.mp4"

SKIP_NORMALIZE=false
AUDIO_ONLY=false

for arg in "$@"; do
    case $arg in
        --skip-normalize) SKIP_NORMALIZE=true ;;
        --audio-only)     AUDIO_ONLY=true ;;
    esac
done

echo "============================================================"
echo "新铁屋记 — 视频拼接与音频叠加"
echo "============================================================"

# 检查依赖
for cmd in ffmpeg ffprobe; do
    if ! command -v $cmd &> /dev/null; then
        echo "❌ 缺少 $cmd，请先安装: brew install ffmpeg"
        exit 1
    fi
done

# 检查音频文件
if [ ! -f "$AUDIO_FILE" ]; then
    echo "❌ 找不到音频文件: $AUDIO_FILE"
    exit 1
fi

AUDIO_DURATION=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$AUDIO_FILE")
echo "🎵 音频时长: ${AUDIO_DURATION}s"

# ──────────────────────────────────────────
# Step 1: 统计可用片段
# ──────────────────────────────────────────

CLIP_COUNT=$(find "$CLIPS_DIR" -name "*.mp4" 2>/dev/null | wc -l | tr -d ' ')

if [ "$CLIP_COUNT" -eq 0 ]; then
    echo "❌ clips/ 目录下没有 mp4 文件"
    echo "   请先运行: python generate_videos.py --mode videos"
    exit 1
fi

echo "📹 找到 $CLIP_COUNT 个视频片段"

# ──────────────────────────────────────────
# Step 2: 标准化所有片段（统一编码、分辨率、帧率）
# ──────────────────────────────────────────

NORMALIZED_DIR="$CLIPS_DIR/normalized"
mkdir -p "$NORMALIZED_DIR"

if [ "$SKIP_NORMALIZE" = false ] && [ "$AUDIO_ONLY" = false ]; then
    echo ""
    echo "📐 Step 1/4: 标准化片段..."
    NORMALIZED_COUNT=$(find "$NORMALIZED_DIR" -name "*.mp4" 2>/dev/null | wc -l | tr -d ' ')

    for clip in "$CLIPS_DIR"/*.mp4; do
        [ -f "$clip" ] || continue
        basename=$(basename "$clip")
        out="$NORMALIZED_DIR/$basename"

        if [ -f "$out" ]; then
            continue
        fi

        echo "  标准化: $basename"
        ffmpeg -y -i "$clip" \
            -vf "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black" \
            -r 24 \
            -c:v libx264 -preset medium -crf 18 \
            -an \
            "$out" 2>/dev/null
    done

    echo "  ✅ 标准化完成"
else
    echo "⏭️  跳过标准化"
fi

# ──────────────────────────────────────────
# Step 3: 生成 concat 列表并拼接
# ──────────────────────────────────────────

if [ "$AUDIO_ONLY" = false ]; then
    echo ""
    echo "🔗 Step 2/4: 拼接视频片段..."

    # 用标准化后的片段生成 concat 列表
    > "$CONCAT_LIST"
    for clip in $(ls "$NORMALIZED_DIR"/*.mp4 2>/dev/null | sort); do
        echo "file '$clip'" >> "$CONCAT_LIST"
    done

    CONCAT_COUNT=$(wc -l < "$CONCAT_LIST" | tr -d ' ')
    echo "  拼接 $CONCAT_COUNT 个片段"

    ffmpeg -y -f concat -safe 0 -i "$CONCAT_LIST" \
        -c:v libx264 -preset medium -crf 18 \
        -r 24 \
        "$MERGED_NORMALIZED" 2>/dev/null

    MERGED_DURATION=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$MERGED_NORMALIZED")
    echo "  ✅ 拼接完成: ${MERGED_DURATION}s"
else
    echo "⏭️  跳过拼接"
fi

# ──────────────────────────────────────────
# Step 4: 调整视频速度以匹配音频时长
# ──────────────────────────────────────────

VIDEO_FILE="$MERGED_NORMALIZED"
if [ ! -f "$VIDEO_FILE" ]; then
    echo "❌ 找不到拼接后的视频: $VIDEO_FILE"
    exit 1
fi

VIDEO_DURATION=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$VIDEO_FILE")

echo ""
echo "⏱️  Step 3/4: 时长匹配..."
echo "  视频时长: ${VIDEO_DURATION}s"
echo "  音频时长: ${AUDIO_DURATION}s"

SPEED_ADJUSTED="$SCRIPT_DIR/merged_speed_adjusted.mp4"

# 目标：视频比音频长 3s（2~5s 范围内）
TARGET_BUFFER=3
TARGET_DURATION=$(echo "$AUDIO_DURATION + $TARGET_BUFFER" | bc -l)
SPEED_FACTOR=$(echo "$TARGET_DURATION / $VIDEO_DURATION" | bc -l)
echo "  目标时长: ${TARGET_DURATION}s (音频 + ${TARGET_BUFFER}s)"
echo "  速度系数: ${SPEED_FACTOR} (< 1 加速, > 1 减速)"

if [ "$AUDIO_ONLY" = false ]; then
    # 使用 setpts 调整视频速度，使视频略长于音频
    ffmpeg -y -i "$VIDEO_FILE" \
        -vf "setpts=${SPEED_FACTOR}*PTS" \
        -c:v libx264 -preset medium -crf 18 \
        -r 24 \
        "$SPEED_ADJUSTED" 2>/dev/null

    VIDEO_FILE="$SPEED_ADJUSTED"
    ADJUSTED_DURATION=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$VIDEO_FILE")
    DIFF_TO_AUDIO=$(echo "$ADJUSTED_DURATION - $AUDIO_DURATION" | bc -l)
    echo "  ✅ 调整后时长: ${ADJUSTED_DURATION}s (比音频长 ${DIFF_TO_AUDIO}s)"
else
    echo "  ⏭️  跳过速度调整"
fi

# ──────────────────────────────────────────
# Step 5: 叠加音频
# ──────────────────────────────────────────

echo ""
echo "🎵 Step 4/4: 叠加音频..."

ffmpeg -y \
    -i "$VIDEO_FILE" \
    -i "$AUDIO_FILE" \
    -c:v copy \
    -c:a aac -b:a 192k \
    -shortest \
    -movflags +faststart \
    "$FINAL_OUTPUT" 2>/dev/null

FINAL_DURATION=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$FINAL_OUTPUT")
FINAL_SIZE=$(du -h "$FINAL_OUTPUT" | cut -f1)

echo ""
echo "============================================================"
echo "✅ 最终视频已生成！"
echo "   📁 路径: $FINAL_OUTPUT"
echo "   ⏱️  时长: ${FINAL_DURATION}s"
echo "   💾 大小: ${FINAL_SIZE}"
echo "============================================================"
