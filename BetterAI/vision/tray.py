import threading

import pystray
from PIL import Image, ImageDraw

class AriaTray:
    def __init__(self, on_show, on_quit):
        self.on_show = on_show
        self.on_quit = on_quit
        self._icon   = None

    def start(self):
        # Draw a simple icon
        img  = Image.new("RGB", (64, 64), color=(20, 10, 40))
        draw = ImageDraw.Draw(img)
        draw.ellipse([16,16,48,48], fill=(180, 100, 255))

        menu = pystray.Menu(
            pystray.MenuItem("Open Aria", self.on_show, default=True),
            pystray.MenuItem("Quit",      self.on_quit),
        )
        self._icon = pystray.Icon("Aria", img, "Aria", menu)
        threading.Thread(target=self._icon.run, daemon=True).start()

    def stop(self):
        if self._icon:
            self._icon.stop()