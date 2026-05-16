# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Setup

```bash
# Create environment and install
conda create -n depth-pro python=3.9
conda activate depth-pro
pip install -e .

# Download pre-trained model weights (~1.9 GB)
source get_pretrained_models.sh
```

## Common Commands

```bash
# Run depth estimation on images
depth-pro-run -i <image_or_dir> -o <output_dir>

# Run with temporal filter on video frames
depth-pro-run -i <frames_dir> -o <output_dir> --filter ema --alpha 0.3

# Process a full video (extract → infer → encode)
./video2depth.sh <video.mp4> [filter_mode] [param1] [param2]

# Run tests
pytest
```

## Architecture

The project wraps Apple's Depth Pro model with a video-processing pipeline.

### Inference Pipeline

```
Input Image → Transform → DepthProEncoder → MultiresConvDecoder → Head → depth (meters)
                                                                 → FOVNetwork → focallength_px
```

**Key files:**
- `src/depth_pro/__init__.py` — Public API: `create_model_and_transforms()`, `load_rgb()`
- `src/depth_pro/depth_pro.py` — `DepthPro` nn.Module + `DepthProConfig` dataclass; `model.infer(image, f_px)` returns `{depth, focallength_px}`
- `src/depth_pro/utils.py` — `load_rgb()` (EXIF rotation, HEIC support), `fpx_from_f35()`

### Network Components

- `src/depth_pro/network/encoder.py` — `DepthProEncoder`: builds an image pyramid, encodes overlapping patches via patch ViT + full image via image ViT, returns multi-resolution feature maps
- `src/depth_pro/network/decoder.py` — `MultiresConvDecoder`: progressively fuses multi-resolution features bottom-up via `FeatureFusionBlock2d`
- `src/depth_pro/network/fov.py` — `FOVNetwork`: estimates camera FOV from decoder features for metric depth conversion
- `src/depth_pro/network/vit_factory.py` — `create_vit()` factory; only preset currently in use is `"dinov2l16_384"` (DINOv2 Large, 384×384)

### CLI & Video Processing

- `src/depth_pro/cli/run.py` — `depth-pro-run` entry point; processes image directories; implements 8 temporal filtering modes; writes 16-bit normalized PNG depth maps
- `video2depth.sh` — Shell orchestrator: validates disk space → extracts frames via ffmpeg → calls `depth-pro-run` → encodes output video (H.264, CRF 18) → cleans up frames

### Temporal Filter Modes

| Mode | Parameters | Description |
|------|-----------|-------------|
| `none` | — | Raw per-frame output |
| `ema` | `--alpha` (0.0–1.0) | Exponential moving average |
| `median` | `--window_size` (3–15) | Sliding window median |
| `combined` | both above | Median + EMA |
| `bilateral` | — | Edge-preserving bilateral filter |
| `optical_flow` | — | Motion-aware depth warping |
| `gmm` | `--components` (2–5) | Gaussian Mixture Model |
| `savgol` | — | Savitzky-Golay polynomial |

## Device & Precision

- Default device: MPS (Apple Silicon) with automatic CPU fallback
- FP16 (half precision) available via CLI flag for faster inference
- `torch.compile()` supported for additional throughput

## Output Format

Depth maps are written as 16-bit PNG (0–65535 range, normalized within each batch).
