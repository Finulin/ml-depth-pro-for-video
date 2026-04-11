# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Depth Pro for Video** — an inference implementation of Apple's Depth Pro monocular depth estimation model, extended with temporal filtering for video processing. It estimates metric depth maps (in meters) from single RGB images or video frames.

## Setup

```bash
conda create -n depth-pro-for-video -y python=3.9
conda activate depth-pro-for-video
pip install -e .
source get_pretrained_models.sh  # Downloads ~1.9 GB model to checkpoints/depth_pro.pt
```

## Common Commands

```bash
# Single image depth estimation
depth-pro-run -i ./data/image/example.jpg -o ./output/ --skip-display

# Video to depth map (8 filter modes: none, ema, median, combined, bilateral, optical_flow, gmm, savgol)
./video2depth.sh ./data/video/example.mp4              # No filter
./video2depth.sh ./data/video/example.mp4 ema 0.6      # EMA filter (alpha=0.6)
./video2depth.sh ./data/video/example.mp4 combined 0.5 6  # Median (window=6) + EMA (alpha=0.5)
./video2depth.sh -h                                    # Show help

# Linting / formatting / type checking
ruff check src/
ruff format src/
pyright src/

# Tests (no test files exist yet, but config is in place)
pytest
pytest tests/test_file.py::test_function
```

## Architecture

```
Input Image
    │
    ▼
DepthProEncoder (src/network/encoder.py)
  ├── Patch ViT backbone (DINOv2-L16, 384×384, 16-token patches)
  ├── Image ViT backbone (same architecture)
  ├── Multi-scale sliding window patch extraction
  └── Hook-based feature collection at ViT layers 5, 11, 17, 23
    │
    ▼
MultiresConvDecoder (src/network/decoder.py)
  └── Fuses multi-resolution features
    │
    ▼
Depth Head + FOV Network (src/network/fov.py)
  └── Outputs inverse depth → converted to metric meters using focal length
    │
    ▼
Optional Temporal Filter (src/depth_pro/cli/run.py)
  └── Applied per-frame for video sequences
```

### Key Files

- **`src/depth_pro/depth_pro.py`** — `DepthPro` model class and `create_model_and_transforms()` factory. `infer()` is the main inference method.
- **`src/depth_pro/cli/run.py`** — CLI entry point (`depth-pro-run`); contains all 8 temporal filter implementations and the frame processing loop.
- **`src/depth_pro/__init__.py`** — Public API surface.
- **`src/depth_pro/network/vit_factory.py`** — ViT preset definitions (currently `dinov2l16_384`).
- **`video2depth.sh`** — Orchestrates ffmpeg frame extraction → `depth-pro-run` → ffmpeg video reconstruction.

### Temporal Filtering

Filters are stateful and applied frame-by-frame in `run.py`:
- **Stateful (recursive):** `ema`, `bilateral` — state = previous depth frame
- **Window-based:** `median`, `savgol`, `combined` — state = rolling buffer of N frames
- **Advanced:** `optical_flow` (motion-compensated warping), `gmm` (Gaussian mixture model)

### Hardware

Target machine: **Apple Mac Mini M4, 16 GB RAM** (unified memory shared between CPU and GPU).

- MPS backend is the primary compute device (auto-detected)
- 16 GB unified memory is shared with the OS and other processes — the model alone uses ~4 GB in FP16; keep this in mind when choosing batch sizes or window sizes for temporal filters
- `torch.mps.empty_cache()` is called periodically during long video runs to return unused memory

## Performance Notes

- Default precision: `torch.half` (FP16)
- `torch.compile()` supported for PyTorch 2.0+
- PNG output uses compression level 1 for fast I/O

## Code Style

- **Python 3.9** — use `Optional[T]` not `T | None`, `from typing import ...`
- **Line length:** 100 characters (Ruff enforced)
- **Imports:** `from __future__ import annotations` first, then stdlib / third-party / local (relative)
- **Docstrings:** Google-style with `Args:` and `Returns:` sections, imperative form
- **Copyright header required** on every source file: `# Copyright (C) 2024 Apple Inc.`
- **Logging:** `LOGGER = logging.getLogger(__name__)` per module
- **Configs:** Use `@dataclass` (see `DepthProConfig`, `ViTPreset`)
- **Inference:** Always wrap in `with torch.no_grad():`
