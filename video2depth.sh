#!/bin/bash

# ==============================================================================
# EINSTELLUNGEN & VARIABLEN
# ==============================================================================

# 1. Eingabedatei
if [ -z "$1" ]; then
    echo "❌ Fehler: Bitte eine Videodatei angeben."
    echo "Nutzung: ./video2depth.sh mein_video.mp4 [glättung: 0.1-1.0]"
    exit 1
fi

INPUT_VIDEO=$(realpath "$1")
# 2. Glättungsparameter EMA (Standardwert 0.1, falls nichts angegeben wurde, zwischen 0.1 und 1.0, 1.0=Rohdaten - 0.1=maximale Glättung)
SMOOTH_VAL=${2:-0.1}

DEPTH_CMD="depth-pro-run"

VIDEO_BASENAME=$(basename "$INPUT_VIDEO")
VIDEO_NAME="${VIDEO_BASENAME%.*}"
DIR_SOURCE=$(dirname "$INPUT_VIDEO")

TMP_FRAMES="${DIR_SOURCE}/tmp_frames_${VIDEO_NAME}"
TMP_DEPTH="${DIR_SOURCE}/tmp_depth_${VIDEO_NAME}"
OUTPUT_VIDEO="${DIR_SOURCE}/${VIDEO_NAME}_depthmap.mp4"

# ==============================================================================
# SPEICHERPLATZ-PRÜFUNG
# ==============================================================================
echo "📊 Analysiere Speicherplatzbedarf..."
FRAME_COUNT=$(ffprobe -v error -select_streams v:0 -count_packets -show_entries stream=nb_read_packets -of csv=p=0 "$INPUT_VIDEO")
ESTIMATED_MB_PER_FRAME=25
TOTAL_REQUIRED_MB=$((FRAME_COUNT * ESTIMATED_MB_PER_FRAME))
AVAILABLE_MB=$(df -m "$DIR_SOURCE" | tail -1 | awk '{print $4}')

echo "   - Frames: $FRAME_COUNT | Bedarf: ~$TOTAL_REQUIRED_MB MB | Verfügbar: $AVAILABLE_MB MB"

if [ "$TOTAL_REQUIRED_MB" -gt "$AVAILABLE_MB" ]; then
    echo "⚠️  Warnung: Speicherplatz knapp!"
    read -p "Trotzdem fortfahren? (y/n): " confirm
    [[ $confirm != [yY] ]] && exit 1
fi

# ==============================================================================
# LOGIK
# ==============================================================================
echo "🎬 Starte Verarbeitung: $VIDEO_BASENAME (Glättung: $SMOOTH_VAL)"
mkdir -p "$TMP_FRAMES" "$TMP_DEPTH"

FPS=$(ffprobe -v 0 -of default=noprint_wrappers=1:nokey=1 -select_streams v:0 -show_entries stream=r_frame_rate "$INPUT_VIDEO")

echo "🔨 Zerlege Video..."
ffmpeg -v error -i "$INPUT_VIDEO" -pix_fmt rgb48be "$TMP_FRAMES/frame_%04d.png"

echo "🧠 Berechne Depth Maps auf GPU..."
# Übergabe des Glättungswerts an das Python-Script
$DEPTH_CMD -i "$TMP_FRAMES" -o "$TMP_DEPTH" --skip-display --smooth "$SMOOTH_VAL"

echo "🎞  Erstelle Video..."
ffmpeg -y -v error -r "$FPS" -i "$TMP_DEPTH/frame_%04d_16bit.png" -c:v libx264 -crf 18 -pix_fmt yuv420p "$OUTPUT_VIDEO"

rm -rf "$TMP_FRAMES" "$TMP_DEPTH"
echo "✅ Fertig: $OUTPUT_VIDEO"
