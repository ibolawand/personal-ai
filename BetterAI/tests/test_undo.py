import datetime as dt

import pytest

from Engines.NotionEngine import card_items
from Engines.Reminders import Reminders
from Engines.Tool_Engine import ToolEngine
from Engines.Undo import Undo


@pytest.fixture
def setup(notion, memory):
    reminders = Reminders(memory, on_due=lambda r: None)
    undo = Undo(notion, reminders)
    tools = ToolEngine(notion=notion, reminders=reminders, undo=undo)
    return tools, undo, notion, reminders


def items(notion, name):
    n = notion._list_note(name, False)
    return [i["text"] for i in card_items(n["content"])] if n else None


def test_undo_adding_to_a_list(setup):
    tools, undo, notion, _ = setup
    tools.execute("add_to_list", {"list_name": "shopping", "items": "eggs"})
    tools.execute("add_to_list", {"list_name": "shopping", "items": "legs"})      # misheard
    assert undo.undo().startswith("Undone: Added legs")
    assert items(notion, "shopping") == ["eggs"]
    assert undo.undo() == "There's nothing I can undo right now."


def test_undo_a_new_list_removes_the_note(setup):
    tools, undo, notion, _ = setup
    tools.execute("add_to_list", {"list_name": "packing", "items": "socks"})
    undo.undo()
    assert items(notion, "packing") is None


def test_undo_tick_off(setup):
    tools, undo, notion, _ = setup
    notion.add_to_list("to-do", "pay rent")
    tools.execute("check_off", {"items": "pay rent"})
    undo.undo()
    assert card_items(notion._list_note("to-do", False)["content"])[0]["checked"] is False


def test_undo_event_and_reminder(setup):
    tools, undo, notion, reminders = setup
    tools.execute("add_event", {"title": "Dentist", "date": "tomorrow", "time": "15:00"})
    undo.undo()
    tomorrow = dt.date.today() + dt.timedelta(days=1)
    assert notion._events_between(tomorrow, tomorrow) == []
    tools.execute("set_reminder", {"text": "call mum", "in_minutes": 30})
    undo.undo()
    assert reminders.pending() == []


def test_undo_a_confirmed_delete(setup, aria):
    tools, undo, notion, _ = setup
    tomorrow = (dt.date.today() + dt.timedelta(days=1)).isoformat()
    notion.add_event("Dentist", tomorrow, "15:00")
    aria.notion, aria.undo, aria.confirm = notion, undo, notion.confirm
    notion.delete_event("dentist")                         # asks first
    reply, _ = aria.handle_turn("yes", check_state=False)
    assert reply.startswith("Deleted 'Dentist'")
    assert undo.undo().startswith("Undone: Deleted 'Dentist'")
    assert [e["title"] for e in notion._events_between(dt.date.fromisoformat(tomorrow), dt.date.fromisoformat(tomorrow))] == ["Dentist"]


def test_reading_is_not_recorded(setup):
    tools, undo, notion, _ = setup
    notion.add_to_list("shopping", "eggs")
    tools.execute("read_note", {"title": "shopping"})
    assert undo.last is None
