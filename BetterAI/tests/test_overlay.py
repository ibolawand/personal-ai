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
