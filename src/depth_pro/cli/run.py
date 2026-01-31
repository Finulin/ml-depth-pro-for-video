#!/usr/bin/env python3
"""
Modified DepthPro script for 16-bit PNG export (No NPZ).
Optimized for Apple Silicon (M4).
"""

import argparse
import logging
from pathlib import Path

import numpy as np
import torch
import cv2
from tqdm import tqdm

from depth_pro import create_model_and_transforms, load_rgb

LOGGER = logging.getLogger(__name__)

def get_torch_device() -> torch.device:
    """Wählt das beste Gerät für den Mac mini M4 (MPS)."""
    if torch.backends.mps.is_available():
        return torch.device("mps")
    elif torch.cuda.is_available():
        return torch.device("cuda:0")
    return torch.device("cpu")

def run(args):
    if args.verbose:
        logging.basicConfig(level=logging.INFO)

    # Modell laden
    model, transform = create_model_and_transforms(
        device=get_torch_device(),
        precision=torch.half,
    )
    model.eval()

    image_paths = [args.image_path]
    if args.image_path.is_dir():
        image_paths = list(args.image_path.glob("**/*"))
        relative_path = args.image_path
    else:
        relative_path = args.image_path.parent

    # Wir entfernen hier die Matplotlib GUI Logik komplett, da du --skip-display nutzt
    # Das macht das Script schlanker für Video-Verarbeitung.

    for image_path in tqdm(image_paths):
        if image_path.suffix.lower() not in [".jpg", ".jpeg", ".png", ".webp", ".bmp"]:
            continue

        try:
            # Bild laden
            image, _, f_px = load_rgb(image_path)
        except Exception as e:
            LOGGER.error(f"Fehler bei {image_path}: {e}")
            continue

        # Inferenz
        prediction = model.infer(transform(image), f_px=f_px)
        depth = prediction["depth"].detach().cpu().numpy().squeeze()

        # Speichern
        if args.output_path is not None:
            output_file_base = (
                args.output_path
                / image_path.relative_to(relative_path).parent
                / image_path.stem
            )
            output_file_base.parent.mkdir(parents=True, exist_ok=True)

            # --- 16-BIT PNG LOGIK ---
            d_min, d_max = depth.min(), depth.max()

            # Division durch Null verhindern
            if d_max - d_min == 0:
                d_max += 1e-8

            depth_relative = (depth - d_min) / (d_max - d_min)
            depth_inverted = 1.0 - depth_relative

            # Umwandlung in 16-bit (0 - 65535)
            depth_16bit = (depth_inverted * 65535).astype(np.uint16)

            # Nur das PNG speichern
            png_path = str(output_file_base) + "_16bit.png"
            cv2.imwrite(png_path, depth_16bit)

            if args.verbose:
                LOGGER.info(f"Gespeichert: {png_path}")

def main():
    parser = argparse.ArgumentParser(description="DepthPro 16-bit Clean Export")
    parser.add_argument("-i", "--image-path", type=Path, required=True, help="Input Bild oder Ordner")
    parser.add_argument("-o", "--output_path", type=Path, help="Output Ordner")
    parser.add_argument("--skip-display", action="store_true", help="Ignoriert (Legacy Flag)")
    parser.add_argument("-v", "--verbose", action="store_true", help="Mehr Details anzeigen")

    run(parser.parse_args())

if __name__ == "__main__":
    main()
