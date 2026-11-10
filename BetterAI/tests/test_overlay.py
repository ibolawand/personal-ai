"""The overlay, rendered off-screen (no window appears)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

pytest.importorskip("PySide6")
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QCheckBox  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def overlay(app, monkeypatch, tmp_path):
    from PySide6.QtCore import QSettings
    for fmt in (QSettings.IniFormat, QSettings.NativeFormat):        # never the real saved orb position
        QSettings.setPath(fmt, QSettings.UserScope, str(tmp_path))
    from ui.overlay import Overlay, OverlayBridge
    bridge = OverlayBridge()
    sent = []
    bridge.aria = type("A", (), {"muted": False, "submit_text": lambda self, t: sent.append(t),
                                  "quick_capture": lambda self, t: sent.append(("capture", t)),
                                  "toggle_from_card": lambda self, *a: sent.append(("toggle",) + a)})()
    o = Overlay(bridge)
    o.sent = sent
    return o


def type_and_enter(o, text):
    o.input.setText(text)
    QTest.keyClick(o.input, Qt.Key_Return)


def test_history_with_arrow_keys(overlay):
    overlay._toggle_input(True)
    type_and_enter(overlay, "first")
    type_and_enter(overlay, "second")
    overlay.input.setText("draft")
    QTest.keyClick(overlay.input, Qt.Key_Up)
    assert overlay.input.text() == "second"
    QTest.keyClick(overlay.input, Qt.Key_Up)
    assert overlay.input.text() == "first"
    QTest.keyClick(overlay.input, Qt.Key_Down)
    QTest.keyClick(overlay.input, Qt.Key_Down)
    assert overlay.input.text() == "draft"
    assert overlay.sent == ["first", "second"]


def test_capture_mode_sends_to_capture(overlay, app):
    overlay._on_remote("capture")
    assert "Quick capture" in overlay.input.placeholderText()
    type_and_enter(overlay, "buy batteries")
    app.processEvents()
    import time
    time.sleep(0.2)
    assert ("capture", "buy batteries") in overlay.sent
    assert overlay.input.placeholderText() == "Message Aria…"


def test_list_card_checkbox(overlay, app):
    overlay.bridge.show_card({"type": "list", "note_id": 7, "title": "Shopping list",
                              "items": [{"text": "eggs", "checked": False}]})
    app.processEvents()
    box = overlay.card.findChildren(QCheckBox)[0]
    box.click()
    import time
    time.sleep(0.2)
    assert ("toggle", 7, "eggs", True) in overlay.sent


# ── starting hidden (MyNotion's Start button): only the hotkey, the menu or a card shows the orb ──

def test_ping_is_an_instance_command():
    from ui import instance
    assert "ping" in instance.COMMANDS


def test_ping_leaves_a_hidden_overlay_alone(overlay):
    overlay.hide()
    overlay._on_remote("ping")
    assert not overlay.isVisible() and not overlay.input.isVisible()


def test_ping_leaves_an_open_text_box_open(overlay):
    overlay.show()
    overlay._on_remote("show")
    assert overlay.input.isVisible()
    overlay._on_remote("ping")
    assert overlay.input.isVisible()


@pytest.mark.parametrize("cmd", ["show", "toggle"])
def test_the_hotkey_shows_a_hidden_orb(overlay, cmd):
    overlay.hide()
    overlay._on_remote(cmd)
    assert overlay.isVisible()


def test_a_card_shows_a_hidden_orb(overlay, app):
    overlay.hide()
    overlay.bridge.show_card({"type": "list", "note_id": 7, "title": "Shopping list",
                              "items": [{"text": "eggs", "checked": False}]})
    app.processEvents()
    assert overlay.isVisible()


# ── a hidden Aria (fixes from the review) ──

LIST_CARD = {"type": "list", "note_id": 7, "title": "Shopping list", "items": [{"text": "eggs", "checked": False}]}


def test_a_card_from_a_panel_turn_leaves_a_hidden_orb_hidden(overlay, app):
    overlay.hide()
    with overlay.bridge.panel_turn():
        overlay.bridge.show_card(dict(LIST_CARD))
    app.processEvents()
    assert not overlay.isVisible() and overlay.card is None


def test_a_card_from_a_panel_turn_still_shows_on_a_visible_orb(overlay, app):
    overlay.show()
    with overlay.bridge.panel_turn():
        overlay.bridge.show_card(dict(LIST_CARD))
    app.processEvents()
    assert overlay.card is not None


def test_only_the_panel_thread_is_quiet(overlay, app):
    import threading
    got = []
    overlay.bridge.cardRequested.connect(lambda c: got.append(c.get("quiet", False)))
    with overlay.bridge.panel_turn():
        t = threading.Thread(target=overlay.bridge.show_card, args=({"type": "reminder", "text": "Call"},))
        t.start(); t.join()                              # a reminder from another thread meanwhile
        overlay.bridge.show_card(dict(LIST_CARD))
    overlay.bridge.show_card(dict(LIST_CARD))
    app.processEvents()
    assert sorted(got) == [False, False, True]


def test_a_hidden_orb_does_not_animate(overlay, monkeypatch):
    overlay.hide()
    painted = []
    monkeypatch.setattr(overlay, "update", lambda *a: painted.append(1))
    monkeypatch.setattr(overlay, "_update_mask", lambda *a: painted.append(1))
    overlay._tick()
    assert painted == []
