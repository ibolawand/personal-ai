"""
Screen & clipboard awareness.

- look_at_screen: screenshot → local vision model in Ollama (nothing leaves the machine)
- read_clipboard / copy_to_clipboard: via Qt, because the overlay already runs a Qt app

Needs a vision model:  ollama pull qwen2.5vl:7b   (or set VISION_MODEL in Engines/.env)
"""

import base64
import io
import os
import threading

import ollama
from PIL import ImageGrab

# One vision model for everything that looks at images (screen, camera, mood)
VISION_MODEL = os.environ.get("VISION_MODEL", "qwen2.5vl:7b")
MAX_SIDE = 1600
MAX_CLIPBOARD_CHARS = 8000


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
        try:
            img = ImageGrab.grab()
        except Exception as e:
            return f"Couldn't take a screenshot: {e}"
        img.thumbnail((MAX_SIDE, MAX_SIDE))
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=85)
        b64 = base64.b64encode(buf.getvalue()).decode()

        prompt = (f"This is a screenshot of the user's computer screen. {question}\n"
                  "Be specific: quote exact error messages, code, or text when relevant. "
                  "Answer concisely.")
        try:
            response = ollama.chat(model=self.model, think=False,
                                   messages=[{"role": "user", "content": prompt, "images": [b64]}])
            return response["message"]["content"].strip()
        except Exception as e:
            return f"Screen analysis failed: {e}"

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
