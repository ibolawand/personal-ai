"""When the laptop starts: Aria opens your study apps (VS Code and MyNotion by default) once per boot.

Only on Aria's first start after the laptop booted (her autostart), so restarting Aria never reopens what you closed.
An app that's already open is left as it is (`LaptopEngine.open_app` switches to it). `ARIA_STARTUP_APPS` in
`Engines/.env` lists the apps (comma separated, names as "open …" understands them); empty turns it off.
"""
from __future__ import annotations

import os
from pathlib import Path

DEFAULT_APPS = "vscode,mynotion"


def boot_time():
    """When the laptop booted (seconds since 1970), or None if it can't be read."""
    try:
        for line in Path("/proc/stat").read_text().splitlines():
            if line.startswith("btime "):
                return int(line.split()[1])
    except Exception:
        pass
    return None


def first_start_since_boot(marker: Path, boot) -> bool:
    """True once per boot: the boot time is remembered in `marker`."""
    if boot is None:
        return False
    marker = Path(marker)
    try:
        if marker.read_text().strip() == str(boot):
            return False
    except Exception:
        pass
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(str(boot))
    except Exception:
        pass
    return True


def open_study_apps(laptop, apps: str):
    for name in [a.strip() for a in (apps or "").split(",") if a.strip()]:
        try:
            print(f"[Startup] {laptop.open_app(name)}")
        except Exception as e:
            print(f"[Startup] couldn't open {name}: {type(e).__name__}: {e}")


def on_laptop_start(laptop):
    """Called when Aria starts: opens the study apps if this is the first start since the laptop booted."""
    cache = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "aria" / "last_boot"
    if first_start_since_boot(cache, boot_time()):
        open_study_apps(laptop, os.environ.get("ARIA_STARTUP_APPS", DEFAULT_APPS))
