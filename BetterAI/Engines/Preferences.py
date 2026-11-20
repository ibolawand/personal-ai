"""Validated desktop preferences. Environment settings supply defaults until saved in the UI."""
import json
import os
import re
import tempfile
from pathlib import Path


def validate(values):
    if values.get("microphone") not in ("typing", "wake"):
        raise ValueError("Choose typing or wake-word mode.")
    for key in ("muted", "autonomous_chats", "claude"):
        if type(values.get(key)) is not bool:
            raise ValueError(f"Invalid setting: {key}")
    quiet = values.get("quiet_hours", "")
    if not isinstance(quiet, str) or (quiet and not re.fullmatch(
            r"(?:[01]\d|2[0-3]):[0-5]\d-(?:[01]\d|2[0-3]):[0-5]\d", quiet)):
        raise ValueError("Use HH:MM-HH:MM for quiet hours, or leave them empty.")
    if quiet and quiet[:5] == quiet[6:]:
        raise ValueError("Quiet hours need different start and end times; leave empty to disable.")
    return {k: values[k] for k in ("microphone", "muted", "autonomous_chats", "claude", "quiet_hours")}


class Preferences:
    def __init__(self, option=0, path=None):
        self.path = Path(path) if path else Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "aria" / "settings.json"
        self.values = dict(microphone="wake" if option == 2 else "typing", muted=False,
                           autonomous_chats=os.environ.get("ARIA_AUTONOMOUS_CHATS", "1") != "0",
                           claude=os.environ.get("ARIA_BIG_MODEL", "1") != "0",
                           quiet_hours=os.environ.get("ARIA_QUIET", "22:30-08:30"))
        try:
            saved = json.loads(self.path.read_text())
            self.values = validate({**self.values, **saved})
        except (OSError, ValueError, TypeError):
            pass

    def save(self, values):
        values = validate(values)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Replace atomically so a crash cannot leave half a settings file.
        name = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", dir=self.path.parent, delete=False) as f:
                name = f.name
                json.dump(values, f, indent=2)
                f.write("\n")
            os.replace(name, self.path)
        finally:
            if name and os.path.exists(name):
                os.unlink(name)
        self.values = values

    def apply(self, aria):
        from Engines import Desk
        aria.muted = self.values["muted"]
        aria.autonomous_chats = self.values["autonomous_chats"]
        Desk.QUIET = self.values["quiet_hours"]
        if getattr(aria, "big", None):
            aria.big.enabled = self.values["claude"]
