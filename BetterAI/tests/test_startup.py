"""When the laptop starts, Aria opens your study apps once (VS Code and MyNotion), not on every restart of Aria."""
from Engines.Startup import first_start_since_boot, open_study_apps


def test_only_the_first_start_after_a_boot(tmp_path):
    marker = tmp_path / "last_boot"
    assert first_start_since_boot(marker, boot=1000) is True
    assert first_start_since_boot(marker, boot=1000) is False      # Aria restarted: you may have closed them
    assert first_start_since_boot(marker, boot=2000) is True       # the laptop was restarted


def test_unknown_boot_time_opens_nothing(tmp_path):
    assert first_start_since_boot(tmp_path / "last_boot", boot=None) is False


class Laptop:
    def __init__(self):
        self.opened = []

    def open_app(self, name):
        self.opened.append(name)
        return f"Opening {name}."


def test_opens_vs_code_and_mynotion_by_default():
    laptop = Laptop()
    open_study_apps(laptop, "")
    assert laptop.opened == []                                      # ARIA_STARTUP_APPS= turns it off
    open_study_apps(laptop, "vscode, mynotion")
    assert laptop.opened == ["vscode", "mynotion"]


def test_an_app_that_fails_does_not_stop_the_others():
    laptop = Laptop()
    laptop.open_app = lambda name: (_ for _ in ()).throw(OSError("gone")) if name == "vscode" else laptop.opened.append(name)
    open_study_apps(laptop, "vscode,mynotion")
    assert laptop.opened == ["mynotion"]
