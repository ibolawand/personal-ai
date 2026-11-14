"""Aria's avatar: when it can show, what the overlay tells the 3D page, and which props orbit her."""
import datetime as dt
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

import ui.avatar_view as A  # noqa: E402


@pytest.fixture
def ready(tmp_path):
    model = tmp_path / "aria.vrm"
    model.write_bytes(b"x")
    vendor = tmp_path / "vendor"
    vendor.mkdir()
    for name in A.VENDOR_FILES:
        (vendor / name).parent.mkdir(parents=True, exist_ok=True)
        (vendor / name).write_text("")
    return str(model), str(vendor)


def test_the_vendored_libraries_are_all_there():
    for name in A.VENDOR_FILES + ("VERSIONS.md", "LICENSE-three", "LICENSE-three-vrm"):
        assert os.path.isfile(os.path.join(A.AVATAR_DIR, "vendor", name)), name


def test_where_the_avatar_file_is(tmp_path, monkeypatch):
    assert A.avatar_path({"ARIA_AVATAR": "0"}) is None
    assert A.avatar_path({"ARIA_AVATAR": str(tmp_path / "me.vrm")}) == str(tmp_path / "me.vrm")
    monkeypatch.setattr(A, "AVATAR_DIR", str(tmp_path))
    assert A.avatar_path({}) == ""                  # nothing set and no file dropped in: her built-in figure
    (tmp_path / "aria.vrm").write_bytes(b"x")
    assert A.avatar_path({}) == str(tmp_path / "aria.vrm")      # a model dropped into ui/avatar/ is used


def test_each_missing_piece_is_named(ready, tmp_path):
    model, vendor = ready
    assert A.available(None) == (False, "switched off (ARIA_AVATAR=0)")
    gone = str(tmp_path / "nope.vrm")
    assert A.available(gone, vendor, True) == (False, f"no avatar file at {gone}")
    assert A.available(str(tmp_path), vendor, True)[0] is False                      # a folder is not a file
    assert A.available(model, str(tmp_path / "empty"), True) == (
        False, "the 3D libraries aren't installed (ui/avatar/vendor)")
    assert A.available(model, vendor, False) == (False, "QtWebEngine isn't installed")
    assert A.available(model, vendor, True) == (True, "ready to load")
    assert A.available("", vendor, True) == (True, "ready to load (built-in figure)")
    assert A.available("", str(tmp_path / "empty"), True)[0] is False


def test_the_page_and_her_figure_are_all_there():
    for name in A.PAGE_FILES:
        assert os.path.isfile(os.path.join(A.AVATAR_DIR, name)), name


NOW = dt.datetime(2026, 11, 13, 15, 0).timestamp()


def test_props_say_what_is_going_on():
    timers = [{"kind": "reminder", "text": "call mum", "due": NOW + 3600, "created": NOW},
              {"kind": "timer", "text": "tea", "due": NOW + 125, "created": NOW},
              {"kind": "focus", "text": "", "due": NOW + 900, "created": NOW}]
    assert A.props_for("listening", True, timers, NOW) == [
        {"kind": "mic", "caption": "listening"}, {"kind": "clock", "caption": "2:05 left"},
        {"kind": "note", "caption": "call mum"}]
    assert A.props_for("listening", False, [], NOW) == []
    assert A.props_for("thinking", True, [], NOW) == [{"kind": "dots", "caption": "thinking"}]


def test_past_timers_tomorrows_reminders_and_odd_texts():
    tomorrow = NOW + 20 * 3600
    timers = [{"kind": "timer", "text": "", "due": NOW - 5, "created": NOW - 60},
              {"kind": "reminder", "text": "x" * 80, "due": NOW + 60, "created": NOW},
              {"kind": "reminder", "text": "later", "due": tomorrow, "created": NOW}]
    assert A.props_for("speaking", False, timers, NOW) == [{"kind": "note", "caption": "x" * 39 + "…"}]
    blank = [{"kind": "reminder", "text": " ", "due": NOW + 60, "created": NOW}]
    assert A.props_for("speaking", False, blank, NOW) == [{"kind": "note", "caption": "reminder"}]
    assert A.props_for("speaking", False, [{"kind": "timer"}, {}, {"kind": "reminder", "due": "soon"}], NOW) == []


@pytest.fixture
def link():
    sent = []
    made = A.AvatarLink(sent.append)
    made.sent = sent
    return made


def test_calls_wait_for_the_page_and_only_the_latest_of_each_kind_is_replayed(link):
    link.set_state("thinking")
    link.set_state("speaking")
    link.set_level(0.12345, 0)
    link.hop()
    link.set_props([{"kind": "mic", "caption": "listening"}])
    link.fade(True)
    link.pause()
    link.resume()
    assert link.sent == [] and link.ready is False
    link.mark_ready()
    assert link.sent == ['window.aria.setState("speaking")',
                         'window.aria.setProps([{"kind": "mic", "caption": "listening"}])',
                         'window.aria.setLevel(0.123,0)', 'window.aria.fade(true)', 'window.aria.resume()']


def test_once_ready_calls_go_straight_through_and_repeats_are_skipped(link):
    link.mark_ready()
    link.set_state("idle")
    link.set_state("idle")
    link.look_at(0.5, -0.25)
    link.hop()
    link.fade(False)
    link.fade(False)
    assert link.sent == ['window.aria.setState("idle")', 'window.aria.lookAt(0.5,-0.25)', 'window.aria.hop()',
                         'window.aria.fade(false)']


def test_a_caption_cannot_break_out_of_the_call(link):
    link.mark_ready()
    link.set_props([{"kind": "note", "caption": 'x"); alert(1); ("'}])
    assert link.sent == ['window.aria.setProps([{"kind": "note", "caption": "x\\"); alert(1); (\\""}])']


def test_after_a_failure_nothing_is_sent(link):
    link.set_state("thinking")
    link.mark_failed("no WebGL")
    link.mark_ready()
    link.set_state("speaking")
    link.resume()
    assert link.sent == [] and link.failed == "no WebGL" and link.ready is False


def test_she_is_told_how_much_room_there_is_and_a_drag_stops_her_trip(link):
    link.set_room(120.7, 900)
    link.mark_ready()
    link.set_room(120, 900)            # unchanged: not sent again
    link.stop_trip()
    link.set_room(0, 1020)
    assert link.sent == ["window.aria.setRoom(120,900)", "window.aria.stopTrip()", "window.aria.setRoom(0,1020)"]


def test_her_window_follows_a_trip_from_where_it_began_and_stays_where_it_ends():
    travel = A.Travel()
    assert travel.follow(None, (500, 600)) is None
    assert travel.follow([1, 40.0, False], (500, 600)) is None   # a trip that ended before it was seen
    assert travel.follow([2, 0.0, True], (500, 600)) == (500, 600)   # she turns first: no distance yet
    assert travel.follow([2, -10.4, True], (500, 600)) == (490, 600)
    assert travel.follow([2, -250.0, True], (490, 600)) == (250, 600)   # from where it began, not where it is
    assert travel.follow([2, -300.0, False], (250, 600)) == (200, 600)  # the end of it
    assert travel.follow([2, -300.0, False], (200, 600)) is None        # and then nothing more
    # a jump: up 400 px onto a window, then the next trip starts from there
    assert travel.follow([3, 0, True, 0.0], (200, 600)) == (200, 600)
    assert travel.follow([3, 0, True, -120.4], (200, 600)) == (200, 480)
    assert travel.follow([3, 0, False, -400], (200, 480)) == (200, 200)
    assert travel.follow([4, 0.0, True], (200, 200)) == (200, 200)
    assert travel.follow([4, 5.0, True], (200, 200)) == (205, 200)
    travel.drop()                                               # being dragged: no longer followed
    assert travel.follow([4, 80.0, True], (900, 200)) is None


# ── the overlay switches between the orb and her (off-screen, with a view that only records) ──

pytest.importorskip("PySide6")
from PySide6.QtCore import QPoint, QSettings, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


class FakeView:
    def __init__(self):
        self.sent, self.shown, self.rect = [], False, None
        self.link = A.AvatarLink(self.sent.append)

    def show(self):
        self.shown = True

    def hide(self):
        self.shown = False

    def setGeometry(self, r):
        self.rect = r


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def stage(app, tmp_path):
    """stage(ready=True, shown=True) -> (overlay, bridge, view), with her page ready and the overlay on screen."""
    for fmt in (QSettings.IniFormat, QSettings.NativeFormat):        # never the real saved orb position
        QSettings.setPath(fmt, QSettings.UserScope, str(tmp_path))
    from ui.overlay import Overlay, OverlayBridge
    made = []

    def make(ready=True, shown=True):
        bridge, view = OverlayBridge(), FakeView()
        bridge.aria = type("Aria", (), {"muted": False, "submit_text": lambda self, t: None})()
        overlay = Overlay(bridge, make_avatar=lambda parent: view)
        made.append(overlay)
        if ready:
            view.link.mark_ready()
        if shown:
            overlay.show()
            app.processEvents()
        return overlay, bridge, view
    yield make
    for overlay in made:
        overlay.timer.stop()
        overlay.close()


def state(app, bridge, name):
    bridge.set_state(name)
    app.processEvents()


def calls(view, name):
    return [c for c in view.sent if c.startswith(f"window.aria.{name}(")]


def test_asleep_the_orb_shows_and_nothing_is_sent(app, stage):
    overlay, bridge, view = stage()
    state(app, bridge, "sleeping")
    for _ in range(5):
        overlay._tick()
    assert not overlay._shows_avatar() and not view.shown
    assert not any(calls(view, n) for n in ("setState", "setLevel", "lookAt", "setProps", "resume"))


def test_waking_brings_the_avatar_and_sleeping_takes_her_away(app, stage):
    import ui.overlay as O
    overlay, bridge, view = stage()
    state(app, bridge, "listening")
    assert overlay._shows_avatar() and view.shown
    assert view.sent[:3] == ["window.aria.resume()", "window.aria.fade(true)", "window.aria.wave()"]     # she says hello
    assert (view.rect.width(), view.rect.height()) == (300, 400)
    state(app, bridge, "sleeping")
    assert view.sent[-2:] == ["window.aria.fade(false)", "window.aria.pause()"]
    QTest.qWait(O.FADE_MS + 60)
    assert not view.shown and not overlay._shows_avatar()


def test_wake_then_sleep_then_wake_inside_the_fade_ends_with_her_shown(app, stage):
    import ui.overlay as O
    overlay, bridge, view = stage()
    for name in ("listening", "sleeping", "thinking"):
        state(app, bridge, name)
    QTest.qWait(O.FADE_MS + 60)
    assert view.shown and overlay._shows_avatar() and calls(view, "fade")[-1] == "window.aria.fade(true)"


def test_a_flash_while_asleep_does_not_show_her_and_while_awake_makes_her_hop(app, stage):
    overlay, bridge, view = stage()
    state(app, bridge, "sleeping")
    state(app, bridge, "alert")
    assert not view.shown and calls(view, "hop") == []
    state(app, bridge, "listening")
    state(app, bridge, "alert")
    assert view.shown and calls(view, "hop") == ["window.aria.hop()"]


def test_until_the_page_is_ready_the_orb_stays_then_she_comes(app, stage):
    overlay, bridge, view = stage(ready=False)
    state(app, bridge, "listening")
    assert not overlay._shows_avatar() and not view.shown
    view.link.mark_ready()
    overlay._tick()
    assert overlay._shows_avatar() and view.shown


def test_a_failure_is_logged_once_and_the_orb_stays(app, stage, monkeypatch):
    from Engines import Diagnostics
    seen = []
    monkeypatch.setattr(Diagnostics, "problem", lambda kind, detail="": seen.append((kind, detail)))
    overlay, bridge, view = stage(ready=False)
    state(app, bridge, "listening")
    view.link.mark_failed("no WebGL")
    for _ in range(3):
        overlay._tick()
    state(app, bridge, "thinking")
    assert seen == [("avatar", "no WebGL")] and bridge.avatar_status == "no WebGL"
    assert not overlay._shows_avatar() and not view.shown


def test_a_hidden_overlay_never_resumes_her_and_showing_it_does(app, stage):
    overlay, bridge, view = stage(shown=False)
    state(app, bridge, "listening")
    overlay._tick()
    assert calls(view, "resume") == [] and not view.shown
    overlay.show()
    app.processEvents()
    assert calls(view, "resume") == ["window.aria.resume()"] and view.shown
    overlay.hide()
    app.processEvents()
    assert view.sent[-1] == "window.aria.pause()"


def test_she_is_told_the_state_the_microphone_and_the_props(app, stage):
    import json
    import time
    overlay, bridge, view = stage()
    bridge.set_mic_open(True)
    bridge.timers = [{"kind": "timer", "text": "tea", "due": time.time() + 120, "created": time.time()}]
    state(app, bridge, "listening")
    overlay._tick()
    assert 'window.aria.setState("listening")' in view.sent
    props = json.loads(calls(view, "setProps")[-1][len("window.aria.setProps("):-1])
    assert [p["kind"] for p in props] == ["mic", "clock"]


def test_levels_and_mouse_are_rate_limited(app, stage, monkeypatch):
    import ui.overlay as O
    overlay, bridge, view = stage()
    state(app, bridge, "speaking")
    overlay.timer.stop()                # only the ticks below count
    clock = [1000.0]
    monkeypatch.setattr(O.time, "monotonic", lambda: clock[0])
    overlay._last_tick, overlay._fed = 1000.0, {"level": 0.0, "look": 0.0, "props": 0.0}
    del view.sent[:]
    for i in range(100):
        clock[0] = 1000.0 + i / 100
        bridge.out = 0.1 + i / 1000         # a new level every tick
        overlay._tick()
    assert 1 <= len(calls(view, "setLevel")) <= 20 and 1 <= len(calls(view, "lookAt")) <= 15
    assert len(calls(view, "setProps")) <= 1


def test_without_an_avatar_the_window_and_the_orb_are_as_before(app, tmp_path):
    import ui.overlay as O
    for fmt in (QSettings.IniFormat, QSettings.NativeFormat):
        QSettings.setPath(fmt, QSettings.UserScope, str(tmp_path))
    overlay = O.Overlay(O.OverlayBridge())
    overlay.timer.stop()
    assert (overlay.width(), overlay.height()) == (O.WIN_W, O.WIN_H)
    assert overlay._anchor_rect() == overlay._orb_rect() and not overlay._shows_avatar()
    crashing = O.Overlay(O.OverlayBridge(), make_avatar=lambda parent: 1 / 0)       # a view that can't be made
    crashing.timer.stop()
    assert crashing.avatar is None and (crashing.width(), crashing.height()) == (O.WIN_W, O.WIN_H)


def test_with_an_avatar_the_window_is_taller_and_stays_on_screen(app, stage, tmp_path):
    import ui.overlay as O
    screen = QApplication.primaryScreen().availableGeometry()
    # the orb was parked so that the old window's top touched the top of the screen
    QSettings("Aria", "overlay").setValue("corner", QPoint(screen.left() + O.WIN_W + 10, screen.top() + O.WIN_H))
    overlay, bridge, view = stage(shown=False)
    assert (overlay.width(), overlay.height()) == (O.WIN_W, O.WIN_H + O.AVATAR_H - O.ORB_BOX)
    assert overlay.y() >= screen.top()
    state(app, bridge, "listening")
    assert overlay._anchor_rect() == overlay._orb_rect()        # hidden: still the orb's layout


def test_clicking_her_opens_the_text_box(app, stage):
    overlay, bridge, view = stage()
    state(app, bridge, "listening")
    assert overlay._anchor_rect() == overlay._avatar_rect()
    QTest.mouseClick(overlay, Qt.LeftButton, pos=overlay._avatar_rect().center() - QPoint(0, 60))
    assert overlay.input.isVisible()
    assert not overlay._in_orb(overlay._avatar_rect().topLeft() + QPoint(4, 4))     # the box's corner isn't her


# ── clicks land on her outline, not on her whole box (ui/xshape.py) ──

def test_the_click_area_follows_her_outline_not_her_box(app):
    from PySide6.QtCore import QRect
    from ui.xshape import avatar_click_rects
    box = QRect(100, 200, 300, 400)
    rects = avatar_click_rects(box)
    assert rects and all(box.contains(r) for r in rects)
    assert max(r.bottom() for r in rects) <= box.top() + 0.8 * box.height() + 1
    area = sum(r.width() * r.height() for r in rects)
    assert 0.38 * box.width() * box.height() < area < 0.5 * box.width() * box.height()  # an ellipse hugging her
    assert not any(r.contains(QPoint(box.left() + 12, box.top() + 200)) for r in rects)  # beside her shoulder
    assert not any(r.contains(box.topLeft() + QPoint(3, 3)) for r in rects)              # the corners stay click-through


def test_setting_the_input_shape_never_raises(monkeypatch):
    import ui.xshape as X
    monkeypatch.setattr(X, "_x", {})
    monkeypatch.setattr(X.ctypes.util, "find_library", lambda name: None)
    assert X.set_input_rects(0, []) is False and X.clear_input_rects(0) is False


@pytest.fixture
def shaped(monkeypatch):
    """Pretend to be on X11 and record what the overlay asks of ui/xshape."""
    import ui.overlay as O
    import ui.xshape as X
    asked = {"set": [], "cleared": 0, "works": True}
    monkeypatch.setattr(O.QGuiApplication, "platformName", staticmethod(lambda: "xcb"))
    monkeypatch.setattr(X, "set_input_rects", lambda win, rects: asked["set"].append(list(rects)) or asked["works"])
    monkeypatch.setattr(X, "clear_input_rects", lambda win: asked.__setitem__("cleared", asked["cleared"] + 1) or True)
    return asked


def test_awake_the_picture_is_not_clipped_and_clicks_get_her_outline(app, stage, shaped):
    from ui.xshape import avatar_click_rects
    overlay, bridge, view = stage()
    state(app, bridge, "listening")
    overlay._update_mask()
    assert overlay.mask().boundingRect() == overlay.rect() and overlay.mask().rectCount() == 1    # nothing is cut away
    strips = avatar_click_rects(overlay._avatar_rect())
    assert shaped["set"] and all(s in shaped["set"][-1] for s in strips)


def test_without_xfixes_her_whole_box_takes_clicks_and_the_self_check_says_so(app, stage, shaped):
    shaped["works"] = False
    overlay, bridge, view = stage()
    state(app, bridge, "listening")
    overlay._update_mask()
    assert overlay.mask().contains(overlay._avatar_rect().topLeft() + QPoint(3, 3))
    assert bridge.avatar_status == "showing, but clicks beside her are blocked (XFixes missing)"


def test_back_to_the_orb_the_old_mask_is_used(app, stage, shaped):
    overlay, bridge, view = stage()
    state(app, bridge, "listening")
    overlay._update_mask()
    state(app, bridge, "sleeping")
    overlay._update_mask()
    assert shaped["cleared"] == 1 and not overlay.mask().isEmpty()
    assert not overlay.mask().contains(overlay._avatar_rect().topLeft() + QPoint(3, 3))


def test_a_view_can_ask_for_a_taller_box(app, tmp_path):
    import ui.overlay as O
    for fmt in (QSettings.IniFormat, QSettings.NativeFormat):
        QSettings.setPath(fmt, QSettings.UserScope, str(tmp_path))
    view = FakeView()
    view.box = A.BOX_MODEL                      # what make_view sets for a loaded .vrm
    overlay = O.Overlay(O.OverlayBridge(), make_avatar=lambda parent: view)
    overlay.timer.stop()
    assert (overlay._avatar_rect().width(), overlay._avatar_rect().height()) == A.BOX_MODEL
    assert overlay.height() == O.WIN_H + 520 - O.ORB_BOX
    assert overlay._avatar_rect().bottomRight() == overlay._orb_rect().bottomRight()


class WalkingView(FakeView):
    """A view whose page reports a walk across the screen."""
    report = None

    def ask_travel(self, answer):
        answer(self.report)


def test_her_window_walks_with_her_and_a_drag_lets_go(app, stage):
    from ui.overlay import Overlay, OverlayBridge
    overlay, bridge, _ = stage(shown=False)
    view = WalkingView()
    overlay = Overlay(bridge, make_avatar=lambda parent: view)
    try:
        view.link.mark_ready()
        overlay.show()
        state(app, bridge, "idle")
        overlay._tick()
        room = calls(view, "setRoom")
        assert room, "she is told the room beside her"
        x0 = overlay.x()
        view.report = [1, 0.0, True]
        overlay._tick()
        view.report = [1, -37.6, True]
        overlay._tick()
        assert overlay.x() == x0 - 38
        # picked up on the way: she stops and her window goes where it is dragged
        start = overlay._avatar_rect().center() - QPoint(0, 60)
        QTest.mousePress(overlay, Qt.LeftButton, pos=start)
        QTest.mouseMove(overlay, start + QPoint(30, 0))
        assert calls(view, "stopTrip")
        QTest.mouseRelease(overlay, Qt.LeftButton, pos=start + QPoint(30, 0))
        moved = overlay.x()
        view.report = [1, -80.0, True]
        overlay._tick()
        assert overlay.x() == moved
    finally:
        overlay.timer.stop()
        overlay.close()


class PerchingView(WalkingView):
    """A view whose page sits 200 px above the bottom of her box when she is on a window."""
    def ask_seat_height(self, answer):
        answer(200.0)


def test_she_is_told_where_to_sit_rides_along_with_the_window_and_hops_down_when_it_goes(app, stage, monkeypatch):
    import json
    import ui.desktop_windows as D
    from ui.overlay import Overlay, OverlayBridge
    _, bridge, _ = stage(shown=False)
    view = PerchingView()
    overlay = Overlay(bridge, make_avatar=lambda parent: view)
    try:
        view.link.mark_ready()
        overlay.show()
        state(app, bridge, "idle")
        screen = overlay.screen().availableGeometry()
        overlay.move(screen.left() + 100 - (overlay.width() - overlay.avatar_w), screen.bottom() - overlay.height())
        app.processEvents()
        box = overlay._avatar_rect().translated(overlay.pos())
        windows = [D.Win(7, box.center().x() - 250, box.bottom() - 450, box.center().x() + 250, box.bottom() - 100)]
        monkeypatch.setattr(D, "open_windows", lambda own=None: list(windows))
        overlay.timer.stop()
        overlay._fed["seats"] = 0.0
        overlay._tick()
        sent = calls(view, "setSeats")
        assert sent, "she is told where she could sit"
        seats = json.loads(sent[-1][len("window.aria.setSeats("):].rsplit(",", 1)[0])
        assert seats and seats[0]["y"] == -450 and abs(seats[0]["x"]) <= seats[0]["half"]   # a stretch right over her
        # she jumps up 250 px (the edge is 450 px up, her seat 200 px above the bottom of her box) and lands
        y0 = overlay.y()
        view.report = [5, 0, True, 0.0]
        overlay._tick()
        view.report = [5, 0, False, -250.0]
        overlay._tick()
        assert overlay.y() == y0 - 250 and overlay._perch and overlay._perch[0] == 7
        # the window moves: she rides along
        windows[0] = D.Win(7, windows[0].left + 40, windows[0].top - 20, windows[0].right + 40, windows[0].bottom - 20)
        x1 = overlay.x()
        overlay._fed["seats"] = 0.0
        overlay._tick()
        assert (overlay.x(), overlay.y()) == (x1 + 40, y0 - 270)
        assert calls(view, "setSeats")[-1].endswith(",270)"), "and knows how far down the floor is"
        # it goes away: she hops down
        windows.clear()
        overlay._fed["seats"] = 0.0
        overlay._tick()
        assert calls(view, "dropDown") and overlay._perch is None
    finally:
        overlay.timer.stop()
        overlay.close()


# ── peeking out from behind an app ──

class HidingView(PerchingView):
    """A page that reports which window she is behind."""
    behind = None

    def ask_travel(self, answer):
        answer(self.report, self.behind)


@pytest.fixture
def hiding(app, stage, monkeypatch):
    """(overlay, view, windows, tick): her overlay on the screen with fake windows (a list to change)."""
    import ui.desktop_windows as D
    from ui.overlay import Overlay
    _, bridge, _ = stage(shown=False)
    view = HidingView()
    overlay = Overlay(bridge, make_avatar=lambda parent: view)
    view.link.mark_ready()
    overlay.show()
    state(app, bridge, "idle")
    screen = overlay.screen().availableGeometry()
    overlay.move(screen.left() + 300 - (overlay.width() - overlay.avatar_w), screen.bottom() - overlay.height())
    app.processEvents()
    overlay.timer.stop()
    windows = []
    monkeypatch.setattr(D, "open_windows", lambda own=None: list(windows))
    monkeypatch.setattr(D, "window_rect", lambda wid: next((w for w in windows if w.id == wid), None))
    from PySide6.QtCore import QRect
    monkeypatch.setattr(overlay, "_screen_area", lambda: QRect(0, 0, 1920, 1040))   # a real-size screen

    def tick():
        overlay._fed["seats"] = 0.0
        overlay._fed["cover"] = 0.0
        overlay._tick()
    yield overlay, view, windows, tick
    overlay.close()


def tall(overlay, wid, left, right):
    """A window from above her head to below her feet, `left`/`right` px from the middle of her box."""
    import ui.desktop_windows as D
    box = overlay._avatar_rect().translated(overlay.pos())
    return D.Win(wid, box.center().x() + left, box.top() - 20, box.center().x() + right, box.bottom() + 20)


def last_json(view, name):
    import json
    sent = calls(view, name)
    return json.loads(sent[-1][len(f"window.aria.{name}("):-1]) if sent else "nothing sent"


def test_she_is_told_where_she_could_hide(hiding):
    overlay, view, windows, tick = hiding
    windows.append(tall(overlay, 3, 150, 400))
    tick()
    assert last_json(view, "setHideouts") == [{"id": 3, "x": 150, "out": -1}, {"id": 3, "x": 400, "out": 1}]


def test_a_window_raised_over_her_hides_her_and_she_is_told(hiding):
    overlay, view, windows, tick = hiding
    tick()                                       # what was there before doesn't count
    assert not calls(view, "hiddenBy")
    windows.append(tall(overlay, 4, -100, 250))
    tick()
    assert last_json(view, "hiddenBy") == {"id": 4, "left": -100, "right": 250}
    tick()
    assert len(calls(view, "hiddenBy")) == 1, "once, not every time we look"


def test_while_behind_the_cut_out_follows_the_window_and_goes_with_it(hiding):
    import ui.desktop_windows as D
    overlay, view, windows, tick = hiding
    win = tall(overlay, 5, -100, 250)
    windows.append(win)
    view.behind = 5
    tick()
    box = overlay._avatar_rect().translated(overlay.pos())
    assert last_json(view, "setCover") == {"left": win.left - box.left(), "top": win.top - box.top(),
                                           "right": win.right - box.left(), "bottom": win.bottom - box.top()}
    windows[0] = D.Win(5, win.left + 30, win.top, win.right + 30, win.bottom)
    tick()
    assert last_json(view, "setCover")["left"] == win.left + 30 - box.left()
    windows.clear()                              # closed: all of her shows again
    tick()
    assert calls(view, "setCover")[-1] == "window.aria.setCover(null)"


def test_no_hiding_reaction_while_up_on_a_window_or_walking(hiding):
    overlay, view, windows, tick = hiding
    tick()
    overlay._aloft = True
    windows.append(tall(overlay, 6, -100, 250))
    tick()
    overlay._aloft = False
    overlay._travel.done = False                 # walking somewhere
    windows.append(tall(overlay, 7, -120, 260))
    tick()
    assert not calls(view, "hiddenBy")


def test_a_drag_while_behind_removes_the_cut_out(hiding):
    overlay, view, windows, tick = hiding
    windows.append(tall(overlay, 8, -100, 250))
    view.behind = 8
    tick()
    start = overlay._avatar_rect().center() - QPoint(0, 60)
    QTest.mousePress(overlay, Qt.LeftButton, pos=start)
    QTest.mouseMove(overlay, start + QPoint(30, 0))
    QTest.mouseRelease(overlay, Qt.LeftButton, pos=start + QPoint(30, 0))
    assert calls(view, "setCover")[-1] == "window.aria.setCover(null)"


def test_clicks_on_the_hidden_part_of_her_go_to_the_app():
    from PySide6.QtCore import QRect
    from ui.xshape import avatar_click_rects
    box, hole = QRect(0, 0, 300, 520), QRect(150, 0, 200, 600)
    rects = avatar_click_rects(box, hole=hole)
    assert rects and not any(r.intersects(hole) for r in rects)
    assert any(r.right() > 140 for r in rects), "the part beside the hole still takes clicks"


def test_when_the_app_she_is_behind_goes_she_is_told_and_just_stands_there(hiding):
    overlay, view, windows, tick = hiding
    windows.append(tall(overlay, 9, -100, 250))
    view.behind = 9
    tick()
    windows.clear()
    tick()
    assert calls(view, "unhide"), "she stops peeking at nothing"


def test_when_the_app_moves_off_her_she_is_told_too(hiding):
    import ui.desktop_windows as D
    overlay, view, windows, tick = hiding
    win = tall(overlay, 10, -100, 250)
    windows.append(win)
    view.behind = 10
    tick()
    windows[0] = D.Win(10, win.left + 2000, win.top, win.right + 2000, win.bottom)
    tick()
    assert calls(view, "unhide")


def test_a_late_report_during_a_drag_does_not_bring_the_cut_out_back(hiding):
    overlay, view, windows, tick = hiding
    windows.append(tall(overlay, 11, -100, 250))
    start = overlay._avatar_rect().center() - QPoint(0, 60)
    QTest.mousePress(overlay, Qt.LeftButton, pos=start)
    QTest.mouseMove(overlay, start + QPoint(30, 0))
    overlay._on_travel(None, 11)                 # sent before the drag, arriving now
    assert overlay._behind is None
    QTest.mouseRelease(overlay, Qt.LeftButton, pos=start + QPoint(30, 0))


def test_the_cut_out_reads_only_that_window(hiding, monkeypatch):
    import ui.desktop_windows as D
    overlay, view, windows, tick = hiding
    windows.append(tall(overlay, 12, -100, 250))
    view.behind = 12
    tick()
    monkeypatch.setattr(D, "open_windows", lambda own=None: (_ for _ in ()).throw(AssertionError("all windows read")))
    overlay._fed["cover"] = 0.0
    overlay._fed["seats"] = overlay._fed["room"] = 10_000.0
    overlay._feed_avatar(10_000.0)               # only the cover is due
    assert calls(view, "setCover")


def test_edges_her_box_cannot_reach_on_the_screen_are_left_out(hiding):
    overlay, view, windows, tick = hiding
    screen = overlay._screen_area()
    box = overlay._avatar_rect().translated(overlay.pos())
    off = screen.left() - box.center().x() + 40      # an edge 40 px from the screen's left: her box can't get there
    windows.append(tall(overlay, 13, off, 150))
    tick()
    assert [e["x"] for e in last_json(view, "setHideouts")] == [150]


def test_raised_over_her_with_one_edge_off_the_screen_she_goes_to_the_other(hiding):
    overlay, view, windows, tick = hiding
    screen = overlay._screen_area()
    box = overlay._avatar_rect().translated(overlay.pos())
    tick()
    windows.append(tall(overlay, 14, screen.left() - box.center().x() - 50, 300))
    tick()
    got = last_json(view, "hiddenBy")
    assert got["right"] == 300 and abs(got["left"]) > 10_000, "the edge off the screen is out of the question"


# ── her window hugs her box, and grows round her only while something else is up ──

def test_with_nothing_else_up_the_window_is_her_box(hiding):
    overlay, view, windows, tick = hiding
    tick()
    assert overlay.size() == overlay._avatar_rect().size() and overlay._avatar_rect().topLeft() == QPoint(0, 0)


def test_the_text_box_widens_the_window_round_her_without_moving_her(hiding):
    overlay, view, windows, tick = hiding
    tick()
    before = overlay._box_screen
    overlay._toggle_input(True)
    tick()
    assert overlay.width() > overlay.avatar_w and overlay._box_screen == before
    assert overlay._avatar_rect().translated(overlay.pos()).topLeft() == before
    assert overlay._input_rect().right() < overlay.width() and overlay._input_rect().left() >= 0


def test_at_the_left_and_top_of_the_screen_the_wide_window_still_fits(hiding):
    overlay, view, windows, tick = hiding
    overlay._place(QPoint(10, 20))              # her box near the top-left corner of the screen
    overlay._toggle_input(True)
    tick()
    assert overlay.x() >= 0 and overlay.y() >= 0, "the window manager would push it back (and her with it)"
    assert overlay._avatar_rect().translated(overlay.pos()).topLeft() == QPoint(10, 20)


def test_an_unused_text_box_closes_and_while_open_she_stays_put(hiding, monkeypatch):
    import ui.overlay as O
    overlay, view, windows, tick = hiding
    overlay._toggle_input(True)
    tick()
    assert calls(view, "setEngaged")[-1] == "window.aria.setEngaged(true)"
    overlay._input_used -= O.INPUT_IDLE_S + 1
    tick()
    assert not overlay.input.isVisible()
    tick()
    assert calls(view, "setEngaged")[-1] == "window.aria.setEngaged(false)"
    assert overlay.size() == overlay._avatar_rect().size()


def test_a_text_box_with_something_typed_stays(hiding):
    import ui.overlay as O
    overlay, view, windows, tick = hiding
    overlay._toggle_input(True)
    overlay.input.setText("half a sent")
    overlay._input_used -= O.INPUT_IDLE_S + 1
    tick()
    assert overlay.input.isVisible()


# ── high up: her box may stick out above the screen (only empty space above her head is cut off) ──

class HeadroomView(HidingView):
    """A page whose seat is 230 px above the bottom of her box, with her head 200 px above that."""
    def ask_seat_height(self, answer):
        answer(230.0, 200.0)


@pytest.fixture
def high(hiding, monkeypatch):
    overlay, view, windows, tick = hiding
    overlay.avatar.__class__ = HeadroomView
    overlay._seat_h = None
    return overlay, view, windows, tick


def test_a_window_high_on_the_screen_is_a_seat_when_her_head_fits_above_it(high):
    import json
    import ui.desktop_windows as D
    overlay, view, windows, tick = high
    box = overlay._avatar_rect().translated(overlay.pos())
    windows.append(D.Win(20, box.center().x() - 300, 230, box.center().x() + 300, 800))   # 230 px from the top
    tick()
    tick()
    seats = json.loads(calls(view, "setSeats")[-1][len("window.aria.setSeats("):].rsplit(",", 1)[0])
    assert seats and seats[0]["y"] == 230 - box.bottom()


def test_her_box_sticks_out_above_the_screen_but_the_window_stays_on_it(high):
    overlay, view, windows, tick = high
    overlay._place(QPoint(400, -150))            # perched high: the top 150 px of her box is above the screen
    tick()
    assert overlay.y() >= 0, "the window manager would push the window (and her) down"
    assert overlay._avatar_rect().translated(overlay.pos()).topLeft() == QPoint(400, -150)
    assert overlay.height() == overlay.avatar_h - 150
    overlay._toggle_input(True)                  # and with the text box up
    tick()
    assert overlay.y() >= 0 and overlay._avatar_rect().translated(overlay.pos()).topLeft() == QPoint(400, -150)


# ── an app maximized: she may sit on the top edge of the bottom panel ──

def panel_seats(view):
    import json
    seats = json.loads(calls(view, "setSeats")[-1][len("window.aria.setSeats("):].rsplit(",", 1)[0])
    return [s for s in seats if s.get("low")]


def test_with_an_app_maximized_the_top_of_the_panel_is_a_seat(high, monkeypatch):
    import ui.desktop_windows as D
    overlay, view, windows, tick = high
    overlay._place(QPoint(400, 1040 - overlay.avatar_h - 14))      # standing on her floor
    monkeypatch.setattr(D, "any_maximized", lambda own=None: False)
    tick()
    tick()
    assert panel_seats(view) == []
    monkeypatch.setattr(D, "any_maximized", lambda own=None: True)
    tick()
    seat = panel_seats(view)
    assert seat and seat[0]["y"] == 1040 - (overlay._box_screen.y() + overlay.avatar_h) and abs(seat[0]["x"]) <= seat[0]["half"]


def test_sitting_down_on_the_panel_her_box_reaches_below_it_and_the_window_does_not(high, monkeypatch):
    import ui.desktop_windows as D
    overlay, view, windows, tick = high
    monkeypatch.setattr(D, "any_maximized", lambda own=None: True)
    floor = 1040 - overlay.avatar_h - 14
    overlay._place(QPoint(400, floor))
    tick()
    tick()
    view.report = [7, 0, True, 0.0]
    tick()
    view.report = [7, 0, False, 244.0]                              # sat down onto the edge: 244 px lower
    tick()
    assert overlay._box_screen.y() == floor + 244
    assert overlay.y() + overlay.height() <= 1040, "the window stays in the work area"
    assert overlay._aloft and overlay._perch and overlay._perch[0] == 0, "up on a seat (the panel)"
    tick()
    assert calls(view, "setSeats")[-1].endswith(",-244)"), "her floor is 244 px above her now"
    assert not calls(view, "dropDown"), "the panel doesn't go away"
