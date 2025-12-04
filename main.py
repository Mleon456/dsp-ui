from eventbus import EventBus
from gui.app import DSPGui
from hardware.rpi import RPiHW   # swap to: from hardware.rpi import RPiHW

if __name__ == "__main__":
    bus = EventBus()
    hw = RPiHW()  # replace with RPiHW() when ready
    app = DSPGui(hw, bus)  
    app.mainloop()