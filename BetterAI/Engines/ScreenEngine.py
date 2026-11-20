"""
Screen & clipboard awareness.

- look_at_screen: screenshot → local vision model in Ollama (nothing leaves the machine)
- read_clipboard / copy_to_clipboard: via Qt, because the overlay already runs a Qt app

Needs a vision model:  ollama pull qwen2.5vl:3b   (or set VISION_MODEL in Engines/.env)

Speed: the chat model and the vision model don't fit on an 8 GB card together, so every look swaps them.
The 3B vision model loads fast, screenshots are shrunk to 1280 px (bigger was 4x slower, smaller no faster),
and the vision model's answer goes straight to Lala ("FINAL ANSWER") while the chat model reloads in the
background — about 8 s instead of ~13 s (and ~40 s with the 7B model at 1600 px).
"""

import base64
import io
import os
import threading

import ollama
from PIL import ImageGrab

# One vision model for everything that looks at images (screen, camera, mood)
VISION_MODEL = os.environ.get("VISION_MODEL", "qwen2.5vl:3b")
MAX_SIDE = 1280
from llm_engine import FINAL_PREFIX  # noqa: E402  (llm_engine returns such results to Lala as is)
MAX_CLIPBOARD_CHARS = 8000


def _jpeg(img):
    img = img.copy()
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode()


def plan_look(windows, screens):
    """What to photograph, decided in code: {"monitor": box or None (everything), "close_up": box or None}.
    `windows`: the app windows, the one in front first (ui.desktop_windows.Shown); `screens`: the monitors as
    (left, top, right, bottom).

    Only the monitor with the window in front is photographed: two monitors side by side shrunk into one picture
    leave the text on both too small to read. And when that window fills less than 60% of its monitor, it is
    photographed again on its own, so its text is larger for the model."""
    if not windows:
        return {"monitor": screens[0] if len(screens) == 1 else None, "close_up": None}
    r = windows[0].rect
    cx, cy = (r.left + r.right) / 2, (r.top + r.bottom) / 2
    monitor = next((m for m in screens if m[0] <= cx < m[2] and m[1] <= cy < m[3]), screens[0] if screens else None)
    if not monitor:
        return {"monitor": None, "close_up": None}
    box = (max(r.left, monitor[0]), max(r.top, monitor[1]), min(r.right, monitor[2]), min(r.bottom, monitor[3]))
    area = max(0, box[2] - box[0]) * max(0, box[3] - box[1])
    whole = (monitor[2] - monitor[0]) * (monitor[3] - monitor[1])
    small = 200 * 150 <= area < 0.6 * whole
    return {"monitor": monitor, "close_up": box if small else None}


def _name(w):
    title = " ".join((w.title or "").split())[:90]
    app = (w.app or "").split(".")[-1]
    return f'"{title}" ({app})' if title and app else f'"{title}"' if title else app or "an untitled window"


def look_prompt(question, windows, plan):
    """What the picture model is told along with the picture(s): the question, and the facts about the screen that
    are known for certain (which window is in front, what else is open), so it doesn't have to guess them."""
    lines = [f"This is a screenshot of Lala's computer screen. Lala asks: {question}"]
    if windows:
        lines.append(f"The window in front, the one Lala is using, is {_name(windows[0])}. "
                     "Unless Lala asks about something else, the question is about that window.")
        if len(windows) > 1:
            lines.append("Also open behind it: " + ", ".join(_name(w) for w in windows[1:5]) + ".")
        if plan.get("close_up"):
            lines.append("The first picture is the whole screen; the second is a close-up of the window in front. "
                         "Read text from the close-up.")
    lines.append("A small animated girl or a glowing orb on the screen is Aria, Lala's assistant: that is you, "
                 "not part of what Lala is looking at. Don't describe her.")
    lines.append("Answer Lala directly, in one to three short spoken sentences, like a friend looking over their "
                 "shoulder. Say only what you can actually see; if something is too small to read, say so instead "
                 "of guessing. Quote exact error messages or text when that's what they ask about. No markdown.")
    return "\n".join(lines)


class ScreenEngine:
    def __init__(self, clipboard=None, model: str = None):
        """clipboard: object with get_text() / set_text(text), or None for a direct Qt fallback."""
        self.model = model or VISION_MODEL
        self.clipboard = clipboard or _DirectClipboard()

    def _model_available(self) -> bool:
        try:
            names = {m.model for m in ollama.list().models}
        except Exception:
            return True  # let the chat call report the real error
        want = self.model if ":" in self.model else self.model + ":latest"
        return want in names

    def look_at_screen(self, question: str = "Describe what's on the screen."):
        if not self._model_available():
            return (f"I can't see the screen yet: the vision model '{self.model}' isn't installed. "
                    f"Run: ollama pull {self.model}")
        windows, screens = self._desktop()
        plan = plan_look(windows, screens)
        try:
            shots = [self.grab(plan["monitor"])]
            if plan["close_up"]:
                shots.append(self.grab(plan["close_up"]))
        except Exception as e:
            return f"Couldn't take a screenshot: {e}"
        try:
            from llm_engine import vision_chat
            response = vision_chat(self.model, [{"role": "user", "content": look_prompt(question, windows, plan),
                                                 "images": [_jpeg(img) for img in shots]}])
            answer = response["message"]["content"].strip()
        except Exception as e:
            return f"Screen analysis failed: {e}"
        return FINAL_PREFIX + answer

    def _desktop(self):
        """(the app windows, front first; the monitors): what is known for certain about the screen, read from
        the window manager and not guessed from the picture. Both empty when that can't be read."""
        try:
            from ui import desktop_windows
            return desktop_windows.shown_windows(own_pid=os.getpid()), desktop_windows.monitors()
        except Exception:
            return [], []

    @staticmethod
    def grab(box=None):
        """A screenshot of `box` (left, top, right, bottom), or of everything."""
        return ImageGrab.grab(bbox=box) if box else ImageGrab.grab()

    def read_clipboard(self):
        try:
            text = self.clipboard.get_text() or ""
        except Exception as e:
            return f"Couldn't read the clipboard: {e}"
        if not text.strip():
            return "The clipboard is empty (or holds something that isn't text)."
        if len(text) > MAX_CLIPBOARD_CHARS:
            text = text[:MAX_CLIPBOARD_CHARS] + "\n…[truncated]"
        return f"Clipboard contents:\n{text}"

    def copy_to_clipboard(self, text: str):
        try:
            self.clipboard.set_text(text)
            return "Copied to your clipboard."
        except Exception as e:
            return f"Couldn't write to the clipboard: {e}"


class _DirectClipboard:
    """Fallback for --no-ui mode: a Qt app on the calling thread. Reading works;
    copied text only stays available while Aria is running."""

    _lock = threading.Lock()

    def _cb(self):
        from PySide6.QtGui import QGuiApplication
        app = QGuiApplication.instance() or QGuiApplication([])
        return app.clipboard()

    def get_text(self):
        with self._lock:
            return self._cb().text()

    def set_text(self, text):
        with self._lock:
            self._cb().setText(text)
