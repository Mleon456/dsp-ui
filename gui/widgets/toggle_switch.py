import tkinter as tk
from tkinter import ttk

class ToggleSwitch(ttk.Frame):
    def __init__(self, master=None, width=64, height=32, value=None, command=None, **kw):
        super().__init__(master, **kw)
        self.width, self.height = width, height
        self.radius, self.pad = height // 2, 2
        self.value = value or tk.BooleanVar(value=True)
        self.command = command
        self.on_toggle = None  # ← Add this attribute
        self.canvas = tk.Canvas(self, width=width, height=height, highlightthickness=0)
        self.canvas.pack()
        for seq in ("<Button-1>", "<space>", "<Return>"):
            self.canvas.bind(seq, self._on_click)
        self.canvas.configure(cursor="hand2")
        self._draw()

    def get(self) -> bool: 
        return bool(self.value.get())
    
    def set(self, state: bool):
        self.value.set(bool(state))
        self._draw()
        # Don't call callbacks when programmatically setting
        
    def toggle(self): 
        new_state = not self.get()
        self.value.set(new_state)
        self._draw()
        # Call callbacks when user toggles
        if self.command: 
            self.command()
        if callable(self.on_toggle):  # ← Call on_toggle if it exists
            self.on_toggle(new_state)
            
    def _on_click(self, _): 
        self.toggle()

    def _draw(self):
        c, w, h, r, p = self.canvas, self.width, self.height, self.radius, self.pad
        c.delete("all")
        on = self.value.get()
        track = "#34C759" if on else "#cfcfcf"
        # track (rounded)
        c.create_oval(p, p, p+2*r, p+2*r, fill=track, outline=track)
        c.create_oval(w-(p+2*r), p, w-p, p+2*r, fill=track, outline=track)
        c.create_rectangle(p+r, p, w-(p+r), p+2*r, fill=track, outline=track)
        # knob
        x0 = w-(p+2*r) if on else p
        c.create_oval(x0, p, x0+2*r, p+2*r, fill="#fff", outline="#b5b5b5")