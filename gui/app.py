# gui/app.py
from __future__ import annotations
import sys
import math
import tkinter as tk
from tkinter import ttk
from typing import Optional, Callable

# Optional plotting deps (Matplotlib preferred, with Tk fallback)
try:
    import numpy as np
except Exception:  # extremely rare on modern installs
    np = None  # type: ignore

try:
    import matplotlib
    matplotlib.use("TkAgg")
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
except Exception:
    matplotlib = None  # type: ignore
    Figure = None      # type: ignore
    FigureCanvasTkAgg = None  # type: ignore

from eventbus import EventBus
from hardware.base import HardwareController
from .widgets.toggle_switch import ToggleSwitch


# --- Simple red LED widget (with continuous flashing capability) ---
class Led(tk.Canvas):
    def __init__(self, master, size=16, **kw):
        super().__init__(master, width=size, height=size, highlightthickness=0, bd=0, **kw)
        d = size - 2
        self._oval = self.create_oval(1, 1, d+1, d+1, fill="#4a0000", outline="#260000")
        self._flashing = False
        self._job = None

    def _set_color(self, on: bool):
        if on:
            self.itemconfigure(self._oval, fill="#ff2b2b", outline="#9c0000")
        else:
            self.itemconfigure(self._oval, fill="#4a0000", outline="#260000")

    def start_flash(self, interval: int = 300):
        """Start flashing the LED red every <interval> ms."""
        if not self._flashing:
            self._flashing = True
            self._flash(interval)

    def _flash(self, interval: int):
        if self._flashing:
            current = self.itemcget(self._oval, "fill")
            self._set_color(current != "#ff2b2b")  # toggle color
            self._job = self.after(interval, lambda: self._flash(interval))

    def stop_flash(self):
        """Stop flashing and turn LED off (dim)."""
        self._flashing = False
        if self._job:
            self.after_cancel(self._job)
            self._job = None
        self._set_color(False)


class DSPGui(tk.Tk):
    def __init__(self, hw: HardwareController, bus: EventBus):
        super().__init__()
        self.hw, self.bus = hw, bus

        # ---------------- Window: borderless (no title bar) ----------------
        self.overrideredirect(True)  # remove title bar
        w, h = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"{w}x{h}+0+0")

        # Escape during development
        self.bind("<Escape>", lambda e: (self.overrideredirect(False), self.destroy()))

        # ---------------- Styling ----------------
        self.configure(padx=16, pady=16)
        style = ttk.Style(self)
        try:
            style.theme_use("vista" if sys.platform.startswith("win") else "clam")
        except Exception:
            pass
        style.configure("Title.TLabel", font=("Segoe UI", 22, "bold"))
        style.configure("Big.TLabel", font=("Segoe UI", 12))
        style.configure("TButton", padding=10)

        # ---------------- Debounce handles ----------------
        self._cf_after_id: Optional[str] = None
        self._bw_after_id: Optional[str] = None
        self._vol_after_id: Optional[str] = None
        self._plot_after_id: Optional[str] = None

        # ---------------- Layout (kept like your full GUI) ----------------
        root = ttk.Frame(self)
        root.pack(fill="both", expand=True)

        # Header title centered
        title = ttk.Label(root, text="DSP Audio Filter Control", style="Title.TLabel", anchor="center")
        title.pack(pady=(0, 8))

        # LEVEL row (label + LED instead of bar)
        level_row = ttk.Frame(root)
        level_row.pack(fill="x", pady=(4, 8))
        ttk.Label(level_row, text="Level", style="Big.TLabel").pack(side="left")
        self.level_led = Led(level_row, size=16)
        self.level_led.pack(side="left", padx=(8, 0))

        # CF row (slider + endpoints like your screenshot)
        cf_frame = ttk.Frame(root)
        cf_frame.pack(fill="x", pady=(8, 4))
        self._make_labeled_slider(cf_frame,
                                  left_label="CF",
                                  var_name="cf_var",
                                  from_=300, to=3000,
                                  command=self._on_cf_change)

        # Bandwidth row (slider + endpoints)
        bw_frame = ttk.Frame(root)
        bw_frame.pack(fill="x", pady=(8, 4))
        self._make_labeled_slider(bw_frame,
                                  left_label="Bandwidth",
                                  var_name="bw_var",
                                  from_=300, to=3000,
                                  command=self._on_bw_change)

        # DSP toggle row (DSP/BYPASS)
        dsp_row = ttk.Frame(root)
        dsp_row.pack(fill="x", pady=(8, 4))
        ttk.Label(dsp_row, text="DSP", style="Big.TLabel").pack(side="left", padx=(0, 8))
        self.bypass_switch = ToggleSwitch(dsp_row, width=60, height=28)
        self.bypass_switch.pack(side="left")
        self.bypass_switch.set(True)  # DSP on by default; toggle sets bypass accordingly
        self.bypass_switch.on_toggle = self._on_dsp_toggled  # True means DSP ON (bypass False)
        ttk.Label(dsp_row, text="BYPASS", style="Big.TLabel").pack(side="left", padx=(12, 0))

        # Volume row
        vol_frame = ttk.Frame(root)
        vol_frame.pack(fill="x", pady=(8, 4))
        self._make_labeled_slider(vol_frame,
                                  left_label="Volume",
                                  var_name="vol_var",
                                  from_=0, to=100,
                                  command=self._on_vol_change,
                                  is_percent=True)

        # Presets row
        presets = ttk.Frame(root)
        presets.pack(fill="x", pady=(8, 4))
        for name in ("Flat", "Bass Boost", "Treble Cut", "Bypass"):
            ttk.Button(presets, text=name, command=lambda n=name: self._on_preset(n)).pack(side="left", padx=6)

        # --- Dev helper: on‑screen Quit button ---
        dev_controls = ttk.Frame(root)
        dev_controls.pack(fill="x", pady=(6, 0))
        ttk.Button(dev_controls, text="Quit", command=self._quit_app).pack(side="left", padx=6)

        # ---------------- Frequency response plot ----------------
        plot_container = ttk.Frame(root)
        plot_container.pack(fill="both", expand=True, pady=(10, 0))

        self._use_mpl = matplotlib is not None and np is not None
        if self._use_mpl:
            self._init_mpl_plot(plot_container)
        else:
            self._init_tk_plot(plot_container)

        # Defaults
        self.cf_var.set(750)
        self.bw_var.set(1200)
        self.vol_var.set(60)

        # Hook hardware callback for level/overload indication
        try:
            self.hw.set_level_callback(self._on_level_update)
        except Exception:
            pass

        # Push initial values to hardware/bus and plot
        self._apply_cf(self.cf_var.get())
        self._apply_bw(self.bw_var.get())
        self._apply_vol(self.vol_var.get() / 100.0)
        self._apply_bypass(False)  # DSP on (not bypassed)
        self._update_plot()

    # ------------- Helpers to build rows that match your layout -------------
    def _make_labeled_slider(
        self,
        parent: tk.Widget,
        left_label: str,
        var_name: str,
        from_: int,
        to: int,
        command: Callable[[str], None],
        is_percent: bool = False,
    ):
        row = ttk.Frame(parent)
        row.pack(fill="x")

        ttk.Label(row, text=left_label, style="Big.TLabel", width=10).pack(side="left")

        var = tk.IntVar(value=from_)
        setattr(self, var_name, var)

        scale = ttk.Scale(
            row,
            from_=from_,
            to=to,
            orient="horizontal",
            variable=var,
            command=lambda _: command(str(var.get())),
        )
        scale.pack(side="left", fill="x", expand=True, padx=(6, 6))

        self_val_lbl = ttk.Label(row, text="", style="Big.TLabel", width=10, anchor="e")
        self_val_lbl.pack(side="right")

        def _update_readout(*_):
            v = int(float(var.get()))
            self_val_lbl.configure(text=(f"{v} %" if is_percent else f"{v} Hz"))

        _update_readout()
        var.trace_add("write", lambda *_: _update_readout())

        if not is_percent:
            end = ttk.Frame(parent)
            end.pack(fill="x", pady=(2, 0))
            ttk.Label(end, text="300 Hz", style="Big.TLabel").pack(side="left")
            ttk.Label(end, text="3000 Hz", style="Big.TLabel").pack(side="right")

    # ---------------- Slider handlers (debounced) ----------------
    def _on_cf_change(self, _s: str):
        if self._cf_after_id: self.after_cancel(self._cf_after_id)
        self._cf_after_id = self.after(120, lambda: (self._apply_cf(int(self.cf_var.get())), self._schedule_plot()))

    def _on_bw_change(self, _s: str):
        if self._bw_after_id: self.after_cancel(self._bw_after_id)
        self._bw_after_id = self.after(120, lambda: (self._apply_bw(int(self.bw_var.get())), self._schedule_plot()))

    def _on_vol_change(self, _s: str):
        if self._vol_after_id: self.after_cancel(self._vol_after_id)
        self._vol_after_id = self.after(120, lambda: (self._apply_vol(float(self.vol_var.get()) / 100.0), self._schedule_plot()))

    # ---------------- DSP/BYPASS ----------------
    def _on_dsp_toggled(self, dsp_on: bool):
        self._apply_bypass(not dsp_on)

    # ---------------- Apply to HW + publish ----------------
    def _apply_cf(self, hz: int):
        try: self.hw.set_center_frequency(hz)
        except Exception: pass
        try: self.bus.publish("center_frequency_hz", hz)
        except Exception: pass

    def _apply_bw(self, hz: int):
        used = False
        if hasattr(self.hw, "set_bandwidth"):
            try:
                self.hw.set_bandwidth(hz)  # type: ignore[attr-defined]
                used = True
            except Exception:
                used = False
        if not used and hasattr(self.hw, "set_bandwidth_mode"):
            mode = "narrow" if hz < 900 else ("medium" if hz < 1800 else "wide")
            try:
                self.hw.set_bandwidth_mode(mode)  # type: ignore[attr-defined]
            except Exception:
                pass
        try: self.bus.publish("bandwidth_hz", hz)
        except Exception: pass

    def _apply_vol(self, pct: float):
        try: self.hw.set_volume(pct)
        except Exception: pass
        try: self.bus.publish("volume_pct", pct)
        except Exception: pass

    def _apply_bypass(self, on: bool):
        try: self.hw.set_bypass(on)
        except Exception: pass
        try: self.bus.publish("bypass", on)
        except Exception: pass

    # ---------------- Overload / LED behavior ----------------
    def set_overload(self, overloaded: bool):
        """Flash LED continuously while overloaded; stop when safe."""
        if overloaded:
            self.level_led.start_flash(interval=300)  # adjust speed here
        else:
            self.level_led.stop_flash()

    def _on_level_update(self, level_pct: float):
        # Example threshold; replace with your VBFM overload signal if available
        overload = level_pct >= 0.90
        self.set_overload(overload)

    # ---------------- Frequency response plotting ----------------
    def _schedule_plot(self):
        if self._plot_after_id:
            self.after_cancel(self._plot_after_id)
        self._plot_after_id = self.after(80, self._update_plot)

    def _init_mpl_plot(self, parent: tk.Widget):
        # Frequencies: 50 Hz .. 4000 Hz to cover your slider ranges comfortably
        self._fmin, self._fmax = 50, 4000
        self._fig = Figure(figsize=(6, 2.6), dpi=100)
        self._ax = self._fig.add_subplot(111)
        self._ax.set_xlabel("Frequency (Hz)")
        self._ax.set_ylabel("Gain (dB)")
        self._ax.set_xlim(self._fmin, self._fmax)
        self._ax.set_ylim(-60, 0)  # like your screenshot
        self._ax.grid(True, which="both", linestyle=":", linewidth=0.7)
        self._line, = self._ax.plot([], [])

        self._canvas = FigureCanvasTkAgg(self._fig, master=parent)
        self._canvas.draw()
        self._canvas.get_tk_widget().pack(fill="both", expand=True)

    def _init_tk_plot(self, parent: tk.Widget):
        # Simple fallback plot using Tk Canvas
        self._fmin, self._fmax = 50, 4000
        self._ymin_db, self._ymax_db = -60, 0
        self._plot_pad = 36
        self._tkc = tk.Canvas(parent, bg="#eee", highlightthickness=0)
        self._tkc.pack(fill="both", expand=True)
        self._tkc.bind("<Configure>", lambda e: self._draw_tk_axes())

    def _bp_mag(self, f: float, f0: float, bw: float) -> float:
        """Analog 2nd‑order band‑pass magnitude (peak ≈1). Avoid SciPy; pure math."""
        if f <= 0 or f0 <= 0 or bw <= 0:
            return 0.0
        Q = max(1e-6, f0 / bw)
        x = f / f0
        num = x / Q
        den = math.sqrt((1 - x * x) ** 2 + (x / Q) ** 2)
        m = num / den if den > 0 else 0.0
        return max(0.0, m)

    def _update_plot(self):
        f0 = float(self.cf_var.get())
        bw = float(self.bw_var.get())
        vol = float(self.vol_var.get()) / 100.0
        # generate freqs
        if np is not None:
            freqs = np.linspace(self._fmin, self._fmax, 600)
            mags = np.array([self._bp_mag(float(f), f0, bw) for f in freqs]) * max(1e-6, vol)
            db = 20.0 * np.log10(np.clip(mags, 1e-6, None))
            if self._use_mpl:
                self._line.set_data(freqs, db)
                self._ax.set_xlim(self._fmin, self._fmax)
                self._ax.set_ylim(-60, 0)
                self._canvas.draw_idle()
            else:
                self._draw_tk_curve(freqs.tolist(), db.tolist())
        else:
            # very minimal fallback without numpy
            freqs = [self._fmin + i * (self._fmax - self._fmin) / 200 for i in range(201)]
            mags = [self._bp_mag(f, f0, bw) * max(1e-6, vol) for f in freqs]
            db = [20.0 * math.log10(max(1e-6, m)) for m in mags]
            self._draw_tk_curve(freqs, db)

    # ---- Tk-only plotting helpers ----
    def _draw_tk_axes(self):
        if not hasattr(self, "_tkc"):
            return
        c = self._tkc
        c.delete("axes")
        w = c.winfo_width()
        h = c.winfo_height()
        pad = self._plot_pad
        # axes box
        c.create_rectangle(pad, pad, w - pad, h - pad, outline="#444", tags="axes")
        # simple x gridlines
        for frac in (0.25, 0.5, 0.75):
            x = pad + frac * (w - 2 * pad)
            c.create_line(x, pad, x, h - pad, fill="#ccc", dash=(2, 2), tags="axes")
        # simple y gridlines
        for frac in (0.25, 0.5, 0.75):
            y = pad + frac * (h - 2 * pad)
            c.create_line(pad, y, w - pad, y, fill="#ccc", dash=(2, 2), tags="axes")
        # labels (minimal)
        c.create_text(pad / 2, h / 2, text="Gain(dB)", angle=90, tags="axes")
        c.create_text(w / 2, h - pad / 3, text="Frequency (Hz)", tags="axes")

    def _draw_tk_curve(self, freqs, db_vals):
        if not hasattr(self, "_tkc"):
            return
        c = self._tkc
        c.delete("curve")
        w = c.winfo_width()
        h = c.winfo_height()
        pad = self._plot_pad
        xmin, xmax = float(self._fmin), float(self._fmax)
        ymin, ymax = -60.0, 0.0
        if w <= 2 * pad or h <= 2 * pad:
            return
        def xmap(f):
            return pad + (f - xmin) / (xmax - xmin) * (w - 2 * pad)
        def ymap(db):
            db = max(ymin, min(ymax, db))
            return h - pad - (db - ymin) / (ymax - ymin) * (h - 2 * pad)
        pts = []
        for f, db in zip(freqs, db_vals):
            pts.extend([xmap(f), ymap(db)])
        if len(pts) >= 4:
            c.create_line(*pts, fill="#1f77b4", width=2, tags="curve")

    # ---------------- Optional: presets ----------------
    def _on_preset(self, name: str):
        try: self.bus.publish("preset", name)
        except Exception: pass

    # ---------------- Dev helper: quit ----------------
    def _quit_app(self):
        """Close the GUI window (useful during development)."""
        try:
            self.destroy()
        except Exception:
            pass
