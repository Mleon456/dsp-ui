# Description:
# This class represents the hardware controller layer for our
# DSP filter system. It is a bridge layer between GUI events
# and hardware control. Each method responds to one GUI control. 
# The class will translate those calls in to real GPIO/I2C/SPI 
# commands to control the VBFM

# TODO:
# We need to decide:
#       * Which GPIO pins/ SPI/I2C channels map to CF, bandwidth, bypass, volume, etc.
#       * How to represent those values 
#           - raw binary codes? 
#           - percentages?
#           - register writes?
# GUI -> EventBus -> RPIHW -> hardware pins
from .base import HardwareController, LevelCallback

# Fill in with real GPIO/SPI/I2C logic
class RPiHW(HardwareController):
    def __init__(self) -> None:
        self._level_cb: LevelCallback | None = None
        # TODO: setup pins / buses
        # Example; 
        # import RPI.GPIO as GPIO
        # GPIO.setmode(GPIO.BCM)
        # GPIO.setup(17, GPIO.OUT) # for DSP enable pin
        # GPIO.setup(27, GPIO.OUT) # for bandwidth select


    # Called whenever the CF slider is moved
    def set_center_frequency(self, hz: int) -> None:
        # TODO: conver Hz to whatever the VBFM or filter IC expects
        pass

    # mode will be "Narrow" or "Wide"
    # Called whenever the user presses Narrow/Wide
    def set_bandwidth_mode(self, mode: str) -> None:
        # TODO: set the appropriate GPIO high/low
        # Example: GPIO.output(27, GPIO.HIGH if mode=="Wide" else GPIO.LOW)
        pass

    # Called when user flips the DSP toggle
    def set_bypass(self, on: bool) -> None:
        # TODO: drive a GPIO 
        pass

    # Called when the Volume slider is adjusted. 
    # Could map 0-100% to a DAC (0-3.3 V)
    def set_volume(self, pct: float) -> None:
        # TODO
        pass

    # Placeholder for multi
    # Question: What does multi do again? 
    def set_multi(self, pct: float) -> None:
        # TODO
        pass

    # Feeds the GUI's signal meter
    def set_level_callback(self, cb: LevelCallback) -> None:
        self._level_cb = cb
        # TODO: start ADC polling thread and call cb(level_pct)
