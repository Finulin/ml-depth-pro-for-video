#!/usr/bin/env python3
"""
Modified DepthPro script for 16-bit PNG export.
Optimized for Apple Silicon (M4).
"""

import argparse
import logging
from pathlib import Path

import numpy as np
import PIL.Image
import torch
import cv2  # Für hochwertigen 16-bit Export
from matplotlib import pyplot as plt
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

    # Modell laden (Nutzt die Neural Engine via torch.half)
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

    if not args.skip_display:
        plt.ion()
        fig = plt.figure(figsize=(12, 6))
        ax_rgb = fig.add_subplot(121)
        ax_disp = fig.add_subplot(122)

    for image_path in tqdm(image_paths):
        if image_path.suffix.lower() not in [".jpg", ".jpeg", ".png", ".webp"]:
            continue

        try:
            LOGGER.info(f"Verarbeite Bild: {image_path} ...")
            image, _, f_px = load_rgb(image_path)
        except Exception as e:
            LOGGER.error(f"Fehler beim Laden von {image_path}: {e}")
            continue

        # Inferenz
        prediction = model.infer(transform(image), f_px=f_px)
        depth = prediction["depth"].detach().cpu().numpy().squeeze()

        # Dateipfad-Logik
        if args.output_path is not None:
            output_file_base = (
                args.output_path
                / image_path.relative_to(relative_path).parent
                / image_path.stem
            )
            output_file_base.parent.mkdir(parents=True, exist_ok=True)

            # --- 16-BIT PNG EXPORT LOGIK ---
            # Wir normieren die metrische Tiefe für Blender Displacement
            # Nah = Hell (Weiß), Fern = Dunkel (Schwarz)
            d_min, d_max = depth.min(), depth.max()
            depth_relative = (depth - d_min) / (d_max - d_min + 1e-8)
            depth_inverted = 1.0 - depth_relative

            # Umwandlung in 16-bit (0 - 65535)
            depth_16bit = (depth_inverted * 65535).astype(np.uint16)

            # Speichern als PNG
            png_path = str(output_file_base) + "_16bit.png"
            cv2.imwrite(png_path, depth_16bit)
            LOGGER.info(f"16-bit Map gespeichert: {png_path}")

            # Optional: Metrische Rohdaten als NPZ speichern
            np.savez_compressed(output_file_base, depth=depth)

        # Anzeige (Invertierte Tiefe für Visualisierung)
        if not args.skip_display:
            inv_depth_viz = 1.0 / np.clip(depth, 0.1, 250.0)
            inv_depth_viz = (inv_depth_viz - inv_depth_viz.min()) / (inv_depth_viz.max() - inv_depth_viz.min())

            ax_rgb.imshow(image)
            ax_rgb.set_title("Original")
            ax_disp.imshow(inv_depth_viz, cmap="turbo")
            ax_disp.set_title("Depth Map (Turbo)")
            fig.canvas.draw()
            fig.canvas.flush_events()

    if not args.skip_display:
        plt.show(block=True)

def main():
    parser = argparse.ArgumentParser(description="DepthPro 16-bit Export für Mac M4")
    parser.add_argument("-i", "--image-path", type=Path, required=True, help="Input Bild oder Ordner")
    parser.add_argument("-o", "--output_path", type=Path, help="Output Ordner")
    parser.add_argument("--skip-display", action="store_true", help="Kein GUI Fenster öffnen")
    parser.add_argument("-v", "--verbose", action="store_true", help="Logging Details")

    run(parser.parse_args())

if __name__ == "__main__":
    main()
