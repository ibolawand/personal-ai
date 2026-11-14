"""
Aria's 3D avatar, seen from the overlay's side.

The avatar itself is a web page (ui/avatar/: three.js drawing her built-in figure, or a VRM file such as a VRoid
Studio avatar when ARIA_AVATAR names one). This module
holds what can be decided without that page: whether the avatar can work at all, which small objects orbit her,
and the link the overlay talks through. The orb stays whenever any of it is missing.

    path = avatar_path()                    # ARIA_AVATAR in Engines/.env: a .vrm, "0" = off, unset = built-in figure
    ok, why = available(path)               # why names the missing piece, for the self-check
    view = make_view(overlay, path)         # the only part that needs QtWebEngine
    view.link.set_state("thinking")         # kept until the page is ready, dropped for good if it failed
"""
import datetime as dt
import importlib.util
import json
import math
import os

AVATAR_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "avatar")
PAGE_FILES = ("avatar.html", "avatar.js", "logic.mjs", "figure.mjs", "vrmrig.mjs")
VENDOR_FILES = ("three.module.js", "three.core.js", "three-vrm.module.js", "addons/loaders/GLTFLoader.js",
                "addons/utils/BufferGeometryUtils.js", "addons/utils/SkeletonUtils.js")     # see vendor/VERSIONS.md
BOX_FIGURE = (300, 400)     # the built-in figure is short and wide
BOX_MODEL = (300, 520)      # a loaded character is tall and slim: a taller box, so she isn't tiny
CAPTION_MAX = 40
LOAD_TIMEOUT_S = 20
TIMER_KINDS = ("timer", "focus", "focusbreak")


def avatar_path(env=os.environ):
    """The avatar's .vrm file; "" for her built-in figure (nothing set, and no ui/avatar/aria.vrm dropped in);
    None when she is switched off."""
    value = (env.get("ARIA_AVATAR") or "").strip()
    if value == "0":
        return None
    if value:
        return os.path.expanduser(value)
    dropped = os.path.join(AVATAR_DIR, "aria.vrm")
    return dropped if os.path.isfile(dropped) else ""


def available(path, vendor_dir=None, has_webengine=None):
    """(can the avatar be loaded, why or why not). Imports nothing heavy."""
    if path is None:
        return False, "switched off (ARIA_AVATAR=0)"
    if path and not os.path.isfile(path):
        return False, f"no avatar file at {path}"
    vendor_dir = vendor_dir or os.path.join(AVATAR_DIR, "vendor")
    if not all(os.path.isfile(os.path.join(vendor_dir, name)) for name in VENDOR_FILES):
        return False, "the 3D libraries aren't installed (ui/avatar/vendor)"
    if has_webengine is None:
        try:
            has_webengine = importlib.util.find_spec("PySide6.QtWebEngineWidgets") is not None
        except (ImportError, ValueError):
            has_webengine = False
    if not has_webengine:
        return False, "QtWebEngine isn't installed"
    return True, "ready to load" if path else "ready to load (built-in figure)"


def _due(item):
    due = item.get("due") if isinstance(item, dict) else None
    return due if isinstance(due, (int, float)) and not isinstance(due, bool) else None


def props_for(state, mic_open, timers, now):
    """The small objects orbiting her, each with the caption shown under the mouse. Decided here, not by the page."""
    props = []
    if state == "listening" and mic_open:
        props.append({"kind": "mic", "caption": "listening"})
    if state == "thinking":
        props.append({"kind": "dots", "caption": "thinking"})
    coming = sorted((item for item in timers or () if _due(item) is not None and _due(item) > now), key=_due)
    running = next((item for item in coming if item.get("kind") in TIMER_KINDS), None)
    if running:
        left = math.ceil(_due(running) - now)
        props.append({"kind": "clock", "caption": f"{left // 60}:{left % 60:02d} left"})
    today = dt.datetime.fromtimestamp(now).date()
    waiting = next((item for item in coming if item.get("kind") == "reminder"
                    and dt.datetime.fromtimestamp(_due(item)).date() == today), None)
    if waiting:
        text = " ".join(str(waiting.get("text") or "").split()) or "reminder"
        if len(text) > CAPTION_MAX:
            text = text[:CAPTION_MAX - 1] + "…"
        props.append({"kind": "note", "caption": text})
    return props


def _num(value):
    n = round(float(value), 3)
    return int(n) if n == int(n) else n


class AvatarLink:
    """Everything the overlay says to the avatar's page, as JavaScript calls on window.aria.

    Until the page reports ready, calls are kept (the latest of each kind) and then replayed; once it has failed,
    they are dropped. A value that hasn't changed isn't sent again."""
    REPLAY = ("state", "props", "level", "look", "room", "fade", "run")

    def __init__(self, run_js):
        self._run_js = run_js
        self.ready = False
        self.failed = None
        self._waiting = {}      # kind -> the call to make once the page is ready
        self._last = {}         # kind -> the value last sent or queued, for the kinds that skip repeats

    def _send(self, kind, call, value=None, repeat=True):
        if self.failed:
            return
        if not repeat:
            if self._last.get(kind, self) == value:
                return
            self._last[kind] = value
        if self.ready:
            self._run_js(call)
        elif kind:
            self._waiting[kind] = call

    def set_state(self, state):
        self._send("state", f"window.aria.setState({json.dumps(str(state))})", state, repeat=False)

    def set_level(self, mic, out):
        self._send("level", f"window.aria.setLevel({json.dumps(_num(mic))},{json.dumps(_num(out))})")

    def look_at(self, x, y):
        self._send("look", f"window.aria.lookAt({json.dumps(_num(x))},{json.dumps(_num(y))})")

    def set_props(self, props):
        text = json.dumps(list(props), ensure_ascii=False)
        self._send("props", f"window.aria.setProps({text})", text, repeat=False)

    def fade(self, visible):
        self._send("fade", f"window.aria.fade({json.dumps(bool(visible))})", bool(visible), repeat=False)

    def set_room(self, left, right):
        """How many pixels of screen there are beside her box on each side: how far she may walk about."""
        room = (int(left), int(right))
        self._send("room", f"window.aria.setRoom({room[0]},{room[1]})", room, repeat=False)

    def stop_trip(self):
        self._send(None, "window.aria.stopTrip()")   # her window is being dragged: she stops where she is

    def hop(self):
        self._send(None, "window.aria.hop()")        # a moment, not a state: never replayed

    def wave(self):
        self._send(None, "window.aria.wave()")       # her hello when she appears

    def pause(self):
        self._send("run", "window.aria.pause()", "pause", repeat=False)

    def resume(self):
        self._send("run", "window.aria.resume()", "resume", repeat=False)

    def mark_ready(self):
        if self.failed or self.ready:
            return
        self.ready = True
        waiting, self._waiting = self._waiting, {}
        for kind in self.REPLAY:
            if kind in waiting:
                self._run_js(waiting[kind])

    def mark_failed(self, why):
        self.failed = str(why) or "the avatar didn't load"
        self.ready = False
        self._waiting = {}


class Travel:
    """Her window following her walks across the screen. While she walks somewhere, the page reports
    [trip id, pixels walked, still walking] (window.ariaTravel); the window moves that far from where it was when
    the trip began, and stays where the trip ends."""

    def __init__(self):
        self.id = None
        self.base = 0
        self.done = True

    def follow(self, report, x):
        """The window's x for this report, with the window now at `x`; None to leave it where it is."""
        if not isinstance(report, (list, tuple)) or len(report) != 3:
            return None
        trip, px, walking = report
        if not isinstance(px, (int, float)):
            return None
        if trip != self.id:
            if not walking:             # a trip that ended before we saw it (or one we let go of)
                return None
            self.id, self.base, self.done = trip, x - px, False
        if self.done:
            return None
        if not walking:
            self.done = True
        return round(self.base + px)

    def drop(self):
        """Stop following (her window is being dragged); a trip that carries on is not followed either."""
        self.done = True


def make_view(parent, path):
    """The web view that shows the avatar, loading at once (hidden and paused until the overlay says otherwise).
    The only function here that needs QtWebEngine; everything it could decide is decided elsewhere."""
    from PySide6.QtCore import Qt, QTimer, QUrl, QUrlQuery
    from PySide6.QtGui import QColor
    from PySide6.QtWebEngineCore import QWebEngineSettings
    from PySide6.QtWebEngineWidgets import QWebEngineView

    class AvatarView(QWebEngineView):
        def __init__(self):
            super().__init__(parent)
            self.setAttribute(Qt.WA_TranslucentBackground)
            self.setAttribute(Qt.WA_TransparentForMouseEvents)      # the overlay handles clicks, drags and hover
            self.setStyleSheet("background: transparent")
            self.page().setBackgroundColor(QColor(0, 0, 0, 0))
            settings = self.settings()
            settings.setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, True)
            settings.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, False)
            self.box = BOX_MODEL if path else BOX_FIGURE
            self.link = AvatarLink(self.page().runJavaScript)
            self.link.pause()
            self.renderProcessTerminated.connect(lambda *_: self.link.mark_failed("the 3D view stopped"))
            self._asked = 0
            self._poll = QTimer(self)
            self._poll.timeout.connect(self._ask)
            url = QUrl.fromLocalFile(os.path.join(AVATAR_DIR, "avatar.html"))
            if path:
                query = QUrlQuery()
                query.addQueryItem("model", QUrl.fromLocalFile(path).toString())
                url.setQuery(query)
            self.hide()
            self.load(url)
            self._poll.start(250)

        def ask_travel(self, answer):
            """answer(window.ariaTravel) once the page says where her walk has got to. (It comes over as JSON text:
            PySide6 hands JavaScript arrays back as empty strings.)"""
            def parse(text):
                try:
                    answer(json.loads(text) if text else None)
                except ValueError:
                    answer(None)
            self.page().runJavaScript("JSON.stringify(window.ariaTravel || null)", parse)

        def _ask(self):
            self._asked += 1
            if self.link.ready or self.link.failed:
                self._poll.stop()
            elif self._asked * 0.25 > LOAD_TIMEOUT_S:
                self._poll.stop()
                self.link.mark_failed("the avatar took too long to load")
            else:
                self.page().runJavaScript("window.ariaStatus || ''", self._status)

        def _status(self, status):
            if status == "ready":
                self.link.mark_ready()
            elif isinstance(status, str) and status.startswith("failed"):
                self.link.mark_failed(status.partition(":")[2].strip() or "the avatar didn't load")

    return AvatarView()
