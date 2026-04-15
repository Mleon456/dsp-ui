from eventbus import EventBus
from gui.app import DSPGui
#from hardware.rpi import RPiHW
from hardware.mock import MockHW  # swap to: from hardware.rpi import RPiHW

if __name__ == "__main__":
    bus = EventBus()
    hw = MockHW()  # RPiHW or MockHW
    app = DSPGui(hw, bus)  
    app.mainloop()