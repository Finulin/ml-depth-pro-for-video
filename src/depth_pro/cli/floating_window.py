#!/usr/bin/env python3
"""Floating Window — schwarze Randbalken auf vorhandene L/R-Stereovideos anwenden.

Verhindert "Window Violations": Vordergrundobjekte, die optisch durch den
Bildschirmrand brechen. Die Balkenbreite wird pro Frame aus der Tiefenkarte
berechnet und zeitlich geglättet (sofort rein, langsam raus).
"""
import argparse
import subprocess
import sys
from pathlib import Path
from typing import Optional, Tuple

import cv2
import numpy as np
from tqdm import tqdm


# ---------------------------------------------------------------------------
# I/O helpers (analog zu depth2stereo.py)
# ---------------------------------------------------------------------------

def load_depth_source(path: Path) -> np.ndarray:
    p = str(path)
    if path.suffix == ".npz":
        data = np.load(p)
        arr = data[list(data.keys())[0]].astype(np.float32)
        return arr  # (N, H, W)

    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", p],
        capture_output=True, text=True, check=True
    )
    w, h = map(int, probe.stdout.strip().split(","))
    cmd = ["ffmpeg", "-v", "error", "-i", p, "-f", "rawvideo", "-pix_fmt", "gray16be", "pipe:1"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    raw = proc.stdout.read()
    proc.wait()
    frames = np.frombuffer(raw, dtype=">u2").reshape(-1, h, w).astype(np.float32)
    # depth maps were stored as (1 - depth_norm) * 65535 — invert back
    frames = 1.0 - frames / 65535.0
    return frames


def get_fps(video_path: str, override: str = None) -> str:
    if override:
        return override
    result = subprocess.run(
        ["ffprobe", "-v", "0", "-of", "default=noprint_wrappers=1:nokey=1",
         "-select_streams", "v:0", "-show_entries", "stream=r_frame_rate", video_path],
        capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def probe_dimensions(video_path: str) -> tuple[int, int]:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", video_path],
        capture_output=True, text=True, check=True
    )
    w, h = map(int, result.stdout.strip().split(","))
    return w, h


def decode_video_frames(video_path: str, w: int, h: int) -> np.ndarray:
    cmd = ["ffmpeg", "-v", "error", "-i", video_path,
           "-f", "rawvideo", "-pix_fmt", "bgr24", "pipe:1"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    raw = proc.stdout.read()
    proc.wait()
    n = len(raw) // (w * h * 3)
    return np.frombuffer(raw, dtype=np.uint8).reshape(n, h, w, 3)


def open_ffmpeg_writer(path: str, fps: str, w: int, h: int):
    cmd = [
        "ffmpeg", "-y", "-v", "error",
        "-f", "rawvideo", "-pix_fmt", "bgr24",
        "-s", f"{w}x{h}", "-r", fps,
        "-i", "pipe:0",
        "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p",
        path
    ]
    return subprocess.Popen(cmd, stdin=subprocess.PIPE)


# ---------------------------------------------------------------------------
# Anaglyph (analog zu depth2stereo.py)
# ---------------------------------------------------------------------------

def make_anaglyph(left_bgr: np.ndarray, right_bgr: np.ndarray, method: str) -> np.ndarray:
    L = cv2.cvtColor(left_bgr, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    R = cv2.cvtColor(right_bgr, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0

    if method == "color":
        out = np.stack([L[:, :, 0], R[:, :, 1], R[:, :, 2]], axis=2)
    elif method == "half-color":
        Lg = 0.299 * L[:, :, 0] + 0.587 * L[:, :, 1] + 0.114 * L[:, :, 2]
        out = np.stack([Lg, R[:, :, 1], R[:, :, 2]], axis=2)
    elif method == "gray":
        Lg = 0.299 * L[:, :, 0] + 0.587 * L[:, :, 1] + 0.114 * L[:, :, 2]
        Rg = 0.299 * R[:, :, 0] + 0.587 * R[:, :, 1] + 0.114 * R[:, :, 2]
        out = np.stack([Lg, Rg, Rg], axis=2)
    elif method == "dubois":
        lm = np.array([[ 0.456100,  0.500484,  0.176381],
                       [-0.040082, -0.037825, -0.015797],
                       [-0.015216, -0.020597, -0.005469]], dtype=np.float32)
        rm = np.array([[-0.043471, -0.087939, -0.001555],
                       [ 0.378476,  0.733640, -0.018450],
                       [-0.072153, -0.112961,  1.226400]], dtype=np.float32)
        H, W = L.shape[:2]
        out = (L.reshape(-1, 3) @ lm.T + R.reshape(-1, 3) @ rm.T).reshape(H, W, 3)
    elif method == "amber-blue":
        out = np.stack([L[:, :, 0], L[:, :, 1], R[:, :, 2]], axis=2)
    elif method == "wimmer":
        out = np.stack([L[:, :, 1] * 0.7 + L[:, :, 2] * 0.3, R[:, :, 1], R[:, :, 2]], axis=2)
    else:
        raise ValueError(f"Unbekannte Anaglyphen-Methode: {method}")

    out = np.clip(out, 0.0, 1.0)
    out = (out * 255).astype(np.uint8)
    return cv2.cvtColor(out, cv2.COLOR_RGB2BGR)


# ---------------------------------------------------------------------------
# Floating Window Berechnung
# ---------------------------------------------------------------------------

_DFW_MIN_PX   = 2    # Mindestbalkenbreite in Pixeln — unterhalb kein Balken (Mikroflimmern vermeiden)
_DFW_MAX_FRAC = 0.07  # Maximale Balkenbreite: 7 % der Bildbreite


def compute_fw_width(depth: np.ndarray, divergence_pct: float,
                     convergence: float, W: int) -> int:
    """Berechnet die FW-Balkenbreite direkt in Pixeln.

    Formel:
      shift_px = (depth - convergence) * max_shift_px
        positiv → Pixel springt aus dem Schirm (window violation möglich)
        negativ → Pixel liegt hinter dem Schirm (kein Problem)

    Randband (max(16, W/40)): 95. Perzentil der positiven Shifts
    → robust gegen Einzelausreißer im Tiefenbild, reagiert aber auf
      einen echten nahenden Rand-Objekt-Bereich.
    """
    max_shift_px = divergence_pct * 0.01 * W
    shift_px = (depth - convergence) * max_shift_px   # [H, W] in Pixeln

    edge_band = max(16, W // 40)
    left_strip  = shift_px[:, :edge_band].ravel()
    right_strip = shift_px[:, -edge_band:].ravel()

    def edge_violation(strip):
        pos = strip[strip > 0]
        if len(pos) < 5:
            return 0.0
        return float(np.percentile(pos, 95))

    violation_px = max(edge_violation(left_strip), edge_violation(right_strip))

    if violation_px < _DFW_MIN_PX:
        return 0

    max_px = int(W * _DFW_MAX_FRAC)
    return min(round(violation_px), max_px)


# ---------------------------------------------------------------------------
# Auto-Erkennung
# ---------------------------------------------------------------------------

def find_depth_file(base_dir: Path, name: str) -> Optional[Path]:
    for suffix in [f"{name}_depth.npz", f"{name}_depthmap.mp4", f"{name}_depth.mp4"]:
        p = base_dir / suffix
        if p.exists():
            return p
    return None


def find_lr_files(base_dir: Path, name: str) -> Tuple[Optional[Path], Optional[Path]]:
    # 1. Exakter Treffer
    exact_l = base_dir / f"{name}_L.mp4"
    exact_r = base_dir / f"{name}_R.mp4"
    if exact_l.exists() and exact_r.exists():
        return exact_l, exact_r
    # 2. Glob mit Infix (z.B. name_stereo_L.mp4)
    l_matches = [p for p in sorted(base_dir.glob(f"{name}*_L.mp4"))
                 if "_depth" not in p.name and "_depthmap" not in p.name]
    r_matches = [p for p in sorted(base_dir.glob(f"{name}*_R.mp4"))
                 if "_depth" not in p.name and "_depthmap" not in p.name]
    return (l_matches[0] if l_matches else None,
            r_matches[0] if r_matches else None)


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run(args):
    video_path = Path(args.video)
    base_dir = video_path.parent
    name = video_path.stem

    # L/R auto-erkennen
    left_path = Path(args.left) if args.left else None
    right_path = Path(args.right) if args.right else None
    if left_path is None or right_path is None:
        auto_l, auto_r = find_lr_files(base_dir, name)
        if left_path is None:
            left_path = auto_l
        if right_path is None:
            right_path = auto_r
    if not left_path or not left_path.exists():
        print(f"❌ Linkes Auge nicht gefunden. Erwartet: {base_dir}/{name}_L.mp4", file=sys.stderr)
        sys.exit(1)
    if not right_path or not right_path.exists():
        print(f"❌ Rechtes Auge nicht gefunden. Erwartet: {base_dir}/{name}_R.mp4", file=sys.stderr)
        sys.exit(1)

    # Depth auto-erkennen
    depth_path = Path(args.depth) if args.depth else find_depth_file(base_dir, name)
    has_depth = depth_path is not None and depth_path.exists()

    output_prefix = args.output or str(base_dir / f"{name}_fw")
    fmt = args.format

    print(f"🎬 Linkes Auge:   {left_path.name}")
    print(f"🎬 Rechtes Auge:  {right_path.name}")
    if has_depth:
        print(f"📐 Tiefenkarte:   {depth_path.name}")
    else:
        print("⚠️  Keine Tiefenkarte — fixer FW-Wert aus Divergenz/Konvergenz")

    W, H = probe_dimensions(str(left_path))
    fps = get_fps(str(left_path), args.fps)
    print(f"📐 Auflösung: {W}×{H} @ {fps} fps")

    print("🎬 Dekodiere L/R-Videos...")
    left_frames = decode_video_frames(str(left_path), W, H)
    right_frames = decode_video_frames(str(right_path), W, H)
    n_frames = min(len(left_frames), len(right_frames))
    print(f"   -> {n_frames} gemeinsame Frames")

    depths = None
    if has_depth:
        print("📂 Lade Tiefendaten...")
        depths = load_depth_source(depth_path)
        # load_depth_source gibt: weiße Pixel→0.0, schwarze→1.0 (interne Invertierung beim Laden)
        # video2depth.sh: weiß=nah → nach Laden nah=0.0 → für FW-Rechnung auf nah=1.0 bringen
        # depth_near='white' (Standard/video2depth.sh): Invertierung nötig
        # depth_near='black': schwarz=nah → nach Laden nah=1.0 → keine Invertierung nötig
        if args.depth_near == "white":
            depths = 1.0 - depths
        print(f"   -> {depths.shape[0]} Depth-Frames")

    # Writer öffnen
    if fmt == "lr":
        out_l = output_prefix + "_L.mp4"
        out_r = output_prefix + "_R.mp4"
        writer_l = open_ffmpeg_writer(out_l, fps, W, H)
        writer_r = open_ffmpeg_writer(out_r, fps, W, H)
        writer = None
    else:
        out_path = output_prefix + f"_{fmt}.mp4"
        writer = open_ffmpeg_writer(out_path, fps, W, H)
        writer_l = writer_r = None

    fw_smooth = 0.0
    smoothing = max(1, args.smoothing)

    print("🔄 Verarbeite Frames...")
    for i in tqdm(range(n_frames)):
        left = left_frames[i].copy()
        right = right_frames[i].copy()

        # FW-Breite berechnen (in Pixeln, 0 = kein Balken)
        if depths is not None and i < len(depths):
            depth = depths[i]
            if depth.shape != (H, W):
                depth = cv2.resize(depth, (W, H), interpolation=cv2.INTER_LINEAR)
            fw_raw = float(compute_fw_width(depth, args.divergence, args.convergence, W))
        else:
            fw_raw = 0.0

        # Zeitliche Glättung: sofort rein (snap), langsam raus (fade über N Frames)
        if fw_raw >= fw_smooth:
            fw_smooth = fw_raw
        else:
            step = fw_smooth / smoothing
            fw_smooth = max(fw_raw, fw_smooth - step)

        fw_px = round(fw_smooth)

        # Balken setzen
        if fw_px > 0:
            left[:, :fw_px] = 0
            right[:, W - fw_px:] = 0

        if fmt == "lr":
            writer_l.stdin.write(left.tobytes())
            writer_r.stdin.write(right.tobytes())
        else:
            frame = make_anaglyph(left, right, args.anaglyph_method)
            writer.stdin.write(frame.tobytes())

    if fmt == "lr":
        writer_l.stdin.close()
        writer_l.wait()
        writer_r.stdin.close()
        writer_r.wait()
        print(f"✅ Fertig:\n   {out_l}\n   {out_r}")
    else:
        writer.stdin.close()
        writer.wait()
        print(f"✅ Fertig: {out_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Floating Window: schwarze Randbalken auf L/R-Stereovideos anwenden."
    )
    parser.add_argument("-i", "--video", type=Path, required=True,
                        help="RGB-Quellvideo (Basis für Namens-Ableitung)")
    parser.add_argument("-l", "--left", type=str, default=None,
                        help="Linkes Auge (Standard: auto *_L.mp4)")
    parser.add_argument("-r", "--right", type=str, default=None,
                        help="Rechtes Auge (Standard: auto *_R.mp4)")
    parser.add_argument("-d", "--depth", type=str, default=None,
                        help="Tiefendaten npz/mp4 (Standard: auto *_depth.npz / *_depth.mp4)")
    parser.add_argument("-o", "--output", type=str, default=None,
                        help="Ausgabe-Prefix ohne Endung (Standard: <video>_fw)")
    parser.add_argument("--format", choices=["anaglyph", "lr"], default="anaglyph",
                        help="Ausgabeformat: anaglyph oder lr (Standard: anaglyph)")
    parser.add_argument("--anaglyph-method",
                        choices=["dubois", "color", "half-color", "gray", "amber-blue", "wimmer"],
                        default="dubois",
                        help="Anaglyphen-Methode (Standard: dubois)")
    parser.add_argument("--divergence", type=float, default=3.0,
                        help="Maximaler Parallaxbetrag in %% der Bildbreite (Standard: 3.0)")
    parser.add_argument("--convergence", type=float, default=0.5,
                        help="Nullparallax-Ebene 0.0–1.0 (Standard: 0.5)")
    parser.add_argument("--depth-near", choices=["white", "black"], default="white",
                        help="Welcher Tonwert bedeutet 'nah' in der Tiefenkarte (Standard: white)")
    parser.add_argument("--smoothing", type=int, default=12,
                        help="Glättung in Frames: Balken erscheinen sofort, "
                             "gleiten langsam aus (Standard: 12)")
    parser.add_argument("--fps", type=str, default=None,
                        help="FPS überschreiben (Standard: aus Quellvideo)")
    run(parser.parse_args())


if __name__ == "__main__":
    main()
