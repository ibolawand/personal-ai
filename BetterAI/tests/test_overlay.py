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


def test_settings_dialog_validates_and_saves(app, tmp_path):
    from Engines.Preferences import Preferences
    from ui.settings import SettingsDialog
    prefs = Preferences(path=tmp_path / "settings.json")
    aria = type("A", (), {"settings_snapshot": lambda self: prefs.values,
                           "save_settings": lambda self, values: prefs.save(values)})()
    dialog = SettingsDialog(aria)
    dialog.quiet.setText("bad time")
    dialog.save()
    assert dialog.error.text() and not prefs.path.exists()
    dialog.quiet.setText("23:00-07:00")
    dialog.checks["claude"].setChecked(False)
    dialog.save()
    assert not Preferences(path=prefs.path).values["claude"]
    assert dialog.result() == dialog.DialogCode.Accepted


def test_diagnostics_card_renders_as_plain_text(overlay, app):
    from PySide6.QtWidgets import QLabel
    overlay.bridge.show_card({"type": "diagnostics", "title": "How Aria is running",
                              "text": "2.0 s typical\nMyNotion: set DB_PATH\n<literal>"})
    app.processEvents()
    labels = overlay.card.findChildren(QLabel)
    assert any("<literal>" in label.text() and label.textFormat() == Qt.PlainText for label in labels)


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


def test_the_bridge_reports_the_microphone_only_when_it_changes(app):
    from ui.overlay import OverlayBridge
    b, seen = OverlayBridge(), []
    b.micOpenChanged.connect(seen.append)
    assert b.mic_open is False
    b.set_mic_open(True); b.set_mic_open(True); b.set_mic_open(False)
    app.processEvents()
    assert seen == [True, False] and b.mic_open is False


def test_typing_in_the_box_tells_aria_you_are_still_there(overlay):
    """She fell asleep (back to the orb) while you were writing a long answer: the conversation's minute ran out."""
    import time
    assert overlay.bridge.typed_at == 0.0
    QTest.keyClicks(overlay.input, "wait")
    assert time.monotonic() - overlay.bridge.typed_at < 1


def test_a_click_on_her_is_felt_once_and_a_drag_is_not(overlay, monkeypatch):
    from types import SimpleNamespace
    from PySide6.QtCore import QPoint
    taps = []
    overlay.avatar = SimpleNamespace(link=SimpleNamespace(tapped=lambda: taps.append(1), carried=lambda *a: None))
    monkeypatch.setattr(overlay, "_shows_avatar", lambda: True)
    monkeypatch.setattr(overlay, "_save_position", lambda: None)
    release = SimpleNamespace(button=lambda: Qt.LeftButton)
    overlay._drag_from, overlay._dragged = QPoint(0, 0), False            # pressed on her, not moved: a click
    overlay.mouseReleaseEvent(release)
    assert taps == [1]
    overlay._drag_from, overlay._dragged = QPoint(0, 0), True             # pressed on her and moved: a drag
    overlay.mouseReleaseEvent(release)
    assert taps == [1]
    overlay.mouseReleaseEvent(release)                                    # a release with no press on her
    assert taps == [1]


def test_seats_are_only_measured_standing_and_a_missed_window_is_not_jumped_at_again(overlay, monkeypatch):
    """The jump-sit-jump loop: seats measured while she was in the air sent her jumping short of the window; she
    was dropped and jumped at it again and again."""
    import time
    from types import SimpleNamespace
    from PySide6.QtCore import QRect
    from ui.desktop_windows import Seat, Win
    import ui.overlay as ov
    win = Win(7, 138, 241, 1578, 900)
    screen = QRect(0, 0, 1920, 1040)
    monkeypatch.setattr(overlay, "_seats_here", lambda: ([win], [Seat(7, 138, 1578, 241)], screen))
    monkeypatch.setattr(ov, "any_maximized", lambda own=None: False, raising=False)
    import ui.desktop_windows as dw
    monkeypatch.setattr(dw, "any_maximized", lambda own=None: False)
    sent = []
    link = SimpleNamespace(set_hideouts=lambda e: None, hidden_by=lambda *a: None, startle=lambda s: None,
                           set_seats=lambda seats, floor: sent.append(seats), drop_down=lambda: sent.append("drop"))
    overlay._seat_h, overlay._headroom = 177, 200
    overlay._watch_seats(link)                                  # standing on her floor: the window is a seat
    assert sent[-1] and sent[-1][0]["y"] < 0
    overlay._aloft = True                                       # up in the air (landed nowhere): no seats measured
    clock = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    overlay._watch_seats(link)
    assert sent[-1] == []
    clock[0] += ov.SEAT_LOST_S + 0.1
    overlay._watch_seats(link)                                  # still no window under her: dropped
    assert "drop" in sent
    overlay._aloft, overlay._perch, overlay._dropping = False, None, False   # back on her floor
    overlay._watch_seats(link)
    assert sent[-1] == [], "the window she missed is not offered again straight away"
    clock[0] += ov.SEAT_BAN_S + 1
    overlay._watch_seats(link)
    assert sent[-1], "after a while it is a seat again"
