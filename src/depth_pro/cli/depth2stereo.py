#!/usr/bin/env python3
import argparse
import subprocess
import sys
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
import torch
from tqdm import tqdm

_nunif_model_cache: dict = {}


# ---------------------------------------------------------------------------
# Device
# ---------------------------------------------------------------------------

def get_torch_device() -> torch.device:
    if torch.backends.mps.is_available():
        return torch.device("mps")
    if torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def load_depth_source(path: Path) -> np.ndarray:
    p = str(path)
    if path.suffix == ".npz":
        data = np.load(p)
        arr = data[list(data.keys())[0]].astype(np.float32)
        return arr  # (N, H, W)

    # Depth video: decode with ffmpeg into numpy
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
# Depth edge dilation (nach nunif/iw3 dilation.py)
# ---------------------------------------------------------------------------

def apply_depth_edge_dilation(depth_norm: np.ndarray, dilation_px: int) -> np.ndarray:
    """Bläht Vordergrundbereiche (hell=nah) in Tiefenkanten hinein.

    Verhindert Säume im Stereobild: ohne Dilation entstehen an Objekt-Hintergrund-
    Übergängen scharfe Tiefensprünge, die nach dem Warp als sichtbare Artefakte
    erscheinen. Die Dilation lässt Vordergrundobjekte in den Hintergrund einwachsen,
    sodass der Warp keine unversorgten Pixel hinterlässt.
    """
    if dilation_px <= 0:
        return depth_norm

    k = 2 * dilation_px + 1
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))

    dilated = cv2.dilate(depth_norm, kernel)
    blurred = cv2.GaussianBlur(dilated, (k, k), dilation_px / 3.0)

    gx = cv2.Sobel(depth_norm, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(depth_norm, cv2.CV_32F, 0, 1, ksize=3)
    grad = np.sqrt(gx ** 2 + gy ** 2)
    g_max = float(np.percentile(grad, 95))
    if g_max <= 0:
        return depth_norm
    w = np.clip(grad / g_max, 0.0, 1.0)

    return (depth_norm * (1.0 - w) + blurred * w).astype(np.float32)


# ---------------------------------------------------------------------------
# Reflect-Padding für Warp-Vorverarbeitung
# ---------------------------------------------------------------------------

def apply_reflect_pad_stereo(rgb: np.ndarray, depth: np.ndarray, pad_frac: float):
    """Spiegelt Bildränder für RGB und Depth-Map vor dem Warp.

    Gibt dem Warp an allen Kanten Kontext-Pixel mit, sodass der Inpainter
    weniger Löcher füllen muss. Nach dem Warp wird das Padding wieder
    abgeschnitten (Originalauflösung bleibt erhalten).
    """
    H, W = rgb.shape[:2]
    pad_h = int(H * pad_frac)
    pad_w = int(W * pad_frac)
    rgb_padded = np.pad(rgb, ((pad_h, pad_h), (pad_w, pad_w), (0, 0)), mode="reflect")
    depth_padded = np.pad(depth, ((pad_h, pad_h), (pad_w, pad_w)), mode="reflect")
    return rgb_padded, depth_padded, pad_h, pad_w


# ---------------------------------------------------------------------------
# Geometric stereo (forward warp + hole fill)
# ---------------------------------------------------------------------------

def forward_warp_rgb(rgb: np.ndarray, depth_norm: np.ndarray,
                     divergence: float, convergence: float,
                     synthetic_view: str = "both"):
    """Forward-Warp für geometrisches Stereo.

    synthetic_view:
      'both'  — beide Augen synthetisieren, jedes bewegt sich um ±shift/2
      'left'  — nur linkes Auge synthetisieren, rechtes = Original (shift×2)
      'right' — nur rechtes Auge synthetisieren, linkes = Original (shift×2)
    """
    H, W = depth_norm.shape

    # Bei single-eye doppelter Shift (das andere Auge bleibt am Original)
    div_factor = 2.0 if synthetic_view != "both" else 1.0
    shift_size = divergence * 0.01 * W * 0.5 * div_factor
    shift = depth_norm * shift_size - shift_size * convergence

    flat_depth = depth_norm.flatten()
    order = np.argsort(flat_depth)  # far → near
    ys = order // W
    xs = order % W
    shifts = shift[ys, xs]

    do_left = synthetic_view in ("both", "left")
    do_right = synthetic_view in ("both", "right")

    left = np.zeros_like(rgb) if do_left else rgb.copy()
    right = np.zeros_like(rgb) if do_right else rgb.copy()
    mask_l = np.ones((H, W), dtype=bool) if do_left else np.zeros((H, W), dtype=bool)
    mask_r = np.ones((H, W), dtype=bool) if do_right else np.zeros((H, W), dtype=bool)

    if do_left:
        xl = np.round(xs + shifts).astype(np.int32)
        valid_l = (xl >= 0) & (xl < W)
        left[ys[valid_l], xl[valid_l]] = rgb[ys[valid_l], xs[valid_l]]
        mask_l[ys[valid_l], xl[valid_l]] = False

    if do_right:
        xr = np.round(xs - shifts).astype(np.int32)
        valid_r = (xr >= 0) & (xr < W)
        right[ys[valid_r], xr[valid_r]] = rgb[ys[valid_r], xs[valid_r]]
        mask_r[ys[valid_r], xr[valid_r]] = False

    return left, right, mask_l, mask_r


def fill_holes_geometric(eye: np.ndarray, mask: np.ndarray, direction: str) -> np.ndarray:
    """Füllt Warp-Löcher durch vektorisierten 2D-Forward-Fill (np.maximum.accumulate).

    Für jede Zeile wird der Index der letzten gültigen Spalte nach rechts propagiert
    (links→rechts) bzw. der erste gültige nach links (rechts→links via Flip).
    Kein Python-Loop über Pixel — vollständig vektorisiert.
    """
    H, W = mask.shape
    result = eye.copy()

    if not mask.any():
        return result

    valid = ~mask
    col_idx = np.broadcast_to(np.arange(W), (H, W))  # (H, W) Spaltenindizes

    if direction == "left":
        # Propagiere letzten gültigen Spaltenindex nach rechts
        idx = np.where(valid, col_idx, -1)
        np.maximum.accumulate(idx, axis=1, out=idx)
        fillable = mask & (idx >= 0)
        rows = np.broadcast_to(np.arange(H)[:, None], (H, W))
        result[fillable] = result[rows[fillable], idx[fillable]]
    else:
        # Flip → Forward-Fill links→rechts → Flip zurück
        result_f = result[:, ::-1, :].copy()
        mask_f = mask[:, ::-1]
        valid_f = ~mask_f
        col_idx_f = np.broadcast_to(np.arange(W), (H, W))
        idx_f = np.where(valid_f, col_idx_f, -1)
        np.maximum.accumulate(idx_f, axis=1, out=idx_f)
        fillable_f = mask_f & (idx_f >= 0)
        rows = np.broadcast_to(np.arange(H)[:, None], (H, W))
        result_f[fillable_f] = result_f[rows[fillable_f], idx_f[fillable_f]]
        result = result_f[:, ::-1, :]

    mask_u8 = mask.astype(np.uint8) * 255
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (7, 1))
    remaining = (cv2.dilate(mask_u8, kernel) > 0) & mask
    if remaining.any():
        result = cv2.inpaint(result, remaining.astype(np.uint8) * 255, 3, cv2.INPAINT_TELEA)

    return result


def fill_holes_lama(eye: np.ndarray, mask: np.ndarray) -> np.ndarray:
    try:
        from simple_lama_inpainting import SimpleLama
    except ImportError:
        print("❌ simple-lama-inpainting nicht installiert: pip install simple-lama-inpainting",
              file=sys.stderr)
        sys.exit(1)

    if not hasattr(fill_holes_lama, "_model"):
        fill_holes_lama._model = SimpleLama()

    if not mask.any():
        return eye

    from PIL import Image
    eye_pil = Image.fromarray(cv2.cvtColor(eye, cv2.COLOR_BGR2RGB))
    mask_pil = Image.fromarray((mask * 255).astype(np.uint8))
    result_pil = fill_holes_lama._model(eye_pil, mask_pil)
    return cv2.cvtColor(np.array(result_pil), cv2.COLOR_RGB2BGR)


# ---------------------------------------------------------------------------
# nunif/iw3 ML-based stereo methods
# ---------------------------------------------------------------------------
#
# Drei vollständige ML-Pipelines aus nunif/iw3:
#
#   row_flow    — RowFlowV3: ML-Backward-Warp (Window-Attention), keine Löcher
#   mlbw_l4     — MLBW L4:  4-Layer Multi-Layer Backward Warp, keine Löcher
#   forward_inpaint  — Forward-Warp + LightInpaint V1 (ML-Hole-Fill)
#   mlbw_inpaint     — MLBW L2 Backward-Warp + LightInpaint V1
#
# Voraussetzung: pip install git+https://github.com/nagadomi/nunif.git
#
# Gewichte werden beim ersten Aufruf automatisch heruntergeladen (~/.cache/nunif/).

_NUNIF_WARP_MODELS = {"row_flow", "mlbw_l4"}
_NUNIF_INPAINT_MODELS = {"forward_inpaint", "mlbw_inpaint"}
NUNIF_METHODS = _NUNIF_WARP_MODELS | _NUNIF_INPAINT_MODELS


_NUNIF_CACHE = Path.home() / ".cache" / "nunif_repo"


def _ensure_nunif():
    """Klont nunif ins Cache-Verzeichnis falls nötig und fügt es dem sys.path hinzu.

    nunif ist KEIN pip-Paket. Das Repo enthält zwei Top-Level-Packages:
      nunif/  → import nunif
      iw3/    → import iw3   (NICHT nunif.iw3)
    Beide werden durch Hinzufügen des Repo-Roots zu sys.path verfügbar.
    """
    import importlib

    if str(_NUNIF_CACHE) not in sys.path:
        sys.path.insert(0, str(_NUNIF_CACHE))

    try:
        import nunif  # noqa
        import iw3    # noqa
        return
    except ImportError:
        pass

    # Klonen wenn noch nicht vorhanden oder unvollständig
    marker = _NUNIF_CACHE / "nunif" / "__init__.py"
    if not marker.exists():
        print(f"📦 Klone nunif nach {_NUNIF_CACHE} ...")
        import shutil
        if _NUNIF_CACHE.exists():
            shutil.rmtree(_NUNIF_CACHE)
        subprocess.run(
            ["git", "clone", "--depth=1", "--quiet",
             "https://github.com/nagadomi/nunif.git", str(_NUNIF_CACHE)],
            check=True,
        )

    # Importcache nach neuem Verzeichnis invalidieren
    importlib.invalidate_caches()

    try:
        import nunif  # noqa
        import iw3    # noqa
    except ImportError as e:
        print(f"❌ nunif/iw3 konnte nicht geladen werden: {e}", file=sys.stderr)
        sys.exit(1)


def _check_nunif():
    _ensure_nunif()


def _load_nunif_stereo_model(method: str, divergence: float, device: torch.device):
    """Lädt das passende nunif-Modell (mit internem Gewichte-Download)."""
    global _nunif_model_cache
    key = (method, str(device))
    if key in _nunif_model_cache:
        return _nunif_model_cache[key]

    _check_nunif()
    print(f"   Lade {method}-Modell (erste Ausführung lädt Gewichte herunter)...")

    if method == "row_flow":
        from iw3.stereo_model_factory import create_stereo_model
        model = create_stereo_model("row_flow_v3", divergence=divergence, device_id=-1)
        model.delta_output = True

    elif method == "mlbw_l4":
        from iw3.stereo_model_factory import create_stereo_model
        model = create_stereo_model("mlbw_l4", divergence=divergence, device_id=-1)
        model.delta_output = True

    elif method == "forward_inpaint":
        from iw3.forward_inpaint import ForwardInpaintImage
        model = ForwardInpaintImage(device_id=-1)

    elif method == "mlbw_inpaint":
        from iw3.mlbw_inpaint import MLBWInpaintImage
        model = MLBWInpaintImage(device_id=-1)

    else:
        raise ValueError(f"Unbekannte nunif-Methode: {method}")

    # Nicht model = model.to(device).eval() — manche nunif-Klassen überschreiben
    # train() ohne return-Statement, weshalb eval() None zurückgibt.
    model.to(device)
    model.eval()
    _nunif_model_cache[key] = model
    return model


def _to_tensor(rgb: np.ndarray, depth_norm: np.ndarray, device: torch.device):
    """Konvertiert numpy HWC uint8 + float32 → torch BCHW float32 auf device."""
    c = torch.from_numpy(rgb.copy()).permute(2, 0, 1).float().div(255).unsqueeze(0).to(device)
    d = torch.from_numpy(depth_norm.copy()).float().unsqueeze(0).unsqueeze(0).to(device)
    return c, d


def _to_uint8(t: torch.Tensor) -> np.ndarray:
    """BCHW float32 [0,1] → HWC uint8 numpy (BGR)."""
    arr = t[0].permute(1, 2, 0).clamp(0, 1).mul(255).byte().cpu().numpy()
    # nunif liefert RGB, wir brauchen BGR für cv2
    return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)


def apply_nunif_stereo(rgb: np.ndarray, depth_norm: np.ndarray, method: str,
                       divergence: float, convergence: float,
                       synthetic_view: str,
                       inner_dilation: int, outer_dilation: int,
                       max_width: Optional[int],
                       device: torch.device) -> tuple:
    """Erzeugt linkes und rechtes Auge via nunif/iw3 ML-Modell."""
    model = _load_nunif_stereo_model(method, divergence, device)
    # nunif erwartet RGB — Eingabe von ffmpeg ist BGR
    rgb_rgb = cv2.cvtColor(rgb, cv2.COLOR_BGR2RGB)
    c, d = _to_tensor(rgb_rgb, depth_norm, device)

    with torch.no_grad():
        if method in _NUNIF_WARP_MODELS:
            # Backward-Warp: direkt über apply_divergence_nn_LR
            from iw3.backward_warp import apply_divergence_nn_LR
            left, right = apply_divergence_nn_LR(
                model, c, d,
                divergence=divergence,
                convergence=convergence,
                steps=1,
                synthetic_view=synthetic_view,
                preserve_screen_border=False,
                enable_amp=False,
            )
        else:
            # Inpaint-Pipeline: model.infer() erledigt alles
            left, right = model.infer(
                c, d,
                divergence=divergence,
                convergence=convergence,
                synthetic_view=synthetic_view,
                inner_dilation=inner_dilation,
                outer_dilation=outer_dilation,
                max_width=max_width,
                enable_amp=False,
            )

    return _to_uint8(left), _to_uint8(right)


# ---------------------------------------------------------------------------
# Anaglyph methods
# ---------------------------------------------------------------------------

def make_anaglyph(left_bgr: np.ndarray, right_bgr: np.ndarray, method: str) -> np.ndarray:
    # BGR uint8 → RGB float32 [0,1]
    L = cv2.cvtColor(left_bgr, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    R = cv2.cvtColor(right_bgr, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0

    if method == "color":
        # Einfache Kanal-Trennung: Rot=links, Cyan=rechts
        out = np.stack([L[:, :, 0], R[:, :, 1], R[:, :, 2]], axis=2)

    elif method == "half-color":
        # Linkes Auge grau im Rotkanal, rechtes Auge farbig im Cyan
        Lg = 0.299 * L[:, :, 0] + 0.587 * L[:, :, 1] + 0.114 * L[:, :, 2]
        out = np.stack([Lg, R[:, :, 1], R[:, :, 2]], axis=2)

    elif method == "gray":
        # Beide Augen grau, Rot-Cyan
        Lg = 0.299 * L[:, :, 0] + 0.587 * L[:, :, 1] + 0.114 * L[:, :, 2]
        Rg = 0.299 * R[:, :, 0] + 0.587 * R[:, :, 1] + 0.114 * R[:, :, 2]
        out = np.stack([Lg, Rg, Rg], axis=2)

    elif method == "dubois":
        # Dubois-Optimierung für Rot-Cyan (minimiert Retinal Rivalry)
        # Quelle: Dubois, E. (2001). A Stereoscopic Imaging System.
        lm = np.array([[ 0.456100,  0.500484,  0.176381],
                       [-0.040082, -0.037825, -0.015797],
                       [-0.015216, -0.020597, -0.005469]], dtype=np.float32)
        rm = np.array([[-0.043471, -0.087939, -0.001555],
                       [ 0.378476,  0.733640, -0.018450],
                       [-0.072153, -0.112961,  1.226400]], dtype=np.float32)
        H, W = L.shape[:2]
        out = (L.reshape(-1, 3) @ lm.T + R.reshape(-1, 3) @ rm.T).reshape(H, W, 3)

    elif method == "amber-blue":
        # Gelb/Amber links (R+G), Blau rechts — natürlichere Farbwiedergabe
        out = np.stack([L[:, :, 0], L[:, :, 1], R[:, :, 2]], axis=2)

    elif method == "wimmer":
        # Wimmer's Optimized Anaglyph: Rot = linkes G*0.7 + B*0.3
        # https://3dtv.at/Knowhow/AnaglyphComparison_en.aspx
        out = np.stack([L[:, :, 1] * 0.7 + L[:, :, 2] * 0.3, R[:, :, 1], R[:, :, 2]], axis=2)

    else:
        raise ValueError(f"Unbekannte Anaglyphen-Methode: {method}")

    out = np.clip(out, 0.0, 1.0)
    out = (out * 255).astype(np.uint8)
    return cv2.cvtColor(out, cv2.COLOR_RGB2BGR)


# ---------------------------------------------------------------------------
# Output format assembly
# ---------------------------------------------------------------------------

def make_output_frame(left: np.ndarray, right: np.ndarray, fmt: str,
                      anaglyph_method: str = "dubois"):
    H, W = left.shape[:2]
    if fmt == "half-sbs":
        return np.concatenate([cv2.resize(left, (W // 2, H)), cv2.resize(right, (W // 2, H))], axis=1)
    elif fmt == "full-sbs":
        return np.concatenate([left, right], axis=1)
    elif fmt == "top-bottom":
        return np.concatenate([left, right], axis=0)
    elif fmt == "anaglyph":
        return make_anaglyph(left, right, anaglyph_method)
    elif fmt == "lr":
        return left, right
    raise ValueError(f"Unbekanntes Format: {fmt}")


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run(args):
    video_path = str(args.video)
    output_prefix = str(args.output)
    fmt = args.format
    device = get_torch_device()

    fps = get_fps(video_path, args.fps)

    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", video_path],
        capture_output=True, text=True, check=True
    )
    W, H = map(int, probe.stdout.strip().split(","))

    print(f"📐 Video: {W}×{H} @ {fps} fps | Device: {device}")
    anaglyph_info = f" | Anaglyphe: {args.anaglyph_method}" if fmt == "anaglyph" else ""
    print(f"🎛  Format: {fmt}{anaglyph_info} | Methode: {args.inpainting} | "
          f"Auge: {args.synthetic_view} | Divergenz: {args.divergence}% | Konvergenz: {args.convergence}")

    print("📂 Lade Tiefendaten...")
    depths = load_depth_source(args.depth)
    N = depths.shape[0]
    print(f"   -> {N} Frames, Shape: {depths.shape}")

    print("🎬 Dekodiere Videoframes...")
    cmd = ["ffmpeg", "-v", "error", "-i", video_path,
           "-f", "rawvideo", "-pix_fmt", "bgr24", "pipe:1"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    raw = proc.stdout.read()
    proc.wait()
    n_vid_frames = len(raw) // (W * H * 3)
    video_frames = np.frombuffer(raw, dtype=np.uint8).reshape(n_vid_frames, H, W, 3)

    n_frames = min(N, n_vid_frames)
    print(f"   -> {n_frames} gemeinsame Frames")

    # Normalisierungs-Skala bestimmen.
    # 'global': feste, perzentil-gekürzte Min/Max-Skala über den GESAMTEN Clip — die
    # Konvergenzebene (depth_norm == convergence) bleibt fix, auch wenn nahe Objekte das
    # Bild verlassen. 'none': geladene Tiefe unverändert (nur auf [0,1] geklemmt).
    if args.norm_mode == "global":
        _vals = depths[:n_frames].reshape(-1)
        if _vals.size > 4_000_000:
            _vals = _vals[np.linspace(0, _vals.size - 1, 4_000_000).astype(np.int64)]
        g_min = float(np.percentile(_vals, args.norm_clip))
        g_max = float(np.percentile(_vals, 100.0 - args.norm_clip))
        if g_max - g_min < 1e-6:  # Fallback bei (fast) konstanter Tiefe
            g_min, g_max = float(depths[:n_frames].min()), float(depths[:n_frames].max())
        print(f"📊 Tiefen-Normalisierung: global [{g_min:.3f}, {g_max:.3f}] (Clip {args.norm_clip}%)")
    else:  # none
        g_min = g_max = None
        print("📊 Tiefen-Normalisierung: keine (Quelle unverändert, auf [0,1] geklemmt)")
        _dmax = float(depths[:n_frames].max())
        if _dmax > 1.5:
            print(f"⚠️  Quelle wirkt nicht normalisiert (max={_dmax:.2f}). 'none' ist für bereits "
                  f"normalisierte Depthmaps gedacht — rohe NPZ in Metern → 'global' verwenden.")

    if fmt == "lr":
        out_l = output_prefix + "_L.mp4"
        out_r = output_prefix + "_R.mp4"
        writer_l = open_ffmpeg_writer(out_l, fps, W, H)
        writer_r = open_ffmpeg_writer(out_r, fps, W, H)
        writer = None
    else:
        out_path = output_prefix + f"_{fmt}.mp4"
        out_w = W * 2 if fmt == "full-sbs" else W
        out_h = H * 2 if fmt == "top-bottom" else H
        writer = open_ffmpeg_writer(out_path, fps, out_w, out_h)
        writer_l = writer_r = None

    use_nunif = args.inpainting in NUNIF_METHODS

    print("🔄 Verarbeite Frames...")
    for i in tqdm(range(n_frames)):
        rgb = video_frames[i]
        raw_depth = depths[i]

        if raw_depth.shape != (H, W):
            raw_depth = cv2.resize(raw_depth, (W, H), interpolation=cv2.INTER_LINEAR)

        if args.norm_mode == "global":
            depth_norm = np.clip((raw_depth - g_min) / (g_max - g_min + 1e-8), 0.0, 1.0)
        else:
            depth_norm = np.clip(raw_depth, 0.0, 1.0)
        if args.depth_near == "white":
            depth_norm = 1.0 - depth_norm

        depth_norm = apply_depth_edge_dilation(depth_norm, args.edge_dilation)

        # Reflect-Padding vor Warp (optional)
        pad_h = pad_w = 0
        if args.reflect_pad:
            rgb, depth_norm, pad_h, pad_w = apply_reflect_pad_stereo(
                rgb, depth_norm, args.reflect_pad_frac
            )

        if use_nunif:
            left, right = apply_nunif_stereo(
                rgb, depth_norm, args.inpainting,
                args.divergence, args.convergence,
                args.synthetic_view,
                args.inner_dilation, args.outer_dilation,
                args.max_width,
                device,
            )
        else:
            left, right, mask_l, mask_r = forward_warp_rgb(
                rgb, depth_norm, args.divergence, args.convergence,
                args.synthetic_view,
            )
            if args.inpainting == "geometric":
                left = fill_holes_geometric(left, mask_l, "left")
                right = fill_holes_geometric(right, mask_r, "right")
            elif args.inpainting == "lama":
                if mask_l.any():
                    left = fill_holes_lama(left, mask_l)
                if mask_r.any():
                    right = fill_holes_lama(right, mask_r)

        # Reflect-Padding wieder abschneiden → Originalauflösung
        if pad_h > 0 or pad_w > 0:
            H_out, W_out = left.shape[:2]
            left  = left [pad_h:H_out - pad_h, pad_w:W_out - pad_w]
            right = right[pad_h:H_out - pad_h, pad_w:W_out - pad_w]

        # Auf Originalauflösung skalieren falls nötig (nunif kann andere Ausgabegröße liefern)
        if left.shape[:2] != (H, W):
            left  = cv2.resize(left,  (W, H), interpolation=cv2.INTER_LINEAR)
            right = cv2.resize(right, (W, H), interpolation=cv2.INTER_LINEAR)

        if fmt == "lr":
            writer_l.stdin.write(left.tobytes())
            writer_r.stdin.write(right.tobytes())
        else:
            frame = make_output_frame(left, right, fmt, args.anaglyph_method)
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
    parser = argparse.ArgumentParser(description="RGB-Video + Tiefenkarte → Stereovideo")
    parser.add_argument("-i", "--video", type=Path, required=True, help="Originalvideo (MP4)")
    parser.add_argument("-d", "--depth", type=Path, required=True,
                        help="Tiefendaten (NPZ oder Depth-Video)")
    parser.add_argument("-o", "--output", type=str, required=True,
                        help="Ausgabepfad/-prefix (ohne Endung)")
    parser.add_argument("--format", type=str,
                        choices=["half-sbs", "full-sbs", "top-bottom", "anaglyph", "lr"],
                        default="half-sbs", help="Ausgabeformat (Standard: half-sbs)")
    parser.add_argument("--divergence", type=float, default=2.5,
                        help="Parallaxbetrag in %% der Bildbreite (Standard: 2.5)")
    parser.add_argument("--convergence", type=float, default=0.5,
                        help="Nullparallax-Ebene 0.0–1.0 (Standard: 0.5)")
    parser.add_argument("--inpainting", type=str,
                        choices=["none", "geometric", "lama",
                                 "row_flow", "mlbw_l4", "forward_inpaint", "mlbw_inpaint"],
                        default="geometric",
                        help=(
                            "Stereo-Methode / Hole-Filling:\n"
                            "  none            Kein Auffüllen (Forward-Warp)\n"
                            "  geometric       Direktionales Auffüllen (Standard)\n"
                            "  lama            LaMa ML-Inpainting (pip install simple-lama-inpainting)\n"
                            "  row_flow        nunif RowFlowV3 ML-Backward-Warp (kein Ghosting)\n"
                            "  mlbw_l4         nunif MLBW-L4 Multi-Layer Backward-Warp\n"
                            "  forward_inpaint Forward-Warp + nunif LightInpaint V1\n"
                            "  mlbw_inpaint    MLBW Backward-Warp + nunif LightInpaint V1\n"
                            "  ML-Methoden: nunif wird beim ersten Aufruf automatisch nach\n"
                            "    ~/.cache/nunif_repo geklont (einmalig, ~400 MB)."
                        ))
    parser.add_argument("--synthetic-view", type=str,
                        choices=["both", "left", "right"], default="both",
                        help="Welches Auge synthetisiert wird:\n"
                             "  both  : Beide Augen synthetisieren (Standard)\n"
                             "  right : Nur rechtes Auge, linkes = Original (schneller, besser)\n"
                             "  left  : Nur linkes Auge, rechtes = Original")
    parser.add_argument("--anaglyph-method", type=str,
                        choices=["color", "half-color", "gray", "dubois", "amber-blue", "wimmer"],
                        default="dubois",
                        help="Anaglyphen-Verfahren (nur bei --format anaglyph):\n"
                             "  dubois     : Optimierte Matrix-Methode, bestes Ergebnis (Standard)\n"
                             "  half-color : Linkes Auge grau/Rot, rechtes Auge farbig/Cyan\n"
                             "  color      : Einfache Kanal-Trennung Rot-Cyan\n"
                             "  gray       : Beide Augen grau, Rot-Cyan\n"
                             "  amber-blue : Gelb/Amber links, Blau rechts\n"
                             "  wimmer     : Wimmer's Optimized (G*0.7+B*0.3 als Rot-Kanal)")
    parser.add_argument("--depth-near", type=str, choices=["white", "black"], default="white",
                        help="Welcher Tonwert in der Tiefenkarte bedeutet 'nah' (Standard: white):\n"
                             "  white : Weiß = nah, Schwarz = fern — Ausgabe von video2depth.sh\n"
                             "  black : Schwarz = nah, Weiß = fern — inverse Tiefenkonvention")
    parser.add_argument("--norm-mode", type=str, choices=["global", "none"], default="global",
                        help="Tiefen-Normalisierung für den Stereo-Warp:\n"
                             "  global : feste, perzentil-gekürzte Skala über den ganzen Clip\n"
                             "           (Standard; stabile Konvergenz, kein Springen wenn\n"
                             "           nahe Objekte das Bild verlassen)\n"
                             "  none   : Tiefenquelle unverändert (nur auf [0,1] geklemmt).\n"
                             "           Für bereits normalisierte/angepasste Depthmaps;\n"
                             "           NICHT für rohe NPZ in Metern.")
    parser.add_argument("--norm-clip", type=float, default=0.5,
                        help="Perzentil zum Kürzen der globalen Skala (nur bei --norm-mode global; "
                             "Standard: 0.5 = 0.5%%/99.5%%). 0 = exaktes globales Min/Max. "
                             "Macht die Skala robust gegen Ausreißer-Pixel.")
    parser.add_argument("--max-width", type=int, default=None,
                        help="Maximale Breite für ML-Inferenz in Pixeln. Frames werden vor der "
                             "Verarbeitung skaliert und danach zurückskaliert. Senkt Speicher- "
                             "und Rechenaufwand deutlich (z.B. --max-width 960). "
                             "Nur wirksam bei ML-Methoden.")
    parser.add_argument("--edge-dilation", type=int, default=0,
                        help="Tiefenkanten-Dilation in Pixeln vor dem Stereo-Warp (Standard: 0 = aus). "
                             "Bläht Vordergrundbereiche in Hintergrundkanten hinein und reduziert "
                             "Säume im Stereobild. Empfohlen: 2–8 Pixel.")
    parser.add_argument("--inner-dilation", type=int, default=0,
                        help="Hole-Maske VOR dem Inpainting aufblähen in Pixeln (Standard: 0). "
                             "Nur wirksam bei ML-Methoden (forward_inpaint, mlbw_inpaint).")
    parser.add_argument("--outer-dilation", type=int, default=0,
                        help="Hole-Maske NACH dem Inpainting aufblähen in Pixeln (Standard: 0). "
                             "Nur wirksam bei ML-Methoden (forward_inpaint, mlbw_inpaint).")
    parser.add_argument("--reflect-pad", action="store_true",
                        help="Bildränder vor dem Warp spiegeln (reduziert Randartefakte beim "
                             "Inpainting). Nach dem Warp wird das Padding wieder entfernt.")
    parser.add_argument("--reflect-pad-frac", type=float, default=0.0625,
                        help="Padding-Größe als Bruchteil der Bildgröße (Standard: 0.0625 = 6.25%%).")
    parser.add_argument("--fps", type=str, default=None,
                        help="FPS überschreiben (Standard: aus Quellvideo)")
    run(parser.parse_args())


if __name__ == "__main__":
    main()
