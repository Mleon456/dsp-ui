# gui/app.py
from __future__ import annotations
import sys
import math
import tkinter as tk
from tkinter import ttk
from typing import Optional, Callable
import os

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


# --- Slider with attached value display + arrow nudges ---
class ArrowButton(tk.Canvas):
    """Minimal, crisp arrow button drawn on a canvas."""
    def __init__(self, master, direction="left", command=None, size=20, **kw):
        super().__init__(master, width=size, height=size,
                         highlightthickness=0, bd=0, **kw)

        # Default background from theme-safe lookup
        try:
            style = ttk.Style()
            bg = style.lookup("TFrame", "background") or "#f0f0f0"
        except Exception:
            bg = "#f0f0f0"
        self.configure(background=bg)

        self._size = size
        self._dir = direction  # "left" or "right"
        self._cmd = command
        self._enabled = True

        # Colors
        self._fg_normal   = "#2b2b2b"
        self._fg_hover    = "#000000"
        self._fg_disabled = "#a9a9a9"

        self.configure(cursor="hand2")
        self._tri = None
        self._draw(self._fg_normal)

        # Events
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)

    def _triangle_points(self):
        s = self._size
        pad = max(2, int(s * 0.18))
        mid = s // 2
        if self._dir == "left":
            return (s - pad, pad, pad, mid, s - pad, s - pad)
        else:
            return (pad, pad, s - pad, mid, pad, s - pad)

    def _draw(self, color):
        if self._tri is not None:
            self.delete(self._tri)
        pts = self._triangle_points()
        self._tri = self.create_polygon(*pts, fill=color, outline="")
        # optional transparent hit box
        self.create_rectangle(0, 0, self._size, self._size, outline="", width=0)

    def _on_enter(self, _):
        if self._enabled:
            self._draw(self._fg_hover)

    def _on_leave(self, _):
        if self._enabled:
            self._draw(self._fg_normal)

    def _on_press(self, _):
        if not self._enabled:
            return
        self._draw(self._fg_hover)
        if callable(self._cmd):
            self.after(0, self._cmd)

    def _on_release(self, _):
        if self._enabled:
            self._draw(self._fg_hover)

    def set_state(self, enabled: bool):
        self._enabled = enabled
        self.configure(cursor="hand2" if enabled else "")
        self._draw(self._fg_normal if enabled else self._fg_disabled)

class ValueSlider(ttk.Frame):
    def __init__(self, master, label, from_, to, command, unit="Hz", is_percent=False, **kw):
        super().__init__(master, **kw)
        self.from_ = from_
        self.to = to
        self.command = command
        self.unit = unit
        self.is_percent = is_percent

        # Step used by arrow buttons (keeps existing behavior: Hz snaps to 25)
        self.step = 25 if not is_percent else 1

        # Main variable
        self.var = tk.IntVar(value=from_)

        # Build UI
        self._create_slider_with_display(label)

        # Bind variable changes
        self.var.trace_add("write", self._on_value_change)

    def _create_slider_with_display(self, label):
        # Top row: Label and value display
        top_row = ttk.Frame(self)
        top_row.pack(fill="x", pady=(0, 4))
        
        ttk.Label(top_row, text=label, style="Compact.TLabel").pack(side="left")

        max_text = f"{self.to} {self.unit}"
        disp_chars = max(8, len(max_text) + 1)

        self.value_display = ttk.Label(
            top_row,
            text="", 
            style="ValueDisplay.TLabel", 
            width=disp_chars, 
            anchor="center"
        )
        self.value_display.pack(side="right")

        # Arrow row (clean custom arrows)
        arrow_row = ttk.Frame(self)
        arrow_row.pack(fill="x", pady=(0, 2))
        
        self.left_btn = ArrowButton(
            arrow_row, direction="left", size=20, command=lambda: self._nudge(-self.step)
            )
        self.left_btn.pack(side="left")
        
        ttk.Label(arrow_row, text="").pack(side="left", expand=True)  # spacer
        
        self.right_btn = ArrowButton(
            arrow_row, direction="right", size=20, command=lambda: self._nudge(+self.step)
            )
        self.right_btn.pack(side="right")


        # Slider row with range labels (unchanged)
        slider_row = ttk.Frame(self)
        slider_row.pack(fill="x", pady=(0, 2))

        # Compute safe widths from the actual strings (prevents DPI truncation)
        left_txt  = f"{self.from_} {self.unit}"   # e.g., "300 Hz"
        right_txt = f"{self.to} {self.unit}"      # e.g., "3000 Hz"
        left_chars  = max(7, len(left_txt)  + 1)  # breathing room
        right_chars = max(7, len(right_txt) + 1)

        # Left range label (anchor west so it hugs the slider nicely)
        self.range_start = ttk.Label(
            slider_row, text=left_txt, style="Range.TLabel",
            width=left_chars, anchor="w", padding=(2, 0)
            )
        self.range_start.pack(side="left", padx=(0, 5))
        
        # Slider (expands to fill the middle)
        self.scale = ttk.Scale(
            slider_row, from_=self.from_, to=self.to,
            orient="horizontal", variable=self.var, command=self._on_slide
            )
        self.scale.pack(side="left", fill="x", expand=True)
        
        # Right range label (anchor east)
        self.range_end = ttk.Label(
            slider_row, text=right_txt, style="Range.TLabel",
            width=right_chars, anchor="e", padding=(2, 0)
            )
        self.range_end.pack(side="left", padx=(5, 0))

        
      

    def _nudge(self, delta: int):
        """Move value by a small step, clamped to range."""
        v = int(self.var.get())
        v = max(self.from_, min(self.to, v + delta))
        # Keep existing snap for frequency sliders
        if not self.is_percent:
            v = round(v / 25) * 25
        self.var.set(v)  # triggers _on_value_change -> your command

    def _on_slide(self, value):
        # Live display while dragging; keep the same 25 Hz snap visual for Hz
        current_val = int(float(value))
        if not self.is_percent:
            current_val = round(current_val / 25) * 25
        self._update_display(current_val)

    def _on_value_change(self, *args):
        current_val = self.var.get()
        self._update_display(current_val)
        if self.command:
            self.command(str(current_val))

    def _update_display(self, value):
        display_text = f"{value} {self.unit}"
        self.value_display.configure(text=display_text)
        if not self.is_percent:
            if value <= 500:
                self.value_display.configure(foreground="#FF6B6B")
            elif value >= 2500:
                self.value_display.configure(foreground="#4ECDC4")
            else:
                self.value_display.configure(foreground="#2E86AB")

    def get(self):
        return self.var.get()

    def set(self, value):
        self.var.set(value)

    def set_state(self, enabled: bool):
        """Enable/disable slider + arrow buttons (keeps your DSP/BYPASS behavior)."""
        state = "normal" if enabled else "disabled"
        self.scale.configure(state=state)
        # update arrow visuals
        self.left_btn.set_state(enabled)
        self.right_btn.set_state(enabled)

        if not enabled:
            self.value_display.configure(foreground="#666666", background="#e0e0e0")
            self.range_start.configure(foreground="#999999")
            self.range_end.configure(foreground="#999999")
        else:
            value = self.var.get()
            if not self.is_percent:
                if value <= 500:
                    self.value_display.configure(foreground="#FF6B6B", background="#2c2c2c")
                elif value >= 2500:
                    self.value_display.configure(foreground="#4ECDC4", background="#2c2c2c")
                else:
                    self.value_display.configure(foreground="#2E86AB", background="#2c2c2c")
            self.range_start.configure(foreground="#666666")
            self.range_end.configure(foreground="#666666")



class PresetManager:
    def __init__(self):
        # Enhanced preset system with auto-save capability
        self.presets = {
            "Custom 1": {"cf": 1000, "bw": 500, "vol": 60},
            "Custom 2": {"cf": 1500, "bw": 800, "vol": 60},
            "Custom 3": {"cf": 2000, "bw": 600, "vol": 60}
        }
    
    def save_current_settings(self, preset_name: str, cf: int, bw: int, vol: int):
        """Save current GUI settings to a preset"""
        self.presets[preset_name] = {"cf": cf, "bw": bw, "vol": vol}
    
    def get_preset(self, preset_name: str):
        """Get preset values"""
        return self.presets.get(preset_name)




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
        
        
        
        # Dynamic font sizing based on screen size
        if self._is_touchscreen_mode():
            # Smaller for touchscreen
            font_size = 9
            title_font_size = 16
            plot_figsize = (5, 3.5)
        else:
            # Larger for laptop  
            font_size = 11
            title_font_size = 20
            plot_figsize = (7, 5.5)

        # Store plot size for later use
        self.plot_figsize = plot_figsize

        # Apply styles
        style.configure("Title.TLabel", font=("Segoe UI", title_font_size, "bold"))
        style.configure("Big.TLabel", font=("Segoe UI", font_size))
        style.configure("Compact.TLabel", font=("Segoe UI", font_size-1), padding=(0,2))
        style.configure("Range.TLabel", font=("Segoe UI", font_size-1),
                foreground="#666666", padding=(2, 1))
        style.configure("ValueDisplay.TLabel",
                        font=("Segoe UI", font_size, "bold"), 
                       background="#2c2c2c", 
                       foreground="white", 
                       relief="raised", 
                       borderwidth=1, 
                       padding=(6, 3),
                       )
        # New style for disabled state
        style.configure("Disabled.TLabel", foreground="#999999")
        style.configure("Disabled.TButton", foreground="#999999")

        if self._is_touchscreen_mode():
            style.configure("TButton", padding=(8, 5))
            style.configure("Compact.TButton", padding=(6, 3))
            style.configure("Preset.TButton", padding=(4, 2), font=("Segoe UI", 8))
        else:
            style.configure("TButton", padding=(8, 5))
            style.configure("Compact.TButton", padding=(6, 4))
            style.configure("Preset.TButton", padding=(5, 3), font=("Segoe UI", 9))

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

        # LEVEL row with DSP/BYPASS toggle integrated - FIXED POSITIONS
        level_row = ttk.Frame(controls_frame)
        level_row.pack(fill="x", pady=(4, 12), ipady=2)
        
        ttk.Label(level_row, text="Level", style="Big.TLabel").pack(side="left")
        self.level_led = Led(level_row, size=16)
        self.level_led.pack(side="left", padx=(8, 0))
        
        # Add spacer between LED and DSP/BYPASS toggle
        ttk.Label(level_row, text="", width=4).pack(side="left")
        
        # DSP/BYPASS toggle integrated in LEVEL row - SWAPPED POSITIONS
        # BYPASS on left, toggle in middle, DSP on right
        self.bypass_label = ttk.Label(level_row, text="BYPASS", style="Big.TLabel")
        self.bypass_label.pack(side="left", padx=(0, 8), pady=2)
        self.bypass_switch = ToggleSwitch(level_row, width=60, height=28)
        self.bypass_switch.pack(side="left", pady=2)
        self.bypass_switch.set(False)  # Start with BYPASS off (DSP on)
        self.bypass_switch.on_toggle = self._on_dsp_toggled
        self.dsp_label = ttk.Label(level_row, text="DSP", style="Big.TLabel")
        self.dsp_label.pack(side="left", padx=(12, 0), pady=2)

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

        # Volume row
        vol_frame = ttk.Frame(controls_frame)
        vol_frame.pack(fill="x", pady=(8, 2))
        self.vol_slider = ValueSlider(vol_frame, "Volume", 0, 100, 
                                    self._on_vol_change, "%", is_percent=True)
        self.vol_slider.pack(fill="x")
        self.vol_var = self.vol_slider.var

        # ---------------- PRESETS SECTION ----------------
        presets_label = ttk.Label(controls_frame, text="PRESETS", style="Big.TLabel")
        presets_label.pack(anchor="w", pady=(20, 8))

        # Preset bank with compact layout
        presets_frame = ttk.Frame(controls_frame)
        presets_frame.pack(fill="x", pady=(0, 8))

        # Initialize preset_slots BEFORE using it
        self.preset_slots = {}

        # Create preset slots - fewer on touchscreen
        preset_names = list(self.preset_manager.presets.keys())

        # Use smaller buttons on touchscreen
        button_style = "Preset.TButton" if self._is_touchscreen_mode() else "TButton"

        for name in preset_names:
            slot_frame = ttk.Frame(presets_frame)
            slot_frame.pack(fill="x", pady=2)  # Reduced padding
            
            # Preset name label - fixed width for alignment
            name_label = ttk.Label(slot_frame, text=name, style="Compact.TLabel", 
                                  width=10 if self._is_touchscreen_mode() else 12, 
                                  anchor="w")
            name_label.pack(side="left", padx=(0, 5))
            
            # Button container to keep Load/Save/Edit together
            button_frame = ttk.Frame(slot_frame)
            button_frame.pack(side="left", fill="x", expand=True)
            
            # Load button
            load_btn = ttk.Button(button_frame, text="Load", style=button_style, 
                                 width=5 if self._is_touchscreen_mode() else 6,
                                 command=lambda n=name: self._apply_preset(n))
            load_btn.pack(side="left", padx=(0, 5))
            
            # Save button (NEW)
            save_btn = ttk.Button(button_frame, text="Save", style=button_style,
                                 width=5 if self._is_touchscreen_mode() else 6,
                                 command=lambda n=name: self._save_preset(n))
            save_btn.pack(side="left", padx=(0, 5))
            
            # Edit button
            edit_btn = ttk.Button(button_frame, text="Edit", style=button_style,
                                 width=5 if self._is_touchscreen_mode() else 6,
                                 command=lambda n=name: self._edit_preset(n))
            edit_btn.pack(side="left")
            
            # Store in preset_slots dictionary
            self.preset_slots[name] = {
                "frame": slot_frame,
                "name_label": name_label,
                "load_btn": load_btn,
                "save_btn": save_btn,
                "edit_btn": edit_btn
            }

        # Edit all presets button - make sure it's visible
        edit_all_btn = ttk.Button(controls_frame, text="Edit All Presets", style="TButton",
                                command=self._show_preset_editor)
        edit_all_btn.pack(fill="x", pady=(12, 0))

        # Quit button at bottom of controls - make sure it's visible
        quit_btn = ttk.Button(controls_frame, text="Quit", style="TButton", command=self._quit_app)
        quit_btn.pack(side="bottom", pady=(15, 0), fill="x")

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

        # Initial state update for DSP/BYPASS
        self._update_dsp_bypass_state(True)  # Start with DSP on

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
        """Better detection for small touchscreen displays"""
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        # Common small touchscreen resolutions
        small_screens = [(800, 480), (1024, 600), (1280, 720)]
        return (screen_width, screen_height) in small_screens or screen_width <= 1024

    def _on_escape(self, event=None):
        """Handle Escape key - exit fullscreen on touchscreen, close on laptop"""
        if self._is_touchscreen_mode():
            self.attributes('-fullscreen', False)
            self.geometry("800x480")
        else:
            self.destroy()

    # ------------- Enhanced Preset System with Save Functionality -------------
    def _save_preset(self, name):
        """Save current GUI settings to a preset"""
        
        current_cf = self.cf_var.get()
        current_bw = self.bw_var.get()
        current_vol = self.vol_var.get()
        
        self.preset_manager.save_current_settings(name, current_cf, current_bw, current_vol)
        
        # Provide visual feedback
        original_text = self.preset_slots[name]["name_label"].cget("text")
        self.preset_slots[name]["name_label"].configure(text="✓ " + original_text)
        self.after(1000, lambda: self.preset_slots[name]["name_label"].configure(text=original_text))

    def _apply_preset(self, name):
        """Apply preset values to sliders"""
        preset = self.preset_manager.get_preset(name)
        if preset:
            self.cf_slider.set(preset["cf"])
            self.bw_slider.set(preset["bw"])
            self.vol_slider.set(preset["vol"])
            self._apply_cf(preset["cf"])
            self._apply_bw(preset["bw"])
            self._apply_vol(preset["vol"] / 100.0)
            self._schedule_plot()

    def _edit_preset(self, name):
        """Quick edit for a single preset"""
        preset = self.preset_manager.get_preset(name)
        if preset:
            self._show_single_preset_editor(name, preset["cf"], preset["bw"])

    def _show_single_preset_editor(self, name, current_cf, current_bw):
        """Popup to edit a single preset including name"""
        editor = tk.Toplevel(self)
        editor.title(f"Edit {name}")
        editor.geometry("300x250")  # Slightly taller for name field
        editor.transient(self)
        editor.grab_set()
        
        ttk.Label(editor, text=f"Editing Preset", style="Big.TLabel").pack(pady=10)
        
        # Name input
        name_frame = ttk.Frame(editor)
        name_frame.pack(fill="x", pady=5, padx=20)
        ttk.Label(name_frame, text="Preset Name:").pack(side="left")
        name_var = tk.StringVar(value=name)
        name_entry = ttk.Entry(name_frame, textvariable=name_var, width=12)
        name_entry.pack(side="right")
        # CF input
        cf_frame = ttk.Frame(editor)
        cf_frame.pack(fill="x", pady=5, padx=20)
        ttk.Label(cf_frame, text="Center Freq (Hz):").pack(side="left")
        cf_var = tk.IntVar(value=current_cf)
        cf_entry = ttk.Entry(cf_frame, textvariable=cf_var, width=8)
        cf_entry.pack(side="right")
        
        # BW input
        bw_frame = ttk.Frame(editor)
        bw_frame.pack(fill="x", pady=5, padx=20)
        ttk.Label(bw_frame, text="Bandwidth (Hz):").pack(side="left")
        bw_var = tk.IntVar(value=current_bw)
        bw_entry = ttk.Entry(bw_frame, textvariable=bw_var, width=8)
        bw_entry.pack(side="right")
        
        def save_and_close():
            new_name = name_var.get()
            # If name changed, update the preset structure
            if new_name != name:
                # Remove old preset and create new one
                self.preset_manager.presets[new_name] = self.preset_manager.presets.pop(name)
                # Update the UI slot if needed
                self._update_preset_slot_name(name, new_name)
            
            # Update values
            self.preset_manager.presets[new_name] = {"cf": cf_var.get(), "bw": bw_var.get(), "vol": 60}
            editor.destroy()
        
        ttk.Button(editor, text="Save", command=save_and_close).pack(pady=10)

    def _update_preset_slot_name(self, old_name, new_name):
        """Update the preset slot display when a preset name changes"""
        if old_name in self.preset_slots:
            slot = self.preset_slots[old_name]
            slot["name_label"].configure(text=new_name)
            # Update the command references
            slot["load_btn"].configure(command=lambda: self._apply_preset(new_name))
            slot["save_btn"].configure(command=lambda: self._save_preset(new_name))
            slot["edit_btn"].configure(command=lambda: self._edit_preset(new_name))
            # Update the slots dictionary
            self.preset_slots[new_name] = self.preset_slots.pop(old_name)

    def _show_preset_editor(self):
        """Popup window to edit all presets including names"""
        editor = tk.Toplevel(self)
        editor.title("Edit All Presets")
        editor.geometry("500x350")  # Slightly wider for name fields
        
        # Make it modal
        editor.transient(self)
        editor.grab_set()
        
        ttk.Label(editor, text="Edit All Presets", style="Big.TLabel").pack(pady=10)
        
        # Preset editing area
        edit_frame = ttk.Frame(editor)
        edit_frame.pack(fill="both", expand=True, padx=20, pady=10)
        
        # Headers
        ttk.Label(edit_frame, text="Name", width=12).grid(row=0, column=0, sticky="w", pady=2)
        ttk.Label(edit_frame, text="CF (Hz)").grid(row=0, column=1, padx=5, pady=2)
        ttk.Label(edit_frame, text="BW (Hz)").grid(row=0, column=2, padx=5, pady=2)
        
        self.preset_vars = {}
        row = 1
        for name, values in self.preset_manager.presets.items():
            # Name entry
            name_var = tk.StringVar(value=name)
            name_entry = ttk.Entry(edit_frame, textvariable=name_var, width=12)
            name_entry.grid(row=row, column=0, padx=5, pady=2, sticky="w")
            
            # CF entry
            cf_var = tk.IntVar(value=values["cf"])
            cf_entry = ttk.Entry(edit_frame, textvariable=cf_var, width=6)
            cf_entry.grid(row=row, column=1, padx=5, pady=2)
            
            # BW entry
            bw_var = tk.IntVar(value=values["bw"])
            bw_entry = ttk.Entry(edit_frame, textvariable=bw_var, width=6)
            bw_entry.grid(row=row, column=2, padx=5, pady=2)
            
            self.preset_vars[name] = {"name": name_var, "cf": cf_var, "bw": bw_var}
            row += 1
        
        def save_all():
            new_presets = {}
            name_changes = {}
            
            # Collect all changes
            for old_name, vars in self.preset_vars.items():
                new_name = vars["name"].get()
                new_presets[new_name] = {
                    "cf": vars["cf"].get(), 
                    "bw": vars["bw"].get(),
                    "vol": 60  # Default volume
                }
                if new_name != old_name:
                    name_changes[old_name] = new_name
            
            # Update the preset manager
            self.preset_manager.presets = new_presets
            
            # Update UI for any name changes
            for old_name, new_name in name_changes.items():
                self._update_preset_slot_name(old_name, new_name)
            
            editor.destroy()
        
        ttk.Button(editor, text="Save All", command=save_all).pack(pady=10)

    # ---------------- DSP/BYPASS State Management ----------------
    def _on_dsp_toggled(self, dsp_on: bool):
        """Handle DSP/BYPASS toggle with visual state updates"""

        
        # The toggle switch returns True when DSP is active (toggle to the right)
        # and False when BYPASS is active (toggle to the left)
        self._apply_bypass(not dsp_on)  # Send bypass=True when DSP is off
        self._update_dsp_bypass_state(dsp_on)

    def _update_dsp_bypass_state(self, dsp_on: bool):
        """Update UI elements based on DSP/BYPASS state"""
        # Update slider states - enable sliders only in DSP mode
        self.cf_slider.set_state(dsp_on)
        self.bw_slider.set_state(dsp_on)
        self.vol_slider.set_state(dsp_on)
        
        # Update DSP/BYPASS label appearance
        if dsp_on:
            # DSP mode active - DSP label normal, BYPASS label greyed out
            self.dsp_label.configure(style="Big.TLabel")
            self.bypass_label.configure(style="Disabled.TLabel")
        else:
            # BYPASS mode active - BYPASS label normal, DSP label greyed out
            self.dsp_label.configure(style="Disabled.TLabel")
            self.bypass_label.configure(style="Big.TLabel")

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
        
        # Use dynamic figure size
        self._fig = Figure(figsize=self.plot_figsize, dpi=80)
        self._ax = self._fig.add_subplot(111)
        
        # Dynamic font sizing for plot
        font_size = 9 if self._is_touchscreen_mode() else 11
        self._ax.set_xlabel("Frequency (Hz)", fontsize=font_size)
        self._ax.set_ylabel("Gain (dB)", fontsize=font_size)
        self._ax.set_xlim(self._fmin, self._fmax)
        self._ax.set_ylim(-60, 5)
        self._ax.grid(True, which="both", linestyle=":", linewidth=0.7)
        self._ax.tick_params(axis='both', which='major', labelsize=font_size-1)
        self._line, = self._ax.plot([], [], linewidth=2.5)
        
        # Add cursors and labels
        self.cf_cursor = self._ax.axvline(x=750, color='red', linestyle='--', alpha=0.8, linewidth=2)
        self.bw_low_cursor = self._ax.axvline(x=600, color='orange', linestyle=':', alpha=0.7, linewidth=1.5)
        self.bw_high_cursor = self._ax.axvline(x=900, color='orange', linestyle=':', alpha=0.7, linewidth=1.5)
        
        text_font_size = 10 if self._is_touchscreen_mode() else 12
        self.cf_text = self._ax.text(0.02, 0.98, 'CF: 750 Hz', transform=self._ax.transAxes, 
                                    verticalalignment='top', fontsize=text_font_size, 
                                    bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.9))
        self.bw_text = self._ax.text(0.02, 0.85, 'BW: 300 Hz', transform=self._ax.transAxes,
                                    verticalalignment='top', fontsize=text_font_size-1, 
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