#!/usr/bin/env python3
"""Einfache tkinter-Oberfläche für depth2stereo.sh"""

import subprocess
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

SCRIPT = Path(__file__).parent / "depth2stereo.sh"

INPAINTING_CHOICES = ["geometric", "none", "lama", "row_flow", "mlbw_l4",
                      "forward_inpaint", "mlbw_inpaint"]
FORMAT_CHOICES = ["half-sbs", "full-sbs", "top-bottom", "anaglyph", "lr"]
ANAGLYPH_CHOICES = ["dubois", "half-color", "color", "gray", "amber-blue", "wimmer"]
SYNTHETIC_CHOICES = ["both", "right", "left"]
DEPTH_NEAR_CHOICES = ["white", "black"]
NORM_MODE_CHOICES = ["global", "none"]

ML_INPAINT_METHODS = {"forward_inpaint", "mlbw_inpaint"}


class Depth2StereoGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("depth2stereo")
        self._build_ui()
        self._on_format_change()
        self._on_inpainting_change()
        self._on_mode_change()
        # Fenstergröße erst NACH dem UI-Aufbau festlegen. Wird die Breite vorab per
        # resizable(width=False) fixiert, übernimmt das Fenster auf macOS seine
        # winzige Startbreite und wächst nicht mehr mit dem Inhalt (Fenster
        # erscheint als schmaler Streifen) — insbesondere wenn die angeforderte
        # Höhe den Bildschirm übersteigt. Deshalb: Geometrie setzen (Höhe auf
        # Bildschirm begrenzen), danach Breite fixieren.
        self.update_idletasks()
        width = self.winfo_reqwidth()
        height = min(self.winfo_reqheight(), self.winfo_screenheight() - 120)
        self.geometry(f"{width}x{height}")
        self.resizable(False, True)

    # ── UI aufbauen ──────────────────────────────────────────────────────────

    def _build_ui(self):
        pad = {"padx": 8, "pady": 4}
        self.columnconfigure(0, weight=1)

        # ── Modus + Eingabe ──
        input_frame = ttk.LabelFrame(self, text="Eingabe")
        input_frame.grid(row=0, column=0, sticky="ew", **pad)
        input_frame.columnconfigure(1, weight=1)

        self.batch_mode = tk.BooleanVar(value=False)
        mode_frame = ttk.Frame(input_frame)
        mode_frame.grid(row=0, column=0, columnspan=3, sticky="w", padx=8, pady=(6, 2))
        ttk.Radiobutton(mode_frame, text="Einzeldatei", variable=self.batch_mode,
                        value=False, command=self._on_mode_change).pack(side="left", padx=(0, 16))
        ttk.Radiobutton(mode_frame, text="Verzeichnis (Batch)", variable=self.batch_mode,
                        value=True, command=self._on_mode_change).pack(side="left")

        self.input_label = ttk.Label(input_frame, text="Videodatei:")
        self.input_label.grid(row=1, column=0, sticky="w", **pad)
        self.input_var = tk.StringVar()
        self.input_var.trace_add("write", lambda *_: self._update_command())
        self.input_entry = ttk.Entry(input_frame, textvariable=self.input_var, width=55)
        self.input_entry.grid(row=1, column=1, sticky="ew", **pad)
        self.browse_btn = ttk.Button(input_frame, text="…", width=3,
                                     command=self._browse)
        self.browse_btn.grid(row=1, column=2, **pad)

        self.depth_label = ttk.Label(input_frame, text="Depthmap (optional):")
        self.depth_label.grid(row=2, column=0, sticky="w", **pad)
        self.depth_var = tk.StringVar()
        self.depth_var.trace_add("write", lambda *_: self._update_command())
        self.depth_entry = ttk.Entry(input_frame, textvariable=self.depth_var, width=55)
        self.depth_entry.grid(row=2, column=1, sticky="ew", **pad)
        self.depth_browse_btn = ttk.Button(input_frame, text="…", width=3,
                                           command=self._browse_depth)
        self.depth_browse_btn.grid(row=2, column=2, **pad)

        # ── Stereo-Parameter ──
        stereo = ttk.LabelFrame(self, text="Stereo")
        stereo.grid(row=1, column=0, sticky="ew", **pad)
        stereo.columnconfigure(1, weight=1)

        self.inpainting_var = tk.StringVar(value="geometric")
        self.inpainting_var.trace_add("write", lambda *_: (self._on_inpainting_change(),
                                                            self._update_command()))
        self._row(stereo, 0, "Inpainting:", ttk.Combobox,
                  dict(textvariable=self.inpainting_var, values=INPAINTING_CHOICES,
                       state="readonly", width=22))

        self.synthetic_var = tk.StringVar(value="right")
        self.synthetic_var.trace_add("write", lambda *_: self._update_command())
        self._row(stereo, 1, "Synthetisches Auge:", ttk.Combobox,
                  dict(textvariable=self.synthetic_var, values=SYNTHETIC_CHOICES,
                       state="readonly", width=22))

        self.divergence_var = tk.DoubleVar(value=2.0)
        self.divergence_var.trace_add("write", lambda *_: self._update_command())
        self._slider_row(stereo, 2, "Divergenz (%):", self.divergence_var,
                         from_=0.0, to=6.0, resolution=0.1)

        self.convergence_var = tk.DoubleVar(value=0.5)
        self.convergence_var.trace_add("write", lambda *_: self._update_command())
        self._slider_row(stereo, 3, "Konvergenz (0–1):", self.convergence_var,
                         from_=0.0, to=1.0, resolution=0.05)

        self.edge_dilation_var = tk.IntVar(value=2)
        self.edge_dilation_var.trace_add("write", lambda *_: self._update_command())
        self._row(stereo, 4, "Edge Dilation (px):", ttk.Spinbox,
                  dict(textvariable=self.edge_dilation_var, from_=0, to=30,
                       increment=1, width=6))

        self.reflect_pad_frac_var = tk.StringVar(value="0.0625")
        self.reflect_pad_frac_var.trace_add("write", lambda *_: self._update_command())
        self._row(stereo, 5, "Reflect Pad (0=aus):", ttk.Combobox,
                  dict(textvariable=self.reflect_pad_frac_var,
                       values=["0", "0.03125", "0.0625", "0.09375", "0.125",
                               "0.15625", "0.1875", "0.21875", "0.25"],
                       state="readonly", width=10))

        self.max_width_var = tk.StringVar(value="")
        self.max_width_var.trace_add("write", lambda *_: self._update_command())
        self._row(stereo, 6, "Max Width (px):", ttk.Entry,
                  dict(textvariable=self.max_width_var, width=8))
        ttk.Label(stereo, text="(leer = keine Begrenzung)", foreground="gray").grid(
            row=6, column=2, sticky="w", padx=4)

        # ── Hole-Filling (nur ML-Inpaint) ──
        self.holes_frame = ttk.LabelFrame(self, text="Hole-Filling (ML-Inpaint)")
        self.holes_frame.grid(row=2, column=0, sticky="ew", **pad)
        self.holes_frame.columnconfigure(1, weight=1)

        self.inner_dilation_var = tk.IntVar(value=0)
        self.inner_dilation_var.trace_add("write", lambda *_: self._update_command())
        self._row(self.holes_frame, 0, "Inner Dilation (px):", ttk.Spinbox,
                  dict(textvariable=self.inner_dilation_var, from_=0, to=30,
                       increment=1, width=6))

        self.outer_dilation_var = tk.IntVar(value=0)
        self.outer_dilation_var.trace_add("write", lambda *_: self._update_command())
        self._row(self.holes_frame, 1, "Outer Dilation (px):", ttk.Spinbox,
                  dict(textvariable=self.outer_dilation_var, from_=0, to=30,
                       increment=1, width=6))

        # ── Ausgabe-Format ──
        fmt_frame = ttk.LabelFrame(self, text="Ausgabe")
        fmt_frame.grid(row=3, column=0, sticky="ew", **pad)
        fmt_frame.columnconfigure(1, weight=1)

        self.format_var = tk.StringVar(value="half-sbs")
        self.format_var.trace_add("write", lambda *_: (self._on_format_change(),
                                                        self._update_command()))
        self._row(fmt_frame, 0, "Format:", ttk.Combobox,
                  dict(textvariable=self.format_var, values=FORMAT_CHOICES,
                       state="readonly", width=22))

        self.anaglyph_var = tk.StringVar(value="dubois")
        self.anaglyph_var.trace_add("write", lambda *_: self._update_command())
        ttk.Label(fmt_frame, text="Anaglyphen-Methode:").grid(
            row=1, column=0, sticky="w", **pad)
        self.anaglyph_combo = ttk.Combobox(fmt_frame, textvariable=self.anaglyph_var,
                                           values=ANAGLYPH_CHOICES, state="readonly", width=22)
        self.anaglyph_combo.grid(row=1, column=1, sticky="w", **pad)

        self.depth_near_var = tk.StringVar(value="white")
        self.depth_near_var.trace_add("write", lambda *_: self._update_command())
        self._row(fmt_frame, 2, "Tiefe: hell = nah:", ttk.Combobox,
                  dict(textvariable=self.depth_near_var, values=DEPTH_NEAR_CHOICES,
                       state="readonly", width=22))

        self.norm_mode_var = tk.StringVar(value="global")
        self.norm_mode_var.trace_add("write", lambda *_: self._update_command())
        self._row(fmt_frame, 3, "Tiefen-Normalisierung:", ttk.Combobox,
                  dict(textvariable=self.norm_mode_var, values=NORM_MODE_CHOICES,
                       state="readonly", width=22))

        # ── Befehlsvorschau ──
        cmd_frame = ttk.LabelFrame(self, text="Befehl")
        cmd_frame.grid(row=4, column=0, sticky="ew", **pad)
        cmd_frame.columnconfigure(0, weight=1)
        self.cmd_text = tk.Text(cmd_frame, height=3, wrap="word", state="disabled",
                                font=("Menlo", 11), background="#f0f0f0",
                                foreground="#1a1a1a")
        self.cmd_text.grid(row=0, column=0, sticky="ew", padx=6, pady=4)

        # ── Buttons ──
        btn_frame = ttk.Frame(self)
        btn_frame.grid(row=5, column=0, sticky="e", **pad)
        self.run_btn = ttk.Button(btn_frame, text="▶  Ausführen", command=self._run)
        self.run_btn.pack(side="right", padx=4)

        # ── Ausgabe ──
        out_frame = ttk.LabelFrame(self, text="Ausgabe")
        out_frame.grid(row=6, column=0, sticky="nsew", **pad)
        out_frame.columnconfigure(0, weight=1)
        out_frame.rowconfigure(0, weight=1)
        self.rowconfigure(6, weight=1)

        self.output_text = tk.Text(out_frame, height=14, wrap="word",
                                   font=("Menlo", 11), state="disabled")
        scrollbar = ttk.Scrollbar(out_frame, command=self.output_text.yview)
        self.output_text.configure(yscrollcommand=scrollbar.set)
        self.output_text.grid(row=0, column=0, sticky="nsew", padx=(6, 0), pady=4)
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
        slider = ttk.Scale(frame, variable=var, from_=from_, to=to, length=180,
                           command=lambda v: var.set(round(float(v) / resolution) * resolution))
        slider.pack(side="left")
        ttk.Label(frame, textvariable=var, width=5).pack(side="left", padx=6)

    def _on_mode_change(self):
        if self.batch_mode.get():
            self.input_label.configure(text="Verzeichnis:")
            self.depth_var.set("")
            self.depth_entry.configure(state="disabled")
            self.depth_browse_btn.configure(state="disabled")
        else:
            self.input_label.configure(text="Videodatei:")
            self.depth_entry.configure(state="normal")
            self.depth_browse_btn.configure(state="normal")
        self.input_var.set("")
        self._update_command()

    def _browse(self):
        if self.batch_mode.get():
            path = filedialog.askdirectory(title="Verzeichnis mit Videos wählen")
        else:
            path = filedialog.askopenfilename(
                title="Videodatei wählen",
                filetypes=[("Videodateien", "*.mp4 *.mov *.mkv"), ("Alle Dateien", "*.*")]
            )
        if path:
            self.input_var.set(path)

    def _browse_depth(self):
        path = filedialog.askopenfilename(
            title="Tiefendatei wählen",
            filetypes=[("Tiefendaten", "*.npz *.mp4"), ("Alle Dateien", "*.*")]
        )
        if path:
            self.depth_var.set(path)

    def _on_format_change(self):
        state = "readonly" if self.format_var.get() == "anaglyph" else "disabled"
        self.anaglyph_combo.configure(state=state)

    def _on_inpainting_change(self):
        is_ml_inpaint = self.inpainting_var.get() in ML_INPAINT_METHODS
        for child in self.holes_frame.winfo_children():
            try:
                child.configure(state="normal" if is_ml_inpaint else "disabled")
            except tk.TclError:
                pass

    def _build_command(self):
        target = self.input_var.get().strip()
        if not target:
            return []

        cmd = [str(SCRIPT), target]
        if not self.batch_mode.get():
            depth = self.depth_var.get().strip()
            if depth:
                cmd += ["--depth", depth]
        cmd += ["--inpainting", self.inpainting_var.get()]
        cmd += ["--format", self.format_var.get()]
        if self.format_var.get() == "anaglyph":
            cmd += ["--anaglyph-method", self.anaglyph_var.get()]
        cmd += ["--synthetic-view", self.synthetic_var.get()]
        cmd += ["--divergence", f"{self.divergence_var.get():.2f}"]
        cmd += ["--convergence", f"{self.convergence_var.get():.2f}"]
        cmd += ["--depth-near", self.depth_near_var.get()]
        cmd += ["--norm-mode", self.norm_mode_var.get()]
        cmd += ["--edge-dilation", str(self.edge_dilation_var.get())]
        _rp_frac = float(self.reflect_pad_frac_var.get())
        if _rp_frac > 0:
            cmd += ["--reflect-pad"]
            cmd += ["--reflect-pad-frac", str(_rp_frac)]
        if self.max_width_var.get().strip():
            cmd += ["--max-width", self.max_width_var.get().strip()]
        if self.inpainting_var.get() in ML_INPAINT_METHODS:
            cmd += ["--inner-dilation", str(self.inner_dilation_var.get())]
            cmd += ["--outer-dilation", str(self.outer_dilation_var.get())]
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

    def _append_output(self, text):
        self.output_text.configure(state="normal")
        self.output_text.insert("end", text)
        self.output_text.see("end")
        self.output_text.configure(state="disabled")

    def _run(self):
        cmd = self._build_command()
        if not cmd:
            label = "Verzeichnis" if self.batch_mode.get() else "Videodatei"
            self._append_output(f"❌ Kein {label} ausgewählt.\n")
            return

        self.run_btn.configure(state="disabled")
        self.output_text.configure(state="normal")
        self.output_text.delete("1.0", "end")
        self.output_text.configure(state="disabled")
        mode_label = "Batch" if self.batch_mode.get() else "Einzeldatei"
        self._append_output(f"▶ {mode_label}: {Path(cmd[1]).name} …\n\n")

        def _worker():
            try:
                proc = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, bufsize=1
                )
                for line in proc.stdout:
                    self.after(0, self._append_output, line)
                proc.wait()
                status = "✅ Fertig." if proc.returncode == 0 else f"❌ Fehler (Code {proc.returncode})."
                self.after(0, self._append_output, f"\n{status}\n")
            except Exception as e:
                self.after(0, self._append_output, f"\n❌ {e}\n")
            finally:
                self.after(0, self.run_btn.configure, {"state": "normal"})

        threading.Thread(target=_worker, daemon=True).start()


if __name__ == "__main__":
    app = Depth2StereoGUI()
    app.mainloop()
