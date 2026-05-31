#!/usr/bin/env python3
"""Tkinter-GUI für floating-window — Floating Window auf L/R-Stereovideos."""

import shutil
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

ANAGLYPH_CHOICES = ["dubois", "half-color", "color", "gray", "amber-blue", "wimmer"]
DEPTH_NEAR_CHOICES = ["white", "black"]


def _find_binary() -> str:
    """Sucht das floating-window-Binary ohne Conda-Aktivierung."""
    # 1. Gleicher bin-Ordner wie das laufende Python (funktioniert wenn GUI in der Conda-Env läuft)
    candidate = Path(sys.executable).parent / "floating-window"
    if candidate.exists():
        return str(candidate)
    # 2. Bekannter Conda-Env-Pfad
    known = Path("/opt/anaconda3/envs/depth-pro-for-video/bin/floating-window")
    if known.exists():
        return str(known)
    # 3. PATH
    found = shutil.which("floating-window")
    if found:
        return found
    return "floating-window"


BINARY = _find_binary()


def _find_lr(d: Path, name: str):
    """Sucht *_L.mp4 / *_R.mp4 im Verzeichnis d.

    Reihenfolge:
      1. Exakt: name_L.mp4
      2. Glob:  name*_L.mp4  (z.B. name_stereo_L.mp4)
    """
    exact_l = d / f"{name}_L.mp4"
    exact_r = d / f"{name}_R.mp4"
    if exact_l.exists() and exact_r.exists():
        return exact_l, exact_r

    # Glob-Suche: name + beliebiger Infix + _L / _R
    l_matches = sorted(d.glob(f"{name}*_L.mp4"))
    r_matches = sorted(d.glob(f"{name}*_R.mp4"))

    # Keine Depth-Map-Dateien matchen
    l_matches = [p for p in l_matches if "_depth" not in p.name and "_depthmap" not in p.name]
    r_matches = [p for p in r_matches if "_depth" not in p.name and "_depthmap" not in p.name]

    return (l_matches[0] if l_matches else None,
            r_matches[0] if r_matches else None)


def _find_depth(d: Path, name: str):
    for suffix in [f"{name}_depth.npz", f"{name}_depthmap.mp4", f"{name}_depth.mp4"]:
        p = d / suffix
        if p.exists():
            return p
    return None


class FloatingWindowGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Floating Window")
        self.resizable(False, True)
        self._left_path = None
        self._right_path = None
        self._depth_path = None
        self._build_ui()
        self._on_format_change()

    # ── UI aufbauen ──────────────────────────────────────────────────────────

    def _build_ui(self):
        pad = {"padx": 8, "pady": 4}
        self.columnconfigure(0, weight=1)

        # ── Eingabe ──
        input_frame = ttk.LabelFrame(self, text="Eingabe")
        input_frame.grid(row=0, column=0, sticky="ew", **pad)
        input_frame.columnconfigure(1, weight=1)

        ttk.Label(input_frame, text="RGB-Video:").grid(row=0, column=0, sticky="w", **pad)
        self.video_var = tk.StringVar()
        self.video_var.trace_add("write", lambda *_: self._on_video_change())
        ttk.Entry(input_frame, textvariable=self.video_var, width=52).grid(
            row=0, column=1, sticky="ew", **pad)
        ttk.Button(input_frame, text="…", width=3,
                   command=self._browse_video).grid(row=0, column=2, **pad)

        ttk.Label(input_frame, text="Linkes Auge:").grid(row=1, column=0, sticky="w", **pad)
        self.left_label = ttk.Label(input_frame, text="—", foreground="gray")
        self.left_label.grid(row=1, column=1, sticky="w", **pad)

        ttk.Label(input_frame, text="Rechtes Auge:").grid(row=2, column=0, sticky="w", **pad)
        self.right_label = ttk.Label(input_frame, text="—", foreground="gray")
        self.right_label.grid(row=2, column=1, sticky="w", **pad)

        ttk.Label(input_frame, text="Tiefenkarte:").grid(row=3, column=0, sticky="w", **pad)
        self.depth_label = ttk.Label(input_frame, text="—", foreground="gray")
        self.depth_label.grid(row=3, column=1, sticky="w", **pad)

        # ── Floating Window Parameter ──
        fw_frame = ttk.LabelFrame(self, text="Floating Window")
        fw_frame.grid(row=1, column=0, sticky="ew", **pad)
        fw_frame.columnconfigure(1, weight=1)

        self.divergence_var = tk.DoubleVar(value=3.0)
        self.divergence_var.trace_add("write", lambda *_: self._update_command())
        self._slider_row(fw_frame, 0, "Divergenz (%):", self.divergence_var,
                         from_=0.5, to=8.0, resolution=0.1)

        self.convergence_var = tk.DoubleVar(value=0.5)
        self.convergence_var.trace_add("write", lambda *_: self._update_command())
        self._slider_row(fw_frame, 1, "Konvergenz (0–1):", self.convergence_var,
                         from_=0.0, to=1.0, resolution=0.05)

        self.smoothing_var = tk.IntVar(value=12)
        self.smoothing_var.trace_add("write", lambda *_: self._update_command())
        self._row(fw_frame, 2, "Glättung (Frames):", ttk.Spinbox,
                  dict(textvariable=self.smoothing_var, from_=1, to=120, increment=1, width=6))
        ttk.Label(fw_frame, text="Balken gleiten über N Frames aus",
                  foreground="gray").grid(row=2, column=2, sticky="w", padx=4)

        self.depth_near_var = tk.StringVar(value="white")
        self.depth_near_var.trace_add("write", lambda *_: self._update_command())
        self._row(fw_frame, 3, "Tiefe: hell = nah:", ttk.Combobox,
                  dict(textvariable=self.depth_near_var, values=DEPTH_NEAR_CHOICES,
                       state="readonly", width=10))

        # ── Ausgabe ──
        out_frame = ttk.LabelFrame(self, text="Ausgabe")
        out_frame.grid(row=2, column=0, sticky="ew", **pad)
        out_frame.columnconfigure(1, weight=1)

        self.format_var = tk.StringVar(value="anaglyph")
        self.format_var.trace_add("write", lambda *_: (self._on_format_change(),
                                                        self._update_command()))
        fmt_inner = ttk.Frame(out_frame)
        fmt_inner.grid(row=0, column=0, columnspan=3, sticky="w", padx=8, pady=4)
        ttk.Label(fmt_inner, text="Format:").pack(side="left", padx=(0, 12))
        ttk.Radiobutton(fmt_inner, text="Anaglyph", variable=self.format_var,
                        value="anaglyph").pack(side="left", padx=(0, 16))
        ttk.Radiobutton(fmt_inner, text="L/R-Dateien", variable=self.format_var,
                        value="lr").pack(side="left")

        self.anaglyph_var = tk.StringVar(value="dubois")
        self.anaglyph_var.trace_add("write", lambda *_: self._update_command())
        ttk.Label(out_frame, text="Anaglyphen-Methode:").grid(row=1, column=0, sticky="w", **pad)
        self.anaglyph_combo = ttk.Combobox(out_frame, textvariable=self.anaglyph_var,
                                           values=ANAGLYPH_CHOICES, state="readonly", width=14)
        self.anaglyph_combo.grid(row=1, column=1, sticky="w", **pad)

        # ── Befehlsvorschau ──
        cmd_frame = ttk.LabelFrame(self, text="Befehl")
        cmd_frame.grid(row=3, column=0, sticky="ew", **pad)
        cmd_frame.columnconfigure(0, weight=1)
        self.cmd_text = tk.Text(cmd_frame, height=2, wrap="word", state="disabled",
                                font=("Menlo", 11), background="#f0f0f0")
        self.cmd_text.grid(row=0, column=0, sticky="ew", padx=6, pady=4)

        # ── Ausführen ──
        btn_frame = ttk.Frame(self)
        btn_frame.grid(row=4, column=0, sticky="e", **pad)
        ttk.Button(btn_frame, text="▶  Ausführen", command=self._run).pack(side="right", padx=4)

        # ── Log ──
        log_frame = ttk.LabelFrame(self, text="Log")
        log_frame.grid(row=5, column=0, sticky="nsew", **pad)
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        self.rowconfigure(5, weight=1)

        self.log_text = tk.Text(log_frame, height=12, wrap="word",
                                font=("Menlo", 11), state="disabled")
        scrollbar = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        self.log_text.grid(row=0, column=0, sticky="nsew", padx=(6, 0), pady=4)
        scrollbar.grid(row=0, column=1, sticky="ns", pady=4, padx=(0, 4))

    # ── Hilfsmethoden ────────────────────────────────────────────────────────

    def _row(self, parent, row, label, widget_cls, widget_kwargs):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=8, pady=4)
        w = widget_cls(parent, **widget_kwargs)
        w.grid(row=row, column=1, sticky="w", padx=8, pady=4)
        return w

    def _slider_row(self, parent, row, label, var, from_, to, resolution):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=8, pady=4)
        frame = ttk.Frame(parent)
        frame.grid(row=row, column=1, sticky="w", padx=8, pady=4)
        slider = ttk.Scale(frame, variable=var, from_=from_, to=to, length=200,
                           command=lambda v: var.set(round(float(v) / resolution) * resolution))
        slider.pack(side="left")
        ttk.Label(frame, textvariable=var, width=5).pack(side="left", padx=6)

    def _browse_video(self):
        path = filedialog.askopenfilename(
            title="RGB-Quellvideo wählen",
            filetypes=[("Videodateien", "*.mp4 *.mov *.mkv"), ("Alle Dateien", "*.*")]
        )
        if path:
            self.video_var.set(path)

    def _on_video_change(self):
        self._left_path = None
        self._right_path = None
        self._depth_path = None

        video = self.video_var.get().strip()
        if not video:
            self.left_label.configure(text="—", foreground="gray")
            self.right_label.configure(text="—", foreground="gray")
            self.depth_label.configure(text="—", foreground="gray")
            self._update_command()
            return

        d = Path(video).parent
        name = Path(video).stem

        l_path, r_path = _find_lr(d, name)
        depth_path = _find_depth(d, name)

        self._left_path = l_path
        self._right_path = r_path
        self._depth_path = depth_path

        self.left_label.configure(
            text=l_path.name if l_path else "nicht gefunden",
            foreground="black" if l_path else "red"
        )
        self.right_label.configure(
            text=r_path.name if r_path else "nicht gefunden",
            foreground="black" if r_path else "red"
        )
        self.depth_label.configure(
            text=depth_path.name if depth_path else "nicht gefunden — fixer FW-Wert",
            foreground="black" if depth_path else "gray"
        )

        self._update_command()

    def _on_format_change(self):
        state = "readonly" if self.format_var.get() == "anaglyph" else "disabled"
        self.anaglyph_combo.configure(state=state)

    def _build_command(self):
        video = self.video_var.get().strip()
        if not video:
            return []

        # Direkt das Binary aufrufen — kein Shell-Script, kein conda activate
        cmd = [BINARY, "-i", video]
        if self._left_path:
            cmd += ["--left", str(self._left_path)]
        if self._right_path:
            cmd += ["--right", str(self._right_path)]
        if self._depth_path:
            cmd += ["--depth", str(self._depth_path)]
        cmd += ["--format", self.format_var.get()]
        if self.format_var.get() == "anaglyph":
            cmd += ["--anaglyph-method", self.anaglyph_var.get()]
        cmd += ["--divergence", f"{self.divergence_var.get():.1f}"]
        cmd += ["--convergence", f"{self.convergence_var.get():.2f}"]
        cmd += ["--depth-near", self.depth_near_var.get()]
        cmd += ["--smoothing", str(self.smoothing_var.get())]
        return cmd

    def _update_command(self):
        cmd = self._build_command()
        self.cmd_text.configure(state="normal")
        self.cmd_text.delete("1.0", "end")
        if cmd:
            self.cmd_text.insert("end", " ".join(
                f'"{c}"' if " " in c else c for c in cmd
            ))
        self.cmd_text.configure(state="disabled")

    def _append_log(self, text):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", text)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _run(self):
        cmd = self._build_command()
        if not cmd:
            self._append_log("❌ Kein Video ausgewählt.\n")
            return
        if not self._left_path or not self._right_path:
            self._append_log("❌ Linkes oder rechtes Auge nicht gefunden.\n")
            return

        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")
        self._append_log(f"▶ {Path(self.video_var.get()).name} …\n\n")
        self._append_log(f"Binary: {BINARY}\n\n")

        def _worker():
            try:
                proc = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, bufsize=1
                )
                for line in proc.stdout:
                    self.after(0, self._append_log, line)
                proc.wait()
                status = "✅ Fertig." if proc.returncode == 0 else f"❌ Fehler (Code {proc.returncode})."
                self.after(0, self._append_log, f"\n{status}\n")
            except Exception as e:
                self.after(0, self._append_log, f"\n❌ {e}\n")

        threading.Thread(target=_worker, daemon=True).start()


if __name__ == "__main__":
    app = FloatingWindowGUI()
    app.mainloop()
