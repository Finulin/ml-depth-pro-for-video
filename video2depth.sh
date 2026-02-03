#!/bin/bash

# =================================================================================
# Hilfsfunktion
# Zeigt die Nutzungsinformationen für das Skript an.
# =================================================================================
show_help() {
cat << EOF
Nutzung: ./video2depth.sh [-h] video.mp4 [modus] [wert1] [wert2]

Erstellt ein Depth-Map-Video aus einer Quelldatei.

ARGUMENTE:
  video.mp4     Pfad zur Eingabevideodatei. (Erforderlich)

  modus         Der zu verwendende Filtermodus. 'ema', 'median' oder 'combined'.
                'combined': Wendet erst Median, dann EMA an.
                (Standard: ema)

  wert1         - Bei 'ema': Glättungsfaktor (0.0 - 1.0). (Standard: 0.6)
                - Bei 'median': Fenstergröße (ungerade Zahl). (Standard: 6)
                - Bei 'combined': Glättungsfaktor für EMA.

  wert2         - Nur bei 'combined': Fenstergröße für Median. (Standard: 6)

OPTIONEN:
  -h, --help    Zeigt diese Hilfenachricht an und beendet das Skript.

BEISPIELE:
  ./video2depth.sh video.mp4 ema 0.5
  ./video2depth.sh video.mp4 combined 0.5 5
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
    echo "Nutzung: ./video2depth.sh video.mp4 [modus: ema|median|combined] [wert1] [wert2]"
    exit 1
fi

INPUT_VIDEO=$(realpath "$1")
MODE=${2:-ema}      # Standard: ema
VAL1=${3:-0.6}      # Standardwert 1
VAL2=${4:-6}        # Standardwert 2 (nur für combined relevant)

# Falls Median gewählt wurde, aber der Standardwert noch auf 0.6 steht, korrigieren
if [ "$MODE" == "median" ] && [ "$VAL1" == "0.6" ]; then VAL1=6; fi

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
    $DEPTH_CMD -i "$TMP_FRAMES" -o "$TMP_DEPTH" --skip-display --filter-mode median --window-size "$VAL1"
elif [ "$MODE" == "combined" ]; then
    echo "   -> Kombinierter Modus: EMA=$VAL1, Median=$VAL2"
    $DEPTH_CMD -i "$TMP_FRAMES" -o "$TMP_DEPTH" --skip-display --filter-mode combined --smooth "$VAL1" --window-size "$VAL2"
else
    $DEPTH_CMD -i "$TMP_FRAMES" -o "$TMP_DEPTH" --skip-display --filter-mode ema --smooth "$VAL1"
fi

echo "🎞  Erstelle Video..."
ffmpeg -y -v error -r "$FPS" -i "$TMP_DEPTH/frame_%04d_16bit.png" -c:v libx264 -crf 18 -pix_fmt yuv420p "$OUTPUT_VIDEO"

rm -rf "$TMP_FRAMES" "$TMP_DEPTH"
echo "✅ Fertig: $OUTPUT_VIDEO"
