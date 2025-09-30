import math, threading, time
from .base import HardwareController, LevelCallback

class MockHW(HardwareController):
    def __init__(self) -> None:
        self._cb: LevelCallback | None = None
        self._stop = False
        threading.Thread(target=self._pump, daemon=True).start()

    def set_center_frequency(self, hz: int) -> None: print(f"[MOCK] CF {hz}")
    def set_bandwidth_mode(self, mode: str) -> None: print(f"[MOCK] BW {mode}")
    def set_bypass(self, on: bool) -> None: print(f"[MOCK] DSP {'ON' if on else 'BYPASS'}")
    def set_volume(self, pct: float) -> None: print(f"[MOCK] VOL {pct:.1f}")
    def set_multi(self, pct: float) -> None: print(f"[MOCK] MULTI {pct:.1f}")

    def set_level_callback(self, cb: LevelCallback) -> None:
        self._cb = cb

    def _pump(self):
        # fake a sine-wave level so the meter moves
        while not self._stop:
            if self._cb:
                t = time.time()
                self._cb(50 + 45 * math.sin(1.6 * t))
            time.sleep(0.10)
