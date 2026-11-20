import pytest

from Engines.AvatarEvents import action_for, focus_scene
from Engines.Tool_Engine import ToolEngine, _tool
from ui.avatar_view import AvatarLink


@pytest.mark.parametrize("name,result,expected", [
    ("set_timer", "Timer set for 5 minutes.", "timerSaved"),
    ("set_reminder", "I'll remind you to call mum at 18:00.", "timerSaved"),
    ("add_note", "Created the note 'Biology'.", "noteSaved"),
    ("check_off", "Ticked off eggs.", "taskDone"),
    ("check_off", "Unticked eggs.", None),
    ("set_timer", "Timer length has to be more than zero.", None),
    ("add_note", "NEEDS CONFIRMATION: overwrite it?", None),
    ("add_note", "Couldn't open the database.", None),
    ("read_note", "Created the note 'this is quoted text'.", None),
])
def test_only_known_completed_actions_are_acknowledged(name, result, expected):
    assert action_for(name, result) == expected


def test_tool_callback_follows_success_and_cannot_turn_success_into_failure():
    events = []
    tools = ToolEngine(on_action=events.append)
    tools._registry["set_timer"] = _tool("set_timer", "test", lambda: "Timer set for 5 minutes.")
    assert tools.execute("set_timer", {}) == "Timer set for 5 minutes."
    assert events == ["timerSaved"]
    with tools.phone():
        tools.execute("set_timer", {})
    assert events == ["timerSaved"]
    tools.on_action = lambda action: (_ for _ in ()).throw(RuntimeError("page gone"))
    assert tools.execute("set_timer", {}) == "Timer set for 5 minutes."
    tools._registry["set_timer"]["handler"] = lambda: "Timer length has to be more than zero."
    tools.on_action = events.append
    tools.execute("set_timer", {})
    assert events == ["timerSaved"]


def test_focus_scene_tracks_live_blocks_and_clears_expired_or_paused_ones():
    assert focus_scene([], 100) == "off"
    assert focus_scene([{"kind": "focus", "due": 100}], 100) == "off"
    assert focus_scene([{"kind": "focus", "due": "bad"}], 100) == "off"
    assert focus_scene([{"kind": "focusbreak", "due": 200}], 100) == "break"
    assert focus_scene([{"kind": "focusbreak", "due": 200}, {"kind": "focus", "due": 300}], 100) == "work"


def test_focus_and_conversation_replay_latest_state_without_replaying_successes():
    sent = []
    link = AvatarLink(sent.append)
    link.set_focus("work")
    link.set_focus("break")
    link.set_conversation("claude", -1)
    link.act("taskDone")
    link.mark_ready()
    assert sent == ['window.aria.setFocus("break")', 'window.aria.setConversation("claude",-1)']
    link.set_focus("break")
    assert len(sent) == 2
    link.set_focus("off")
    assert sent[-1] == 'window.aria.setFocus("off")'
