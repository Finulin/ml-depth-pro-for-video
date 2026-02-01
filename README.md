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
./video2depth.sh ./data/video/example.mp4 median 3
# Führe `video2depth.sh -h` aus, um verfügbare Optionen anzuzeigen.
```
### Optionen

- `median`: Median Filter für die Depthmap-Berechnung
- `3`: Kernelgröße für den Median Filter
- `ema`: Exponentieller Mittelwert Filter für die Depthmap-Berechnung
- `0.7`: Alpha-Wert für den Exponentiellen Mittelwert Filter

## License
This sample code is released under the [LICENSE](LICENSE) terms.

The model weights are released under the [LICENSE](LICENSE) terms.

## Acknowledgements

Our codebase is built using multiple opensource contributions, please see [Acknowledgements](ACKNOWLEDGEMENTS.md) for more details.

Please check the paper for a complete list of references and datasets used in this work.
