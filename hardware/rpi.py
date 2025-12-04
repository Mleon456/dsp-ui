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
import sys
import time
import RPi.GPIO as GPIO
import spidev

# Fill in with real GPIO/SPI/I2C logic
class RPiHW(HardwareController):
    
    ENC_A = 17      # to RC6
    ENC_B = 27      # to RC7
    BUTTON = 22     # to RB7 (mode toggle button)
    LED_BW = 25     # to RB13 (bandwidth mode LED output) — input
    LED_CF = 24     # to RA7 (centre freq LED output) — input
    LED_OVER = 23   # overdrive LED
    BYPASS = 26     # GPIO for bypass switch

    # Gray code sequence for one detent step (CW)
    GRAY_SEQ = [
        (0, 0),
        (0, 1),
        (1, 1),
        (1, 0),
    ]
    def __init__(self) -> None:
        self._level_cb: LevelCallback | None = None
        

        # Setup encoder pins as outputs
        GPIO.setup(self.ENC_A, GPIO.OUT, initial=GPIO.LOW)
        GPIO.setup(self.ENC_B, GPIO.OUT, initial=GPIO.LOW)

        # Setup button pin as output (simulate press)
        GPIO.setup(self.BUTTON, GPIO.OUT, initial=GPIO.HIGH)

        # LED mode pins as inputs
        GPIO.setup(self.LED_BW, GPIO.IN)
        GPIO.setup(self.LED_CF, GPIO.IN)
        GPIO.setup(self.LED_OVER, GPIO.IN)

        # Bypass pin
        GPIO.setup(self.BYPASS, GPIO.OUT, initial=GPIO.LOW)
        self.bypass_state = False

        # SPI (MCP41010 digital potentiometer)
        self.spi = spidev.SpiDev()
        self.spi.open(0, 0)  # /dev/spidev0.0
        self.spi.max_speed_hz = 1_000_000
        self.spi.mode = 0
        self.volume = 128  # Default volume midpoint (0–255)

        # Track internal values
        self.mode = "centre"
        self.center_freq = 1500
        self.bandwidth = 2400


    # Called whenever the CF slider is moved
    def set_center_frequency(self, target_freq):
        target = max(200, min(3500, target_freq))
        if self.mode != "centre":
            self.toggle_mode()

        while self.center_freq != target:
            direction = "CW" if target > self.center_freq else "CCW"
            self.step(direction, detents=1)
            time.sleep(0.01)
    
    def set_bandwidth(self, target_bw):
        target = max(200, min(3500, target_bw))
        if self.mode != "bandwidth":
            self.toggle_mode()

        while self.bandwidth != target:
            direction = "CW" if target > self.bandwidth else "CCW"
            self.step(direction, detents=1)
            time.sleep(0.01)


    # Called when user flips the DSP toggle
    def set_bypass(self, on: bool) -> None:
        self.bypass_state = state
        GPIO.output(self.BYPASS, GPIO.HIGH if state else GPIO.LOW)
        print(f"Bypass {'ENABLED' if state else 'DISABLED'}.")
        pass
    def toggle_bypass(self):
        self.set_bypass(not self.bypass_state)
    # Called when the Volume slider is adjusted. 
    # Could map 0-100% to a DAC (0-3.3 V)
    def set_wiper(self, value):
        """Low-level MCP41010 write (0–255)."""
        value = max(0, min(255, value))
        cmd = 0x11  # Write to wiper 0
        self.spi.xfer2([cmd, value])
        self.volume = value
        print(f"Volume set to {value}/255")


    def set_volume(self, pct: float) -> None:
        self.set_wiper(value)
        pass


    
    def toggle_mode(self):

        # Press button (active low)
        GPIO.output(self.BUTTON, GPIO.LOW)
        time.sleep(0.1)
        GPIO.output(self.BUTTON, GPIO.HIGH)

        # Allow time for LEDs
        time.sleep(0.05)

        cf = GPIO.input(self.LED_CF)
        bw = GPIO.input(self.LED_BW)

        if cf == 1 and bw == 0:
            self.mode = "centre"
        elif cf == 0 and bw == 1:
            self.mode = "bandwidth"
        else:
            print("Warning: LED mode state invalid, keeping previous mode.")
            return

        print(f"Mode toggled — hardware reports mode = {self.mode}")
    # Feeds the GUI's signal meter
    def step_once(self, direction="CW", delay=0.005):
        if direction == "CW":
            seq = self.GRAY_SEQ
        else:
            seq = list(reversed(self.GRAY_SEQ))

        for (a, b) in seq:
            GPIO.output(self.ENC_A, a)
            GPIO.output(self.ENC_B, b)
            time.sleep(delay)
    def step(self, direction="CW", detents=1):
        for _ in range(detents):
            self.step_once(direction)

        if self.mode == "centre":
            self._update_center(direction, detents)
        else:
            self._update_bandwidth(direction, detents)
    def _update_center(self, direction, detents):
        step_size = 25 if self.center_freq < 2000 else 50
        delta = detents * step_size * (1 if direction == "CW" else -1)
        new_cf = max(200, min(3500, self.center_freq + delta))
        self.center_freq = new_cf
        print(f"Center frequency now: {self.center_freq} Hz")

    def _update_bandwidth(self, direction, detents):
        bw = self.bandwidth
        if bw < 400:
            step_size = 20
        elif bw < 700:
            step_size = 50
        else:
            step_size = 100

        delta = detents * step_size * (1 if direction == "CW" else -1)
        new_bw = max(200, min(3500, bw + delta))
        self.bandwidth = new_bw
        print(f"Bandwidth now: {self.bandwidth} Hz")

    def set_level_callback(self, cb: LevelCallback) -> None:
        self._level_cb = cb
        # TODO: start ADC polling thread and call cb(level_pct)
