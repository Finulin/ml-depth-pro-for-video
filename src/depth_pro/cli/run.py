#!/usr/bin/env python3
import argparse
import logging
from pathlib import Path
import numpy as np
import torch
import cv2
from tqdm import tqdm
from scipy.signal import savgol_filter
from sklearn.mixture import GaussianMixture
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

    prev_depth = None
    prev_image = None
    window = []
    gmm_models = {}

    for image_path in tqdm(image_paths):
        if image_path.suffix.lower() not in [".jpg", ".jpeg", ".png", ".webp", ".bmp"]: continue

        try:
            image, _, f_px = load_rgb(image_path)
        except: continue

        prediction = model.infer(transform(image), f_px=f_px)
        depth = prediction["depth"].detach().cpu().numpy().squeeze()

        if args.filter_mode == "bilateral":
            if prev_depth is not None and depth.shape == prev_depth.shape:
                diff = np.abs(depth - prev_depth)
                spatial_sigma = args.bilateral_spatial
                range_sigma = args.bilateral_range
                weights = np.exp(-(diff ** 2) / (2 * range_sigma ** 2))
                depth = prev_depth + weights * (depth - prev_depth)
            prev_depth = depth.copy()

        elif args.filter_mode == "optical_flow":
            if prev_depth is not None and prev_image is not None and depth.shape == prev_depth.shape:
                prev_gray = cv2.cvtColor(prev_image, cv2.COLOR_RGB2GRAY)
                curr_gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
                flow = cv2.calcOpticalFlowFarneback(prev_gray, curr_gray, None, 0.5, 3, 15, 3, 5, 1.2, 0)
                h, w = depth.shape
                y, x = np.mgrid[0:h, 0:w].astype(np.float32)
                map_x = (x - flow[:, :, 0]).astype(np.float32)
                map_y = (y - flow[:, :, 1]).astype(np.float32)
                warped_prev = cv2.remap(prev_depth, map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
                depth = (args.flow_alpha * depth) + ((1.0 - args.flow_alpha) * warped_prev)
            prev_depth = depth.copy()
            prev_image = image.copy()

        elif args.filter_mode == "gmm":
            if prev_depth is not None and depth.shape == prev_depth.shape:
                combined = np.stack([prev_depth.flatten(), depth.flatten()], axis=1)
                n_components = min(args.gmm_components, len(combined))
                try:
                    gmm = GaussianMixture(n_components=n_components, covariance_type='diag', random_state=42)
                    gmm.fit(combined)
                    means = gmm.means_
                    weights_gmm = gmm.weights_
                    mean_depth = np.sum(means[:, 1] * weights_gmm)
                    depth_flat = depth.flatten()
                    depth_flat = 0.7 * depth_flat + 0.3 * mean_depth
                    depth = depth_flat.reshape(depth.shape)
                except:
                    pass
            prev_depth = depth.copy()

        elif args.filter_mode == "savgol":
            window.append(depth.copy())
            if len(window) > args.window_size:
                window.pop(0)
            if len(window) >= 3:
                window_arr = np.array(window)
                smoothed = savgol_filter(window_arr, window_length=min(len(window), args.window_size), polyorder=2, axis=0)
                depth = smoothed[-1]
            else:
                depth = window[-1]

        elif args.filter_mode == "median":
            window.append(depth)
            if len(window) > args.window_size:
                window.pop(0)
            depth = np.median(np.array(window), axis=0).astype(depth.dtype)

        elif args.filter_mode == "ema":
            if prev_depth is not None and depth.shape == prev_depth.shape:
                depth = (args.smooth * depth) + ((1.0 - args.smooth) * prev_depth)
            prev_depth = depth.copy()

        elif args.filter_mode == "combined":
            window.append(depth)
            if len(window) > args.window_size:
                window.pop(0)
            depth = np.median(np.array(window), axis=0).astype(depth.dtype)
            if prev_depth is not None and depth.shape == prev_depth.shape:
                depth = (args.smooth * depth) + ((1.0 - args.smooth) * prev_depth)
            prev_depth = depth.copy()

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
    parser.add_argument("--filter-mode", type=str, choices=["none", "ema", "median", "combined", "bilateral", "optical_flow", "gmm", "savgol"], default="ema")
    parser.add_argument("--smooth", type=float, default=0.6, help="EMA Faktor (0.1-1.0)")
    parser.add_argument("--window-size", type=int, default=6, help="Fenstergröße für Median/Savitzky-Golay")
    parser.add_argument("--bilateral-spatial", type=float, default=5.0, help="Räumliche Sigma für Bilateral")
    parser.add_argument("--bilateral-range", type=float, default=0.1, help="Wertebereich-Sigma für Bilateral")
    parser.add_argument("--flow-alpha", type=float, default=0.5, help="Alpha für Optical Flow Mischung")
    parser.add_argument("--gmm-components", type=int, default=3, help="Anzahl GMM Komponenten")
    parser.add_argument("-v", "--verbose", action="store_true")
    run(parser.parse_args())

if __name__ == "__main__":
    main()
