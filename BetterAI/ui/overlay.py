"""
Aria overlay — a frameless, transparent, always-on-top orb with speech bubbles.

    python main.py            # keyboard input via the overlay (click the orb)
    python main.py --voice    # wake word + speech

Orb:   left-click → type a message · drag → move · right-click → menu
       hover → shows recent messages · Esc → hide the text box
Cards: lists, the calendar and yes/no questions appear as a small card above the orb —
       tick items, click an event to open the calendar, or answer with the buttons.

Qt owns the main thread; Aria runs in a worker thread and talks to the UI
through OverlayBridge (signals for state/messages, plain floats for audio levels).
"""

import math
import signal
import sys
import threading
import time
import traceback

import random

import numpy as np
from PySide6.QtCore import (QEvent, QObject, QPoint, QPointF, QRect, QRectF, QSettings, Qt, QThread, QTimer,
                            Signal)
from PySide6.QtGui import (QAction, QColor, QFont, QFontMetrics, QGuiApplication, QPainter, QPainterPath,
                           QPen, QRadialGradient, QRegion)
from PySide6.QtWidgets import (QApplication, QCheckBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QMenu,
                               QPushButton, QScrollArea, QVBoxLayout, QWidget)

# ── Look ──────────────────────────────────────────────────────────────────────

WIN_W, WIN_H = 420, 600
OLD_WIN_H = 440                # saved positions from before cards existed used this height
ORB_R = 28                     # base orb radius
ORB_BOX = 160                  # square around the orb that holds its glow + particles
MARGIN = 14
BUBBLE_MAX_W = 300
BUBBLE_PAD_X, BUBBLE_PAD_Y = 13, 9
MAX_CHARS = 280
HOVER_HISTORY = 4

STATE_COLORS = {
    "booting":   (140, 140, 165),
    "sleeping":  (140, 85, 225),
    "listening": (105, 195, 255),
    "thinking":  (185, 120, 255),
    "speaking":  (235, 125, 255),
    "error":     (255, 95, 95),
}
FLASH_COLORS = {"unknown": (255, 180, 70), "alert": (255, 110, 160)}
RING_COLORS = {"focus": (255, 165, 60), "focusbreak": (110, 220, 150), "timer": (235, 230, 255)}
STATE_LABELS = {
    "booting": "starting up…", "sleeping": "asleep", "listening": "listening",
    "thinking": "thinking…", "speaking": "speaking", "error": "something broke — see terminal",
}

BUBBLE_BG = QColor(18, 14, 28, 225)
BUBBLE_TEXT = QColor(240, 236, 250)
USER_TEXT = QColor(200, 185, 235)

INPUT_STYLE = """
QLineEdit {
    background: rgba(18, 14, 28, 235);
    color: #f0ecfa;
    border: 1px solid rgba(185, 120, 255, 140);
    border-radius: 19px;
    padding: 0 16px;
    selection-background-color: rgba(185, 120, 255, 160);
}
"""
CARD_W = 300
CARD_MAX_H = 260
CARD_STAY = {"list": 45, "agenda": 45, "confirm": 90, "reminder": 180, "dictation": 3600}   # seconds without hovering before a card fades
CARD_STYLE = """
QFrame#card { background: rgba(18, 14, 28, 238); border: 1px solid rgba(185, 120, 255, 130); border-radius: 14px; }
QLabel { color: #f0ecfa; background: transparent; }
QLabel#title { font-weight: bold; }
QLabel#day { color: #b99cf0; font-size: 8pt; font-weight: bold; padding-top: 4px; }
QLabel#muted { color: #9a90b0; }
QCheckBox { color: #f0ecfa; spacing: 8px; background: transparent; padding: 2px 0; }
QCheckBox:checked { color: #8f86a6; }
QCheckBox::indicator { width: 15px; height: 15px; border-radius: 4px; border: 1px solid #8a6cc8; background: #221a33; }
QCheckBox::indicator:checked { background: #b978ff; border-color: #b978ff; image: none; }
QPushButton { color: #f0ecfa; background: #2a2140; border: 1px solid #4a3a6c; border-radius: 9px; padding: 4px 12px; }
QPushButton:hover { background: #3a2d58; }
QPushButton#yes { background: #6d3fc0; border-color: #8a5be0; }
QPushButton#yes:hover { background: #7f4fd6; }
QPushButton#link { background: transparent; border: none; color: #c9a8ff; padding: 2px 4px; }
QPushButton#link:hover { color: #ffffff; }
QPushButton#event { background: transparent; border: none; border-radius: 6px; text-align: left; padding: 3px 4px; }
QPushButton#event:hover { background: #2a2140; }
QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; border: none; }
QScrollBar:vertical { width: 6px; background: transparent; }
QScrollBar::handle:vertical { background: #4a3a6c; border-radius: 3px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
"""
MENU_STYLE = """
QMenu { background: #17121f; color: #eee8f8; border: 1px solid #3a2d52; border-radius: 8px; padding: 4px; }
QMenu::item { padding: 6px 18px; border-radius: 5px; }
QMenu::item:selected { background: #3a2d52; }
QMenu::separator { height: 1px; background: #3a2d52; margin: 4px 8px; }
"""


def _lerp(a, b, t):
    return a + (b - a) * t


def _clamp01(x):
    return max(0.0, min(1.0, x))


# ── Bridge: the only thing Aria knows about ──────────────────────────────────

class OverlayBridge(QObject):
    stateChanged = Signal(str)
    messageAdded = Signal(str, str)
    _clipRequest = Signal(str, str)
    remoteCommand = Signal(str)   # from ui/instance.py: toggle / show / quit
    cardRequested = Signal(object)  # a card dict, or {"type": "clear", "kind": ...}

    def __init__(self):
        super().__init__()
        self.aria = None
        self.state = "booting"
        self.mic = 0.0      # latest mic volume (mean abs, ~0..0.1)
        self.out = 0.0      # latest playback RMS (~0..0.3)
        self.timers = []    # pending reminders: [{"text", "kind", "due", "created"}]
        self._clip_lock = threading.Lock()
        self._clip_done = threading.Event()
        self._clip_result = None
        self._clipRequest.connect(self._clip_slot, Qt.QueuedConnection)

    # Called by Aria (from any thread). Qt queues signals onto the UI thread.
    def set_state(self, state):
        if state not in FLASH_COLORS:
            self.state = state
        self.stateChanged.emit(state)

    def set_timers(self, items):
        self.timers = list(items)

    # Clipboard — Qt only allows it on the GUI thread, so worker threads hop over and wait
    def get_text(self):
        return self._clip("get")

    def set_text(self, text):
        self._clip("set", text)

    def _clip(self, op, text=""):
        if QThread.currentThread() == self.thread():
            return self._do_clip(op, text)
        with self._clip_lock:
            self._clip_done.clear()
            self._clipRequest.emit(op, text)
            if not self._clip_done.wait(3):
                raise TimeoutError("clipboard didn't respond")
            return self._clip_result

    def _clip_slot(self, op, text):
        try:
            self._clip_result = self._do_clip(op, text)
        except Exception as e:
            self._clip_result = None
            print(f"[Overlay] clipboard: {e}")
        finally:
            self._clip_done.set()

    @staticmethod
    def _do_clip(op, text):
        cb = QGuiApplication.clipboard()
        if op == "get":
            return cb.text()
        cb.setText(text)

    def message(self, role, text):
        self.messageAdded.emit(role, text)

    # Cards: {"type": "list", "note_id", "title", "items": [{"text", "checked"}]}
    #        {"type": "agenda", "title", "days": [{"label", "events": [{"time", "title", "repeat"}]}]}
    #        {"type": "confirm", "text"}
    def show_card(self, card):
        self.cardRequested.emit(card)

    def clear_card(self, kind=None):
        self.cardRequested.emit({"type": "clear", "kind": kind})

    def mic_level(self, volume):
        self.mic = volume

    # VoiceEngine's avatar hooks
    def feed_audio(self, chunk):
        self.out = float(np.sqrt(np.mean(np.square(chunk)))) if len(chunk) else 0.0
        if self.state != "speaking":
            self.set_state("speaking")

    def stop_talking(self):
        self.out = 0.0


# ── Cards ─────────────────────────────────────────────────────────────────────

class Card(QFrame):
    """A small interactive panel above the orb. on_action(kind, payload) goes back to the overlay:
    ("toggle", (note_id, text, checked)) · ("open", what) · ("answer", "yes"|"no") · ("close", None)"""

    def __init__(self, parent, card, on_action):
        super().__init__(parent)
        self.setObjectName("card")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(CARD_STYLE)
        self.setFixedWidth(CARD_W)
        self.kind = card["type"]
        self.on_action = on_action
        self.font_ = QFont("Noto Sans", 10)
        self.setFont(self.font_)

        box = QVBoxLayout(self)
        box.setContentsMargins(14, 10, 10, 12)
        box.setSpacing(4)

        head = QHBoxLayout()
        title = QLabel({"confirm": "Confirm", "reminder": card.get("title", "Reminder")}.get(
            self.kind, card.get("title", "")))
        title.setObjectName("title")
        head.addWidget(title, 1)
        if self.kind == "list":
            head.addWidget(self._link("Open", lambda: on_action("open", card["title"])))
        elif self.kind == "agenda":
            head.addWidget(self._link("Open calendar", lambda: on_action("open", "calendar")))
        head.addWidget(self._link("✕", lambda: on_action("close", None)))
        box.addLayout(head)

        body = QWidget()
        rows = QVBoxLayout(body)
        rows.setContentsMargins(0, 0, 0, 0)
        rows.setSpacing(1)
        getattr(self, f"_build_{self.kind}")(rows, card)
        rows.addStretch(1)

        body.adjustSize()
        room = CARD_MAX_H - 50
        if body.sizeHint().height() > room:
            scroll = QScrollArea()
            scroll.setWidget(body)
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            scroll.setFixedHeight(room)
            box.addWidget(scroll)
        else:
            box.addWidget(body)
        self.adjustSize()

    @staticmethod
    def _link(text, fn):
        b = QPushButton(text)
        b.setObjectName("link")
        b.setCursor(Qt.PointingHandCursor)
        b.clicked.connect(fn)
        return b

    @staticmethod
    def _muted(text):
        l = QLabel(text)
        l.setObjectName("muted")
        return l

    def _build_list(self, rows, card):
        items = card.get("items") or []
        if not items:
            rows.addWidget(self._muted("Empty."))
        for it in items:
            if it.get("checked") is None:
                l = QLabel("•  " + it["text"])
                l.setWordWrap(True)
                rows.addWidget(l)
                continue
            cb = QCheckBox(it["text"])
            cb.setChecked(bool(it["checked"]))
            cb.setCursor(Qt.PointingHandCursor)
            self._strike(cb)

            def toggled(state, cb=cb, text=it["text"]):
                self._strike(cb)
                self.on_action("toggle", (card["note_id"], text, cb.isChecked()))
            cb.toggled.connect(toggled)
            rows.addWidget(cb)
        left = sum(1 for it in items if it.get("checked") is False)
        if any(it.get("checked") is not None for it in items):
            self.left_label = self._muted(f"{left} left" if left else "All done ✓")
            rows.addWidget(self.left_label)

    def _strike(self, cb):
        f = cb.font()
        f.setStrikeOut(cb.isChecked())
        cb.setFont(f)
        label = getattr(self, "left_label", None)
        if label is not None:
            left = sum(1 for w in self.findChildren(QCheckBox) if not w.isChecked())
            label.setText(f"{left} left" if left else "All done ✓")

    def _build_agenda(self, rows, card):
        days = card.get("days") or []
        if not days:
            rows.addWidget(self._muted("Nothing planned."))
        for d in days:
            day = QLabel(d["label"].upper())
            day.setObjectName("day")
            rows.addWidget(day)
            for e in d["events"]:
                text = f"{e['time']:>7}   {e['title']}" + ("  ↻" if e.get("repeat") else "")
                b = QPushButton(text)
                b.setObjectName("event")
                b.setCursor(Qt.PointingHandCursor)
                b.setToolTip("Open the calendar in MyNotion")
                b.clicked.connect(lambda: self.on_action("open", "calendar"))
                rows.addWidget(b)

    def _build_reminder(self, rows, card):
        q = QLabel(card["text"])
        q.setWordWrap(True)
        rows.addWidget(q)
        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 8, 0, 0)
        for label, payload in (("Snooze 5 min", 5), ("10 min", 10), ("Done", None)):
            b = QPushButton(label)
            b.setCursor(Qt.PointingHandCursor)
            if payload is None:
                b.setObjectName("yes")
                b.clicked.connect(lambda: self.on_action("close", None))
            else:
                b.clicked.connect(lambda _=False, m=payload: self.on_action("snooze", m))
            buttons.addWidget(b)
        rows.addLayout(buttons)

    def _build_dictation(self, rows, card):
        text = QLabel(card.get("text") or "Listening… start talking.")
        text.setWordWrap(True)
        if not card.get("text"):
            text.setObjectName("muted")
        rows.addWidget(text)
        rows.addWidget(self._muted(f"{card.get('words', 0)} words · say “stop” to save, “scratch that” to undo"))
        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 8, 0, 0)
        buttons.addStretch(1)
        for label, say in (("Cancel", "cancel dictation"), ("Save", "stop dictating")):
            b = QPushButton(label)
            b.setCursor(Qt.PointingHandCursor)
            if say == "stop dictating":
                b.setObjectName("yes")
            b.clicked.connect(lambda _=False, t=say: self.on_action("answer", t))
            buttons.addWidget(b)
        rows.addLayout(buttons)

    def _build_confirm(self, rows, card):
        q = QLabel(card["text"][:1].upper() + card["text"][1:] + "?")
        q.setWordWrap(True)
        rows.addWidget(q)
        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 8, 0, 0)
        buttons.addStretch(1)
        for label, answer in (("No", "no"), ("Yes", "yes")):
            b = QPushButton(label)
            b.setCursor(Qt.PointingHandCursor)
            if answer == "yes":
                b.setObjectName("yes")
            b.clicked.connect(lambda _=False, a=answer: self.on_action("answer", a))
            buttons.addWidget(b)
        rows.addLayout(buttons)


# ── Overlay window ────────────────────────────────────────────────────────────

class Overlay(QWidget):
    def __init__(self, bridge: OverlayBridge):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.bridge = bridge
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.setFixedSize(WIN_W, WIN_H)
        self.setWindowTitle("Aria")

        self.font_ = QFont("Noto Sans", 10)
        self.font_small = QFont("Noto Sans", 9)

        self.state = bridge.state
        self.color = list(STATE_COLORS[self.state])
        self.level = 0.0
        self.flash = 0.0
        self.flash_color = FLASH_COLORS["unknown"]
        self.t = 0.0
        self._last_tick = time.monotonic()
        self.spin = 0.0            # plasma swirl phase (speeds up when busy/loud)
        self.particles = []        # sparks: {"x","y","vx","vy","age","life","size","hue","kind"}
        self.waves = []            # shockwave rings: {"age","life","strength"}
        self._spawn_acc = 0.0
        self._last_wave = 0.0
        self._prev_flash = 0.0

        self.bubbles = []          # [{"role", "text", "expire"}]
        self.card = None           # the Card widget currently shown (one at a time)
        self.card_expire = 0.0
        self.hover = False
        self._drag_from = None
        self._dragged = False
        self._mask_key = None

        self.input = QLineEdit(self)
        self.input.setFont(self.font_)
        self.input.setStyleSheet(INPUT_STYLE)
        self.input.setPlaceholderText("Message Aria…")
        self.input.setGeometry(self._input_rect())
        self.input.returnPressed.connect(self._submit)
        self.capture_mode = False      # quick capture (Ctrl+Alt+N): the text is filed, not chatted about
        self.history = []              # what was typed, for ↑ / ↓ in the text box
        self._hist_pos = 0
        self._draft = ""
        self.input.installEventFilter(self)
        self.input.hide()

        bridge.stateChanged.connect(self._on_state)
        bridge.messageAdded.connect(self._on_message)
        bridge.remoteCommand.connect(self._on_remote)
        bridge.cardRequested.connect(self._on_card)

        self._restore_position()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(16)

    # ── Geometry ──

    def _orb_center(self) -> QPointF:
        return QPointF(WIN_W - ORB_BOX / 2, WIN_H - ORB_BOX / 2)

    def _orb_rect(self) -> QRect:
        return QRect(WIN_W - ORB_BOX, WIN_H - ORB_BOX, ORB_BOX, ORB_BOX)

    def _input_rect(self) -> QRect:
        c = self._orb_center()
        w, h = 260, 38
        return QRect(int(c.x() - ORB_R - 18 - w), int(c.y() - h / 2), w, h)

    def _in_orb(self, pos) -> bool:
        c = self._orb_center()
        return math.hypot(pos.x() - c.x(), pos.y() - c.y()) <= ORB_R + 14

    def _restore_position(self):
        # stored as the window's bottom-right corner (where the orb is), so a taller window keeps the orb in place
        settings = QSettings("Aria", "overlay")
        corner = settings.value("corner")
        pos = None
        if isinstance(corner, QPoint):
            pos = corner - QPoint(WIN_W, WIN_H)
        elif isinstance(settings.value("pos"), QPoint):
            pos = settings.value("pos") + QPoint(0, OLD_WIN_H - WIN_H)
        screen = QApplication.primaryScreen().availableGeometry()
        if isinstance(pos, QPoint) and any(s.availableGeometry().contains(pos + QPoint(WIN_W - 60, WIN_H - 60))
                                           for s in QApplication.screens()):
            self.move(pos)
        else:
            self.move(screen.right() - WIN_W - MARGIN, screen.bottom() - WIN_H - MARGIN)

    def _save_position(self):
        QSettings("Aria", "overlay").setValue("corner", self.pos() + QPoint(WIN_W, WIN_H))

    # ── Bridge events ──

    def _on_state(self, state):
        if state in FLASH_COLORS:
            self.flash = 1.0 if state == "unknown" else 2.5  # alerts pulse longer
            self.flash_color = FLASH_COLORS[state]
            return
        self.state = state

    def _on_remote(self, cmd):
        """Hotkey / second launch. Bring the orb forward and focus the text box."""
        if cmd == "quit":
            quit_app()
            return
        if cmd == "ping":
            return                      # only checks she's running: the orb stays as it is
        if not self.isVisible():
            self.show()
        self._add_wave(0.6)
        if cmd == "toggle" and self.input.isVisible():
            self._toggle_input(False)
            return
        self._set_capture(cmd == "capture")
        self._toggle_input(True)
        # the hotkey fires while another app has focus; ask the window manager for it
        if self.windowHandle():
            self.windowHandle().requestActivate()

    def _on_message(self, role, text):
        text = " ".join(text.split())
        if len(text) > MAX_CHARS:
            text = text[:MAX_CHARS].rsplit(" ", 1)[0] + "…"
        stay = 5.0 if role == "user" else max(7.0, len(text) / 14)
        now = time.monotonic()
        if role == "aria":
            # keep the user line visible as long as the reply it belongs to
            for b in self.bubbles[-1:]:
                if b["role"] == "user":
                    b["expire"] = now + stay
        self.bubbles.append({"role": role, "text": text, "expire": now + stay})
        self.bubbles = self.bubbles[-20:]

    # ── Cards ──

    def _on_card(self, card):
        if card.get("type") == "clear":
            if self.card and (card.get("kind") in (None, self.card.kind)):
                self._close_card()
            return
        self._close_card()
        self.card = Card(self, card, self._card_action)
        self.card.move(self._card_pos())
        self.card.show()
        self.card_expire = time.monotonic() + CARD_STAY.get(card["type"], 45)
        self._mask_key = None
        if not self.isVisible():
            self.show()

    def _card_pos(self) -> QPoint:
        right = WIN_W - (ORB_BOX - 2 * ORB_R) / 2 + 4
        bottom = WIN_H - ORB_BOX + 6
        return QPoint(int(right - CARD_W), int(bottom - self.card.height()))

    def _close_card(self):
        if self.card:
            self.card.hide()
            self.card.deleteLater()
            self.card = None
            self._mask_key = None

    def _card_action(self, kind, payload):
        aria = self.bridge.aria
        self.card_expire = time.monotonic() + CARD_STAY.get(self.card.kind if self.card else "", 45)
        if kind == "close":
            self._close_card()
        elif kind == "answer":
            self._close_card()
            if aria:
                aria.submit_text(payload)
        elif kind == "open" and aria:
            threading.Thread(target=aria.open_from_card, args=(payload,), daemon=True).start()
        elif kind == "snooze":
            self._close_card()
            if aria:
                threading.Thread(target=aria.snooze_from_card, args=(payload,), daemon=True).start()
        elif kind == "toggle" and aria:
            threading.Thread(target=aria.toggle_from_card, args=payload, daemon=True).start()

    # ── Animation ──

    def _tick(self):
        now = time.monotonic()
        dt = min(0.05, now - self._last_tick)
        self._last_tick = now
        self.t += dt

        target = STATE_COLORS.get(self.state, STATE_COLORS["thinking"])
        k = 1 - math.exp(-dt * 6)
        self.color = [_lerp(c, tc, k) for c, tc in zip(self.color, target)]

        if self.state == "listening":
            raw = _clamp01(self.bridge.mic * 14)
        elif self.state == "speaking":
            raw = _clamp01(self.bridge.out * 5)
        else:
            raw = 0.0
        # fast attack, slow release, so it pulses with syllables instead of flickering
        # a sudden syllable / loud bit while speaking fires a shockwave ring
        if self.state == "speaking" and raw > 0.35 and raw > self.level + 0.12 and now - self._last_wave > 0.22:
            self._add_wave(0.5 + 0.5 * raw)
        self.level = _lerp(self.level, raw, 0.45 if raw > self.level else 0.12)
        if self.flash > self._prev_flash + 0.5:      # unknown face / reminder: big burst
            self._burst(36, self.flash_color)
            self._add_wave(1.0)
            self._add_wave(0.7, delay=0.18)
        self.flash = max(0.0, self.flash - dt / 1.6)
        self._prev_flash = self.flash

        speed = {"thinking": 4.0, "booting": 2.5, "speaking": 1.6 + 5 * self.level,
                 "listening": 1.0 + 3 * self.level, "sleeping": 0.25}.get(self.state, 1.0)
        self.spin += dt * speed
        self._update_particles(dt)

        if self.card:
            if self.hover:
                self.card_expire = max(self.card_expire, now + 8)
            elif now > self.card_expire:
                self._close_card()

        self._update_mask()
        self.update()

    # ── Particles & shockwaves ──

    def _add_wave(self, strength, delay=0.0):
        self.waves.append({"age": -delay, "life": 0.75, "strength": strength})
        self._last_wave = time.monotonic()

    def _burst(self, n, rgb=None):
        for _ in range(n):
            a = random.uniform(0, 2 * math.pi)
            v = random.uniform(60, 150)
            self.particles.append({"x": ORB_R * math.cos(a), "y": ORB_R * math.sin(a),
                                   "vx": v * math.cos(a), "vy": v * math.sin(a), "age": 0.0,
                                   "life": random.uniform(0.4, 0.8), "size": random.uniform(1.5, 3.2),
                                   "hue": random.uniform(-25, 25), "kind": "spark", "rgb": rgb})

    def _spawn(self, dt):
        lvl, st = self.level, self.state
        rate = {"listening": 8 + 70 * lvl, "speaking": 10 + 90 * lvl,
                "thinking": 22, "booting": 10, "sleeping": 1.2}.get(st, 0)
        self._spawn_acc += rate * dt
        while self._spawn_acc >= 1:
            self._spawn_acc -= 1
            a = random.uniform(0, 2 * math.pi)
            if st == "listening":       # sucked in towards the orb
                d = ORB_R * random.uniform(2.0, 2.5)
                v = -random.uniform(35, 70) * (1 + 2 * lvl)
                p = {"x": d * math.cos(a), "y": d * math.sin(a), "vx": v * math.cos(a), "vy": v * math.sin(a),
                     "life": 1.4, "size": random.uniform(1.2, 2.4), "kind": "in"}
            elif st == "speaking":      # thrown outwards with the voice
                v = random.uniform(30, 60) * (1 + 2.5 * lvl)
                p = {"x": ORB_R * math.cos(a), "y": ORB_R * math.sin(a), "vx": v * math.cos(a),
                     "vy": v * math.sin(a), "life": random.uniform(0.5, 0.9),
                     "size": random.uniform(1.4, 2.8), "kind": "spark"}
            elif st in ("thinking", "booting"):   # spiral around, slowly falling in
                d = ORB_R * random.uniform(1.5, 2.2)
                p = {"x": d * math.cos(a), "y": d * math.sin(a), "vx": 0, "vy": 0,
                     "life": random.uniform(1.0, 1.8), "size": random.uniform(1.0, 2.2), "kind": "swirl"}
            else:                         # sleeping: dust drifting up
                p = {"x": random.uniform(-ORB_R, ORB_R), "y": -ORB_R * 0.6,
                     "vx": random.uniform(-4, 4), "vy": -random.uniform(8, 14),
                     "life": 3.0, "size": random.uniform(1.0, 1.8), "kind": "dust"}
            p.update(age=0.0, hue=random.uniform(-30, 30), rgb=None)
            self.particles.append(p)

    def _update_particles(self, dt):
        self._spawn(dt)
        limit = ORB_BOX / 2 - 4
        alive = []
        for p in self.particles:
            p["age"] += dt
            if p["kind"] == "swirl":      # tangential + slight inward pull
                x, y = p["x"], p["y"]
                d = math.hypot(x, y) or 1
                tang, pull = 140 / d * 28, 18
                p["vx"] = (-y / d) * tang - (x / d) * pull
                p["vy"] = (x / d) * tang - (y / d) * pull
            elif p["kind"] == "spark":
                p["vx"] *= 0.97
                p["vy"] *= 0.97
            p["x"] += p["vx"] * dt
            p["y"] += p["vy"] * dt
            d = math.hypot(p["x"], p["y"])
            if p["age"] < p["life"] and d < limit and not (p["kind"] == "in" and d < ORB_R * 0.9):
                alive.append(p)
        self.particles = alive[-160:]
        for w in self.waves:
            w["age"] += dt
        self.waves = [w for w in self.waves if w["age"] < w["life"]]

    # ── Bubbles layout ──

    def _visible_bubbles(self):
        """Returns [(bubble, alpha)] newest last."""
        now = time.monotonic()
        if self.hover:
            return [(b, 1.0) for b in self.bubbles[-HOVER_HISTORY:]]
        out = []
        for b in self.bubbles[-HOVER_HISTORY:]:
            a = _clamp01(1 - (now - b["expire"]) / 0.6)
            if a > 0:
                out.append((b, a))
        return out

    def _layout_bubbles(self):
        """Returns [(rect, bubble, alpha)], stacked upward from above the orb, right-aligned."""
        right = WIN_W - (ORB_BOX - 2 * ORB_R) / 2 + 4
        bottom = WIN_H - ORB_BOX + 6
        if self.card:
            bottom = self.card.y() - 6
        laid = []
        for b, a in reversed(self._visible_bubbles()):
            fm = QFontMetrics(self.font_small if b["role"] == "user" else self.font_)
            tr = fm.boundingRect(QRect(0, 0, BUBBLE_MAX_W - 2 * BUBBLE_PAD_X, 2000),
                                 Qt.TextWordWrap, b["text"])
            w, h = tr.width() + 2 * BUBBLE_PAD_X, tr.height() + 2 * BUBBLE_PAD_Y
            top = bottom - h
            if top < 4:
                break
            laid.append((QRect(int(right - w), int(top), int(w), int(h)), b, a))
            bottom = top - 6
        return laid

    def _caption_rect(self):
        c = self._orb_center()
        return QRect(int(c.x() - ORB_R - 18 - 280), int(c.y() - 11), 280, 22)

    def _update_mask(self):
        rects = [r for r, _, _ in self._layout_bubbles()]
        show_caption = self.hover and not self.input.isVisible()
        card = self.card.geometry() if self.card else None
        key = (tuple((r.x(), r.y(), r.width(), r.height()) for r in rects),
               self.input.isVisible(), show_caption,
               (card.x(), card.y(), card.width(), card.height()) if card else None)
        if key == self._mask_key:
            return
        self._mask_key = key
        region = QRegion(self._orb_rect(), QRegion.Ellipse)
        for r in rects:
            region = region.united(QRegion(r.adjusted(-2, -2, 2, 2)))
        if self.input.isVisible():
            region = region.united(QRegion(self._input_rect().adjusted(-2, -2, 2, 2)))
        if show_caption:
            region = region.united(QRegion(self._caption_rect()))
        if card:
            region = region.united(QRegion(card.adjusted(-1, -1, 1, 1)))
        self.setMask(region)

    # ── Painting ──

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        self._paint_bubbles(p)
        self._paint_orb(p)
        if self.hover and not self.input.isVisible():
            self._paint_caption(p)
        p.end()

    def _paint_bubbles(self, p: QPainter):
        accent = QColor(*[int(c) for c in self.color])
        for rect, b, a in self._layout_bubbles():
            p.setOpacity(a)
            bg = QColor(BUBBLE_BG)
            border = QColor(accent)
            border.setAlpha(110 if b["role"] == "aria" else 50)
            p.setPen(QPen(border, 1))
            p.setBrush(bg)
            p.drawRoundedRect(QRectF(rect).adjusted(0.5, 0.5, -0.5, -0.5), 14, 14)
            p.setPen(BUBBLE_TEXT if b["role"] == "aria" else USER_TEXT)
            p.setFont(self.font_ if b["role"] == "aria" else self.font_small)
            p.drawText(rect.adjusted(BUBBLE_PAD_X, BUBBLE_PAD_Y, -BUBBLE_PAD_X, -BUBBLE_PAD_Y),
                       Qt.TextWordWrap, b["text"])
        p.setOpacity(1.0)

    def _paint_caption(self, p: QPainter):
        text = STATE_LABELS.get(self.state, self.state)
        if self.bridge.aria and self.bridge.aria.muted:
            text += " · muted"
        text += self._timer_caption()
        p.setFont(self.font_small)
        fm = QFontMetrics(self.font_small)
        cr = self._caption_rect()
        w = fm.horizontalAdvance(text) + 20
        r = QRect(cr.right() - w, cr.y(), w, cr.height())
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(18, 14, 28, 200))
        p.drawRoundedRect(r, 11, 11)
        p.setPen(QColor(220, 212, 238))
        p.drawText(r, Qt.AlignCenter, text)

    def _active_timer(self):
        """Soonest timer or focus session (reminders at a clock time don't get a ring)."""
        items = [x for x in self.bridge.timers if x["kind"] in RING_COLORS and x["due"] > time.time()]
        return min(items, key=lambda x: x["due"]) if items else None

    def _paint_countdown(self, p: QPainter, c: QPointF):
        tm = self._active_timer()
        if not tm:
            return
        total = max(1.0, tm["due"] - tm["created"])
        frac = _clamp01((tm["due"] - time.time()) / total)
        rr = ORB_R + 21
        box = QRectF(c.x() - rr, c.y() - rr, 2 * rr, 2 * rr)
        col = QColor(*RING_COLORS[tm["kind"]])
        track = QColor(col)
        track.setAlpha(40)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(track, 2.5))
        p.drawEllipse(box)
        col.setAlpha(220)
        pen = QPen(col, 2.5)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.drawArc(box, 90 * 16, int(-360 * 16 * frac))  # from 12 o'clock, clockwise, shrinking

    def _timer_caption(self):
        tm = self._active_timer()
        if not tm:
            return ""
        left = int(tm["due"] - time.time())
        clock = f"{left // 3600}:{left % 3600 // 60:02d}:{left % 60:02d}" if left >= 3600 else f"{left // 60}:{left % 60:02d}"
        label = {"focus": "focus", "focusbreak": "break"}.get(tm["kind"]) or ("" if tm["text"] == "timer" else tm["text"])
        return f" · ⏱ {clock}" + (f" {label}" if label else "")

    @staticmethod
    def _hue(col: QColor, shift: float, alpha: int = 255, light: float = 0.0) -> QColor:
        h, sat, v, _ = col.getHsvF()
        h = ((h if h >= 0 else 0.75) + shift / 360) % 1.0
        out = QColor.fromHsvF(h, max(0.0, sat - light * 0.5), min(1.0, v + light))
        out.setAlpha(alpha)
        return out

    def _blob_path(self, c, r, wobble, t, spikes=0.0):
        path = QPainterPath()
        n = 96
        for i in range(n + 1):
            a = 2 * math.pi * i / n
            d = (math.sin(3 * a + t * 2.1) * 0.5 +
                 math.sin(5 * a - t * 3.3) * 0.3 +
                 math.sin(2 * a + t * 1.3) * 0.2)
            if spikes:
                d += spikes * max(0.0, math.sin(7 * a - t * 6)) ** 6
            rad = r * (1 + wobble * d)
            pt = QPointF(c.x() + rad * math.cos(a), c.y() + rad * math.sin(a))
            path.moveTo(pt) if i == 0 else path.lineTo(pt)
        path.closeSubpath()
        return path

    def _paint_orb(self, p: QPainter):
        c = self._orb_center()
        t, lvl, st = self.t, self.level, self.state
        flash = min(1.0, self.flash) * (0.6 + 0.4 * abs(math.sin(t * 6)) if self.flash > 1 else 1)
        rgb = [_lerp(x, u, flash) for x, u in zip(self.color, self.flash_color)]
        col = QColor(*[int(x) for x in rgb])

        r = ORB_R
        wobble, spikes = 0.03, 0.0
        glow_a = 90
        if st == "sleeping":
            breathe = 0.5 + 0.5 * math.sin(t * 2 * math.pi / 4.5)
            r *= 0.92 + 0.06 * breathe
            glow_a = int(35 + 45 * breathe)
            col = col.darker(130)
        elif st == "listening":
            r *= 1 + 0.12 * lvl + 0.02 * math.sin(t * 3)
            wobble = 0.03 + 0.05 * lvl
            glow_a = int(90 + 140 * lvl)
        elif st == "speaking":
            r *= 1 + 0.08 * lvl + 0.015 * math.sin(t * 9)
            wobble = 0.03 + 0.045 * lvl
            glow_a = int(110 + 140 * lvl)
        elif st in ("thinking", "booting"):
            r *= 1 + 0.03 * math.sin(t * 5)
            wobble, spikes = 0.04, 0.35
            glow_a = 120
        glow_a = min(255, int(glow_a + 140 * flash))

        # outer glow, slowly colour-shifting
        g = QRadialGradient(c, r * 2.4)
        g.setColorAt(0.3, self._hue(col, 18 * math.sin(t * 0.7), glow_a))
        g.setColorAt(0.6, self._hue(col, -30 * math.sin(t * 0.5), glow_a // 3))
        g.setColorAt(1.0, self._hue(col, 0, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(g)
        p.drawEllipse(c, r * 2.4, r * 2.4)

        self._paint_countdown(p, c)
        self._paint_waves(p, c, r, col)

        # listening: equaliser spikes around the orb that jump with your voice
        if st == "listening":
            n = 48
            for i in range(n):
                a = 2 * math.pi * i / n + t * 0.4
                noise = 0.5 + 0.5 * math.sin(i * 1.7 + t * 9) * math.sin(i * 0.63 - t * 5.3)
                ln = 2 + 24 * lvl * noise
                c1 = self._hue(col, 40 * math.sin(a * 2 + t), int(90 + 160 * lvl * noise), 0.15)
                pen = QPen(c1, 2.2)
                pen.setCapStyle(Qt.RoundCap)
                p.setPen(pen)
                r0 = r + 6
                p.drawLine(QPointF(c.x() + r0 * math.cos(a), c.y() + r0 * math.sin(a)),
                           QPointF(c.x() + (r0 + ln) * math.cos(a), c.y() + (r0 + ln) * math.sin(a)))

        # thinking / booting: comets with tails + a counter-rotating dashed halo
        if st in ("thinking", "booting"):
            p.setBrush(Qt.NoBrush)
            halo = self._hue(col, -40, 120, 0.2)
            pen = QPen(halo, 1.3)
            pen.setDashPattern([2, 5])
            pen.setDashOffset(t * 30)
            p.setPen(pen)
            p.drawEllipse(c, r + 17, r + 17)
            for k in range(3):
                w = (4.2, -3.1, 5.6)[k]
                base = r + (11, 15, 20)[k]
                for j in range(14):
                    tt = t - j * 0.018
                    a = tt * w + k * 2.1
                    rr = base + 3 * math.sin(tt * 3 + k)
                    alpha = int(230 * (1 - j / 14) ** 1.5)
                    p.setPen(Qt.NoPen)
                    p.setBrush(self._hue(col, 60 * k - 40, alpha, 0.25))
                    p.drawEllipse(QPointF(c.x() + rr * math.cos(a), c.y() + rr * math.sin(a)),
                                  3.2 - j * 0.18, 3.2 - j * 0.18)

        # the orb body
        path = self._blob_path(c, r, wobble, t, spikes)
        body = QRadialGradient(c, r * 1.15)
        body.setColorAt(0.0, col.lighter(115))
        body.setColorAt(0.8, col)
        body.setColorAt(1.0, col.darker(180))
        p.setPen(Qt.NoPen)
        p.setBrush(body)
        p.drawPath(path)

        # plasma: coloured blobs swirling inside the orb like a lava lamp
        p.save()
        p.setClipPath(path)
        p.setCompositionMode(QPainter.CompositionMode_Plus)
        sp = self.spin
        for k, (hs, fx, fy, size) in enumerate(((50, 1.0, 1.3, 0.8), (-60, -1.4, 0.9, 0.7),
                                                 (150, 0.7, -1.1, 0.6), (0, 1.9, 1.6, 0.45))):
            bx = c.x() + r * 0.45 * math.sin(sp * fx + k)
            by = c.y() + r * 0.45 * math.cos(sp * fy + k * 1.7)
            bg = QRadialGradient(QPointF(bx, by), r * size)
            bg.setColorAt(0.0, self._hue(col, hs, int(75 + 45 * lvl), 0.15))
            bg.setColorAt(1.0, self._hue(col, hs, 0))
            p.setBrush(bg)
            p.drawEllipse(QPointF(bx, by), r * size, r * size)
        p.restore()

        # glassy highlight + rim
        hl = QRadialGradient(QPointF(c.x() - r * 0.35, c.y() - r * 0.42), r * 0.75)
        hl.setColorAt(0.0, QColor(255, 255, 255, 190))
        hl.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.setBrush(hl)
        p.drawPath(path)
        p.setPen(QPen(QColor(255, 255, 255, 60 + int(80 * lvl)), 1.2))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)

        self._paint_particles(p, c, col)
        if st == "sleeping":
            self._paint_zzz(p, c, r)

    def _paint_waves(self, p, c, r, col):
        p.setBrush(Qt.NoBrush)
        for w in self.waves:
            if w["age"] < 0:
                continue
            f = w["age"] / w["life"]
            rr = r + (ORB_BOX / 2 - 4 - r) * (1 - (1 - f) ** 2.5)
            p.setPen(QPen(self._hue(col, 30 * f, int(200 * w["strength"] * (1 - f)), 0.25),
                          1 + 3 * w["strength"] * (1 - f)))
            p.drawEllipse(c, rr, rr)

    def _paint_particles(self, p, c, col):
        p.save()
        p.setCompositionMode(QPainter.CompositionMode_Plus)
        p.setPen(Qt.NoPen)
        for q in self.particles:
            f = q["age"] / q["life"]
            fade = min(1.0, q["age"] * 6) * (1 - f)
            base = QColor(*q["rgb"]) if q["rgb"] else col
            pc = self._hue(base, q["hue"], int(230 * fade), 0.3)
            pos = QPointF(c.x() + q["x"], c.y() + q["y"])
            s = q["size"] * (1.4 if q["kind"] == "in" else 1)
            gg = QRadialGradient(pos, s * 2.2)
            gg.setColorAt(0.0, pc)
            pc2 = QColor(pc)
            pc2.setAlpha(0)
            gg.setColorAt(1.0, pc2)
            p.setBrush(gg)
            p.drawEllipse(pos, s * 2.2, s * 2.2)
        p.restore()

    def _paint_zzz(self, p, c, r):
        p.save()
        for k in range(3):
            f = ((self.t * 0.35) + k / 3) % 1.0
            x = c.x() + r * 0.5 + 22 * f + 4 * math.sin(f * 9)
            y = c.y() - r * 0.6 - 34 * f
            font = QFont(self.font_)
            font.setPointSizeF(7 + 6 * f)
            font.setBold(True)
            p.setFont(font)
            p.setPen(QColor(200, 175, 255, int(200 * math.sin(f * math.pi))))
            p.drawText(QPointF(x, y), "z")
        p.restore()

    # ── Input ──

    def _toggle_input(self, show=None):
        show = (not self.input.isVisible()) if show is None else show
        if show:
            self.input.show()
            self.activateWindow()
            self.raise_()
            self.input.setFocus()
        else:
            self.input.clear()
            self.input.hide()

    def _set_capture(self, on: bool):
        self.capture_mode = on
        self.input.setPlaceholderText("Quick capture: list item, event, reminder or note…" if on else "Message Aria…")
        self.input.setStyleSheet(INPUT_STYLE.replace("rgba(185, 120, 255, 140)", "rgba(110, 220, 150, 170)")
                                 if on else INPUT_STYLE)

    def eventFilter(self, obj, e):
        """↑ / ↓ in the text box walk through what was typed before, like a terminal."""
        if obj is self.input and e.type() == QEvent.KeyPress and e.key() in (Qt.Key_Up, Qt.Key_Down):
            if not self.history:
                return True
            if self._hist_pos == len(self.history):
                self._draft = self.input.text()
            step = -1 if e.key() == Qt.Key_Up else 1
            self._hist_pos = max(0, min(len(self.history), self._hist_pos + step))
            self.input.setText(self.history[self._hist_pos] if self._hist_pos < len(self.history) else self._draft)
            return True
        return super().eventFilter(obj, e)

    def _remember_typed(self, text):
        if not self.history or self.history[-1] != text:
            self.history = (self.history + [text])[-50:]
        self._hist_pos = len(self.history)
        self._draft = ""

    def _submit(self):
        text = self.input.text().strip()
        self.input.clear()
        if text:
            self._remember_typed(text)
        if not text:
            self._toggle_input(False)
            return
        if self.capture_mode:
            self._set_capture(False)
            self._toggle_input(False)
            self._on_message("user", "➕ " + text)
            if self.bridge.aria:
                threading.Thread(target=self.bridge.aria.quick_capture, args=(text,), daemon=True).start()
            return
        if self.bridge.aria:
            self.bridge.aria.submit_text(text)
        else:
            self._on_message("aria", "Still starting up — give me a second.")

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self._set_capture(False)
            self._toggle_input(False)
        else:
            super().keyPressEvent(e)

    # ── Mouse ──

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and self._in_orb(e.position()):
            self._drag_from = e.globalPosition().toPoint() - self.pos()
            self._press_at = e.globalPosition().toPoint()
            self._dragged = False

    def mouseMoveEvent(self, e):
        if self._drag_from is not None:
            gp = e.globalPosition().toPoint()
            if (gp - self._press_at).manhattanLength() > 4:
                self._dragged = True
            if self._dragged:
                self.move(gp - self._drag_from)
        self.setCursor(Qt.PointingHandCursor if self._in_orb(e.position()) else Qt.ArrowCursor)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self._drag_from is not None:
            if self._dragged:
                self._save_position()
            else:
                self._add_wave(0.6)
                self._burst(14)
                self._toggle_input()
            self._drag_from = None

    def contextMenuEvent(self, e):
        aria = self.bridge.aria
        menu = QMenu(self)
        menu.setStyleSheet(MENU_STYLE)

        type_act = QAction("Type a message", menu)
        type_act.triggered.connect(lambda: self._toggle_input(True))
        menu.addAction(type_act)

        sleep_act = QAction("Go to sleep", menu)
        sleep_act.setEnabled(bool(aria) and self.state not in ("sleeping", "booting"))
        sleep_act.triggered.connect(lambda: aria.request_sleep())
        menu.addAction(sleep_act)

        mute_act = QAction("Unmute voice" if aria and aria.muted else "Mute voice", menu)
        mute_act.setEnabled(bool(aria))
        mute_act.triggered.connect(lambda: aria.toggle_mute())
        menu.addAction(mute_act)

        clear_act = QAction("Clear bubbles", menu)
        clear_act.triggered.connect(lambda: (self.bubbles.clear(), self._close_card()))
        menu.addAction(clear_act)

        menu.addSeparator()
        quit_act = QAction("Quit Aria", menu)
        quit_act.triggered.connect(quit_app)
        menu.addAction(quit_act)
        menu.exec(e.globalPos())

    def enterEvent(self, _):
        self.hover = True

    def leaveEvent(self, _):
        self.hover = False


# ── App entry ─────────────────────────────────────────────────────────────────

_bridge = None


def quit_app():
    aria = _bridge.aria if _bridge else None
    if aria:
        # shutdown() saves the session and ends with os._exit; keep the UI responsive meanwhile
        threading.Thread(target=aria.shutdown, daemon=True).start()
    else:
        QApplication.quit()


def run_with_overlay(make_aria, visible: bool = True):
    """make_aria(bridge) -> Aria. Builds Aria in a worker thread so the orb appears instantly.
    visible=False (MyNotion's Start): the orb stays hidden until the hotkey, the menu or a card shows it."""
    global _bridge
    app = QApplication.instance() or QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    _bridge = OverlayBridge()
    overlay = Overlay(_bridge)
    if visible:
        overlay.show()

    from ui import instance
    instance.listen(_bridge.remoteCommand.emit)

    # Ctrl+C in the terminal: Qt blocks Python signal handling unless the interpreter gets to run
    signal.signal(signal.SIGINT, lambda *_: quit_app())
    keepalive = QTimer()
    keepalive.timeout.connect(lambda: None)
    keepalive.start(200)

    def worker():
        try:
            aria = make_aria(_bridge)
            _bridge.aria = aria
            aria.run()
        except Exception:
            traceback.print_exc()
            _bridge.set_state("error")
            _bridge.message("aria", "I crashed — check the terminal.")

    threading.Thread(target=worker, daemon=True).start()
    sys.exit(app.exec())


if __name__ == "__main__":
    # Demo mode: `python -m ui.overlay` cycles through the states without loading Aria.
    class _Demo:
        muted = False
        def submit_text(self, text):
            _bridge.message("user", text)
            _bridge.set_state("thinking")
            QTimer.singleShot(1200, lambda: _bridge.message("aria", f"You said: {text}. Demo mode, no brain attached."))
            QTimer.singleShot(1200, lambda: _bridge.set_state("speaking"))
            QTimer.singleShot(4000, lambda: _bridge.set_state("listening"))
        def request_sleep(self): _bridge.set_state("sleeping")
        def toggle_mute(self): self.muted = not self.muted; return self.muted
        def shutdown(self): import os; os._exit(0)

    def demo(bridge):
        demo_aria = _Demo()
        time.sleep(1.5)
        script = [("sleeping", None, 3), ("unknown", None, 0.1), ("listening", None, 3),
                  ("thinking", "user:play some lana del rey", 2),
                  ("speaking", "aria:Playing tracks by Lana Del Rey.", 3), ("listening", None, 0)]
        for state, msg, wait in script:
            bridge.set_state(state)
            if msg:
                role, text = msg.split(":", 1)
                bridge.message(role, text)
            end = time.time() + wait
            while time.time() < end:  # fake audio levels
                bridge.mic = abs(math.sin(time.time() * 7)) * 0.05
                bridge.out = abs(math.sin(time.time() * 9) * math.sin(time.time() * 2.3)) * 0.25
                time.sleep(0.03)

        class _Runner:
            muted = False
            def run(self):
                while True:
                    bridge.mic = abs(math.sin(time.time() * 5)) * 0.03
                    bridge.out = abs(math.sin(time.time() * 9)) * 0.2
                    time.sleep(0.03)
        demo_aria.run = _Runner().run
        return demo_aria

    run_with_overlay(demo)
