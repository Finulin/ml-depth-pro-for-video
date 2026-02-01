#!/usr/bin/env python3
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
    if torch.backends.mps.is_available(): return torch.device("mps")
    return torch.device("cpu")

def run(args):
    if args.verbose: logging.basicConfig(level=logging.INFO)

    model, transform = create_model_and_transforms(device=get_torch_device(), precision=torch.half)
    model.eval()

    if args.image_path.is_dir():
        image_paths = sorted(list(args.image_path.glob("**/*")))
        relative_path = args.image_path
    else:
        image_paths = [args.image_path]
        relative_path = args.image_path.parent

    # Filter-Variablen
    prev_depth = None
    window = [] # Für Median-Filter

    for image_path in tqdm(image_paths):
        if image_path.suffix.lower() not in [".jpg", ".jpeg", ".png", ".webp", ".bmp"]: continue

        try:
            image, _, f_px = load_rgb(image_path)
        except: continue

        prediction = model.infer(transform(image), f_px=f_px)
        depth = prediction["depth"].detach().cpu().numpy().squeeze()

        # --- FILTER LOGIK ---
        if args.filter_mode == "median":
            # Median-Filter (Zeitliches Fenster)
            window.append(depth)
            if len(window) > args.window_size:
                window.pop(0)
            # Berechne Median über die Achse des Fensters
            depth = np.median(np.array(window), axis=0).astype(depth.dtype)

        elif args.filter_mode == "ema":
            # EMA-Filter (Gleitender Durchschnitt)
            if prev_depth is not None and depth.shape == prev_depth.shape:
                depth = (args.smooth * depth) + ((1.0 - args.smooth) * prev_depth)
            prev_depth = depth.copy()

        # --- 16-BIT EXPORT ---
        if args.output_path:
            out_base = args.output_path / image_path.relative_to(relative_path).parent / image_path.stem
            out_base.parent.mkdir(parents=True, exist_ok=True)

            d_min, d_max = depth.min(), depth.max()
            depth_norm = (depth - d_min) / (d_max - d_min + 1e-8)
            depth_16bit = ((1.0 - depth_norm) * 65535).astype(np.uint16)

            cv2.imwrite(str(out_base) + "_16bit.png", depth_16bit)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-i", "--image-path", type=Path, required=True)
    parser.add_argument("-o", "--output_path", type=Path)
    parser.add_argument("--skip-display", action="store_true")
    parser.add_argument("--filter-mode", type=str, choices=["ema", "median", "none"], default="ema")
    parser.add_argument("--smooth", type=float, default=0.7, help="EMA Faktor (0.1-1.0)")
    parser.add_argument("--window-size", type=int, default=3, help="Fenstergröße für Median")
    parser.add_argument("-v", "--verbose", action="store_true")
    run(parser.parse_args())

if __name__ == "__main__":
    main()
