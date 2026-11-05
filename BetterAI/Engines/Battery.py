"""
Low battery warning: on battery at 15% and again at 7%, Aria says so (and wakes up to say it).
Reads /sys/class/power_supply directly, every minute.
"""

import glob
import threading
import time

LEVELS = (15, 7)
CHECK_EVERY_S = 60


def read_battery(root="/sys/class/power_supply"):
    """(percent, status) of the first battery, or None if there isn't one."""
    for bat in sorted(glob.glob(f"{root}/BAT*")):
        try:
            with open(f"{bat}/capacity") as f:
                pct = int(f.read().strip())
            with open(f"{bat}/status") as f:
                status = f.read().strip()
            return pct, status
        except (OSError, ValueError):
            continue
    return None


class BatteryWatch:
    def __init__(self, say, read=read_battery):
        self.say = say               # fn(text): Aria announces it
        self.read = read
        self.warned = set()

    def check(self):
        state = self.read()
        if not state:
            return None
        pct, status = state
        if status != "Discharging":
            self.warned.clear()      # plugged in: warn again next time
            return None
        for level in sorted(LEVELS):
            if pct <= level and level not in self.warned:
                self.warned.update(l for l in LEVELS if l >= level)
                text = (f"Battery's at {pct} percent, you might want to plug me in." if level > min(LEVELS)
                        else f"Battery's almost empty, {pct} percent. Plug in soon or save your work.")
                self.say(text)
                return text
        return None

    def start(self):
        def loop():
            while True:
                try:
                    self.check()
                except Exception as e:
                    print(f"[Battery] {e}")
                time.sleep(CHECK_EVERY_S)
        threading.Thread(target=loop, daemon=True).start()
