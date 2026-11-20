"""
Claude's 3D figure beside Aria while the two of them talk (Engines/Duet.py).

He has a small window of his own (ui/avatar/claude.html), separate from hers: her page already walks, sits on
windows and hides behind them, and he only exists for the length of a conversation, so his window is made the
first time he's needed and is hidden and paused the rest of the time. It's transparent and never takes a click.

    place_beside(box, screen, size)   # where his window goes next to her (pure, tested)
    win = make_window()               # the only part that needs QtWebEngine
    win.appear(box, screen); win.say("happy"); win.listen(); win.leave()
"""
import json
import os

from ui.avatar_view import AVATAR_DIR, BOX_FIGURE, LOAD_TIMEOUT_S, AvatarLink, screen_hz

SIZE = BOX_FIGURE               # his box: as big as hers with her built-in figure
OVERLAP = 70                    # his box overlaps hers this much: they stand close, the boxes are mostly air


def place_beside(box, screen, size=SIZE, overlap=OVERLAP):
    """(x, y, side) for his window. `box` is her box (left, top, width, height) and `screen` the usable screen
    (left, top, right, bottom), in screen pixels. He stands on her left when there's room, otherwise on her right,
    with his feet level with hers. `side` is +1 when she is to his right (he turns that way), -1 otherwise."""
    left, top, w, h = box
    sl, st, sr, sb = screen
    width, height = size
    x, side = left - width + overlap, 1
    if x < sl:
        x, side = left + w - overlap, -1
    x = max(sl, min(x, sr - width))
    y = max(st, min(top + h - height, sb - height))
    return int(x), int(y), side


class ClaudeLink(AvatarLink):
    """What the overlay says to his page (window.claude), kept until the page is ready."""
    REPLAY = ("side", "state", "feeling", "enter", "run")

    def set_side(self, side):
        self._send("side", f"window.claude.setSide({int(side)})", int(side), repeat=False)

    def set_state(self, state):
        self._send("state", f"window.claude.setState({json.dumps(str(state))})", state, repeat=False)

    def set_level(self, out):
        self._send(None, f"window.claude.setLevel({round(float(out), 3)})")

    def set_feeling(self, feeling):
        self._send("feeling", f"window.claude.setFeeling({json.dumps(str(feeling))})")

    def enter(self):
        self._send("enter", "window.claude.enter()")

    def leave(self):
        self._send(None, "window.claude.leave()")

    def pause(self):
        self._send("run", "window.claude.pause()", "pause", repeat=False)

    def resume(self):
        self._send("run", "window.claude.resume()", "resume", repeat=False)


def make_window():
    """His window, loading at once and hidden until appear()."""
    from PySide6.QtCore import Qt, QTimer, QUrl, QUrlQuery
    from PySide6.QtGui import QColor, QGuiApplication
    from PySide6.QtWebEngineCore import QWebEngineSettings
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWidgets import QWidget

    class ClaudeWindow(QWidget):
        def __init__(self):
            super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
                             | Qt.WindowDoesNotAcceptFocus | Qt.WindowTransparentForInput)
            self.setAttribute(Qt.WA_TranslucentBackground)
            self.setAttribute(Qt.WA_TransparentForMouseEvents)
            self.setAttribute(Qt.WA_ShowWithoutActivating)
            self.resize(*SIZE)
            self.view = QWebEngineView(self)
            self.view.setAttribute(Qt.WA_TranslucentBackground)
            self.view.setAttribute(Qt.WA_TransparentForMouseEvents)
            self.view.setStyleSheet("background: transparent")
            self.view.page().setBackgroundColor(QColor(0, 0, 0, 0))
            self.view.settings().setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, True)
            self.view.settings().setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, False)
            self.view.setGeometry(0, 0, *SIZE)
            self.link = ClaudeLink(self.view.page().runJavaScript)
            self.view.renderProcessTerminated.connect(lambda *_: self._failed("his 3D view stopped"))
            self.showing = False
            self._asked = 0
            self._poll = QTimer(self)
            self._poll.timeout.connect(self._ask)
            self._gone = QTimer(self)
            self._gone.timeout.connect(self._check_gone)
            url = QUrl.fromLocalFile(os.path.join(AVATAR_DIR, "claude.html"))
            query, screen = QUrlQuery(), QGuiApplication.primaryScreen()
            query.addQueryItem("hz", str(screen_hz(screen.refreshRate() if screen else None)))   # the screen's own rate
            url.setQuery(query)
            self.view.load(url)
            self._poll.start(250)

        def appear(self, box, screen):
            if self.link.failed:
                return
            self.place(box, screen)
            self._gone.stop()
            self.showing = True
            self.show()
            self.link.resume()
            self.link.set_state("idle")
            self.link.enter()

        def place(self, box, screen):
            x, y, side = place_beside(box, screen)
            if (self.x(), self.y()) != (x, y):
                self.move(x, y)
            self.link.set_side(side)

        def say(self, feeling):
            self.link.set_feeling(feeling)
            self.link.set_state("talking")

        def listen(self):
            self.link.set_state("listening")

        def leave(self):
            if not self.showing:
                return
            self.showing = False
            self.link.set_state("idle")
            self.link.leave()
            self._gone.start(100)

        def _check_gone(self):
            def answer(gone):
                if gone or self.link.failed:
                    self._gone.stop()
                    if not self.showing:
                        self.link.pause()
                        self.hide()
            self.view.page().runJavaScript("!!window.claudeGone", answer)

        def _failed(self, why):
            self.link.mark_failed(why)
            self.showing = False
            self.hide()
            print(f"[Claude] his figure won't show: {why}")

        def _ask(self):
            self._asked += 1
            if self.link.ready or self.link.failed:
                self._poll.stop()
            elif self._asked * 0.25 > LOAD_TIMEOUT_S:
                self._poll.stop()
                self._failed("his figure took too long to load")
            else:
                self.view.page().runJavaScript("window.claudeStatus || ''", self._status)

        def _status(self, status):
            if status == "ready":
                self.link.mark_ready()
                if not self.showing:
                    self.link.pause()
            elif isinstance(status, str) and status.startswith("failed"):
                self._failed(status.partition(":")[2].strip() or "his figure didn't load")

    return ClaudeWindow()
