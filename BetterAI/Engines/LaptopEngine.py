"""
Laptop control for Linux Mint / Cinnamon (X11).

Every action is a fixed command built here — the LLM only picks from allowlisted
apps/actions and never gets a shell. Risky actions go through Confirmer.
"""

import difflib
import json
import os
import re
import time
import shutil
import subprocess
import urllib.parse

# name → launch command, WM_CLASS fragment (from `wmctrl -lx`), extra spoken aliases
APPS = {
    "vscode":     (["code"], "vscode", ["vs code", "code", "visual studio code", "editor"]),
    "pycharm":    (["pycharm"], "jetbrains-pycharm", ["py charm", "jetbrains"]),
    "chrome":     (["google-chrome"], "google-chrome", ["google chrome", "browser"]),
    "firefox":    (["firefox"], "firefox", []),
    "spotify":    (["spotify"], "spotify", []),
    "files":      (["nemo"], "nemo.nemo", ["file manager", "nemo", "explorer", "folders"]),
    "terminal":   (["gnome-terminal"], "gnome-terminal", ["console", "shell"]),
    "settings":   (["cinnamon-settings"], "cinnamon-settings", ["system settings"]),
    "calculator": (["gnome-calculator"], "gnome-calculator", ["calc"]),
}

WEBSITES = {
    "github": "https://github.com", "youtube": "https://youtube.com", "gmail": "https://mail.google.com",
    "google drive": "https://drive.google.com", "chatgpt": "https://chatgpt.com", "claude": "https://claude.ai",
    "calendar": "https://calendar.google.com", "maps": "https://maps.google.com",
    "stackoverflow": "https://stackoverflow.com", "netflix": "https://netflix.com", "whatsapp": "https://web.whatsapp.com",
}

MEDIA_ACTIONS = {"play_pause": "PlayPause", "play": "Play", "pause": "Pause",
                 "next": "Next", "previous": "Previous", "stop": "Stop"}


def _run(cmd, timeout=5) -> str:
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if out.returncode != 0:
        raise RuntimeError((out.stderr or out.stdout).strip() or f"{cmd[0]} failed")
    return out.stdout


def _launch(cmd):
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def _match_app(name: str):
    name = (name or "").lower().strip()
    for key, (_, _, aliases) in APPS.items():
        if name == key or name in aliases:
            return key
    names = list(APPS) + [a for _, _, al in APPS.values() for a in al]
    close = difflib.get_close_matches(name, names, n=1, cutoff=0.8)   # typos only ("pycharn"); "discord" ≠ "vscode"
    if close:
        return next(k for k, (_, _, al) in APPS.items() if close[0] == k or close[0] in al)
    return None


# ── Any app from the Mint menu ────────────────────────────────────────────────
# Read from the same .desktop files the menu uses and launched with gtk-launch, exactly like
# clicking it in the menu. Aria never builds a command line herself.

MENU_DIRS = ["/usr/share/applications", "/usr/local/share/applications",
             os.path.expanduser("~/.local/share/applications"),
             "/var/lib/flatpak/exports/share/applications",
             os.path.expanduser("~/.local/share/flatpak/exports/share/applications"),
             "/var/lib/snapd/desktop/applications"]


def _norm_words(text: str) -> list:
    return re.sub(r"[^a-z0-9+#]+", " ", (text or "").lower()).split()


def _read_desktop(path):
    entry, section = {}, None
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if line.startswith("["):
                    section = line
                    continue
                if section == "[Desktop Entry]" and "=" in line:
                    k, v = line.split("=", 1)
                    entry.setdefault(k.strip(), v.strip())      # unlocalised keys come first
    except OSError:
        return None
    if entry.get("Type") != "Application" or entry.get("NoDisplay") == "true" or entry.get("Hidden") == "true":
        return None
    if "Cinnamon" in entry.get("NotShowIn", "") or (entry.get("OnlyShowIn") and "X-Cinnamon" not in entry["OnlyShowIn"]
                                                    and "Cinnamon" not in entry["OnlyShowIn"]):
        return None
    exe = os.path.basename(entry.get("Exec", "").split()[0]) if entry.get("Exec") else ""
    return {"id": os.path.basename(path)[:-len(".desktop")], "name": entry.get("Name", ""),
            "generic": entry.get("GenericName", ""), "keywords": entry.get("Keywords", ""),
            "wm": (entry.get("StartupWMClass") or re.sub(r"\.(appimage|sh|py)$", "", exe, flags=re.I)).lower()}


class MenuApps:
    """The apps in the Mint menu, re-read at most once a minute (new installs show up)."""
    def __init__(self):
        self._apps, self._at = [], 0.0

    def all(self):
        if time.time() - self._at > 60:
            seen, apps = set(), []
            for d in MENU_DIRS:
                try:
                    names = sorted(os.listdir(d))
                except OSError:
                    continue
                for fn in names:
                    if fn.endswith(".desktop") and fn not in seen:
                        app = _read_desktop(os.path.join(d, fn))
                        if app and app["name"]:
                            seen.add(fn)
                            apps.append(app)
            self._apps, self._at = apps, time.time()
        return self._apps

    def find(self, query: str):
        """Best menu entry for 'packet tracer' / 'discord' / 'libre office writer', or None."""
        q = _norm_words(query)
        q = [w for w in q if w not in ("the", "app", "my", "program", "application")] or q
        if not q:
            return None
        best, best_score = None, 0
        for a in self.all():
            name = _norm_words(a["name"])
            extra = _norm_words(a["generic"] + " " + a["keywords"].replace(";", " "))
            if name == q:
                score = 100
            elif all(w in name for w in q):
                score = 85 - len(name)          # "Cisco Packet Tracer 9.0.1" beats "…Ptsa 9.0.1"
            elif "".join(q) in "".join(name):
                score = 70 - len(name)          # "libreoffice" vs "LibreOffice Writer"
            elif all(w in name + extra for w in q):
                score = 50 - len(name)          # matched via GenericName/Keywords ("web browser")
            else:
                ratio = difflib.SequenceMatcher(None, " ".join(q), " ".join(name)).ratio()
                score = 40 * ratio if ratio > 0.75 else 0
            if score > best_score:
                best, best_score = a, score
        return best


class LaptopEngine:
    def __init__(self, confirmer):
        self.confirm = confirmer
        self.menu = MenuApps()

    # ── Apps & windows ────────────────────────────────────────────────────────

    def _windows(self):
        """[(window_id, wm_class, title)]"""
        rows = []
        for line in _run(["wmctrl", "-lx"]).splitlines():
            parts = line.split(None, 4)
            if len(parts) >= 5 and parts[1] != "-1":
                rows.append((parts[0], parts[2].lower(), parts[4]))
        return rows

    def _app_windows(self, key):
        frag = APPS[key][1]
        return [w for w in self._windows() if frag in w[1]]

    def _menu_windows(self, entry):
        frag = entry["wm"]
        title = entry["name"].lower()
        return [w for w in self._windows() if (frag and frag in w[1]) or title in w[2].lower()]

    def open_app(self, app: str):
        key = _match_app(app)
        if key and shutil.which(APPS[key][0][0]):
            if self._app_windows(key):
                return self.switch_to_app(key)
            _launch(APPS[key][0])
            return f"Opening {key}."
        entry = self.menu.find(app)
        if not entry:
            return f"I couldn't find an app called '{app}' in your menu."
        wins = self._menu_windows(entry)
        if wins:
            _run(["wmctrl", "-i", "-a", wins[0][0]])
            return f"{entry['name']} is already open — switched to it."
        _launch(["gtk-launch", entry["id"]])
        return f"Opening {entry['name']}."

    def find_app(self, app: str):
        """'where is packet tracer' / 'do I have discord installed?'"""
        key = _match_app(app)
        entry = self.menu.find(app)
        if not entry and not (key and shutil.which(APPS[key][0][0])):
            return f"'{app}' isn't installed as an app (it's not in your menu). If it's a file, use find_files."
        name = entry["name"] if entry else key
        running = bool(self._menu_windows(entry) if entry else self._app_windows(key))
        return f"{name} is installed and in your Mint menu" + (" — it's open right now." if running else
                                                             ". I can open it for you.")

    def switch_to_app(self, app: str):
        key = _match_app(app)
        wins = self._app_windows(key) if key else []
        if not wins:
            entry = self.menu.find(app)
            wins = self._menu_windows(entry) if entry else []
        if not wins:
            # fall back to matching a window title, e.g. "switch to the essay document"
            q = (app or "").lower()
            wins = [w for w in self._windows() if q and q in w[2].lower()]
        if not wins:
            return f"No open window for '{app}'."
        _run(["wmctrl", "-i", "-a", wins[0][0]])
        return f"Switched to {wins[0][2]}."

    def close_app(self, app: str):
        key = _match_app(app)
        wins = self._app_windows(key) if key else []
        if not wins:
            entry = self.menu.find(app)
            if entry:
                key, wins = entry["name"], self._menu_windows(entry)
        if not wins:
            return f"{app} isn't open."

        def do():
            for wid, _, _ in wins:
                _run(["wmctrl", "-i", "-c", wid])  # polite close — apps can still ask to save
            return f"Closed {key}."
        n = len(wins)
        return self.confirm.request(f"close {key} ({n} window{'s' if n != 1 else ''})", do)

    def list_open_windows(self):
        wins = [w for w in self._windows() if "nemo-desktop" not in w[1] and w[2] != "Aria"]
        if not wins:
            return "Nothing is open."
        return "Open windows: " + "; ".join(t for _, _, t in wins[:15])

    # ── Sound ─────────────────────────────────────────────────────────────────

    def _volume(self):
        vol = re.search(r"(\d+)%", _run(["pactl", "get-sink-volume", "@DEFAULT_SINK@"]))
        muted = "yes" in _run(["pactl", "get-sink-mute", "@DEFAULT_SINK@"]).lower()
        return (int(vol.group(1)) if vol else None), muted

    def set_laptop_volume(self, level):
        level = max(0, min(100, int(float(level))))
        _run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "0"])
        _run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{level}%"])
        return f"Laptop volume set to {level}%."

    def change_laptop_volume(self, amount):
        amount = int(float(amount))
        vol, _ = self._volume()
        return self.set_laptop_volume((vol or 0) + amount)

    def mute_laptop(self, mute=True):
        on = str(mute).lower() not in ("false", "0", "no")
        _run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "1" if on else "0"])
        return "Laptop muted." if on else "Laptop unmuted."

    def _sinks(self):
        return json.loads(_run(["pactl", "--format=json", "list", "sinks"]))

    def list_audio_outputs(self):
        default = _run(["pactl", "get-default-sink"]).strip()
        return "Audio outputs: " + "; ".join(
            s["description"] + (" (current)" if s["name"] == default else "") for s in self._sinks())

    def switch_audio_output(self, device: str):
        sinks = self._sinks()
        q = (device or "").lower()
        match = next((s for s in sinks if q in s["description"].lower()), None)
        if not match:
            descs = [s["description"] for s in sinks]
            close = difflib.get_close_matches(device, descs, n=1, cutoff=0.3)
            match = next((s for s in sinks if close and s["description"] == close[0]), None)
        if not match:
            return f"No audio output matching '{device}'. " + self.list_audio_outputs()
        _run(["pactl", "set-default-sink", match["name"]])
        return f"Audio now plays through {match['description']}."

    # ── Media (any MPRIS player: Spotify, browser, VLC...) ────────────────────

    def _players(self):
        out = _run(["gdbus", "call", "--session", "--dest", "org.freedesktop.DBus",
                    "--object-path", "/org/freedesktop/DBus", "--method", "org.freedesktop.DBus.ListNames"])
        return re.findall(r"'(org\.mpris\.MediaPlayer2\.[^']+)'", out)

    def media_control(self, action: str):
        method = MEDIA_ACTIONS.get((action or "").lower().replace(" ", "_").replace("/", "_"))
        if not method:
            return f"Unknown media action '{action}'. Use one of: {', '.join(MEDIA_ACTIONS)}."
        players = self._players()
        if not players:
            return "No media player is running."
        # prefer one that's currently playing
        target = players[0]
        for p in players:
            try:
                status = _run(["gdbus", "call", "--session", "--dest", p, "--object-path", "/org/mpris/MediaPlayer2",
                               "--method", "org.freedesktop.DBus.Properties.Get",
                               "org.mpris.MediaPlayer2.Player", "PlaybackStatus"])
                if "Playing" in status:
                    target = p
                    break
            except Exception:
                pass
        _run(["gdbus", "call", "--session", "--dest", target, "--object-path", "/org/mpris/MediaPlayer2",
              "--method", f"org.mpris.MediaPlayer2.Player.{method}"])
        name = target.split(".")[3] if len(target.split(".")) > 3 else "player"
        return f"{action.replace('_', '/')} on {name}."

    # ── System ────────────────────────────────────────────────────────────────

    def lock_screen(self):
        _launch(["cinnamon-screensaver-command", "--lock"])
        return "Locking the screen."

    def power(self, action: str):
        action = (action or "").lower()
        cmds = {"suspend": ["systemctl", "suspend"], "sleep": ["systemctl", "suspend"],
                "shutdown": ["systemctl", "poweroff"], "restart": ["systemctl", "reboot"]}
        if action not in cmds:
            return "Power action must be suspend, shutdown or restart."

        def do():
            _launch(cmds[action])
            return f"Okay — {action}."
        return self.confirm.request(f"{action} the laptop", do)

    def laptop_status(self):
        parts = []
        try:
            bat = next(l for l in _run(["upower", "-e"]).splitlines() if "BAT" in l)
            info = _run(["upower", "-i", bat])
            pct = re.search(r"percentage:\s*(\d+)", info)
            state = re.search(r"state:\s*([\w-]+)", info)
            tte = re.search(r"time to (empty|full):\s*([\d,.]+\s*\w+)", info)
            s = f"battery {pct.group(1)}% {state.group(1) if state else ''}".strip()
            if tte:
                s += f", {tte.group(2).replace(',', '.')} to {tte.group(1)}"
            parts.append(s)
        except Exception:
            pass
        try:
            data = json.loads(_run(["sensors", "-j"]))
            temps = []
            for chip, label in (("k10temp", "CPU"), ("amdgpu", "GPU")):
                for name, vals in data.items():
                    if name.startswith(chip):
                        t = [v for d in vals.values() if isinstance(d, dict)
                             for k, v in d.items() if k.endswith("_input") and k.startswith("temp")]
                        if t:
                            temps.append(f"{label} {round(max(t))}°C")
                        break
            if temps:
                parts.append(", ".join(temps))
        except Exception:
            pass
        try:
            mem = {l.split(":")[0]: int(l.split()[1]) for l in open("/proc/meminfo") if ":" in l}
            used = 1 - mem["MemAvailable"] / mem["MemTotal"]
            parts.append(f"RAM {round(used * 100)}% used")
        except Exception:
            pass
        try:
            du = shutil.disk_usage("/home")
            parts.append(f"{du.free // 2**30} GB free disk")
        except Exception:
            pass
        return "Laptop: " + "; ".join(parts) + "." if parts else "Couldn't read laptop status."

    def set_wifi(self, on=True):
        on = str(on).lower() not in ("false", "0", "no", "off")
        if on:
            _run(["nmcli", "radio", "wifi", "on"])
            return "Wi-Fi on."
        # turning Wi-Fi off also cuts Spotify, Home Assistant and web search
        return self.confirm.request("turn Wi-Fi off (this also cuts Spotify, Home Assistant and search)",
                                    lambda: (_run(["nmcli", "radio", "wifi", "off"]), "Wi-Fi off.")[1])

    def set_bluetooth(self, on=True):
        on = str(on).lower() not in ("false", "0", "no", "off")
        _run(["bluetoothctl", "power", "on" if on else "off"])
        return f"Bluetooth {'on' if on else 'off'}."

    def connect_bluetooth(self, device: str):
        _run(["bluetoothctl", "power", "on"])
        devices = re.findall(r"Device ([0-9A-F:]{17}) (.+)", _run(["bluetoothctl", "devices"]))
        if not devices:
            return "No paired Bluetooth devices. Pair it once in Bluetooth settings first."
        q = (device or "").lower()
        match = next((d for d in devices if q in d[1].lower()), None)
        if not match:
            close = difflib.get_close_matches(device, [d[1] for d in devices], n=1, cutoff=0.3)
            match = next((d for d in devices if close and d[1] == close[0]), None)
        if not match:
            return f"No paired device like '{device}'. Paired: {', '.join(d[1] for d in devices)}."
        try:
            _run(["bluetoothctl", "connect", match[0]], timeout=15)
            return f"Connected to {match[1]}."
        except Exception as e:
            return f"Couldn't connect to {match[1]}: {e}"

    # ── Web & notifications ───────────────────────────────────────────────────

    def open_website(self, site: str):
        s = (site or "").strip()
        key = s.lower()
        if key in WEBSITES:
            url = WEBSITES[key]
        elif re.match(r"^(https?://)?[\w-]+(\.[\w-]+)+(/\S*)?$", s):
            url = s if s.startswith("http") else "https://" + s
        else:
            url = "https://www.google.com/search?q=" + urllib.parse.quote_plus(s)
        _launch(["xdg-open", url])
        return f"Opening {url}."

    def notify_desktop(self, message: str, title: str = "Aria"):
        _run(["notify-send", "-a", "Aria", title or "Aria", message])
        return "Notification shown."
