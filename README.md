# Depth Pro: Scharfe Monokulare Metrische Depthmaps für Videos

## Erste Schritte

```bash
# Virtuelle Umgebung erstellen (miniconda empfohlen)
conda create -n depth-pro-for-video -y python=3.9
conda activate depth-pro-for-video

# Paket installieren
pip install -e .

# Vortrainierte Modelle herunterladen
source get_pretrained_models.sh
```

---

## Schnellstart

### Einzelbild verarbeiten
```bash
depth-pro-run -i ./data/image/example.jpg -o ./output/ --skip-display
```

### Video verarbeiten
```bash
./video2depth.sh ./data/video/example.mp4              # Ohne Filter
./video2depth.sh ./data/video/example.mp4 ema 0.6      # Mit EMA-Filter
```

---

## Filter-Optionen im Detail

Alle Filter reduzieren zeitliches Flackern und verbessern die Konsistenz zwischen aufeinanderfolgenden Frames.

### Übersicht aller Filter

| Filter | Parameter | Standard | Speicher | Geschwindigkeit | Best für |
|--------|-----------|----------|----------|-----------------|----------|
| `none` | – | – | Minimal | Schnellst | Benchmarking |
| `ema` | `alpha` | 0.6 | Minimal | Schnell | Statische Szenen |
| `median` | `window_size` | 6 | Mittel | Mittel | Ausreißer entfernen |
| `combined` | `alpha`, `window_size` | 0.6, 6 | Hoch | Mittel | Maximale Stabilität |
| `bilateral` | `spatial_sigma`, `range_sigma` | 5.0, 0.1 | Minimal | Mittel | Kantenerhaltung |
| `optical_flow` | `alpha` | 0.5 | Mittel | Langsam | Bewegte Szenen |
| `gmm` | `components` | 3 | Hoch | Mittel | Szenenwechsel |
| `savgol` | `window_size` | 6 | Mittel | Mittel | Details erhalten |

---

### `none` – Kein Filter
Rohe Depthmaps ohne zeitliche Glättung. Ideal für Benchmarking oder nachträgliche Filterung.

```bash
./video2depth.sh video.mp4
```

---

### `ema` – Exponentieller Mittelwert
Gewichteter Durchschnitt zwischen aktuellem und vorherigem Frame.

**Parameter:**
| Parameter | Bereich | Standard | Effekt |
|-----------|---------|----------|--------|
| `alpha` | 0.0–1.0 | 0.6 | Höher = mehr aktueller Frame |

**Alpha-Werte im Vergleich:**
- `0.9`: Minimale Glättung, fast rohe Frames
- `0.6`: Ausgewogene Glättung (Standard)
- `0.3`: Starke Glättung, langsame Anpassung
- `0.1`: Sehr starke Glättung, Geisterbilder möglich

**Beispiele:**
```bash
# Standard-Glättung
./video2depth.sh video.mp4 ema 0.6

# Minimale Glättung für schnelle Bewegungen
./video2depth.sh video.mp4 ema 0.8

# Starke Glättung für statische Szenen
./video2depth.sh video.mp4 ema 0.3
```

**Vorteile:** Schnell, einfach, minimaler Speicher  
**Nachteile:** Geisterbilder bei schnellen Bewegungen

---

### `median` – Median-Filter
Berechnet den Median über ein Fenster von Frames. Entfernt Ausreißer effektiv.

**Parameter:**
| Parameter | Bereich | Standard | Effekt |
|-----------|---------|----------|--------|
| `window_size` | 3–15 | 6 | Größer = stärkere Glättung, mehr Latenz |

**Beispiele:**
```bash
# Standard-Fenster
./video2depth.sh video.mp4 median 6

# Kleines Fenster für schnellere Reaktion
./video2depth.sh video.mp4 median 3

# Großes Fenster für maximale Stabilität
./video2depth.sh video.mp4 median 10
```

**Vorteile:** Robust gegen Ausreißer, erhält Kanten  
**Nachteile:** Benötigt Speicher für Fenster, Latenz

---

### `combined` – Median + EMA
Kombiniert Median (Ausreißerentfernung) mit EMA (Glättung). Beste Gesamtqualität.

**Parameter:**
| Parameter | Bereich | Standard | Effekt |
|-----------|---------|----------|--------|
| `alpha` | 0.0–1.0 | 0.6 | EMA-Glättungsfaktor |
| `window_size` | 3–15 | 6 | Median-Fenstergröße |

**Beispiele:**
```bash
# Standard-Kombination
./video2depth.sh video.mp4 combined 0.6 6

# Stärkere Glättung für Interviews/Vlogs
./video2depth.sh video.mp4 combined 0.4 8

# Für Action-Aufnahmen
./video2depth.sh video.mp4 combined 0.7 4
```

**Vorteile:** Maximale Stabilität, beste Flackern-Unterdrückung  
**Nachteile:** Höchster Speicherverbrauch

---

### `bilateral` – Zeitlicher Bilateral-Filter
Kantenerhaltender Filter – nur ähnliche Tiefenwerte beeinflussen sich gegenseitig.

**Parameter:**
| Parameter | Bereich | Standard | Effekt |
|-----------|---------|----------|--------|
| `spatial_sigma` | 1.0–20.0 | 5.0 | Räumliche Glättung |
| `range_sigma` | 0.01–1.0 | 0.1 | Wertebereich-Glättung |

**Beispiele:**
```bash
# Standard-Einstellungen
./video2depth.sh video.mp4 bilateral 5.0 0.1

# Starke Kantenerhaltung
./video2depth.sh video.mp4 bilateral 3.0 0.05

# Stärkere Glättung
./video2depth.sh video.mp4 bilateral 10.0 0.2
```

**Vorteile:** Erhält scharfe Objektkanten  
**Nachteile:** Rechenintensiver als EMA

---

### `optical_flow` – Optical Flow Glättung
Nutzt Bewegungsvektoren für Warping vor der Mischung. Beste Qualität bei Bewegung.

**Parameter:**
| Parameter | Bereich | Standard | Effekt |
|-----------|---------|----------|--------|
| `alpha` | 0.0–1.0 | 0.5 | Mischungsverhältnis |

**Beispiele:**
```bash
# Standard-Optical-Flow
./video2depth.sh video.mp4 optical_flow 0.5

# Mehr vom aktuellen Frame
./video2depth.sh video.mp4 optical_flow 0.7

# Mehr vom gewarpten Frame
./video2depth.sh video.mp4 optical_flow 0.3
```

**Vorteile:** Beste Ergebnisse bei Kamera-/Objektbewegung  
**Nachteile:** Am rechenintensivsten

---

### `gmm` – Gaussian Mixture Model
Modelliert Tiefenverteilung als Mischung von Gaußverteilungen. Robust bei Szenenwechseln.

**Parameter:**
| Parameter | Bereich | Standard | Effekt |
|-----------|---------|----------|--------|
| `components` | 2–5 | 3 | Anzahl der Gauß-Komponenten |

**Beispiele:**
```bash
# Standard-GMM
./video2depth.sh video.mp4 gmm 3

# Weniger Komponenten (schneller)
./video2depth.sh video.mp4 gmm 2

# Mehr Komponenten (komplexere Szenen)
./video2depth.sh video.mp4 gmm 5
```

**Vorteile:** Robust bei Szenenwechseln  
**Nachteile:** Speicherintensiv

---

### `savgol` – Savitzky-Golay Filter
Polynomielle Glättung, die lokale Details besser erhält.

**Parameter:**
| Parameter | Bereich | Standard | Effekt |
|-----------|---------|----------|--------|
| `window_size` | 3–15 (ungerade) | 7 | Größer = stärkere Glättung |

**Beispiele:**
```bash
# Standard-Savitzky-Golay
./video2depth.sh video.mp4 savgol 7

# Kleines Fenster für Details
./video2depth.sh video.mp4 savgol 5

# Großes Fenster für Glättung
./video2depth.sh video.mp4 savgol 11
```

**Vorteile:** Erhält lokale Details und Spitzenwerte  
**Nachteile:** Weniger robust gegen Ausreißer als Median

---

## Praktische Anwendungsbeispiele

### Interview / Vlog (statische Kamera)
```bash
./video2depth.sh interview.mp4 ema 0.4
# oder für maximale Qualität:
./video2depth.sh interview.mp4 combined 0.4 8
```

### Action-Sport (schnelle Bewegung)
```bash
./video2depth.sh action.mp4 optical_flow 0.6
```

### Drohnen-Aufnahme (langsame Kamerabewegung)
```bash
./video2depth.sh drone.mp4 optical_flow 0.4
```

### Dokumentarfilm (gemischte Szenen)
```bash
./video2depth.sh docu.mp4 combined 0.5 6
```

### 3D-Konvertierung (maximale Qualität)
```bash
# Schritt 1: Video auf optimale Größe skalieren
ffmpeg -i input.mp4 -vf "scale=1536:1536:force_original_aspect_ratio=decrease,pad=1536:1536:(ow-iw)/2:(oh-ih)/2:black" input_1536.mp4

# Schritt 2: Mit bestmöglichem Filter verarbeiten
./video2depth.sh input_1536.mp4 combined 0.5 8
```

### Low-Memory Situation (8GB RAM)
```bash
# Einzelbilder extrahieren
ffmpeg -i video.mp4 frames/%04d.png

# Mit Memory-Optimierung verarbeiten
depth-pro-run -i ./frames -o ./depth --filter-mode ema --smooth 0.6 --low-memory

# Video aus Depthmaps erstellen
ffmpeg -framerate 30 -i ./depth/%04d_16bit.png -c:v libx265 depth_video.mp4
```

---

## Empfehlungen nach Szenario

| Szenario | Filter | Parameter | Begründung |
|----------|--------|-----------|------------|
| Interview/Talking Head | `ema` | 0.4 | Statisch, einfacher Filter reicht |
| Vlog (Handkamera) | `combined` | 0.5, 6 | Kompensiert Wackeln |
| Sport/Action | `optical_flow` | 0.6 | Berücksichtigt Bewegung |
| Drohne (langsam) | `optical_flow` | 0.4 | Sanfte Bewegungen |
| Drohne (schnell) | `optical_flow` | 0.6 | Schnelle Bewegungen |
| Spielfilm | `combined` | 0.5, 8 | Maximale Qualität |
| Zeitraffer | `savgol` | 7 | Erhält Details |
| Security-Cam | `median` | 5 | Robust gegen Rauschen |
| Low-Memory | `ema` | 0.6 | Minimaler Speicher |

---

## Performance-Optimierung

### Automatische Optimierungen (Apple Silicon)

| Optimierung | Beschreibung |
|-------------|--------------|
| MPS Backend | Metal Performance Shaders GPU-Beschleunigung |
| Half Precision (FP16) | Halber Speicher, doppelte Geschwindigkeit |
| PNG Fast-Write | Kompression Stufe 1 für schnelleres Schreiben |

### Manuelle CLI-Optionen

```bash
depth-pro-run -i ./frames -o ./depth \
    --filter-mode ema \
    --smooth 0.6 \
    --torch-compile \       # PyTorch 2.0+ JIT-Kompilierung
    --low-memory \          # Memory-Optimierungen
    --png-compression 1     # 0=schnell, 9=klein
```

### RAM-Disk für temporäre Dateien

```bash
# 4GB RAM-Disk erstellen (macOS)
sudo diskutil erasevolume HFS+ RAMDisk "$(hdiutil attach -nomount ram://8388608)"

# Video in RAM-Disk verarbeiten
./video2depth.sh /Volumes/RAMDisk/video.mp4 ema 0.6
```

### Geschwindigkeitsvergleich (M4, 16GB)

| Konfiguration | Frames/s |
|---------------|----------|
| CPU only | ~0.5 fps |
| MPS + FP16 | ~2-3 fps |
| MPS + FP16 + torch.compile | ~3-4 fps |

---

## Optimale Bildgröße

Das Modell arbeitet intern mit **1536×1536 Pixeln**.

### Empfehlung für beste Qualität

```bash
# Mit Padding (Aspect Ratio beibehalten)
ffmpeg -i input.mp4 -vf "scale=1536:1536:force_original_aspect_ratio=decrease,pad=1536:1536:(ow-iw)/2:(oh-ih)/2:black" output.mp4

# Ohne Padding
ffmpeg -i input.mp4 -vf "scale=1536:1536" output.mp4
```

---

## License

This sample code is released under the [LICENSE](LICENSE) terms.

The model weights are released under the [LICENSE](LICENSE) terms.

## Acknowledgements

Our codebase is built using multiple opensource contributions, please see [Acknowledgements](ACKNOWLEDGEMENTS.md) for more details.

Please check the paper for a complete list of references and datasets used in this work.