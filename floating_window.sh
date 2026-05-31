#!/bin/bash

# =================================================================================
# Hilfsfunktion
# =================================================================================
show_help() {
cat << EOF
Nutzung: ./floating_window.sh [-h] [Optionen] video.mp4 [ausgabe-prefix]

Legt Floating-Window-Balken auf vorhandene L/R-Stereovideos.
Die Balkenbreite wird aus der Tiefenkarte berechnet und zeitlich geglättet
(sofort rein, langsam raus).

ARGUMENTE:
  video.mp4         RGB-Quellvideo (Basis für Namens-Ableitung der L/R/Depth-Dateien)
  ausgabe-prefix    Prefix für Ausgabedateien (Standard: <video>_fw)

  Im selben Verzeichnis werden automatisch gesucht:
    <name>_L.mp4               Linkes Auge (Pflicht)
    <name>_R.mp4               Rechtes Auge (Pflicht)
    <name>_depth.npz           Tiefendaten (bevorzugt)
    <name>_depthmap.mp4        Tiefendaten (Fallback)
    <name>_depth.mp4           Tiefendaten (Fallback)

OPTIONEN:
  -h, --help            Zeigt diese Hilfemeldung
  --format FORMAT       Ausgabeformat:
                          'anaglyph' : Rot-Cyan-Anaglyphe (Standard)
                          'lr'       : Zwei separate Dateien (_L.mp4 / _R.mp4)
  --anaglyph-method M   Anaglyphen-Methode (nur bei --format anaglyph):
                          'dubois'     : Optimiert, empfohlen (Standard)
                          'half-color' : Linkes Auge grau, rechtes farbig
                          'color'      : Einfache Kanal-Trennung
                          'gray'       : Beide Augen grau
                          'amber-blue' : Gelb/Amber links, Blau rechts
                          'wimmer'     : Wimmer's Optimized
  --divergence N        Parallaxbetrag in % der Bildbreite (Standard: 3.0)
  --convergence N       Nullparallax-Ebene 0.0–1.0 (Standard: 0.5)
  --depth-near MODE     Welcher Tonwert bedeutet 'nah':
                          'white' : Weiß=nah (Standard, Ausgabe von video2depth.sh)
                          'black' : Schwarz=nah
  --smoothing N         Glättung in Frames: Balken erscheinen sofort,
                        gleiten langsam aus (Standard: 12)
  --fps N               FPS überschreiben (Standard: aus Quellvideo)

BEISPIELE:
  ./floating_window.sh video.mp4
  ./floating_window.sh video.mp4 --format anaglyph --divergence 3.5
  ./floating_window.sh video.mp4 --format lr --convergence 0.4
  ./floating_window.sh video.mp4 --smoothing 24 --depth-near black
EOF
}

# =================================================================================
# Parameter-Verarbeitung
# =================================================================================
EXTRA_ARGS=()
POSITIONAL=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)
            show_help
            exit 0
            ;;
        --format|--anaglyph-method|--divergence|--convergence|--depth-near|--smoothing|--fps|--left|-l|--right|-r|--depth|-d)
            EXTRA_ARGS+=("$1" "$2")
            shift 2
            ;;
        *)
            POSITIONAL+=("$1")
            shift
            ;;
    esac
done

INPUT_VIDEO="${POSITIONAL[0]}"
OUTPUT_PREFIX="${POSITIONAL[1]}"

if [ -z "$INPUT_VIDEO" ]; then
    echo "❌ Fehler: Videodatei fehlt."
    echo "Nutzung: ./floating_window.sh video.mp4 [ausgabe-prefix]"
    exit 1
fi

if [ ! -f "$INPUT_VIDEO" ]; then
    echo "❌ Datei nicht gefunden: $INPUT_VIDEO"
    exit 1
fi

source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate depth-pro-for-video

CMD=(floating-window -i "$INPUT_VIDEO")
if [ -n "$OUTPUT_PREFIX" ]; then
    CMD+=(-o "$OUTPUT_PREFIX")
fi
CMD+=("${EXTRA_ARGS[@]}")

echo "▶ ${CMD[*]}"
"${CMD[@]}"
