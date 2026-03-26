# AGENTS.md – Richtlinien für Coding Agents

## Build / Installation

```bash
# Virtuelle Umgebung erstellen (miniconda empfohlen)
conda create -n depth-pro-for-video -y python=3.9
conda activate depth-pro-for-video

# Paket installieren (entwicklungsmodus)
pip install -e .

# Vortrainierte Modelle herunterladen
source get_pretrained_models.sh
```

## Test / Lint / Typecheck

```bash
# Tests ausführen (pytest, testpaths = "tests")
pytest
pytest -v                          # Ausführliche Ausgabe
pytest tests/test_file.py          # Einzelne Testdatei
pytest tests/test_file.py::test_function  # Einzelner Test

# Linting mit Ruff
ruff check src/
ruff check src/depth_pro/utils.py  # Einzelne Datei
ruff format src/                   # Formatierung prüfen

# Typecheck mit Pyright
pyright src/
pyright src/depth_pro/depth_pro.py # Einzelne Datei
```

## Wichtige CLI-Befehle

```bash
# Depthmap aus Einzelbild erstellen
depth-pro-run -i ./data/image/example.jpg -o ./output/ --skip-display

# Depthmaps aus Video erstellen
./video2depth.sh ./data/video/example.mp4              # Ohne Filter
./video2depth.sh ./data/video/example.mp4 ema 0.6      # EMA-Filter
./video2depth.sh -h                                    # Hilfe anzeigen
```

## Code Style Guidelines

### Imports
- `from __future__ import annotations` zu Beginn jeder Datei
- Standardbibliotheken zuerst, dann Third-Party, dann lokale Imports
- Relative Imports für interne Module: `from .network.encoder import ...`
- Imports gruppieren und mit Leerzeile trennen

```python
from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

import numpy as np
import torch
from torch import nn

from .network.decoder import MultiresConvDecoder
```

### Formatierung
- **Zeilenlänge**: Maximal 100 Zeichen (Ruff Konfiguration)
- **Einrückung**: 4 Leerzeichen, keine Tabs
- **Leerzeilen**: 
  - 2 Leerzeilen zwischen Top-Level-Definitionen (Klassen, Funktionen)
  - 1 Leerzeile zwischen Methoden
  - 1 Leerzeile innerhalb von Funktionen zur logischen Gruppierung

### Typisierung
- Type Hints für alle Funktionsparameter und Rückgabewerte verwenden
- `Optional[T]` statt `Union[T, None]` bevorzugen
- `Iterable`, `Mapping` für generische Typen nutzen
- `dataclass` für Konfigurationsklassen verwenden

```python
from typing import Iterable, Optional, Tuple

@dataclass
class DepthProConfig:
    patch_encoder_preset: ViTPreset
    decoder_features: int
    checkpoint_uri: Optional[str] = None

def create_backbone_model(
    preset: ViTPreset
) -> Tuple[nn.Module, ViTPreset]:
    ...
```

### Benennungskonventionen
- **Klassen**: PascalCase (`DepthProEncoder`, `MultiresConvDecoder`)
- **Funktionen/Methoden**: snake_case (`create_model_and_transforms`, `load_rgb`)
- **Konstanten**: UPPER_CASE (`DEFAULT_MONODEPTH_CONFIG_DICT`)
- **Private Member**: `_prefix` für interne Methoden/Attribute
- **Logging**: `LOGGER = logging.getLogger(__name__)` pro Modul

### Docstrings
- Google-Style Docstrings mit `Args:` und `Returns:` Sektionen
- Beschreibung in imperativer Form ("Create...", "Return...")
- Alle Parameter und Rückgabewerte dokumentieren

```python
def load_rgb(
    path: Union[Path, str],
    auto_rotate: bool = True,
) -> Tuple[np.ndarray, List[bytes], float]:
    """Load an RGB image.

    Args:
    ----
        path: The url to the image to load.
        auto_rotate: Rotate the image based on the EXIF data.

    Returns:
    -------
        img: The loaded image as numpy array.
        icc_profile: The color profile.
        f_px: The focal length in pixels.

    """
```

### Fehlerbehandlung
- Spezifische Exceptions verwenden (`ValueError`, `KeyError`)
- `try/except` mit aussagekräftigen Fehlermeldungen
- Logging für nicht-kritische Fehler (`LOGGER.warning`)
- Bare `except:` vermeiden, außer zum kontrollierten Überspringen

```python
if preset in VIT_CONFIG_DICT:
    config = VIT_CONFIG_DICT[preset]
else:
    raise KeyError(f"Preset {preset} not found.")

try:
    image, _, f_px = load_rgb(image_path)
except Exception:
    continue  # Datei überspringen bei Ladefehler
```

### PyTorch-spezifische Konventionen
- `nn.Module` für alle Netzwerk-Komponenten
- `torch.device` für Device-Management (CPU/MPS)
- `with torch.no_grad():` für Inferenz
- Explizites Memory-Management bei begrenztem RAM:
  ```python
  del prediction
  torch.mps.empty_cache()
  ```

## Projektstruktur

```
ml-depth-pro-for-video/
├── src/depth_pro/           # Hauptpaket
│   ├── __init__.py          # Public API Export
│   ├── depth_pro.py         # Hauptmodell & Factory-Funktionen
│   ├── utils.py             # Hilfsfunktionen (load_rgb, exif)
│   ├── cli/                 # Kommandozeilen-Interface
│   ├── network/             # Modellarchitektur
│   │   ├── encoder.py       # DepthProEncoder
│   │   ├── decoder.py       # MultiresConvDecoder
│   │   ├── vit.py           # Vision Transformer
│   │   ├── vit_factory.py   # ViT Factory & Presets
│   │   └── fov.py           # FOV Network
│   └── eval/                # Evaluierungsmetriken
├── checkpoints/             # Vortrainierte Modelle
├── data/                    # Beispielbilder/Videos
├── pyproject.toml           # Build/Lint/Typecheck Config
├── video2depth.sh           # Video-Verarbeitungsskript
└── get_pretrained_models.sh # Modell-Download
```

## Ruff-Konfiguration (aus pyproject.toml)

```toml
[tool.ruff]
line-length = 100
lint.select = ["E", "F", "D", "I"]  # Pyflakes, pycodestyle, pydocstyle, isort
lint.ignore = ["D100", "D105"]      # Docstring in public module/class ignorieren

[tool.lint.per-file-ignores]
"__init__.py" = ["F401", "D100", "D104"]  # Unused imports, docstrings
```

## Wichtige Hinweise

- **Python-Version**: 3.9 (in pyproject.toml konfiguriert)
- **Keine Tests im Repo**: Tests-Verzeichnis existiert nicht, pytest-Config vorhanden
- **Keine Cursor/Copilot Rules**: Keine .cursorrules oder .github/copilot-instructions.md
- **Apple Silicon Optimierung**: MPS-Backend wird automatisch erkannt und genutzt
- **Half Precision**: Standardmäßig `torch.half` für Inferenz
- **Copyright-Header**: Jede Datei beginnt mit `# Copyright (C) 2024 Apple Inc.`
