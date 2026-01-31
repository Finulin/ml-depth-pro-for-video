#!/bin/bash

# ==============================================================================
# EINSTELLUNGEN & VARIABLEN
# ==============================================================================

# 1. Eingabedatei (wird als erstes Argument übergeben)
INPUT_VIDEO="$1"

# 2. Befehl für das Python-Script
# Stelle sicher, dass 'depth-pro-run' im Pfad ist oder nutze den vollen Pfad (z.B. /Users/deinname/.../venv/bin/python run.py)
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
# LOGIK
# ==============================================================================

# Abbruch bei fehlendem Video
if [ -z "$INPUT_VIDEO" ]; then
    echo "❌ Fehler: Bitte eine Videodatei angeben."
    echo "Nutzung: ./video2depth.sh /Pfad/zu/deinem/Video.mp4"
    exit 1
fi

echo "🎬 Starte Verarbeitung für: $VIDEO_BASENAME"
echo "---------------------------------------------"

# 1. Temporäre Ordner erstellen
echo "📁 Erstelle temporäre Verzeichnisse..."
mkdir -p "$TMP_FRAMES"
mkdir -p "$TMP_DEPTH"

# 2. FPS auslesen (Wichtig für die Rekonstruktion!)
echo "i  Ermittle Bildwiederholrate (FPS)..."
FPS=$(ffprobe -v 0 -of default=noprint_wrappers=1:nokey=1 -select_streams v:0 -show_entries stream=r_frame_rate "$INPUT_VIDEO")
echo "   -> FPS erkannt: $FPS"

# 3. Video in 16-bit PNG Einzelbilder zerlegen
echo "🔨 Zerlege Video in Einzelbilder (16-bit)..."
# -pix_fmt rgb48be sorgt für 16-bit Big Endian RGB (höchste Qualität für die KI)
ffmpeg -v error -i "$INPUT_VIDEO" -pix_fmt rgb48be "$TMP_FRAMES/frame_%04d.png"

# 4. KI-Inferenz (Schleife)
echo "🧠 Berechne Depth Maps (Das kann dauern)..."

# Wir zählen die Dateien für einen Fortschrittsbalken
TOTAL_FILES=$(ls "$TMP_FRAMES"/*.png | wc -l)
CURRENT=0

for img in "$TMP_FRAMES"/*.png; do
    ((CURRENT++))
    # Dateiname extrahieren für Logging
    bname=$(basename "$img")
    
    echo "   [$CURRENT / $TOTAL_FILES] Verarbeite: $bname"
    
    # Der eigentliche Befehl wie angefordert
    $DEPTH_CMD -i "$img" -o "$TMP_DEPTH" --skip-display > /dev/null 2>&1
done

echo "✅ KI-Berechnung abgeschlossen."

# 5. Bilder zu Video zusammensetzen
echo "🎞  Erstelle MP4-Video aus Depth Maps..."

# HINWEIS: Dein Python-Script speichert die Dateien als *_16bit.png.
# Wir müssen ffmpeg sagen, dass es nach diesem Muster suchen soll.
# -glob pattern funktioniert auf Mac oft besser als %04d bei komplexen Suffixen, 
# aber wir nutzen hier das strikte %04d Pattern mit dem Suffix.

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
