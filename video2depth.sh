#!/bin/bash

# =================================================================================
# Hilfsfunktion
# Zeigt die Nutzungsinformationen für das Skript an.
# =================================================================================
show_help() {
cat << EOF
Nutzung: ./video2depth.sh [-h] [-p] [-N] [-E] [-t] [-f BRENNWEITE|-F] video.mp4 [modus] [wert1] [wert2]
         ./video2depth.sh [-h] [-p] [-N] [-E] [-t] [-f BRENNWEITE|-F] verzeichnis/

Erstellt ein Depth-Map-Video aus einer Quelldatei oder allen Videos in einem Verzeichnis.

ARGUMENTE:
  video.mp4     Pfad zur Eingabevideodatei. (Erforderlich im Einzel-Modus)
  verzeichnis/  Verzeichnis mit Videodateien (.mp4, .mov, .mkv). Batch-Modus:
                alle Videos werden nacheinander mit Standardwerten verarbeitet.

  modus         Der zu verwendende Filtermodus. Optional.
                'none': Kein Filter
                Standard: 'optical_flow' mit Alpha 0.5
                'ema': Exponentieller Mittelwert
                'median': Median-Filter
                'combined': Median + EMA kombiniert
                'bilateral': Zeitlicher Bilateral-Filter (kantenerhaltend)
                'optical_flow': Optical Flow basierte Glättung
                'gmm': Gaussian Mixture Model
                'savgol': Savitzky-Golay Filter
                'ema_norm': Range-EMA (nunif-Stil) – glättet nur den
                            Normalisierungsbereich, kein Ghosting bei Bewegung

  wert1         - 'ema': Glättungsfaktor (0.0-1.0). (Standard: 0.6)
                - 'median': Fenstergröße. (Standard: 6)
                - 'combined': EMA-Glättungsfaktor. (Standard: 0.6)
                - 'bilateral': Räumliche Sigma. (Standard: 5.0)
                - 'optical_flow': Alpha-Wert (0.0-1.0). (Standard: 0.5) ← Standardmodus
                - 'gmm': Anzahl Komponenten. (Standard: 3)
                - 'savgol': Fenstergröße. (Standard: 6)

  wert2         - Nur bei 'combined': Fenstergröße für Median. (Standard: 6)
                - Bei 'bilateral': Wertebereich-Sigma. (Standard: 0.1)

OPTIONEN:
  -h, --help      Zeigt diese Hilfenachricht an und beendet das Skript.
  -p, --pad       Skaliert Frames auf 1536×1536 mit schwarzen Balken (Letterbox/Pillarbox)
                  bevor die Depth Maps berechnet werden. Verhindert Verzerrungen durch
                  das modellseitige Squishing auf 1:1 und verbessert die Inferenzqualität
                  bei nicht-quadratischen Videos.
  -n, --npz       Speichert alle Tiefenkarten als kombinierte NPZ-Datei
                  (<video>_depth.npz) mit rohen Float32-Tiefenwerten in Metern.
                  Array-Shape: (Frames, H, W). (Standard: aktiv)
  -N, --no-npz    Deaktiviert den NPZ-Export.
  -e, --enhance   Verbesserte Normalisierung: Percentile-Clipping (2%/98%) + Log-Skalierung.
                  (Standard: aktiv)
  -E, --no-enhance  Deaktiviert verbesserte Normalisierung, verwendet min/max-Normalisierung.
  -t, --tile      Zerlegt jeden Frame in 1536×1536-Kacheln, berechnet Depth Maps
                  pro Kachel und setzt sie zusammen. Höhere Detailauflösung bei
                  großen Frames (4K+), aber proportional mehr Rechenaufwand.
                  Schließt -p aus (Tiling hat Vorrang).
  -f, --f-px      Feste Brennweite in Pixeln (Standard: 1200). Überschreibt EXIF
                  und die per-Frame-FOV-Schätzung des Modells. Stabilisiert die
                  Tiefenskala über alle Frames und verhindert Hintergrund-Flicker.
  -F, --no-f-px   Deaktiviert die feste Brennweite; das Modell schätzt den FOV
                  pro Frame automatisch (ursprüngliches Verhalten).
  -r, --reflect-pad
                  Spiegelt Bildränder (6.25%) vor der Inferenz (nach nunif/iw3).
                  Reduziert Artefakte an Rändern, besonders bei Tiling.
  -b, --norm-buffer-size WERT
                  Puffergröße für ema_norm-Modus: Min/Max über N Frames
                  stabilisieren (Standard: 30; 1=deaktiviert).

BEISPIELE:
  ./video2depth.sh video.mp4
  ./video2depth.sh video.mp4 ema 0.5
  ./video2depth.sh video.mp4 bilateral 5.0 0.1
  ./video2depth.sh video.mp4 optical_flow 0.5
  ./video2depth.sh video.mp4 combined 0.5 5
  ./video2depth.sh -p video.mp4 ema 0.5
  ./video2depth.sh -N video.mp4
  ./video2depth.sh -t video.mp4 none
  ./video2depth.sh -f 1800 video.mp4
  ./video2depth.sh /Volumes/Videos/scenes/
  ./video2depth.sh -p /Volumes/Videos/scenes/
EOF
}

# =================================================================================
# Parameter-Verarbeitung
# =================================================================================
PAD_TO_SQUARE=false
SAVE_NPZ=true
TILING=false
ENHANCE=true
F_PX=1200
REFLECT_PAD=false
NORM_BUFFER_SIZE=30
ARGS=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        -p|--pad)           PAD_TO_SQUARE=true ;;
        -n|--npz)           SAVE_NPZ=true ;;
        -N|--no-npz)        SAVE_NPZ=false ;;
        -e|--enhance)       ENHANCE=true ;;
        -E|--no-enhance)    ENHANCE=false ;;
        -t|--tile)          TILING=true ;;
        -f|--f-px)          F_PX="$2"; shift ;;
        --f-px=*)           F_PX="${1#*=}" ;;
        -F|--no-f-px)       F_PX="" ;;
        -r|--reflect-pad)   REFLECT_PAD=true ;;
        -b|--norm-buffer-size) NORM_BUFFER_SIZE="$2"; shift ;;
        --norm-buffer-size=*)  NORM_BUFFER_SIZE="${1#*=}" ;;
        -h|--help)          show_help; exit 0 ;;
        *)                  ARGS+=("$1") ;;
    esac
    shift
done
set -- "${ARGS[@]}"

if [[ "$1" == "-h" ]] || [[ "$1" == "--help" ]]; then
    show_help
    exit 0
fi

if [ -z "$1" ]; then
    echo "❌ Fehler: Videodatei oder Verzeichnis fehlt."
    echo "Nutzung: ./video2depth.sh video.mp4 [modus] [wert1] [wert2]"
    echo "         ./video2depth.sh verzeichnis/"
    exit 1
fi

# =================================================================================
# Conda-Umgebung aktivieren (einmalig)
# =================================================================================
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate depth-pro-for-video

# =================================================================================
# Verarbeitungsfunktion für ein einzelnes Video
# Verwendet globale Variablen: MODE, VAL1, VAL2, PAD_TO_SQUARE, SAVE_NPZ,
#                              TILING, ENHANCE, BATCH_MODE
# =================================================================================
process_video() {
    local INPUT_VIDEO
    INPUT_VIDEO=$(realpath "$1")

    if [ ! -f "$INPUT_VIDEO" ]; then
        echo "❌ Datei nicht gefunden: $INPUT_VIDEO"
        return 1
    fi

    local ORIG_W ORIG_H
    ORIG_W=$(ffprobe -v error -select_streams v:0 -show_entries stream=width -of csv=p=0 "$INPUT_VIDEO")
    ORIG_H=$(ffprobe -v error -select_streams v:0 -show_entries stream=height -of csv=p=0 "$INPUT_VIDEO")

    local DEPTH_CMD="depth-pro-run"
    local VIDEO_NAME
    VIDEO_NAME=$(basename "$INPUT_VIDEO" | cut -f 1 -d '.')
    local DIR_SOURCE
    DIR_SOURCE=$(dirname "$INPUT_VIDEO")

    local TMP_FRAMES="${DIR_SOURCE}/tmp_frames_${VIDEO_NAME}"
    local TMP_PADDED="${DIR_SOURCE}/tmp_padded_${VIDEO_NAME}"
    local TMP_DEPTH="${DIR_SOURCE}/tmp_depth_${VIDEO_NAME}"
    local OUTPUT_VIDEO="${DIR_SOURCE}/${VIDEO_NAME}_depthmap.mp4"

    echo "📊 Analysiere Speicherplatzbedarf..."
    local FRAME_COUNT
    FRAME_COUNT=$(ffprobe -v error -select_streams v:0 -count_packets -show_entries stream=nb_read_packets -of csv=p=0 "$INPUT_VIDEO")
    local ESTIMATED_MB_PER_FRAME=25
    local TOTAL_REQUIRED_MB=$(( FRAME_COUNT * ESTIMATED_MB_PER_FRAME ))
    local AVAILABLE_MB
    AVAILABLE_MB=$(df -m "$DIR_SOURCE" | tail -1 | awk '{print $4}')

    echo "   - Frames: $FRAME_COUNT | Bedarf: ~$TOTAL_REQUIRED_MB MB | Verfügbar: $AVAILABLE_MB MB"

    if [ "$TOTAL_REQUIRED_MB" -gt "$AVAILABLE_MB" ]; then
        echo "⚠️  Warnung: Speicherplatz knapp!"
        if [ "${BATCH_MODE:-false}" = true ]; then
            echo "   Überspringe (Batch-Modus, kein interaktiver Prompt)."
            return 1
        fi
        read -p "Trotzdem fortfahren? (y/n): " confirm
        [[ $confirm != [yY] ]] && return 1
    fi

    local NPZ_FLAG=""
    if [ "$SAVE_NPZ" = true ]; then NPZ_FLAG="--save-npz"; fi

    local NORM_FLAG=""
    if [ "$ENHANCE" = true ]; then NORM_FLAG="--norm-mode enhanced"; fi

    local F_PX_FLAG=""
    if [[ -n "$F_PX" ]]; then F_PX_FLAG="--f-px ${F_PX}"; fi

    local REFLECT_FLAG=""
    if [ "$REFLECT_PAD" = true ]; then REFLECT_FLAG="--reflect-pad"; fi

    local NORM_BUFFER_FLAG="--norm-buffer-size ${NORM_BUFFER_SIZE}"

    local TILE_FLAG=""
    local PAD_ACTIVE="$PAD_TO_SQUARE"
    if [ "$TILING" = true ]; then
        TILE_FLAG="--tiling"
        if [ "$PAD_ACTIVE" = true ]; then
            echo "⚠️  -p wird ignoriert, da -t aktiv ist."
            PAD_ACTIVE=false
        fi
    fi

    echo "🎬 Modus: $MODE | Wert1: $VAL1 | Wert2: $VAL2 | Pad: $PAD_ACTIVE | Tile: $TILING | NPZ: $SAVE_NPZ | Enhance: $ENHANCE | f_px: $F_PX | ReflectPad: $REFLECT_PAD | NormBuf: $NORM_BUFFER_SIZE"
    mkdir -p "$TMP_FRAMES" "$TMP_DEPTH"

    local FPS
    FPS=$(ffprobe -v 0 -of default=noprint_wrappers=1:nokey=1 -select_streams v:0 -show_entries stream=r_frame_rate "$INPUT_VIDEO")

    echo "🔨 Zerlege Video..."
    ffmpeg -v error -i "$INPUT_VIDEO" -pix_fmt rgb48be "$TMP_FRAMES/frame_%04d.png"

    local INFERENCE_FRAMES="$TMP_FRAMES"
    local CROP_FILTER=""
    if [ "$PAD_ACTIVE" = true ]; then
        echo "🔲 Skaliere auf 1536×1536 (Letterbox)..."
        mkdir -p "$TMP_PADDED"
        ffmpeg -v error -i "$TMP_FRAMES/frame_%04d.png" \
            -vf "scale=1536:1536:force_original_aspect_ratio=decrease,pad=1536:1536:(ow-iw)/2:(oh-ih)/2:black" \
            "$TMP_PADDED/frame_%04d.png"
        INFERENCE_FRAMES="$TMP_PADDED"

        local SCALED_W SCALED_H CROP_X CROP_Y
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
            $DEPTH_CMD -i "$INFERENCE_FRAMES" -o "$TMP_DEPTH" --skip-display --filter-mode none --torch-compile --low-memory --png-compression 1 $NPZ_FLAG $TILE_FLAG $NORM_FLAG $F_PX_FLAG $REFLECT_FLAG $NORM_BUFFER_FLAG
            ;;
        median)
            $DEPTH_CMD -i "$INFERENCE_FRAMES" -o "$TMP_DEPTH" --skip-display --filter-mode median --window-size "$VAL1" --torch-compile --low-memory --png-compression 1 $NPZ_FLAG $TILE_FLAG $NORM_FLAG $F_PX_FLAG $REFLECT_FLAG $NORM_BUFFER_FLAG
            ;;
        combined)
            echo "   -> Kombinierter Modus: EMA=$VAL1, Median=$VAL2"
            $DEPTH_CMD -i "$INFERENCE_FRAMES" -o "$TMP_DEPTH" --skip-display --filter-mode combined --smooth "$VAL1" --window-size "$VAL2" --torch-compile --low-memory --png-compression 1 $NPZ_FLAG $TILE_FLAG $NORM_FLAG $F_PX_FLAG $REFLECT_FLAG $NORM_BUFFER_FLAG
            ;;
        bilateral)
            echo "   -> Bilateral: Spatial=$VAL1, Range=$VAL2"
            $DEPTH_CMD -i "$INFERENCE_FRAMES" -o "$TMP_DEPTH" --skip-display --filter-mode bilateral --bilateral-spatial "$VAL1" --bilateral-range "$VAL2" --torch-compile --low-memory --png-compression 1 $NPZ_FLAG $TILE_FLAG $NORM_FLAG $F_PX_FLAG $REFLECT_FLAG $NORM_BUFFER_FLAG
            ;;
        optical_flow)
            echo "   -> Optical Flow: Alpha=$VAL1"
            $DEPTH_CMD -i "$INFERENCE_FRAMES" -o "$TMP_DEPTH" --skip-display --filter-mode optical_flow --flow-alpha "$VAL1" --torch-compile --low-memory --png-compression 1 $NPZ_FLAG $TILE_FLAG $NORM_FLAG $F_PX_FLAG $REFLECT_FLAG $NORM_BUFFER_FLAG
            ;;
        gmm)
            echo "   -> GMM: Components=$VAL1"
            $DEPTH_CMD -i "$INFERENCE_FRAMES" -o "$TMP_DEPTH" --skip-display --filter-mode gmm --gmm-components "$VAL1" --torch-compile --low-memory --png-compression 1 $NPZ_FLAG $TILE_FLAG $NORM_FLAG $F_PX_FLAG $REFLECT_FLAG $NORM_BUFFER_FLAG
            ;;
        savgol)
            echo "   -> Savitzky-Golay: Window=$VAL1"
            $DEPTH_CMD -i "$INFERENCE_FRAMES" -o "$TMP_DEPTH" --skip-display --filter-mode savgol --window-size "$VAL1" --torch-compile --low-memory --png-compression 1 $NPZ_FLAG $TILE_FLAG $NORM_FLAG $F_PX_FLAG $REFLECT_FLAG $NORM_BUFFER_FLAG
            ;;
        ema_norm)
            echo "   -> Range-EMA (nunif): Decay=$VAL1"
            $DEPTH_CMD -i "$INFERENCE_FRAMES" -o "$TMP_DEPTH" --skip-display --filter-mode ema_norm --norm-decay "$VAL1" --torch-compile --low-memory --png-compression 1 $NPZ_FLAG $TILE_FLAG $NORM_FLAG $F_PX_FLAG $REFLECT_FLAG $NORM_BUFFER_FLAG
            ;;
        *)
            $DEPTH_CMD -i "$INFERENCE_FRAMES" -o "$TMP_DEPTH" --skip-display --filter-mode ema --smooth "$VAL1" --torch-compile --low-memory --png-compression 1 $NPZ_FLAG $TILE_FLAG $NORM_FLAG $F_PX_FLAG $REFLECT_FLAG $NORM_BUFFER_FLAG
            ;;
    esac

    if [ "$SAVE_NPZ" = true ]; then
        echo "📦 Füge NPZ-Einzelbilder zusammen..."
        local OUTPUT_NPZ="${DIR_SOURCE}/${VIDEO_NAME}_depth.npz"
        python -c "
import numpy as np, glob
files = sorted(glob.glob('${TMP_DEPTH}/*_depth.npz'))
loaded = [np.load(f) for f in files]
depth = np.stack([d['depth'] for d in loaded])
focallength_px = np.array([float(d['focallength_px']) for d in loaded], dtype=np.float32)
np.savez_compressed('${OUTPUT_NPZ}', depth=depth, focallength_px=focallength_px)
print(f'   -> {len(loaded)} Frames, depth shape: {depth.shape}, f_px: min={focallength_px.min():.1f} max={focallength_px.max():.1f} mean={focallength_px.mean():.1f}')
"
    fi

    echo "🎞  Erstelle Video..."
    ffmpeg -y -v error -r "$FPS" -i "$TMP_DEPTH/frame_%04d_16bit.png" $CROP_FILTER -c:v libx264 -crf 18 -pix_fmt yuv420p "$OUTPUT_VIDEO"

    rm -rf "$TMP_FRAMES" "$TMP_PADDED" "$TMP_DEPTH"
    echo "✅ Fertig: $OUTPUT_VIDEO"
}

# =================================================================================
# Einzel- oder Batch-Modus
# =================================================================================
if [ -d "$1" ]; then
    # ── Batch-Modus ──────────────────────────────────────────────────────────────
    BATCH_MODE=true
    INPUT_DIR=$(realpath "$1")
    MODE=optical_flow
    VAL1=0.5
    VAL2=6

    VIDEO_FILES=()
    while IFS= read -r -d '' f; do
        VIDEO_FILES+=("$f")
    done < <(find "$INPUT_DIR" -maxdepth 1 -type f \( -iname "*.mp4" -o -iname "*.mov" -o -iname "*.mkv" \) -print0 | sort -z)

    TOTAL=${#VIDEO_FILES[@]}
    if [ "$TOTAL" -eq 0 ]; then
        echo "❌ Keine Videodateien (.mp4, .mov, .mkv) in: $INPUT_DIR"
        exit 1
    fi

    echo "📁 Batch-Modus: $TOTAL Videos in $INPUT_DIR"
    echo "   Modus: $MODE $VAL1 | NPZ: $SAVE_NPZ | Enhance: $ENHANCE | Pad: $PAD_TO_SQUARE | Tile: $TILING"

    DONE=0
    FAILED=0
    for i in "${!VIDEO_FILES[@]}"; do
        echo ""
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        echo "[$((i+1))/$TOTAL] $(basename "${VIDEO_FILES[$i]}")"
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        if process_video "${VIDEO_FILES[$i]}"; then
            DONE=$(( DONE + 1 ))
        else
            FAILED=$(( FAILED + 1 ))
        fi
    done

    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "📁 Batch abgeschlossen: $DONE/$TOTAL erfolgreich${FAILED:+, $FAILED übersprungen}."

else
    # ── Einzel-Modus ─────────────────────────────────────────────────────────────
    BATCH_MODE=false

    if [ ! -f "$1" ]; then
        echo "❌ Fehler: Datei oder Verzeichnis nicht gefunden: $1"
        exit 1
    fi

    MODE=${2:-optical_flow}
    VAL1=${3:-0.5}
    VAL2=${4:-6}

    if [ "$MODE" == "ema_norm" ] && [ "$VAL1" == "0.5" ]; then VAL1=0.9; fi
    if [ "$MODE" == "ema" ] && [ "$VAL1" == "0.5" ]; then VAL1=0.6; fi
    if [ "$MODE" == "median" ] && [ "$VAL1" == "0.5" ]; then VAL1=6; fi
    if [ "$MODE" == "savgol" ] && [ "$VAL1" == "0.5" ]; then VAL1=6; fi
    if [ "$MODE" == "gmm" ] && [ "$VAL1" == "0.5" ]; then VAL1=3; fi
    if [ "$MODE" == "bilateral" ] && [ "$VAL1" == "0.5" ]; then VAL1=5.0; fi
    if [ "$MODE" == "bilateral" ] && [ "$VAL2" == "6" ]; then VAL2=0.1; fi

    process_video "$1"
fi
