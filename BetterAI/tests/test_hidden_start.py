"""Starting Aria from MyNotion's panel: the full Aria, with the orb hidden (main.py --hidden, aria.sh --hidden)."""
import main


def test_hidden_start_only_pings():
    sent = []
    assert main.already_running(True, lambda c: sent.append(c) or True) is True
    assert sent == ["ping"]


def test_normal_start_still_shows_a_running_aria():
    sent = []
    assert main.already_running(False, lambda c: sent.append(c) or True) is True
    assert sent == ["show"]


def test_nothing_running():
    assert main.already_running(True, lambda c: False) is False
    assert main.already_running(False, lambda c: False) is False


def test_no_ui_listener_ignores_ping():
    calls = []
    aria = type("A", (), {"shutdown": lambda self: calls.append("quit")})()
    main._no_ui_command(aria, "ping")
    assert calls == []
    main._no_ui_command(aria, "quit")
    assert calls == ["quit"]
