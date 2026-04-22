#!/bin/bash
# 视频拼接与音频叠加
#
# 只做三件事:
#   1. 统一分辨率/编码/帧率到 1920×1080
#   2. setpts 调速让视频≈音频时长
#   3. 拼接+叠加音频
#
# 用法:
#   bash assemble.sh --audio ../xxx.wav --output ../xxx.mp4
#   bash assemble.sh --audio ../xxx.wav --output ../xxx.mp4 --skip-normalize
#   bash assemble.sh --audio ../xxx.wav --output ../xxx.mp4 --audio-only

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CLIPS_DIR="$SCRIPT_DIR/clips"
NORMALIZED_DIR="$CLIPS_DIR/normalized"
CONCAT_LIST="$SCRIPT_DIR/concat_list.txt"
MERGED_RAW="$SCRIPT_DIR/merged_raw.mp4"
SPEED_ADJUSTED="$SCRIPT_DIR/merged_speed_adjusted.mp4"

SKIP_NORMALIZE=false
AUDIO_ONLY=false
AUDIO_FILE=""
FINAL_OUTPUT=""

for arg in "$@"; do
    case "$arg" in
        --skip-normalize) SKIP_NORMALIZE=true ;;
        --audio-only)     AUDIO_ONLY=true ;;
        --audio=*)        AUDIO_FILE="${arg#*=}" ;;
        --output=*)       FINAL_OUTPUT="${arg#*=}" ;;
    esac
done

if [ -z "$AUDIO_FILE" ]; then
    echo "❌ 缺少 --audio 参数"
    echo "   用法: bash assemble.sh --audio ../xxx.wav --output ../xxx.mp4"
    exit 1
fi
if [ -z "$FINAL_OUTPUT" ]; then
    echo "❌ 缺少 --output 参数"
    echo "   用法: bash assemble.sh --audio ../xxx.wav --output ../xxx.mp4"
    exit 1
fi

echo "============================================================"
echo "视频拼接与音频叠加"
echo "============================================================"

for cmd in ffmpeg ffprobe; do
    if ! command -v "$cmd" &>/dev/null; then
        echo "❌ 缺少 $cmd，请先安装: brew install ffmpeg"
        exit 1
    fi
done

if [ ! -f "$AUDIO_FILE" ]; then
    echo "❌ 找不到音频文件: $AUDIO_FILE"
    exit 1
fi

AUDIO_DURATION=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$AUDIO_FILE")
echo "🎵 音频时长: ${AUDIO_DURATION}s"

CLIP_COUNT=$(find "$CLIPS_DIR" -maxdepth 1 -name "*.mp4" 2>/dev/null | wc -l | tr -d ' ')

if [ "$CLIP_COUNT" -eq 0 ]; then
    echo "❌ clips/ 目录下没有 mp4 文件"
    echo "   请先运行: python generate_images.py --mode videos"
    exit 1
fi

echo "📹 找到 $CLIP_COUNT 个视频片段"

# ──────────────────────────────────────────
# Step 1: 标准化所有片段到 1920×1080
# ──────────────────────────────────────────

mkdir -p "$NORMALIZED_DIR"

if [ "$SKIP_NORMALIZE" = false ] && [ "$AUDIO_ONLY" = false ]; then
    echo ""
    echo "📐 Step 1/3: 标准化片段 → 1920×1080..."

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
            "$out" </dev/null 2>/dev/null
    done

    echo "  ✅ 标准化完成"
else
    echo "⏭️  跳过标准化"
fi

# ──────────────────────────────────────────
# Step 2: 拼接 + setpts 调速
# ──────────────────────────────────────────

if [ "$AUDIO_ONLY" = false ]; then
    echo ""
    echo "🔗 Step 2/3: 拼接视频片段..."

    > "$CONCAT_LIST"
    if [ -d "$NORMALIZED_DIR" ] && [ "$(ls "$NORMALIZED_DIR"/*.mp4 2>/dev/null | wc -l | tr -d ' ')" -gt 0 ]; then
        for clip in $(ls "$NORMALIZED_DIR"/*.mp4 2>/dev/null | sort); do
            echo "file '$clip'" >> "$CONCAT_LIST"
        done
    else
        echo "  ⚠️  无标准化片段，使用原始 clips/"
        for clip in $(ls "$CLIPS_DIR"/*.mp4 2>/dev/null | sort); do
            echo "file '$clip'" >> "$CONCAT_LIST"
        done
    fi

    CONCAT_COUNT=$(wc -l < "$CONCAT_LIST" | tr -d ' ')
    echo "  拼接 $CONCAT_COUNT 个片段"

    ffmpeg -y -f concat -safe 0 -i "$CONCAT_LIST" \
        -c:v libx264 -preset medium -crf 18 \
        -r 24 \
        "$MERGED_RAW" </dev/null 2>/dev/null

    MERGED_DURATION=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$MERGED_RAW")
    echo "  ✅ 拼接完成: ${MERGED_DURATION}s"

    echo ""
    echo "⏱️  调整速度以匹配音频..."
    echo "  视频时长: ${MERGED_DURATION}s"
    echo "  音频时长: ${AUDIO_DURATION}s"

    TARGET_DURATION=$(echo "$AUDIO_DURATION + 3" | bc -l)
    SPEED_FACTOR=$(echo "$TARGET_DURATION / $MERGED_DURATION" | bc -l)
    echo "  目标时长: ${TARGET_DURATION}s (音频 + 3s)"
    echo "  速度系数: ${SPEED_FACTOR} (< 1 加速, > 1 减速)"

    ffmpeg -y -i "$MERGED_RAW" \
        -vf "setpts=${SPEED_FACTOR}*PTS" \
        -c:v libx264 -preset medium -crf 18 \
        -r 24 \
        "$SPEED_ADJUSTED" </dev/null 2>/dev/null

    ADJUSTED_DURATION=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$SPEED_ADJUSTED")
    DIFF_TO_AUDIO=$(echo "$ADJUSTED_DURATION - $AUDIO_DURATION" | bc -l)
    echo "  ✅ 调整后时长: ${ADJUSTED_DURATION}s (比音频长 ${DIFF_TO_AUDIO}s)"

    VIDEO_FILE="$SPEED_ADJUSTED"
else
    echo "⏭️  跳过拼接和调速"
    VIDEO_FILE="$MERGED_RAW"
fi

# ──────────────────────────────────────────
# Step 3: 叠加音频
# ──────────────────────────────────────────

if [ ! -f "$VIDEO_FILE" ]; then
    echo "❌ 找不到视频文件: $VIDEO_FILE"
    exit 1
fi

echo ""
echo "🎵 Step 3/3: 叠加音频..."

ffmpeg -y \
    -i "$VIDEO_FILE" \
    -i "$AUDIO_FILE" \
    -c:v copy \
    -c:a aac -b:a 192k \
    -shortest \
    -movflags +faststart \
    "$FINAL_OUTPUT" </dev/null 2>/dev/null

FINAL_DURATION=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$FINAL_OUTPUT")
FINAL_SIZE=$(du -h "$FINAL_OUTPUT" | cut -f1)

echo ""
echo "============================================================"
echo "✅ 最终视频已生成！"
echo "   📁 路径: $FINAL_OUTPUT"
echo "   ⏱️  时长: ${FINAL_DURATION}s"
echo "   💾 大小:  $FINAL_SIZE"
echo "============================================================"
