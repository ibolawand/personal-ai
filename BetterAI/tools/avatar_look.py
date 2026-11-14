"""
See Aria's avatar without starting Aria: shows her page in a small window on a plain background, runs a script of
calls on it and saves a screenshot after each named step. For tuning how she looks and moves (the tests only cover
the decisions, not the picture).

    .venv/bin/python tools/avatar_look.py OUTDIR [--model FILE.vrm | --figure] STEP...

--seat X,Y,W,H opens a plain window there for her to sit on ("perch").
A STEP is  "javascript|milliseconds|name" ("name*N" films N shots of the screen's width, 150 ms apart):  at that many milliseconds run the JavaScript (may be empty), and if a
name is given save OUTDIR/name.png 350 ms later. Without --model or --figure she is whoever Aria would show.

    tools/avatar_look.py /tmp/shots 'window.aria.act("stroll")|3000|' '|3800|stride' '|4600|turning'
    tools/avatar_look.py /tmp/shots --figure 'window.aria.setState("thinking")|2500|thinking'

A step's JavaScript can also measure: push onto window.ariaLog and it is printed at the end, for example
    '(window.ariaLog ||= []).push(window.aria.where("rightHand", "rightLowerArm"))|4500|'

Calls: window.aria.setState("listening|thinking|speaking|idle"), setLevel(mic, out), lookAt(x, y), setProps([...]),
wave(), hop(), act("trip" (across the screen; the window goes along) | "perch" | "hopDown" | "stroll" | "strollPeek" | "sit:1" | "stand" | a fidget like "curious:-1"),
tune({bone: [x, y, z, twist]}) to pin bones while fitting a pose (tune() lets go). Her pose waits for the
model: act on it after about 3000 ms.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import Qt, QTimer  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from ui import avatar_view  # noqa: E402


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    out, args = argv[0], argv[1:]
    path = avatar_view.avatar_path() or ""
    if args[0] == "--figure":
        path, args = "", args[1:]
    elif args[0] == "--model":
        path, args = args[1], args[2:]
    seat_at = None
    if args and args[0] == "--seat":                # a plain window at X,Y,W,H for her to sit on
        seat_at, args = [int(v) for v in args[1].split(",")], args[2:]
    steps = [a.rsplit("|", 2) for a in args]
    os.makedirs(out, exist_ok=True)

    app = QApplication(sys.argv[:1])
    win = QWidget(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
    win.setStyleSheet("background: #4a5568")
    view = avatar_view.make_view(win, path)
    w, h = view.box
    screen = QGuiApplication.primaryScreen()
    area = screen.availableGeometry()
    win.setGeometry(area.right() - w - 60, area.bottom() - h - 60, w, h)
    view.setGeometry(0, 0, w, h)
    view.show()
    win.show()
    view.link.resume()
    view.link.fade(True)
    if seat_at:
        bench = QWidget(None)
        bench.setWindowTitle("A window to sit on")
        bench.setStyleSheet("background: #e8e6f0")
        bench.setGeometry(*seat_at)
        bench.show()
        win.raise_()

    def shoot(name):
        screen.grabWindow(0, win.x(), win.y(), w, h).save(os.path.join(out, name + ".png"))

    def shoot_wide(name):
        screen.grabWindow(0, area.left(), area.top(), area.width(), area.height()).save(os.path.join(out, name + ".png"))

    # her walks across the screen move this window, as they move the overlay's (ui/avatar_view.Travel)
    travel = avatar_view.Travel()

    floor = [None]
    seat_h = [None]
    view.ask_seat_height(lambda px: seat_h.__setitem__(0, px))

    def follow():
        box = win.geometry()
        view.link.set_room(box.left() - area.left(), area.right() - box.right())
        view.ask_travel(lambda report: (at := travel.follow(report, (win.x(), win.y()))) is not None and win.move(*at))
        if seat_h[0] is None:
            view.ask_seat_height(lambda px: seat_h.__setitem__(0, px))
            return
        # the seats on the windows that are open, as the overlay works them out (ui/overlay.py _watch_seats)
        from ui.desktop_windows import open_windows, seats
        if floor[0] is None or travel.done and abs(win.y() - floor[0]) < 2:
            floor[0] = win.y()
        free = seats(open_windows(own=int(win.winId())), (area.left(), area.top(), area.right(), area.bottom()),
                     above=int(h - seat_h[0]) + 4)
        out_ = [{"x": (s.left + s.right) // 2 - box.center().x(), "half": (s.right - s.left) // 2, "y": s.top - box.bottom()}
                for s in free]
        view.link.set_seats(out_, max(0, floor[0] - win.y()))
    walker = QTimer(win)
    walker.timeout.connect(follow)
    walker.start(16)

    for js, at, name in steps:
        if js:
            QTimer.singleShot(int(at), lambda js=js: view.page().runJavaScript(js))
        if name and "*" in name:            # "name*N": N shots of the whole width of the screen, 150 ms apart
            stem, n = name.split("*")
            for i in range(int(n)):
                QTimer.singleShot(int(at) + 150 * i, lambda f=f"{stem}{i:02d}": shoot_wide(f))
        elif name:
            QTimer.singleShot(int(at) + 350, lambda name=name: shoot(name))
    end = max(int(at) + (150 * int(name.split("*")[1]) if "*" in name else 0) for _, at, name in steps) + 900

    def report(status):
        print(f"page: {status} | link ready: {view.link.ready} | failed: {view.link.failed}")
        app.quit()
    QTimer.singleShot(end, lambda: view.page().runJavaScript(
        "String(window.ariaStatus) + ' / model: ' + String(window.ariaModel)"
        " + (window.ariaLog ? '\\nlog: ' + JSON.stringify(window.ariaLog) : '')", report))
    QTimer.singleShot(end + 3000, app.quit)
    app.exec()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
