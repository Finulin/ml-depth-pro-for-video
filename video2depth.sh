#!/bin/bash

# ==============================================================================
# EINSTELLUNGEN & VARIABLEN
# ==============================================================================

# 1. Eingabedatei (wird als erstes Argument übergeben)
if [ -z "$1" ]; then
    echo "❌ Fehler: Bitte eine Videodatei angeben."
    echo "Nutzung: ./video2depth.sh /Pfad/zu/deinem/Video.mp4"
    exit 1
fi

INPUT_VIDEO=$(realpath "$1")

# 2. Befehl für das Python-Script (wieder auf den Alias/Link zurückgesetzt)
DEPTH_CMD="depth-pro-run"

# 3. Benennung der temporären Ordner (basiert auf dem Videonamen)
VIDEO_BASENAME=$(basename "$INPUT_VIDEO")
VIDEO_NAME="${VIDEO_BASENAME%.*}"
DIR_SOURCE=$(dirname "$INPUT_VIDEO")

TMP_FRAMES="${DIR_SOURCE}/tmp_frames_${VIDEO_NAME}"
TMP_DEPTH="${DIR_SOURCE}/tmp_depth_${VIDEO_NAME}"

# 4. Ausgabedatei
OUTPUT_VIDEO="${DIR_SOURCE}/${VIDEO_NAME}_depthmap.mp4"

# ==============================================================================
# SPEICHERPLATZ-PRÜFUNG
# ==============================================================================

echo "📊 Analysiere Speicherplatzbedarf..."

# Ermittle Anzahl der Frames
FRAME_COUNT=$(ffprobe -v error -select_streams v:0 -count_packets -show_entries stream=nb_read_packets -of csv=p=0 "$INPUT_VIDEO")

# Schätzung: 25MB pro Frame (Original PNG + Depth PNG Puffer)
ESTIMATED_MB_PER_FRAME=25
TOTAL_REQUIRED_MB=$((FRAME_COUNT * ESTIMATED_MB_PER_FRAME))

# Verfügbarer Platz auf dem Ziel-Laufwerk
AVAILABLE_MB=$(df -m "$DIR_SOURCE" | tail -1 | awk '{print $4}')

echo "   - Bilder im Video: $FRAME_COUNT"
echo "   - Geschätzter Bedarf: ~$TOTAL_REQUIRED_MB MB"
echo "   - Verfügbar auf SSD: $AVAILABLE_MB MB"

if [ "$TOTAL_REQUIRED_MB" -gt "$AVAILABLE_MB" ]; then
    echo "⚠️  ACHTUNG: Der Speicherplatz auf deiner SSD könnte knapp werden!"
    read -p "Möchtest du trotzdem fortfahren? (y/n): " confirm
    if [[ $confirm != [yY] ]]; then
        echo "❌ Abbruch durch Benutzer."
        exit 1
    fi
fi

# ==============================================================================
# LOGIK
# ==============================================================================

echo "🎬 Starte Verarbeitung für: $VIDEO_BASENAME"
echo "---------------------------------------------"

# 1. Temporäre Ordner erstellen
echo "📁 Erstelle temporäre Verzeichnisse..."
mkdir -p "$TMP_FRAMES"
mkdir -p "$TMP_DEPTH"

# 2. FPS auslesen
echo "i  Ermittle Bildwiederholrate (FPS)..."
FPS=$(ffprobe -v 0 -of default=noprint_wrappers=1:nokey=1 -select_streams v:0 -show_entries stream=r_frame_rate "$INPUT_VIDEO")
echo "   -> FPS erkannt: $FPS"

# 3. Video in 16-bit PNG Einzelbilder zerlegen
echo "🔨 Zerlege Video in Einzelbilder (16-bit)..."
ffmpeg -v error -i "$INPUT_VIDEO" -pix_fmt rgb48be "$TMP_FRAMES/frame_%04d.png"

# 4. KI-Inferenz
echo "🧠 Berechne Depth Maps auf der GPU..."
# Der Batch-Aufruf nutzt das Verzeichnis für maximale Performance
$DEPTH_CMD -i "$TMP_FRAMES" -o "$TMP_DEPTH" --skip-display

echo "✅ KI-Berechnung abgeschlossen."

# 5. Bilder zu Video zusammensetzen
echo "🎞  Erstelle MP4-Video aus Depth Maps..."

ffmpeg -y -v error \
    -r "$FPS" \
    -i "$TMP_DEPTH/frame_%04d_16bit.png" \
    -c:v libx264 \
    -crf 18 \
    -pix_fmt yuv420p \
    "$OUTPUT_VIDEO"

echo "   -> Video gespeichert unter: $OUTPUT_VIDEO"

# 6. Aufräumen
echo "🧹 Lösche temporäre Ordner..."
rm -rf "$TMP_FRAMES"
rm -rf "$TMP_DEPTH"

echo "---------------------------------------------"
echo "🎉 Fertig!"
