#!/bin/bash

# =================================================================================
# Hilfsfunktion
# =================================================================================
show_help() {
cat << EOF
Nutzung: ./depth2stereo.sh [-h] [--format FORMAT] [--divergence N] [--convergence N]
                           [--inpainting MODE] [--fps N]
                           video.mp4 [ausgabe-prefix]
         ./depth2stereo.sh [-h] [Optionen] verzeichnis/

Erstellt ein Stereovideo aus einem Originalvideo und zugehörigen Tiefenkarten.

ARGUMENTE:
  video.mp4         Pfad zum Originalvideo. (Erforderlich im Einzel-Modus)
  verzeichnis/      Verzeichnis mit Videodateien. Batch-Modus: alle Videos werden
                    nacheinander mit den angegebenen Optionen verarbeitet.
  ausgabe-prefix    Präfix für die Ausgabedatei(en). (Standard: <video>_stereo)

  Die Tiefendaten werden automatisch im selben Verzeichnis wie das Video gesucht:
    1. <videoname>_depth.npz    (bevorzugt, aus video2depth.sh --save-npz)
    2. <videoname>_depthmap.mp4
    3. <videoname>_depth.mp4
  Mit --depth PATH kann stattdessen eine Tiefendatei explizit vorgegeben werden
  (überschreibt die automatische Suche; nur im Einzel-Modus).

OPTIONEN:
  -h, --help        Zeigt diese Hilfenachricht an.
  --depth PATH      Explizite Tiefendatei (NPZ oder Depth-Video). Überschreibt die
                    automatische Suche. Nur im Einzel-Modus wirksam.
  --format FORMAT   Ausgabeformat:
                    'half-sbs'   : L|R nebeneinander, je W/2 Breite (Standard)
                    'full-sbs'   : L|R nebeneinander, volle Auflösung (2W×H)
                    'top-bottom' : L über R (W×2H)
                    'anaglyph'   : Rot-Cyan-Anaglyphe (W×H)
                    'lr'         : Zwei separate Dateien (_L.mp4 / _R.mp4)
  --divergence N    Parallaxbetrag in % der Bildbreite. (Standard: 2.5)
  --convergence N   Nullparallax-Ebene 0.0–1.0. (Standard: 0.5)
  --inpainting MODE Stereo-Methode / Hole-Filling:
                    'geometric'      : Direktionales Auffüllen + morphologisches Closing (Standard)
                    'lama'           : LaMa ML-Inpainting (pip install simple-lama-inpainting)
                    'none'           : Kein Auffüllen (Forward-Warp)
                    'row_flow'       : nunif RowFlowV3 ML-Backward-Warp (kein Ghosting)
                    'mlbw_l4'        : nunif MLBW-L4 Multi-Layer Backward-Warp
                    'forward_inpaint': Forward-Warp + nunif LightInpaint V1
                    'mlbw_inpaint'   : MLBW Backward-Warp + nunif LightInpaint V1
                    ML-Methoden: nunif wird beim ersten Aufruf automatisch
                      nach ~/.cache/nunif_repo geklont.
  --synthetic-view M  Welches Auge synthetisiert wird:
                    'both'  : Beide Augen (Standard)
                    'right' : Nur rechtes Auge, linkes = Original (schneller)
                    'left'  : Nur linkes Auge, rechtes = Original
  --anaglyph-method M  Anaglyphen-Verfahren (nur bei --format anaglyph):
                    'dubois'     : Optimierte Matrix-Methode (Standard, empfohlen)
                    'half-color' : Linkes Auge grau/Rot, rechtes farbig/Cyan
                    'color'      : Einfache Kanal-Trennung Rot-Cyan
                    'gray'       : Beide Augen grau, Rot-Cyan
                    'amber-blue' : Gelb/Amber links, Blau rechts
                    'wimmer'     : Wimmer's Optimized (G*0.7+B*0.3 als Rot-Kanal)
  --depth-near MODE Welcher Tonwert bedeutet 'nah':
                    'white' : Weiß=nah, Schwarz=fern (Standard, Ausgabe von video2depth.sh)
                    'black' : Schwarz=nah, Weiß=fern
  --norm-mode MODE  Tiefen-Normalisierung für den Stereo-Warp:
                    'global' : feste Skala über den ganzen Clip (Standard, stabile Konvergenz)
                    'none'   : Tiefenquelle unverändert (nur [0,1]-Clip); für bereits
                               normalisierte/angepasste Depthmaps, NICHT für rohe NPZ.
  --norm-clip N     Perzentil zum Kürzen der globalen Skala (nur bei --norm-mode global,
                    Standard: 0.5). 0 = exaktes globales Min/Max.
  --max-width N     Maximale Breite für ML-Inferenz. Senkt Rechenaufwand stark
                      (z.B. --max-width 960 für halbe Auflösung).
                      Nur bei ML-Methoden (row_flow, mlbw_l4, forward_inpaint, mlbw_inpaint).
  --edge-dilation N   Tiefenkanten-Dilation in Pixeln vor dem Stereo-Warp (Standard: 0).
                      Bläht Vordergrundbereiche in Hintergrundkanten hinein, reduziert
                      Säume im Stereobild. Empfohlen: 2–8 Pixel.
  --inner-dilation N  Hole-Maske vor dem Inpainting aufblähen (Standard: 0)
                      Nur bei ML-Methoden (forward_inpaint, mlbw_inpaint).
  --outer-dilation N  Hole-Maske nach dem Inpainting aufblähen (Standard: 0)
                      Nur bei ML-Methoden (forward_inpaint, mlbw_inpaint).
  --reflect-pad     Bildränder vor dem Warp spiegeln (reduziert Randartefakte beim Inpainting).
                    Nach dem Warp wird das Padding automatisch wieder entfernt.
  --reflect-pad-frac F  Padding-Größe als Anteil der Bildgröße (Standard: 0.0625 = 6.25%%).
  --fps N           FPS überschreiben (Standard: aus Quellvideo)

BEISPIELE:
  ./depth2stereo.sh video.mp4
  ./depth2stereo.sh video.mp4 --format anaglyph
  ./depth2stereo.sh video.mp4 --format lr --divergence 3.0
  ./depth2stereo.sh video.mp4 --format half-sbs --inpainting lama
  ./depth2stereo.sh video.mp4 --inpainting row_flow
  ./depth2stereo.sh video.mp4 --inpainting mlbw_inpaint --format anaglyph
  ./depth2stereo.sh video.mp4 --divergence 2.0 --convergence 0.4
  ./depth2stereo.sh /Volumes/Videos/scenes/ --format anaglyph --inpainting mlbw_inpaint
EOF
}

# =================================================================================
# Parameter-Verarbeitung
# =================================================================================
EXTRA_ARGS=()
POSITIONAL=()
DEPTH_OVERRIDE=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)
            show_help
            exit 0
            ;;
        --depth)
            DEPTH_OVERRIDE="$2"
            shift 2
            ;;
        --format|--divergence|--convergence|--inpainting|--synthetic-view|--anaglyph-method|--depth-near|--norm-mode|--norm-clip|--max-width|--edge-dilation|--inner-dilation|--outer-dilation|--reflect-pad-frac|--fps)
            EXTRA_ARGS+=("$1" "$2")
            shift 2
            ;;
        --reflect-pad)
            EXTRA_ARGS+=("$1")
            shift
            ;;
        *)
            POSITIONAL+=("$1")
            shift
            ;;
    esac
done

source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate depth-pro-for-video

# =================================================================================
# Verarbeitungsfunktion für ein einzelnes Video
# =================================================================================
process_video() {
    local INPUT_VIDEO
    INPUT_VIDEO=$(realpath "$1")
    local OUTPUT_PREFIX="$2"

    if [ ! -f "$INPUT_VIDEO" ]; then
        echo "❌ Datei nicht gefunden: $INPUT_VIDEO"
        return 1
    fi

    local DIR_SOURCE VIDEO_NAME
    DIR_SOURCE=$(dirname "$INPUT_VIDEO")
    VIDEO_NAME=$(basename "$INPUT_VIDEO" | cut -f 1 -d '.')

    # Tiefendaten: expliziter Override (--depth) oder automatische Suche
    local DEPTH_FILE=""
    if [ -n "$DEPTH_OVERRIDE" ]; then
        if [ ! -f "$DEPTH_OVERRIDE" ]; then
            echo "❌ Angegebene Tiefendatei nicht gefunden: $DEPTH_OVERRIDE"
            return 1
        fi
        DEPTH_FILE=$(realpath "$DEPTH_OVERRIDE")
    elif [ -f "${DIR_SOURCE}/${VIDEO_NAME}_depth.npz" ]; then
        DEPTH_FILE="${DIR_SOURCE}/${VIDEO_NAME}_depth.npz"
    elif [ -f "${DIR_SOURCE}/${VIDEO_NAME}_depthmap.mp4" ]; then
        DEPTH_FILE="${DIR_SOURCE}/${VIDEO_NAME}_depthmap.mp4"
    elif [ -f "${DIR_SOURCE}/${VIDEO_NAME}_depth.mp4" ]; then
        DEPTH_FILE="${DIR_SOURCE}/${VIDEO_NAME}_depth.mp4"
    else
        echo "⚠️  Keine Tiefendaten gefunden für: $VIDEO_NAME — übersprungen."
        echo "   Gesucht:"
        echo "     ${DIR_SOURCE}/${VIDEO_NAME}_depth.npz"
        echo "     ${DIR_SOURCE}/${VIDEO_NAME}_depthmap.mp4"
        echo "     ${DIR_SOURCE}/${VIDEO_NAME}_depth.mp4"
        return 1
    fi
    echo "📎 Tiefendaten: $(basename "$DEPTH_FILE")"

    if [ -z "$OUTPUT_PREFIX" ]; then
        OUTPUT_PREFIX="${DIR_SOURCE}/${VIDEO_NAME}_stereo"
    fi

    depth2stereo -i "$INPUT_VIDEO" -d "$DEPTH_FILE" -o "$OUTPUT_PREFIX" "${EXTRA_ARGS[@]}"
}

# =================================================================================
# Einzel- oder Batch-Modus
# =================================================================================
INPUT_ARG="${POSITIONAL[0]}"
OUTPUT_PREFIX="${POSITIONAL[1]}"

if [ -z "$INPUT_ARG" ]; then
    echo "❌ Fehler: Videodatei oder Verzeichnis fehlt."
    echo "Nutzung: ./depth2stereo.sh video.mp4 [ausgabe-prefix]"
    echo "         ./depth2stereo.sh verzeichnis/"
    exit 1
fi

if [ -d "$INPUT_ARG" ]; then
    # ── Batch-Modus ──────────────────────────────────────────────────────────
    INPUT_DIR=$(realpath "$INPUT_ARG")

    if [ -n "$DEPTH_OVERRIDE" ]; then
        echo "⚠️  --depth wird im Batch-Modus ignoriert (gilt nur pro Einzeldatei)."
        DEPTH_OVERRIDE=""
    fi

    VIDEO_FILES=()
    while IFS= read -r -d '' f; do
        VIDEO_FILES+=("$f")
    done < <(find "$INPUT_DIR" -maxdepth 1 -type f \( -iname "*.mp4" -o -iname "*.mov" -o -iname "*.mkv" \) -print0 | sort -z)

    # Depthmap-Dateien ausfiltern
    SCENE_FILES=()
    for f in "${VIDEO_FILES[@]}"; do
        name=$(basename "$f")
        [[ "$name" == *_depthmap.mp4 || "$name" == *_depth.mp4 ]] && continue
        SCENE_FILES+=("$f")
    done

    TOTAL=${#SCENE_FILES[@]}
    if [ "$TOTAL" -eq 0 ]; then
        echo "❌ Keine Videodateien (.mp4, .mov, .mkv) in: $INPUT_DIR"
        exit 1
    fi

    echo "📁 Batch-Modus: $TOTAL Videos in $INPUT_DIR"

    DONE=0
    FAILED=0
    for i in "${!SCENE_FILES[@]}"; do
        echo ""
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        echo "[$((i+1))/$TOTAL] $(basename "${SCENE_FILES[$i]}")"
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        if process_video "${SCENE_FILES[$i]}"; then
            DONE=$(( DONE + 1 ))
        else
            FAILED=$(( FAILED + 1 ))
        fi
    done

    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "📁 Batch abgeschlossen: $DONE/$TOTAL erfolgreich${FAILED:+, $FAILED übersprungen}."

else
    # ── Einzel-Modus ─────────────────────────────────────────────────────────
    process_video "$INPUT_ARG" "$OUTPUT_PREFIX"
fi
