"""Where on the other windows Aria's avatar can sit (ui/desktop_windows.py): pure geometry, no X needed."""
from ui.desktop_windows import Seat, Win, open_windows, seats

SCREEN = (0, 0, 1920, 1040)


def test_a_free_window_can_be_sat_on_along_its_whole_top():
    assert seats([Win(1, 300, 500, 1100, 900)], SCREEN) == [Seat(1, 300, 1100, 500)]


def test_no_room_above_or_barely_on_the_screen_is_no_seat():
    assert seats([Win(1, 0, 100, 1920, 1040)], SCREEN) == []      # maximized-like: her box would leave the screen
    assert seats([Win(1, 0, 1020, 900, 1300)], SCREEN) == []      # its top is at the bottom of the screen


def test_a_window_over_it_takes_away_that_part_of_the_edge():
    under, over = Win(1, 200, 600, 1400, 1000), Win(2, 600, 300, 900, 800)
    assert seats([under, over], SCREEN) == [Seat(1, 200, 600, 600), Seat(1, 900, 1400, 600), Seat(2, 600, 900, 300)]


def test_a_window_under_it_or_far_above_it_does_not_matter():
    low, high = Win(1, 200, 600, 1400, 1000), Win(2, 300, 750, 900, 1000)     # starts lower: below the edge
    assert Seat(1, 200, 1400, 600) in seats([low, high], SCREEN)
    top_band = Win(3, 200, 200, 1400, 350)                                    # ends well above where she'd sit
    assert Seat(1, 200, 1400, 600) in seats([low, top_band], SCREEN)


def test_too_narrow_a_stretch_and_the_screen_edge():
    under, over = Win(1, 200, 600, 1400, 1000), Win(2, 250, 300, 1350, 800)
    assert seats([under, over], SCREEN) == [Seat(2, 250, 1350, 300)]          # 50 px either side: too narrow
    assert seats([Win(1, -300, 600, 400, 900)], SCREEN) == [Seat(1, 0, 400, 600)]


def test_without_x_there_are_no_windows(monkeypatch):
    import builtins
    real = builtins.__import__
    monkeypatch.setattr(builtins, "__import__",
                        lambda name, *a, **k: (_ for _ in ()).throw(ImportError()) if name.startswith("Xlib") else real(name, *a, **k))
    import ui.desktop_windows as D
    monkeypatch.setattr(D, "_display", [])
    assert open_windows() == []
