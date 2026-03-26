## Depth Pro: Scharfe Monokulare Metrische Depthmaps für Videos

# Erste Schritte

Wir empfehlen, eine virtuelle Umgebung einzurichten. Zum Beispiel mit miniconda kann das `depth_pro_for_video`-Paket wie folgt installiert werden:

```bash
conda create -n depth-pro-for-video -y python=3.9
conda activate depth-pro-for-video

pip install -e .
```

Um vortrainierte KI-Modelle (Checkpoints) herunterzuladen, führen Sie das folgende Code-Schnipsel aus:
```bash
source get_pretrained_models.sh   # Files will be downloaded to `checkpoints` directory.
```

### Ausführung über die Kommandozeile

Wir stellen Hilfsskripte bereit, um das Modell direkt auf einem einzelnen Bild oder einem Video auszuführen:
```bash
# Führe die Erstellung einer Depthmap auf einem einzelnen Bild aus:
depth-pro-run -i ./data/image/example.jpg -o ./data/image/depth/ --skip-display
# Führe `depth-pro-run -h` aus, um verfügbare Optionen anzuzeigen.

# Führe die Erstellung von Depthmaps auf einem Video aus:
./video2depth.sh ./data/video/example.mp4              # Ohne Filter
./video2depth.sh ./data/video/example.mp4 ema 0.6      # Mit EMA-Filter
# Weitere Filter-Beispiele siehe unten
# Führe `video2depth.sh -h` aus, um verfügbare Optionen anzuzeigen.
```
### Filter-Optionen

Die folgenden Filter können angewendet werden, um zeitliches Flackern in Depthmap-Videos zu reduzieren und die Konsistenz zwischen aufeinanderfolgenden Frames zu verbessern.

#### `none` – Kein Filter
Verwendet die rohen Depthmaps ohne jede zeitliche Glättung. Nützlich für Benchmarking oder wenn nachträglich eigene Filter angewendet werden sollen.

#### `ema` – Exponentieller Mittelwert (Exponential Moving Average)
Berechnet einen gewichteten Durchschnitt zwischen der aktuellen und der vorherigen Depthmap. Der `alpha`-Parameter (0.0–1.0) bestimmt, wie stark der aktuelle Frame gewichtet wird:
- `alpha = 0.9`: Starke Betonung des aktuellen Frames, minimale Glättung
- `alpha = 0.5`: Gleiche Gewichtung, moderate Glättung
- `alpha = 0.1`: Starke Glättung, langsamer Reaktion auf Änderungen

**Vorteile:** Schnell, einfach, geringer Speicherverbrauch  
**Nachteile:** Kann bei schnellen Bewegungen Geisterbilder erzeugen

#### `median` – Median-Filter
Speichert ein Fenster der letzten N Frames und berechnet den Median pro Pixel. Entfernt effektiv Ausreißer und plötzliche Rauschspitzen, ohne Werte zu "verwaschen".

- `window_size`: Anzahl der Frames im Puffer (Standard: 6)

**Vorteile:** Robust gegen Ausreißer, erhält Kanten  
**Nachteile:** Benötigt mehr Speicher, Latenz durch Fenstergröße

#### `combined` – Median + EMA
Wendet zuerst den Median-Filter an (entfernt Ausreißer), dann EMA (glättet den Verlauf). Kombiniert die Vorteile beider Filter.

- `alpha`: EMA-Glättungsfaktor (Standard: 0.6)
- `window_size`: Median-Fenstergröße (Standard: 6)

**Vorteile:** Maximale Stabilität, beste Unterdrückung von Flackern  
**Nachteile:** Höchster Speicherverbrauch und Latenz

#### `bilateral` – Zeitlicher Bilateral-Filter
Ein kantenerhaltender Filter, der Pixel basierend auf ihrer Ähnlichkeit gewichtet. Nur Pixel mit ähnlichen Tiefenwerten beeinflussen sich gegenseitig, wodurch Objektkanten scharf bleiben.

- `spatial_sigma`: Räumliche Gewichtung (Standard: 5.0) – höhere Werte = stärkere Glättung
- `range_sigma`: Wertebereich-Gewichtung (Standard: 0.1) – niedrigere Werte = stärkere Kantenerhaltung

**Vorteile:** Erhält scharfe Kanten zwischen Objekten  
**Nachteile:** Rechenintensiver als EMA

#### `optical_flow` – Optical Flow basierte Glättung
Nutzt Bewegungsvektoren zwischen Frames, um die vorherige Depthmap an die neue Position zu "verziehen" (Warping), bevor die Mischung erfolgt. Dadurch wird Bewegung berücksichtigt und Geisterbilder werden reduziert.

- `alpha`: Mischungsverhältnis zwischen aktuellem und gewarptem Frame (Standard: 0.5)

**Vorteile:** Beste Ergebnisse bei Kamerabewegung oder sich bewegenden Objekten  
**Nachteile:** Am rechenintensivsten, kann bei schnellen Bewegungen Artefakte erzeugen

#### `gmm` – Gaussian Mixture Model
Modelliert die Tiefenverteilung pro Pixel als Mischung von Gaußverteilungen. Robust gegen plötzliche Änderungen und kann mehrere Tiefenhypothesen verwalten.

- `components`: Anzahl der Gauß-Komponenten (Standard: 3)

**Vorteile:** Robust bei Szenenwechseln, modelliert Unsicherheit  
**Nachteile:** Speicherintensiv, komplexer Algorithmus

#### `savgol` – Savitzky-Golay Filter
Ein polynomieller Glättungsfilter, der lokale Maxima und Minima besser erhält als ein einfacher Durchschnitt. Passt ein Polynom an ein Fenster von Frames an.

- `window_size`: Fenstergröße, muss ungerade und ≥3 sein (Standard: 6)

**Vorteile:** Erhält lokale Details und Spitzenwerte  
**Nachteile:** Benötisiert mehrere Frames, weniger robust gegen Ausreißer als Median

---

### Empfehlungen

| Szenario | Empfohlener Filter | Begründung |
|----------|-------------------|------------|
| Statische Szene, wenig Bewegung | `ema` mit α=0.4–0.6 | Einfach, effektiv |
| Schnelle Bewegung, Action | `optical_flow` | Berücksichtigt Bewegung |
| Starke Ausreißer, Rauschen | `median` oder `combined` | Robust gegen Ausreißer |
| Scharfe Kanten wichtig | `bilateral` | Kantenerhaltend |
| Szenen mit Hintergrund/Vordergrund | `gmm` | Mehrere Tiefenhypothesen |
| Maximale Qualität | `combined` oder `optical_flow` | Beste Stabilität |

---

### Schnellreferenz

| Filter | Parameter | Standard | Befehl |
|--------|-----------|----------|--------|
| `none` | – | – | `./video2depth.sh video.mp4` |
| `ema` | `alpha` | 0.6 | `./video2depth.sh video.mp4 ema 0.6` |
| `median` | `window_size` | 6 | `./video2depth.sh video.mp4 median 6` |
| `combined` | `alpha`, `window_size` | 0.6, 6 | `./video2depth.sh video.mp4 combined 0.6 6` |
| `bilateral` | `spatial_sigma`, `range_sigma` | 5.0, 0.1 | `./video2depth.sh video.mp4 bilateral 5.0 0.1` |
| `optical_flow` | `alpha` | 0.5 | `./video2depth.sh video.mp4 optical_flow 0.5` |
| `gmm` | `components` | 3 | `./video2depth.sh video.mp4 gmm 3` |
| `savgol` | `window_size` | 6 | `./video2depth.sh video.mp4 savgol 7` |

---

## Performance-Optimierung für Apple Silicon

Das Skript ist bereits für Apple Silicon (M1/M2/M3/M4) optimiert:

### Automatisch aktivierte Optimierungen

| Optimierung | Beschreibung |
|-------------|--------------|
| **MPS Backend** | Nutzt Metal Performance Shaders für GPU-Beschleunigung |
| **Half Precision (FP16)** | Reduziert Speicherverbrauch, verdoppelt Geschwindigkeit |
| **torch.compile()** | Just-In-Time-Kompilierung für schnellere Inferenz (PyTorch 2.0+) |
| **Memory Management** | Regelmäßiges Freigeben von GPU-Speicher |
| **PNG Fast-Write** | Kompression auf Stufe 1 für schnelleres Schreiben |

### Manuelle CLI-Optionen

Für `depth-pro-run` stehen weitere Optionen zur Verfügung:

```bash
depth-pro-run -i ./frames -o ./depth \
    --torch-compile \       # Aktiviert torch.compile() (PyTorch 2.0+)
    --low-memory \          # Memory-Optimierungen für wenig RAM
    --png-compression 1     # 0=schnell, 9=klein (Standard: 1)
```

### RAM-Disk für temporäre Dateien (optional)

Für noch schnellere I/O kann eine RAM-Disk verwendet werden:

```bash
# RAM-Disk erstellen (4GB)
sudo diskutil erasevolume HFS+ RAMDisk "$(hdiutil attach -nomount ram://8388608)"

# Video in RAM-Disk verarbeiten
./video2depth.sh /Volumes/RAMDisk/video.mp4 ema 0.6
```

### Geschwindigkeitsvergleich (M4, 16GB)

| Szenario | Frames/s | Anmerkung |
|----------|----------|-----------|
| Ohne Optimierung | ~0.5 fps | Nur CPU |
| MPS + FP16 | ~2-3 fps | Standard |
| + torch.compile | ~3-4 fps | Nach Warmup |

---

## Optimale Bildgröße

Das KI-Modell arbeitet intern mit einer festen Auflösung von **1536×1536 Pixeln**.

### Multi-Scale Architektur

| Ebene | Auflösung | Beschreibung |
|-------|-----------|--------------|
| ViT Backbone | 384×384 | Basis-Auflösung des Vision Transformers (DINOv2) |
| Niedrig | 384×384 | Patch-basierte Verarbeitung mit 25% Overlap |
| Mittel | 768×768 | 50% der vollen Auflösung |
| Hoch (Full) | **1536×1536** | Optimale Netzwerk-Eingabegröße |

### Automatische Anpassung

Bilder mit anderer Auflösung werden automatisch verarbeitet:
1. Skalierung auf 1536×1536 (interne Verarbeitung)
2. Depthmap-Berechnung
3. Zurückskalierung auf Originalgröße

**Hinweis:** Das Aspect Ratio wird nicht beibehalten, was bei stark nicht-quadratischen Bildern zu leichten Verzerrungen führen kann.

### Empfehlung für beste Qualität

Für optimale und konsistente Ergebnisse sollte das Video vorab auf 1536×1536 skaliert werden:

```bash
# Mit Padding (Aspect Ratio beibehalten)
ffmpeg -i input.mp4 -vf "scale=1536:1536:force_original_aspect_ratio=decrease,pad=1536:1536:(ow-iw)/2:(oh-ih)/2:black" output.mp4

# Ohne Padding (Aspect Ratio ändern)
ffmpeg -i input.mp4 -vf "scale=1536:1536" output.mp4
```

### Performance-Tipps

- **Kleinere Auflösungen** (z.B. 768×768): Schnellere Verarbeitung, geringere Qualität
- **Größere Auflösungen** (z.B. 2048×2048): Langsamer, automatische Skalierung auf 1536×1536
- **Native 1536×1536**: Beste Balance aus Qualität und Geschwindigkeit

## License
This sample code is released under the [LICENSE](LICENSE) terms.

The model weights are released under the [LICENSE](LICENSE) terms.

## Acknowledgements

Our codebase is built using multiple opensource contributions, please see [Acknowledgements](ACKNOWLEDGEMENTS.md) for more details.

Please check the paper for a complete list of references and datasets used in this work.
