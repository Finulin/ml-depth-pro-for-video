#!/usr/bin/env python3
import argparse
import logging
import gc
from pathlib import Path
import numpy as np
import torch
import cv2
from tqdm import tqdm
from scipy.signal import savgol_filter
from sklearn.mixture import GaussianMixture
from depth_pro import create_model_and_transforms, load_rgb

LOGGER = logging.getLogger(__name__)

def infer_tiled(model, transform, image, f_px, overlap=64):
    H, W = image.shape[:2]
    mid = W // 2

    if f_px is None:
        pred = model.infer(transform(image))
        f_px = float(pred["focallength_px"].item())
        del pred
    else:
        f_px = float(f_px) if not isinstance(f_px, float) else f_px

    x_left_end = min(mid + overlap, W)
    x_right_start = max(mid - overlap, 0)

    tile_left = image[:, :x_left_end]
    pred_left = model.infer(transform(tile_left), f_px=torch.tensor(f_px * (x_left_end / W), dtype=torch.float32))
    depth_left = pred_left["depth"].detach().cpu().numpy().squeeze()
    del pred_left

    tile_right = image[:, x_right_start:]
    pred_right = model.infer(transform(tile_right), f_px=torch.tensor(f_px * ((W - x_right_start) / W), dtype=torch.float32))
    depth_right = pred_right["depth"].detach().cpu().numpy().squeeze()
    del pred_right

    depth_map = np.zeros((H, W), dtype=np.float32)
    depth_map[:, :x_right_start] = depth_left[:, :x_right_start]
    depth_map[:, x_left_end:] = depth_right[:, x_left_end - x_right_start:]

    blend_w = x_left_end - x_right_start
    alphas = np.linspace(0, 1, blend_w, dtype=np.float32)
    depth_map[:, x_right_start:x_left_end] = (
        (1 - alphas) * depth_left[:, x_right_start:x_left_end]
        + alphas * depth_right[:, :blend_w]
    )

    return depth_map

def get_torch_device() -> torch.device:
    if torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")

def run(args):
    if args.verbose: logging.basicConfig(level=logging.INFO)

    device = get_torch_device()
    model, transform = create_model_and_transforms(device=device, precision=torch.half)
    model.eval()
    
    if args.torch_compile and hasattr(torch, 'compile'):
        try:
            LOGGER.info("Compiling model with torch.compile()...")
            model = torch.compile(model, mode="reduce-overhead")
        except Exception as e:
            LOGGER.warning(f"torch.compile() failed: {e}")

    if args.low_memory:
        pass

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
    frame_count = 0
    ema_norm_min = None
    ema_norm_max = None

    for image_path in tqdm(image_paths):
        if image_path.suffix.lower() not in [".jpg", ".jpeg", ".png", ".webp", ".bmp"]: continue

        try:
            image, _, f_px = load_rgb(image_path)
        except: continue

        if args.tiling:
            depth = infer_tiled(model, transform, image, f_px, overlap=args.tile_overlap)
        else:
            with torch.no_grad():
                prediction = model.infer(transform(image), f_px=f_px)
                depth = prediction["depth"].detach().cpu().numpy().squeeze()
                del prediction
        if args.low_memory:
            torch.mps.empty_cache()

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

        elif args.filter_mode == "ema_norm":
            cur_min, cur_max = float(depth.min()), float(depth.max())
            if ema_norm_min is None:
                ema_norm_min, ema_norm_max = cur_min, cur_max
            else:
                ema_norm_min = args.norm_decay * ema_norm_min + (1 - args.norm_decay) * cur_min
                ema_norm_max = args.norm_decay * ema_norm_max + (1 - args.norm_decay) * cur_max

        if args.output_path:
            out_base = args.output_path / image_path.relative_to(relative_path).parent / image_path.stem
            out_base.parent.mkdir(parents=True, exist_ok=True)

            if args.filter_mode == "ema_norm" and ema_norm_min is not None:
                d_min, d_max = ema_norm_min, ema_norm_max
                depth_norm = np.clip((depth - d_min) / (d_max - d_min + 1e-8), 0, 1)
            elif args.norm_mode == "enhanced":
                d = np.log(np.clip(depth, 1e-3, None))
                d_min = np.percentile(d, 2)
                d_max = np.percentile(d, 98)
                depth_norm = np.clip((d - d_min) / (d_max - d_min + 1e-8), 0, 1)
            else:
                d_min, d_max = depth.min(), depth.max()
                depth_norm = (depth - d_min) / (d_max - d_min + 1e-8)
            depth_16bit = ((1.0 - depth_norm) * 65535).astype(np.uint16)

            cv2.imwrite(str(out_base) + "_16bit.png", depth_16bit, [cv2.IMWRITE_PNG_COMPRESSION, args.png_compression])

            if args.save_npz:
                np.savez_compressed(str(out_base) + "_depth.npz", depth=depth.astype(np.float32))

        frame_count += 1
        if args.low_memory and frame_count % 10 == 0:
            gc.collect()
            torch.mps.empty_cache()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-i", "--image-path", type=Path, required=True)
    parser.add_argument("-o", "--output_path", type=Path)
    parser.add_argument("--skip-display", action="store_true")
    parser.add_argument("--filter-mode", type=str, choices=["none", "ema", "median", "combined", "bilateral", "optical_flow", "gmm", "savgol", "ema_norm"], default="ema")
    parser.add_argument("--smooth", type=float, default=0.6, help="EMA Faktor (0.1-1.0)")
    parser.add_argument("--window-size", type=int, default=6, help="Fenstergröße für Median/Savitzky-Golay")
    parser.add_argument("--bilateral-spatial", type=float, default=5.0, help="Räumliche Sigma für Bilateral")
    parser.add_argument("--bilateral-range", type=float, default=0.1, help="Wertebereich-Sigma für Bilateral")
    parser.add_argument("--flow-alpha", type=float, default=0.5, help="Alpha für Optical Flow Mischung")
    parser.add_argument("--gmm-components", type=int, default=3, help="Anzahl GMM Komponenten")
    parser.add_argument("--torch-compile", action="store_true", help="Aktiviert torch.compile() für schnelleres Inferenz (PyTorch 2.0+)")
    parser.add_argument("--low-memory", action="store_true", help="Aktiviert Memory-Optimierungen für Systeme mit wenig RAM")
    parser.add_argument("--png-compression", type=int, default=1, help="PNG-Kompression (0-9, 0=schnell, 9=klein)")
    parser.add_argument("--save-npz", action="store_true", help="Speichert rohe Tiefenwerte (float32, Meter) zusätzlich als .npz")
    parser.add_argument("--norm-mode", type=str, choices=["minmax", "enhanced"], default="minmax",
        help="Normalisierung: 'minmax'=min/max (Standard), 'enhanced'=Percentile-Clipping + Log-Skala")
    parser.add_argument("--norm-decay", type=float, default=0.9,
        help="EMA-Decay für ema_norm-Modus (0.0–1.0, Standard: 0.9)")
    parser.add_argument("--tiling", action="store_true", help="Zerlegt jeden Frame in 1536×1536-Kacheln für höhere Detailauflösung bei großen Bildern")
    parser.add_argument("--tile-overlap", type=int, default=64, help="Überlappung in Pixeln zwischen Kacheln (Standard: 64)")
    parser.add_argument("-v", "--verbose", action="store_true")
    run(parser.parse_args())

if __name__ == "__main__":
    main()
