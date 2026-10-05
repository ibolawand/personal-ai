import subprocess
import webbrowser
import os
from ctypes import cast, POINTER
from comtypes import CLSCTX_ALL
from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
from samsungtvws import SamsungTVWS


class PCEngine:
    def __init__(self,tv_ip=None):
        # App paths — adjust if yours are different

        self._init_volume()
        self.tv = SamsungTVWS(tv_ip) if tv_ip else None
        self.apps = {
            "pycharm": r"C:\Program Files\JetBrains\PyCharm Community Edition 2024.1\bin\pycharm64.exe",
            "vscode": r"C:\Users\lala\AppData\Local\Programs\Microsoft VS Code\Code.exe",
            "arduino": r"C:\Program Files\Arduino IDE\Arduino IDE.exe",
            "discord": r"C:\Users\lala\AppData\Local\Discord\Update.exe --processStart Discord.exe",
            "explorer": r"explorer.exe",
            "lmstudio": r"C:\Users\lala\AppData\Local\Programs\LM Studio\LM Studio.exe",
            "spotify": r"C:\Users\lala\AppData\Roaming\Spotify\Spotify.exe",
        }
        self._init_volume()

    def _init_volume(self):
        try:
            devices = AudioUtilities.GetSpeakers()
            interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            self.volume = cast(interface, POINTER(IAudioEndpointVolume))
        except Exception as e:
            print(f"[PC] Volume control unavailable: {e}")
            self.volume = None

    def open_app(self, app: str) -> str:
        app = app.lower().strip()

        # Check known apps
        for key, path in self.apps.items():
            if key in app:
                try:
                    subprocess.Popen(path, shell=True)
                    return f"Opening {key}."
                except Exception as e:
                    return f"Failed to open {key}: {e}"

        # Try opening as a generic command
        try:
            subprocess.Popen(app, shell=True)
            return f"Opening {app}."
        except Exception as e:
            return f"Couldn't open {app}: {e}"

    def open_browser(self, url: str = "https://google.com") -> str:
        webbrowser.open(url)
        return f"Opened {url}"

    def set_volume(self, level: int) -> str:
        if not self.volume:
            return "Volume control unavailable."
        level = max(0, min(100, level))
        self.volume.SetMasterVolumeLevelScalar(level / 100, None)
        return f"Volume set to {level}%"

    def tv_power(self) -> str:
        if not self.tv: return "TV not configured."
        try:
            self.tv.shortcuts().power()
            return "TV toggled."
        except Exception as e:
            return f"TV error: {e}"

    def tv_volume_up(self) -> str:
        if not self.tv: return "TV not configured."
        self.tv.shortcuts().volume_up()
        return "TV volume up."

    def tv_volume_down(self) -> str:
        if not self.tv: return "TV not configured."
        self.tv.shortcuts().volume_down()
        return "TV volume down."

    def tv_mute(self) -> str:
        if not self.tv: return "TV not configured."
        self.tv.shortcuts().mute()
        return "TV muted."
    def mute(self) -> str:
        if not self.volume:
            return "Volume control unavailable."
        self.volume.SetMute(1, None)
        return "Muted."

    def unmute(self) -> str:
        if not self.volume:
            return "Volume control unavailable."
        self.volume.SetMute(0, None)
        return "Unmuted."

    def screenshot(self) -> str:
        try:
            import pyautogui
            path = f"C:\\Users\\lala\\Pictures\\Screenshots\\aria_{int(__import__('time').time())}.png"
            pyautogui.screenshot(path)
            return f"Screenshot saved."
        except Exception as e:
            return f"Screenshot failed: {e}"

    def shutdown(self) -> str:
        os.system("shutdown /s /t 5")
        return "Shutting down in 5 seconds."

    def restart(self) -> str:
        os.system("shutdown /r /t 5")
        return "Restarting in 5 seconds."

    def sleep_pc(self) -> str:
        os.system("rundll32.exe powrprof.dll,SetSuspendState 0,1,0")
        return "Going to sleep."

    def lock(self) -> str:
        os.system("rundll32.exe user32.dll,LockWorkStation")
        return "PC locked."