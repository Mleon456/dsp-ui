from typing import Protocol, Callable

LevelCallback = Callable[[float], None]

class HardwareController(Protocol):
    def set_center_frequency(self, hz: int) -> None: ...
    def set_bandwidth_mode(self, mode: str) -> None: ...        # "Narrow" | "Wide"
    def set_bypass(self, on: bool) -> None: ...                 # True=ON, False=BYPASS
    def set_volume(self, pct: float) -> None: ...               # 0..100
    def set_multi(self, pct: float) -> None: ...                # 0..100
    def set_level_callback(self, cb: LevelCallback) -> None: ...
