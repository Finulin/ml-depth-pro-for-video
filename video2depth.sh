#!/bin/bash

# =================================================================================
# Hilfsfunktion
# Zeigt die Nutzungsinformationen für das Skript an.
# =================================================================================
show_help() {
cat << EOF
Nutzung: ./video2depth.sh [-h] [-p] video.mp4 [modus] [wert1] [wert2]

Erstellt ein Depth-Map-Video aus einer Quelldatei.

ARGUMENTE:
  video.mp4     Pfad zur Eingabevideodatei. (Erforderlich)

  modus         Der zu verwendende Filtermodus. Optional.
                'none': Kein Filter
                'ema': Exponentieller Mittelwert
                'median': Median-Filter
                'combined': Median + EMA kombiniert
                'bilateral': Zeitlicher Bilateral-Filter (kantenerhaltend)
                'optical_flow': Optical Flow basierte Glättung
                'gmm': Gaussian Mixture Model
                'savgol': Savitzky-Golay Filter
                Wenn kein Modus angegeben wird, wird kein Filter angewendet.

  wert1         - 'ema': Glättungsfaktor (0.0-1.0). (Standard: 0.6)
                - 'median': Fenstergröße. (Standard: 6)
                - 'combined': EMA-Glättungsfaktor. (Standard: 0.6)
                - 'bilateral': Räumliche Sigma. (Standard: 5.0)
                - 'optical_flow': Alpha-Wert (0.0-1.0). (Standard: 0.5)
                - 'gmm': Anzahl Komponenten. (Standard: 3)
                - 'savgol': Fenstergröße. (Standard: 6)

  wert2         - Nur bei 'combined': Fenstergröße für Median. (Standard: 6)
                - Bei 'bilateral': Wertebereich-Sigma. (Standard: 0.1)

OPTIONEN:
  -h, --help    Zeigt diese Hilfenachricht an und beendet das Skript.
  -p, --pad     Skaliert Frames auf 1536×1536 mit schwarzen Balken (Letterbox/Pillarbox)
                bevor die Depth Maps berechnet werden. Verhindert Verzerrungen durch
                das modellseitige Squishing auf 1:1 und verbessert die Inferenzqualität
                bei nicht-quadratischen Videos.

BEISPIELE:
  ./video2depth.sh video.mp4
  ./video2depth.sh video.mp4 ema 0.5
  ./video2depth.sh video.mp4 bilateral 5.0 0.1
  ./video2depth.sh video.mp4 optical_flow 0.5
  ./video2depth.sh video.mp4 combined 0.5 5
  ./video2depth.sh -p video.mp4 ema 0.5
EOF
}

# =================================================================================
# Parameter-Verarbeitung
# =================================================================================
PAD_TO_SQUARE=false
ARGS=()
for arg in "$@"; do
    if [[ "$arg" == "-p" ]] || [[ "$arg" == "--pad" ]]; then
        PAD_TO_SQUARE=true
    elif [[ "$arg" == "-h" ]] || [[ "$arg" == "--help" ]]; then
        show_help
        exit 0
    else
        ARGS+=("$arg")
    fi
done
set -- "${ARGS[@]}"

if [[ "$1" == "-h" ]] || [[ "$1" == "--help" ]]; then
    show_help
    exit 0
fi

if [ -z "$1" ]; then
    echo "❌ Fehler: Videodatei fehlt."
    echo "Nutzung: ./video2depth.sh video.mp4 [modus] [wert1] [wert2]"
    exit 1
fi

INPUT_VIDEO=$(realpath "$1")
ORIG_W=$(ffprobe -v error -select_streams v:0 -show_entries stream=width -of csv=p=0 "$INPUT_VIDEO")
ORIG_H=$(ffprobe -v error -select_streams v:0 -show_entries stream=height -of csv=p=0 "$INPUT_VIDEO")
MODE=${2:-none}
VAL1=${3:-0.6}
VAL2=${4:-6}

if [ "$MODE" == "median" ] && [ "$VAL1" == "0.6" ]; then VAL1=6; fi
if [ "$MODE" == "savgol" ] && [ "$VAL1" == "0.6" ]; then VAL1=6; fi
if [ "$MODE" == "gmm" ] && [ "$VAL1" == "0.6" ]; then VAL1=3; fi
if [ "$MODE" == "bilateral" ] && [ "$VAL1" == "0.6" ]; then VAL1=5.0; fi
if [ "$MODE" == "bilateral" ] && [ "$VAL2" == "6" ]; then VAL2=0.1; fi
if [ "$MODE" == "optical_flow" ] && [ "$VAL1" == "0.6" ]; then VAL1=0.5; fi

source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate depth-pro-for-video

DEPTH_CMD="depth-pro-run"
VIDEO_NAME=$(basename "$INPUT_VIDEO" | cut -f 1 -d '.')
DIR_SOURCE=$(dirname "$INPUT_VIDEO")

TMP_FRAMES="${DIR_SOURCE}/tmp_frames_${VIDEO_NAME}"
TMP_PADDED="${DIR_SOURCE}/tmp_padded_${VIDEO_NAME}"
TMP_DEPTH="${DIR_SOURCE}/tmp_depth_${VIDEO_NAME}"
OUTPUT_VIDEO="${DIR_SOURCE}/${VIDEO_NAME}_depthmap.mp4"

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

echo "🎬 Modus: $MODE | Wert1: $VAL1 | Wert2: $VAL2 | Pad: $PAD_TO_SQUARE"
mkdir -p "$TMP_FRAMES" "$TMP_DEPTH"

FPS=$(ffprobe -v 0 -of default=noprint_wrappers=1:nokey=1 -select_streams v:0 -show_entries stream=r_frame_rate "$INPUT_VIDEO")

echo "🔨 Zerlege Video..."
ffmpeg -v error -i "$INPUT_VIDEO" -pix_fmt rgb48be "$TMP_FRAMES/frame_%04d.png"

INFERENCE_FRAMES="$TMP_FRAMES"
CROP_FILTER=""
if [ "$PAD_TO_SQUARE" = true ]; then
    echo "🔲 Skaliere auf 1536×1536 (Letterbox)..."
    mkdir -p "$TMP_PADDED"
    ffmpeg -v error -i "$TMP_FRAMES/frame_%04d.png" \
        -vf "scale=1536:1536:force_original_aspect_ratio=decrease,pad=1536:1536:(ow-iw)/2:(oh-ih)/2:black" \
        "$TMP_PADDED/frame_%04d.png"
    INFERENCE_FRAMES="$TMP_PADDED"

    if [ "$ORIG_W" -ge "$ORIG_H" ]; then
        SCALED_W=1536
        SCALED_H=$(( (1536 * ORIG_H / ORIG_W) / 2 * 2 ))
    else
        SCALED_H=1536
        SCALED_W=$(( (1536 * ORIG_W / ORIG_H) / 2 * 2 ))
    fi
    CROP_X=$(( (1536 - SCALED_W) / 2 ))
    CROP_Y=$(( (1536 - SCALED_H) / 2 ))
    CROP_FILTER="-vf crop=${SCALED_W}:${SCALED_H}:${CROP_X}:${CROP_Y}"
fi

echo "🧠 Berechne Depth Maps..."
case "$MODE" in
    none)
        $DEPTH_CMD -i "$INFERENCE_FRAMES" -o "$TMP_DEPTH" --skip-display --filter-mode none --torch-compile --low-memory --png-compression 1
        ;;
    median)
        $DEPTH_CMD -i "$INFERENCE_FRAMES" -o "$TMP_DEPTH" --skip-display --filter-mode median --window-size "$VAL1" --torch-compile --low-memory --png-compression 1
        ;;
    combined)
        echo "   -> Kombinierter Modus: EMA=$VAL1, Median=$VAL2"
        $DEPTH_CMD -i "$INFERENCE_FRAMES" -o "$TMP_DEPTH" --skip-display --filter-mode combined --smooth "$VAL1" --window-size "$VAL2" --torch-compile --low-memory --png-compression 1
        ;;
    bilateral)
        echo "   -> Bilateral: Spatial=$VAL1, Range=$VAL2"
        $DEPTH_CMD -i "$INFERENCE_FRAMES" -o "$TMP_DEPTH" --skip-display --filter-mode bilateral --bilateral-spatial "$VAL1" --bilateral-range "$VAL2" --torch-compile --low-memory --png-compression 1
        ;;
    optical_flow)
        echo "   -> Optical Flow: Alpha=$VAL1"
        $DEPTH_CMD -i "$INFERENCE_FRAMES" -o "$TMP_DEPTH" --skip-display --filter-mode optical_flow --flow-alpha "$VAL1" --torch-compile --low-memory --png-compression 1
        ;;
    gmm)
        echo "   -> GMM: Components=$VAL1"
        $DEPTH_CMD -i "$INFERENCE_FRAMES" -o "$TMP_DEPTH" --skip-display --filter-mode gmm --gmm-components "$VAL1" --torch-compile --low-memory --png-compression 1
        ;;
    savgol)
        echo "   -> Savitzky-Golay: Window=$VAL1"
        $DEPTH_CMD -i "$INFERENCE_FRAMES" -o "$TMP_DEPTH" --skip-display --filter-mode savgol --window-size "$VAL1" --torch-compile --low-memory --png-compression 1
        ;;
    *)
        $DEPTH_CMD -i "$INFERENCE_FRAMES" -o "$TMP_DEPTH" --skip-display --filter-mode ema --smooth "$VAL1" --torch-compile --low-memory --png-compression 1
        ;;
esac

echo "🎞  Erstelle Video..."
ffmpeg -y -v error -r "$FPS" -i "$TMP_DEPTH/frame_%04d_16bit.png" $CROP_FILTER -c:v libx264 -crf 18 -pix_fmt yuv420p "$OUTPUT_VIDEO"

rm -rf "$TMP_FRAMES" "$TMP_PADDED" "$TMP_DEPTH"
echo "✅ Fertig: $OUTPUT_VIDEO"
