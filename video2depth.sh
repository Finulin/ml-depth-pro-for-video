#!/bin/bash

# =================================================================================
# Hilfsfunktion
# Zeigt die Nutzungsinformationen für das Skript an.
# =================================================================================
show_help() {
cat << EOF
Nutzung: ./video2depth.sh [-h] video.mp4 [modus] [wert]

Erstellt ein Depth-Map-Video aus einer Quelldatei.

ARGUMENTE:
  video.mp4     Pfad zur Eingabevideodatei. (Erforderlich)

  modus         Der zu verwendende Filtermodus. Kann 'ema' oder 'median' sein.
                'ema': Exponential Moving Average - glättet die Depth Maps über die Zeit.
                'median': Medianfilter - reduziert Ausreißer über mehrere Frames.
                (Standard: ema)

  wert          Der Wert für den gewählten Filtermodus.
                - Für 'ema': Ein Glättungsfaktor zwischen 0.0 und 1.0. (Standard: 0.7)
                - Für 'median': Eine ungerade Fenstergröße für den Medianfilter. (Standard: 3)

OPTIONEN:
  -h, --help    Zeigt diese Hilfenachricht an und beendet das Skript.

BEISPIELE:
  ./video2depth.sh mein_video.mp4
  ./video2depth.sh mein_video.mp4 ema 0.5
  ./video2depth.sh mein_video.mp4 median 5
EOF
}


# =================================================================================
# Parameter-Verarbeitung
# =================================================================================
if [[ "$1" == "-h" ]] || [[ "$1" == "--help" ]]; then
    show_help
    exit 0
fi

# Nutzung: ./video2depth.sh video.mp4 [ema|median] [wert]
# Beispiel EMA:    ./video2depth.sh test.mp4 ema 0.5
# Beispiel Median: ./video2depth.sh test.mp4 median 5

if [ -z "$1" ]; then
    echo "❌ Fehler: Videodatei fehlt."
    echo "Nutzung: ./video2depth.sh video.mp4 [modus: ema|median] [wert]"
    exit 1
fi

INPUT_VIDEO=$(realpath "$1")
MODE=${2:-ema}      # Standard: ema
VAL=${3:-0.7}       # Standardwert (0.7 für EMA, 3 für Median)

# Falls Median gewählt wurde, aber der Standardwert noch auf 0.7 steht, korrigieren
if [ "$MODE" == "median" ] && [ "$VAL" == "0.7" ]; then VAL=3; fi

DEPTH_CMD="depth-pro-run"
VIDEO_NAME=$(basename "$INPUT_VIDEO" | cut -f 1 -d '.')
DIR_SOURCE=$(dirname "$INPUT_VIDEO")

TMP_FRAMES="${DIR_SOURCE}/tmp_frames_${VIDEO_NAME}"
TMP_DEPTH="${DIR_SOURCE}/tmp_depth_${VIDEO_NAME}"
OUTPUT_VIDEO="${DIR_SOURCE}/${VIDEO_NAME}_depthmap.mp4"

# Speicherplatz-Prüfung
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


echo "🎬 Modus: $MODE | Wert: $VAL"
mkdir -p "$TMP_FRAMES" "$TMP_DEPTH"

FPS=$(ffprobe -v 0 -of default=noprint_wrappers=1:nokey=1 -select_streams v:0 -show_entries stream=r_frame_rate "$INPUT_VIDEO")

echo "🔨 Zerlege Video..."
ffmpeg -v error -i "$INPUT_VIDEO" -pix_fmt rgb48be "$TMP_FRAMES/frame_%04d.png"

echo "🧠 Berechne Depth Maps..."
if [ "$MODE" == "median" ]; then
    $DEPTH_CMD -i "$TMP_FRAMES" -o "$TMP_DEPTH" --skip-display --filter-mode median --window-size "$VAL"
else
    $DEPTH_CMD -i "$TMP_FRAMES" -o "$TMP_DEPTH" --skip-display --filter-mode ema --smooth "$VAL"
fi

echo "🎞  Erstelle Video..."
ffmpeg -y -v error -r "$FPS" -i "$TMP_DEPTH/frame_%04d_16bit.png" -c:v libx264 -crf 18 -pix_fmt yuv420p "$OUTPUT_VIDEO"

rm -rf "$TMP_FRAMES" "$TMP_DEPTH"
echo "✅ Fertig: $OUTPUT_VIDEO"
