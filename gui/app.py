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
except Exception:
    np = None

try:
    import scipy.signal
except Exception:
    scipy = None

try:
    import matplotlib
    matplotlib.use("TkAgg")
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
except Exception:
    matplotlib = None
    Figure = None
    FigureCanvasTkAgg = None

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


# --- Slider with attached value display ---
class ValueSlider(ttk.Frame):
    def __init__(self, master, label, from_, to, command, unit="Hz", is_percent=False, **kw):
        super().__init__(master, **kw)
        self.from_ = from_
        self.to = to
        self.command = command
        self.unit = unit
        self.is_percent = is_percent
        
        # Main variable
        self.var = tk.IntVar(value=from_)
        
        # Create slider with value display attached
        self._create_slider_with_display(label)
        
        # Range labels
        self._create_range_labels()
        
        # Bind variable changes
        self.var.trace_add("write", self._on_value_change)

    def _create_slider_with_display(self, label):
        # Top row: Label and current value display
        top_row = ttk.Frame(self)
        top_row.pack(fill="x", pady=(0, 3))
        ttk.Label(top_row, text=label, style="Compact.TLabel", width=14).pack(side="left")
        
        # Current value display (always visible above slider)
        self.value_display = ttk.Label(top_row, text="", style="ValueDisplay.TLabel", 
                                     width=6, anchor="center")
        self.value_display.pack(side="right")
        
        # Slider row with range labels
        slider_row = ttk.Frame(self)
        slider_row.pack(fill="x", pady=(0, 2))
        
        # Range start label
        self.range_start = ttk.Label(slider_row, text=f"{self.from_} {self.unit}", 
                                   style="Range.TLabel", width=5)
        self.range_start.pack(side="left", padx=(0, 5))
        
        # Slider
        self.scale = ttk.Scale(
            slider_row,
            from_=self.from_,
            to=self.to,
            orient="horizontal",
            variable=self.var,
            command=self._on_slide
        )
        self.scale.pack(side="left", fill="x", expand=True)
        
        # Range end label
        self.range_end = ttk.Label(slider_row, text=f"{self.to} {self.unit}", 
                                 style="Range.TLabel", width=5)
        self.range_end.pack(side="left", padx=(5, 0))

    def _create_range_labels(self):
        # Frequency range clarification for 300-3000Hz sliders
        if not self.is_percent and self.from_ == 300 and self.to == 3000:
            range_clarification = ttk.Frame(self)
            range_clarification.pack(fill="x", pady=(1, 0))
            ttk.Label(range_clarification, 
                     text="300 Hz (Low) to 3000 Hz (High)", 
                     style="Range.TLabel", 
                     foreground="#2E86AB",
                     font=("Segoe UI", 8)).pack(anchor="center")

    def _on_slide(self, value):
        # Update value display in real-time while sliding
        current_val = int(float(value))
        if not self.is_percent:
            current_val = round(current_val / 25) * 25  # Apply step size
        
        # Update display text
        self._update_display(current_val)

    def _on_value_change(self, *args):
        # Final value update when sliding stops
        current_val = self.var.get()
        self._update_display(current_val)
        if self.command:
            self.command(str(current_val))

    def _update_display(self, value):
        """Update the value display with proper formatting"""
        display_text = f"{value} {self.unit}"
        self.value_display.configure(text=display_text)
        
        # Add visual feedback for extreme values (for frequency sliders only)
        if not self.is_percent:
            if value <= 500:  # Very low frequencies
                self.value_display.configure(foreground="#FF6B6B")
            elif value >= 2500:  # Very high frequencies
                self.value_display.configure(foreground="#4ECDC4")
            else:  # Mid frequencies
                self.value_display.configure(foreground="#2E86AB")

    def get(self):
        return self.var.get()

    def set(self, value):
        self.var.set(value)


class PresetManager:
    def __init__(self):
        self.presets = {
            "Voice": {"cf": 1000, "bw": 500},
            "Bass": {"cf": 400, "bw": 300},
            "Midrange": {"cf": 1500, "bw": 800},
            "Treble": {"cf": 2500, "bw": 600},
            "Wide Voice": {"cf": 1000, "bw": 1200},
            "Narrow Bass": {"cf": 400, "bw": 200},
            "Custom 1": {"cf": 750, "bw": 400}
        }


class DSPGui(tk.Tk):
    def __init__(self, hw: HardwareController, bus: EventBus):
        super().__init__()
        self.hw, self.bus = hw, bus

        # ---------------- Window Configuration ----------------
        self.title("DSP Audio Filter Control")
        
        # Set appropriate sizes for different displays
        if self._is_touchscreen_mode():
            # Touchscreen mode - fullscreen
            self.attributes('-fullscreen', True)
        else:
            # Laptop mode - balanced window for 50/50 split
            self.geometry("1000x700+50+50")  # Good balance for 50/50
            self.minsize(900, 600)
        
        # Escape to exit fullscreen on touchscreen, close on laptop
        self.bind("<Escape>", self._on_escape)

        # ---------------- Styling ----------------
        self.configure(padx=10, pady=10)
        style = ttk.Style(self)
        try:
            style.theme_use("vista" if sys.platform.startswith("win") else "clam")
        except Exception:
            pass
        
        # Balanced styles for 50/50 layout
        if self._is_touchscreen_mode():
            font_size = 10
            style.configure("Title.TLabel", font=("Segoe UI", 18, "bold"))
        else:
            font_size = 11
            style.configure("Title.TLabel", font=("Segoe UI", 20, "bold"))
            
        # Comfortable styles for 50/50 layout
        style.configure("Big.TLabel", font=("Segoe UI", font_size))
        style.configure("Compact.TLabel", font=("Segoe UI", font_size-1))
        style.configure("Range.TLabel", font=("Segoe UI", font_size-1), foreground="#666666")  # Slightly larger
        style.configure("ValueDisplay.TLabel", font=("Segoe UI", font_size, "bold"), 
                       background="#2c2c2c", foreground="white", relief="raised", 
                       borderwidth=1, padding=(4, 2))  # Slightly larger padding
        
        if self._is_touchscreen_mode():
            style.configure("TButton", padding=(10, 6))
            style.configure("Compact.TButton", padding=(8, 4))
        else:
            style.configure("TButton", padding=(8, 5))
            style.configure("Compact.TButton", padding=(6, 4))  # More comfortable buttons

        # ---------------- Debounce handles ----------------
        self._cf_after_id: Optional[str] = None
        self._bw_after_id: Optional[str] = None
        self._vol_after_id: Optional[str] = None
        self._plot_after_id: Optional[str] = None

        # ---------------- Preset Manager ----------------
        self.preset_manager = PresetManager()

        # ---------------- Layout - 50/50 Split ----------------
        root = ttk.Frame(self)
        root.pack(fill="both", expand=True, padx=8, pady=8)

        # Main container with two equal columns
        main_container = ttk.Frame(root)
        main_container.pack(fill="both", expand=True)

        # Left column: Controls (50% width)
        controls_frame = ttk.Frame(main_container)
        controls_frame.pack(side="left", fill="both", expand=True, padx=(0, 5))
        
        # Right column: Graph (50% width)
        graph_frame = ttk.Frame(main_container)
        graph_frame.pack(side="right", fill="both", expand=True, padx=(5, 0))

        # Header title in controls column
        title = ttk.Label(controls_frame, text="DSP Audio Filter Control", style="Title.TLabel", anchor="center")
        title.pack(pady=(0, 15))

        # LEVEL row
        level_row = ttk.Frame(controls_frame)
        level_row.pack(fill="x", pady=(0, 10))
        ttk.Label(level_row, text="Level", style="Big.TLabel").pack(side="left")
        self.level_led = Led(level_row, size=16)
        self.level_led.pack(side="left", padx=(8, 0))

        # CF row with enhanced slider
        cf_frame = ttk.Frame(controls_frame)
        cf_frame.pack(fill="x", pady=(8, 2))
        self.cf_slider = ValueSlider(cf_frame, "Center Frequency", 300, 3000, 
                                   self._on_cf_change, "Hz")
        self.cf_slider.pack(fill="x")
        self.cf_var = self.cf_slider.var

        # Bandwidth row with enhanced slider
        bw_frame = ttk.Frame(controls_frame)
        bw_frame.pack(fill="x", pady=(8, 2))
        self.bw_slider = ValueSlider(bw_frame, "Bandwidth", 300, 3000, 
                                   self._on_bw_change, "Hz")
        self.bw_slider.pack(fill="x")
        self.bw_var = self.bw_slider.var

        # DSP toggle row
        dsp_row = ttk.Frame(controls_frame)
        dsp_row.pack(fill="x", pady=(12, 2))
        ttk.Label(dsp_row, text="DSP", style="Big.TLabel").pack(side="left", padx=(0, 8))
        self.bypass_switch = ToggleSwitch(dsp_row, width=60, height=28)
        self.bypass_switch.pack(side="left")
        self.bypass_switch.set(True)
        self.bypass_switch.on_toggle = self._on_dsp_toggled
        ttk.Label(dsp_row, text="BYPASS", style="Big.TLabel").pack(side="left", padx=(12, 0))

        # Volume row
        vol_frame = ttk.Frame(controls_frame)
        vol_frame.pack(fill="x", pady=(8, 2))
        self.vol_slider = ValueSlider(vol_frame, "Volume", 0, 100, 
                                    self._on_vol_change, "%", is_percent=True)
        self.vol_slider.pack(fill="x")
        self.vol_var = self.vol_slider.var

        # Presets section
        presets_label = ttk.Label(controls_frame, text="Presets:", style="Big.TLabel")
        presets_label.pack(anchor="w", pady=(15, 8))
        
        # Preset buttons in a comfortable layout
        presets_frame = ttk.Frame(controls_frame)
        presets_frame.pack(fill="x", pady=(0, 8))
        
        preset_names = list(self.preset_manager.presets.keys())
        if self._is_touchscreen_mode():
            preset_names = preset_names[:4]  # Show first 4 on touchscreen
        
        # Create comfortable button layout
        for i, name in enumerate(preset_names):
            btn = ttk.Button(presets_frame, text=name, style="Compact.TButton",
                           command=lambda n=name: self._apply_preset(n))
            btn.pack(fill="x", pady=2)

        # Edit presets button
        edit_btn = ttk.Button(controls_frame, text="Edit Presets", style="TButton",
                            command=self._show_preset_editor)
        edit_btn.pack(fill="x", pady=(8, 0))

        # Quit button at bottom of controls
        quit_btn = ttk.Button(controls_frame, text="Quit", style="TButton", command=self._quit_app)
        quit_btn.pack(side="bottom", pady=(10, 0))

        # ---------------- Frequency response plot (50% width but still large) ----------------
        plot_container = ttk.Frame(graph_frame)
        plot_container.pack(fill="both", expand=True)

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

    def _is_touchscreen_mode(self):
        """Detect if we're running on the touchscreen (small resolution)"""
        return self.winfo_screenwidth() <= 800 or self.winfo_screenheight() <= 480

    def _on_escape(self, event=None):
        """Handle Escape key - exit fullscreen on touchscreen, close on laptop"""
        if self._is_touchscreen_mode():
            self.attributes('-fullscreen', False)
            self.geometry("800x480")
        else:
            self.destroy()

    # ------------- Preset System -------------
    def _apply_preset(self, name):
        """Apply preset values to sliders"""
        preset = self.preset_manager.presets.get(name)
        if preset:
            self.cf_slider.set(preset["cf"])
            self.bw_slider.set(preset["bw"])
            self._apply_cf(preset["cf"])
            self._apply_bw(preset["bw"])
            self._schedule_plot()

    def _show_preset_editor(self):
        """Popup window to edit presets"""
        editor = tk.Toplevel(self)
        editor.title("Edit Presets")
        editor.geometry("500x400")
        
        # Make it modal
        editor.transient(self)
        editor.grab_set()
        
        # Preset list with scrollbar
        frame = ttk.Frame(editor)
        frame.pack(fill="both", expand=True, padx=10, pady=10)
        
        canvas = tk.Canvas(frame)
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        for i, (name, values) in enumerate(self.preset_manager.presets.items()):
            row = ttk.Frame(scrollable_frame)
            row.pack(fill="x", pady=4)
            
            ttk.Label(row, text=name, width=15).pack(side="left")
            ttk.Label(row, text="CF:").pack(side="left", padx=(10, 2))
            cf_var = tk.IntVar(value=values["cf"])
            ttk.Entry(row, textvariable=cf_var, width=6).pack(side="left")
            
            ttk.Label(row, text="BW:").pack(side="left", padx=(10, 2))
            bw_var = tk.IntVar(value=values["bw"])
            ttk.Entry(row, textvariable=bw_var, width=6).pack(side="left")
            
            ttk.Button(row, text="Update", 
                      command=lambda n=name, c=cf_var, b=bw_var: 
                      self._update_preset(n, c.get(), b.get())).pack(side="right")
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        ttk.Button(editor, text="Close", command=editor.destroy).pack(pady=10)

    def _update_preset(self, name, cf, bw):
        """Update a preset with new values"""
        self.preset_manager.presets[name] = {"cf": cf, "bw": bw}

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
                self.hw.set_bandwidth(hz)
                used = True
            except Exception:
                used = False
        if not used and hasattr(self.hw, "set_bandwidth_mode"):
            mode = "narrow" if hz < 900 else ("medium" if hz < 1800 else "wide")
            try:
                self.hw.set_bandwidth_mode(mode)
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
            self.level_led.start_flash(interval=300)
        else:
            self.level_led.stop_flash()

    def _on_level_update(self, level_pct: float):
        overload = level_pct >= 0.90
        self.set_overload(overload)

    # ---------------- Improved Filter with Butterworth ----------------
    def _butterworth_response(self, f0, bw, order=4):
        """Calculate Butterworth bandpass filter response"""
        try:
            nyquist = 4000
            low = max(20, f0 - bw/2) / nyquist
            high = min(nyquist-1, f0 + bw/2) / nyquist
            
            if low >= high:
                freqs = np.linspace(self._fmin, self._fmax, 600)
                return freqs, np.ones_like(freqs)
                
            b, a = scipy.signal.butter(order, [low, high], btype='band')
            w, h = scipy.signal.freqz(b, a, worN=8000)
            freqs = w * nyquist / np.pi
            mag = np.abs(h)
            
            return freqs, mag
        except Exception:
            # Fallback to Gaussian
            return self._gaussian_fallback(f0, bw)

    def _gaussian_fallback(self, f0, bw):
        """Fallback filter response"""
        freqs = np.linspace(self._fmin, self._fmax, 600)
        mag = np.exp(-((freqs - f0) / (bw/2))**2)
        return freqs, mag

    # ---------------- Frequency response plotting with cursors ----------------
    def _schedule_plot(self):
        if self._plot_after_id:
            self.after_cancel(self._plot_after_id)
        self._plot_after_id = self.after(80, self._update_plot)

    def _init_mpl_plot(self, parent: tk.Widget):
        self._fmin, self._fmax = 50, 4000
        # Balanced figure sizes for 50/50 layout
        if self._is_touchscreen_mode():
            figsize = (6, 4.5)  # Good balance for touchscreen
        else:
            figsize = (7, 5.5)  # Good balance for laptop
            
        self._fig = Figure(figsize=figsize, dpi=80)
        self._ax = self._fig.add_subplot(111)
        self._ax.set_xlabel("Frequency (Hz)", fontsize=12)
        self._ax.set_ylabel("Gain (dB)", fontsize=12)
        self._ax.set_xlim(self._fmin, self._fmax)
        self._ax.set_ylim(-60, 5)
        self._ax.grid(True, which="both", linestyle=":", linewidth=0.7)
        self._ax.tick_params(axis='both', which='major', labelsize=11)
        self._line, = self._ax.plot([], [], linewidth=2.5)
        
        # Add cursors and labels
        self.cf_cursor = self._ax.axvline(x=750, color='red', linestyle='--', alpha=0.8, linewidth=2)
        self.bw_low_cursor = self._ax.axvline(x=600, color='orange', linestyle=':', alpha=0.7, linewidth=1.5)
        self.bw_high_cursor = self._ax.axvline(x=900, color='orange', linestyle=':', alpha=0.7, linewidth=1.5)
        
        self.cf_text = self._ax.text(0.02, 0.98, 'CF: 750 Hz', transform=self._ax.transAxes, 
                                    verticalalignment='top', fontsize=12, 
                                    bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.9))
        self.bw_text = self._ax.text(0.02, 0.85, 'BW: 300 Hz', transform=self._ax.transAxes,
                                    verticalalignment='top', fontsize=11, 
                                    bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.9))

        self._canvas = FigureCanvasTkAgg(self._fig, master=parent)
        self._canvas.draw()
        self._canvas.get_tk_widget().pack(fill="both", expand=True)

    def _update_cursors(self, f0, bw):
        """Update cursor positions and labels"""
        low_freq = max(300, f0 - bw/2)
        high_freq = min(3000, f0 + bw/2)
        
        self.cf_cursor.set_xdata([f0, f0])
        self.bw_low_cursor.set_xdata([low_freq, low_freq])
        self.bw_high_cursor.set_xdata([high_freq, high_freq])
        
        self.cf_text.set_text(f'CF: {f0} Hz')
        self.bw_text.set_text(f'BW: {bw} Hz\nRange: {low_freq:.0f}-{high_freq:.0f} Hz')

    def _update_plot(self):
        f0 = float(self.cf_var.get())
        bw = float(self.bw_var.get())
        vol = float(self.vol_var.get()) / 100.0
        
        try:
            if scipy is not None and np is not None:
                freqs, mags = self._butterworth_response(f0, bw)
                db = 20.0 * np.log10(np.clip(mags * vol, 1e-6, None))
            else:
                # Fallback to original method
                freqs = np.linspace(self._fmin, self._fmax, 600)
                mags = np.array([self._bp_mag(float(f), f0, bw) for f in freqs]) * max(1e-6, vol)
                db = 20.0 * np.log10(np.clip(mags, 1e-6, None))
            
            if self._use_mpl:
                self._line.set_data(freqs, db)
                self._update_cursors(f0, bw)
                self._ax.set_xlim(self._fmin, self._fmax)
                self._ax.set_ylim(-60, 5)
                self._canvas.draw_idle()
            else:
                self._draw_tk_curve(freqs.tolist(), db.tolist())
        except Exception as e:
            print(f"Plot error: {e}")

    def _bp_mag(self, f: float, f0: float, bw: float) -> float:
        """Original bandpass magnitude (fallback)"""
        if f <= 0 or f0 <= 0 or bw <= 0:
            return 0.0
        Q = max(1e-6, f0 / bw)
        x = f / f0
        num = x / Q
        den = math.sqrt((1 - x * x) ** 2 + (x / Q) ** 2)
        m = num / den if den > 0 else 0.0
        return max(0.0, m)

    # ---- Tk-only plotting helpers ----
    def _init_tk_plot(self, parent: tk.Widget):
        self._fmin, self._fmax = 50, 4000
        self._ymin_db, self._ymax_db = -60, 0
        self._plot_pad = 36
        self._tkc = tk.Canvas(parent, bg="#eee", highlightthickness=0)
        self._tkc.pack(fill="both", expand=True)
        self._tkc.bind("<Configure>", lambda e: self._draw_tk_axes())

    def _draw_tk_axes(self):
        if not hasattr(self, "_tkc"):
            return
        c = self._tkc
        c.delete("axes")
        w = c.winfo_width()
        h = c.winfo_height()
        pad = self._plot_pad
        c.create_rectangle(pad, pad, w - pad, h - pad, outline="#444", tags="axes")
        for frac in (0.25, 0.5, 0.75):
            x = pad + frac * (w - 2 * pad)
            c.create_line(x, pad, x, h - pad, fill="#ccc", dash=(2, 2), tags="axes")
        for frac in (0.25, 0.5, 0.75):
            y = pad + frac * (h - 2 * pad)
            c.create_line(pad, y, w - pad, y, fill="#ccc", dash=(2, 2), tags="axes")
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

    # ---------------- Dev helper: quit ----------------
    def _quit_app(self):
        """Close the GUI window (useful during development)."""
        try:
            self.destroy()
        except Exception:
            pass