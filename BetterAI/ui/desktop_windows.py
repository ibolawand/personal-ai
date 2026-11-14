"""
The tops of the other windows on the screen, as places Aria's avatar can sit (X11 only, like the overlay's
click-through).

`seats(...)` is the decision and needs no X: given the open windows from bottom to top of the stacking order, it
returns the stretches of each window's top edge that she could sit on: not covered by a window above it (where
she would sit, or the edge itself), long enough for her, and low enough that her box stays on the screen.
`open_windows()` reads those windows from the window manager (through python-xlib) and returns [] when it can't.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Win:
    id: int
    left: int
    top: int            # its visible top edge (title bar included, shadows left out)
    right: int
    bottom: int


@dataclass(frozen=True)
class Seat:
    id: int             # the window she would sit on
    left: int           # the stretch of its top edge she can sit on (screen pixels)
    right: int
    top: int


def _minus(spans, cut_left, cut_right):
    """[(left, right)] with (cut_left, cut_right) taken out."""
    out = []
    for left, right in spans:
        if cut_right <= left or cut_left >= right:
            out.append((left, right))
            continue
        if cut_left > left:
            out.append((left, cut_left))
        if cut_right < right:
            out.append((cut_right, right))
    return out


def seats(windows, screen, above=200, width=110, below=8):
    """Where she could sit. `windows` from the bottom of the stacking order to the top; `screen` (left, top, right,
    bottom); `above`: how much room she needs over an edge (her body, and her box staying on the screen); `width`:
    how wide a stretch she needs; `below`: how much of the edge itself has to be visible."""
    s_left, s_top, s_right, s_bottom = screen
    out = []
    for i, w in enumerate(windows):
        if w.top - above < s_top or w.top > s_bottom - 40:
            continue                    # no room over it (a maximized window), or barely on the screen
        spans = [(max(w.left, s_left), min(w.right, s_right))]
        for higher in windows[i + 1:]:  # a window over it hides the edge, or the space where she would sit
            if higher.top < w.top + below and higher.bottom > w.top - above:
                spans = _minus(spans, higher.left, higher.right)
        out += [Seat(w.id, a, b, w.top) for a, b in spans if b - a >= width]
    return out


# ── reading them from X ──

_SKIP_STATES = ("_NET_WM_STATE_HIDDEN", "_NET_WM_STATE_FULLSCREEN", "_NET_WM_STATE_MAXIMIZED_VERT")
_display = []


def open_windows(own=None):
    """The normal windows on the current workspace, bottom to top, without `own` (a window id) and without
    minimized, fullscreen or maximized ones. [] when X or python-xlib isn't there."""
    try:
        from Xlib import X, display as xdisplay
        if not _display:
            _display.append(xdisplay.Display())
        d = _display[0]
        root = d.screen().root
        atom = d.intern_atom

        def prop(win, name, kind=X.AnyPropertyType):
            p = win.get_full_property(atom(name), kind)
            return list(p.value) if p is not None else []

        desktop = (prop(root, "_NET_CURRENT_DESKTOP") or [0])[0]
        normal = atom("_NET_WM_WINDOW_TYPE_NORMAL")
        skip = {atom(n) for n in _SKIP_STATES}
        out = []
        for wid in prop(root, "_NET_CLIENT_LIST_STACKING"):
            if wid == own:
                continue
            win = d.create_resource_object("window", wid)
            try:
                types = prop(win, "_NET_WM_WINDOW_TYPE")
                if types and normal not in types:
                    continue
                if skip & set(prop(win, "_NET_WM_STATE")):
                    continue
                on = prop(win, "_NET_WM_DESKTOP")
                if on and on[0] not in (desktop, 0xFFFFFFFF):
                    continue
                geo = win.get_geometry()
                at = win.translate_coords(root, 0, 0)
                x, y = -at.x, -at.y
                # client-side decorations draw a shadow round the window (inside it); the window manager's own
                # decorations add a title bar outside it
                gl, gr, gt, gb = (prop(win, "_GTK_FRAME_EXTENTS") + [0, 0, 0, 0])[:4]
                fl, fr, ft, fb = (prop(win, "_NET_FRAME_EXTENTS") + [0, 0, 0, 0])[:4]
                out.append(Win(wid, x + gl - fl, y + gt - ft, x + geo.width - gr + fr, y + geo.height - gb + fb))
            except Exception:           # it closed while we looked
                continue
        return out
    except Exception:
        return []
