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
    assert (overlay._avatar_rect().width(), overlay._avatar_rect().height()) == (300, 520)
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
