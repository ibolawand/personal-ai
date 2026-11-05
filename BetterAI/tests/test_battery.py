from Engines.Battery import BatteryWatch, read_battery


def watch(states):
    said, it = [], iter(states)
    return BatteryWatch(said.append, read=lambda: next(it)), said


def test_warns_once_per_level_while_discharging():
    w, said = watch([(40, "Discharging"), (15, "Discharging"), (14, "Discharging"), (7, "Discharging"), (5, "Discharging")])
    for _ in range(5):
        w.check()
    assert said == ["Battery's at 15 percent, you might want to plug me in.",
                    "Battery's almost empty, 7 percent. Plug in soon or save your work."]


def test_no_warning_while_charging_and_reset_after():
    w, said = watch([(10, "Charging"), (14, "Discharging"), (60, "Charging"), (12, "Discharging")])
    for _ in range(4):
        w.check()
    assert len(said) == 2                     # warned again after being plugged in


def test_dropping_straight_to_critical_warns_once():
    w, said = watch([(6, "Discharging"), (5, "Discharging")])
    w.check(); w.check()
    assert said == ["Battery's almost empty, 6 percent. Plug in soon or save your work."]


def test_read_battery(tmp_path):
    (tmp_path / "BAT1").mkdir()
    (tmp_path / "BAT1" / "capacity").write_text("38\n")
    (tmp_path / "BAT1" / "status").write_text("Charging\n")
    assert read_battery(str(tmp_path)) == (38, "Charging")
    assert read_battery(str(tmp_path / "none")) is None
