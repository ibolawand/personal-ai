"""
Where clicks land on the overlay while the avatar shows.

Qt's setMask() sets a window's *bounding* shape: it decides what is drawn as well as what can be clicked, with hard
1-bit edges. That suits the round orb, but it would cut the avatar's hair and soft outline. X11 also has a separate
*input* shape, which only decides where clicks land. This module sets that one (through libXfixes), so the whole
picture is drawn and only her outline, the bubbles and the cards take clicks; everything beside her passes through
to the window behind. X11 only, like the overlay's click-through has always been.
"""
import ctypes
import ctypes.util

from PySide6.QtCore import QRect

SHAPE_INPUT = 2
HER_WIDTH = 0.72        # how much of her box's width she fills (head, tails and arms); the rest passes clicks through
_x = {}         # the libraries and the display, opened once


class _XRectangle(ctypes.Structure):
    _fields_ = [("x", ctypes.c_short), ("y", ctypes.c_short), ("width", ctypes.c_ushort), ("height", ctypes.c_ushort)]


def avatar_click_rects(avatar: QRect, step: int = 8, hole: QRect = None):
    """Horizontal strips that fill an ellipse in the upper 80% of her box, 72% of its width: her outline, near
    enough, for clicks; without `hole` (the part an app in front of her covers: clicks there go to the app).
    (The same ellipse Overlay._in_orb uses to decide that a click was on her.)"""
    rx, ry = avatar.width() * HER_WIDTH / 2, avatar.height() * 0.4
    cx, cy = avatar.left() + avatar.width() / 2, avatar.top() + ry
    rects, y = [], avatar.top()
    bottom = avatar.top() + int(2 * ry)
    while y < bottom:
        h = min(step, bottom - y)
        mid = (y + h / 2 - cy) / ry
        half = rx * max(0.0, 1 - mid * mid) ** 0.5
        if half >= 1:
            strip = QRect(int(cx - half), y, int(2 * half), h)
            if hole is None or not strip.intersects(hole):
                rects.append(strip)
            else:                       # what's left of the strip beside the hole
                if hole.left() > strip.left():
                    rects.append(QRect(strip.left(), y, hole.left() - strip.left(), h))
                if hole.right() < strip.right():
                    rects.append(QRect(hole.right() + 1, y, strip.right() - hole.right(), h))
        y += h
    return rects


def _open():
    if "display" in _x:
        return _x["display"] is not None
    _x["display"] = None
    x11, xfixes = ctypes.util.find_library("X11"), ctypes.util.find_library("Xfixes")
    if not x11 or not xfixes:
        return False
    lib, fixes = ctypes.CDLL(x11), ctypes.CDLL(xfixes)
    lib.XOpenDisplay.restype = ctypes.c_void_p
    lib.XOpenDisplay.argtypes = [ctypes.c_char_p]
    lib.XFlush.argtypes = [ctypes.c_void_p]
    fixes.XFixesCreateRegion.restype = ctypes.c_ulong
    fixes.XFixesCreateRegion.argtypes = [ctypes.c_void_p, ctypes.POINTER(_XRectangle), ctypes.c_int]
    fixes.XFixesSetWindowShapeRegion.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_int,
                                                 ctypes.c_int, ctypes.c_ulong]
    fixes.XFixesDestroyRegion.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    display = lib.XOpenDisplay(None)
    if not display:
        return False
    _x.update(display=display, lib=lib, fixes=fixes)
    return True


def set_input_rects(win_id: int, rects) -> bool:
    """Only these rectangles (window coordinates) take clicks from now on. False, with nothing changed, when it
    can't be done here (no X11, no libXfixes). Never raises."""
    try:
        if not _open():
            return False
        rects = [r for r in rects if r.width() > 0 and r.height() > 0]
        array = (_XRectangle * max(1, len(rects)))(*[_XRectangle(max(0, r.x()), max(0, r.y()), r.width(), r.height())
                                                    for r in rects])
        region = _x["fixes"].XFixesCreateRegion(_x["display"], array, len(rects))
        _x["fixes"].XFixesSetWindowShapeRegion(_x["display"], int(win_id), SHAPE_INPUT, 0, 0, region)
        _x["fixes"].XFixesDestroyRegion(_x["display"], region)
        _x["lib"].XFlush(_x["display"])
        return True
    except Exception as e:
        print(f"[Overlay] couldn't set where clicks land: {type(e).__name__}")
        return False


def clear_input_rects(win_id: int) -> bool:
    """Back to the default: clicks land wherever the window is."""
    try:
        if not _open():
            return False
        _x["fixes"].XFixesSetWindowShapeRegion(_x["display"], int(win_id), SHAPE_INPUT, 0, 0, 0)
        _x["lib"].XFlush(_x["display"])
        return True
    except Exception as e:
        print(f"[Overlay] couldn't reset where clicks land: {type(e).__name__}")
        return False
