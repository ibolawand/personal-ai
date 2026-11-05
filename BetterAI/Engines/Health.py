"""
"Are all your systems okay?" — a self-check of everything Aria depends on, with a fix for anything missing.
Also printed to the log at startup. (The vision model was missing for weeks without anyone noticing.)
"""

import os


def _check(name, fn):
    try:
        ok, detail = fn()
    except Exception as e:
        ok, detail = False, str(e)[:120]
    return name, ok, detail


class Health:
    def __init__(self, aria):
        self.aria = aria

    def checks(self):
        a = self.aria
        out = []

        def ollama_models():
            import ollama
            from llm_engine import LLM_MODEL_DEFAULT
            from Engines.ScreenEngine import VISION_MODEL
            names = {m.model for m in ollama.list().models}
            missing = [m for m in (LLM_MODEL_DEFAULT, VISION_MODEL) if m not in names and m + ":latest" not in names]
            if missing:
                return False, "missing model(s): " + ", ".join(missing) + " — run: ollama pull " + " ".join(missing)
            return True, f"{LLM_MODEL_DEFAULT} and {VISION_MODEL} installed"
        out.append(_check("Language and vision models", ollama_models))

        def mynotion():
            if not a.notion:
                return False, "database not found — set DB_PATH in Engines/.env"
            return True, f"{len(a.notion._notes())} notes"
        out.append(_check("MyNotion", mynotion))

        def spotify():
            if not a.spotify:
                return False, "not connected — set SPOTIFY_CLIENT_ID/SECRET in Engines/.env and restart"
            token = a.spotify.sp.auth_manager.get_cached_token()
            return (True, "logged in") if token else (False, "not logged in — restart Aria and log in once")
        out.append(_check("Spotify", spotify))

        def camera():
            v = a.vision
            if getattr(v, "_camera_index", None) is None:
                return False, "no camera found (set CAMERA_INDEX if you have one)"
            return True, f"camera {v._camera_index}" + (", someone is here" if v.is_present else "")
        out.append(_check("Camera", camera))

        def microphone():
            import sounddevice as sd
            dev = sd.query_devices(kind="input")
            return True, dev["name"]
        out.append(_check("Microphone", microphone))

        def voice():
            return (True, "speaking") if a.voice else (False, "voice engine failed to load (see the log)")
        out.append(_check("Voice", voice))

        def weather():
            w = getattr(a, "weather", None)
            if not w:
                return False, "not available"
            home = w.state.get("home") or w.state.get("home_name")
            name = home["name"] if isinstance(home, dict) else home
            return (True, f"home city {name}") if home else (False, "no home city — tell me 'I live in …'")
        out.append(_check("Weather", weather))

        def web():
            key = os.environ.get("BRAVE_API_KEY")
            return True, "Wikipedia + Brave Search" if key else "Wikipedia only (add BRAVE_API_KEY for recent things)"
        out.append(_check("Web search", web))

        def files():
            import sqlite3
            from Engines.FilesEngine import INDEX_FILE
            if not INDEX_FILE.exists():
                return True, "document index not built yet (it builds in the background)"
            conn = sqlite3.connect(INDEX_FILE)
            n = conn.execute("SELECT COUNT(*) FROM docs").fetchone()[0]
            conn.close()
            return True, f"{n} documents indexed"
        out.append(_check("Files", files))
        return out

    def report(self):
        """Tool: a summary the model turns into a spoken answer."""
        rows = self.checks()
        bad = [r for r in rows if not r[1]]
        lines = [f"{'OK' if ok else 'PROBLEM'} — {name}: {detail}" for name, ok, detail in rows]
        head = "Everything works." if not bad else f"{len(bad)} thing(s) need attention."
        return (head + " Mention the problems and how to fix them; don't read out every OK line.\n" + "\n".join(lines))

    def log_startup(self):
        for name, ok, detail in self.checks():
            print(f"[Health] {'✓' if ok else '✗'} {name}: {detail}")
