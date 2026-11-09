import datetime as dt

import pytest

from Engines.DueDates import due_tag, parse_due_text, split_due, strip_by_phrase, with_due
from Engines.NotionEngine import card_items
from Engines.Reminders import Reminders

TODAY = dt.date(2026, 11, 7)      # a Saturday


@pytest.mark.parametrize("text, expected", [
    ("Finish the essay · due Fri 13 Nov", ("Finish the essay", dt.date(2026, 11, 13))),
    ("Finish the essay due 13.11.", ("Finish the essay", dt.date(2026, 11, 13))),
    ("Report - due 2027-01-04", ("Report", dt.date(2027, 1, 4))),
    ("Tax return (due 3 january)", ("Tax return", dt.date(2027, 1, 3))),
    ("Pay rent · due Mon 2 Nov", ("Pay rent", dt.date(2026, 11, 2))),     # overdue stays this year
    ("Book due to arrive", ("Book due to arrive", None)),                 # 'due' in the text, no date
    ("Buy milk", ("Buy milk", None)),
])
def test_split_due(text, expected):
    assert split_due(text, TODAY) == expected


def test_due_tag_adds_the_year_only_when_needed():
    assert due_tag(dt.date(2026, 11, 13), TODAY) == "due Fri 13 Nov"
    assert due_tag(dt.date(2027, 9, 1), TODAY) == "due Wed 1 Sep 2027"
    assert parse_due_text("1 Sep 2027", TODAY) == dt.date(2027, 9, 1)


def test_with_due_replaces_the_old_tag():
    assert with_due("Essay · due Fri 13 Nov", dt.date(2026, 11, 16), TODAY) == "Essay · due Mon 16 Nov"
    assert with_due("Essay · due Fri 13 Nov", None, TODAY) == "Essay"


def test_strip_by_phrase():
    assert strip_by_phrase("finish the essay by friday") == ("finish the essay", "friday")
    assert strip_by_phrase("hand in the report before 20 november") == ("hand in the report", "20 november")
    assert strip_by_phrase("call mum and dad") == ("call mum and dad", None)


def _items(notion):
    return [i["text"] for i in card_items(notion._list_note("to-do", False)["content"])]


def test_add_todo_with_a_due_date(notion):
    friday = dt.date.today() + dt.timedelta(days=3)
    msg = notion.add_todo("finish the essay", friday.isoformat())
    assert msg.startswith("Added 'Finish the essay' to your To-do list, due")
    assert _items(notion) == [with_due("Finish the essay", friday)]


def test_add_todo_takes_the_date_out_of_the_task_and_never_splits_it(notion):
    notion.add_todo("call mum and dad by tomorrow")
    tomorrow = dt.date.today() + dt.timedelta(days=1)
    assert _items(notion) == [with_due("Call mum and dad", tomorrow)]


def test_add_todo_again_moves_the_date(notion):
    notion.add_todo("essay", "tomorrow")
    notion.add_todo("essay", "in 3 days")
    assert _items(notion) == [with_due("Essay", dt.date.today() + dt.timedelta(days=3))]


def test_unknown_date_is_not_guessed(notion):
    assert "didn't get the date" in notion.add_todo("essay", "sometime soonish")


def test_set_due_and_remove_it(notion):
    notion.add_todo("finish the essay", "tomorrow")
    assert "is due" in notion.set_due("essay", "in 5 days")
    assert _items(notion) == [with_due("Finish the essay", dt.date.today() + dt.timedelta(days=5))]
    assert notion.set_due("essay", "none") == "'Finish the essay' has no due date now."
    assert _items(notion) == ["Finish the essay"]


def test_check_off_ignores_the_due_tag(notion):
    notion.add_todo("pay the rent", "tomorrow")
    assert notion.check_off("I paid the rent").startswith("Ticked off Pay the rent")
    assert card_items(notion._list_note("to-do", False)["content"])[0]["checked"] is True
    assert notion.due_items() == []                     # done: no longer due


def test_get_due_lists_overdue_first(notion):
    notion.add_todo("old thing", (dt.date.today() - dt.timedelta(days=2)).isoformat())
    notion.add_todo("essay", "tomorrow")
    notion.add_todo("far away", (dt.date.today() + dt.timedelta(days=40)).isoformat())
    out = notion.get_due("this week")
    assert out.startswith("Overdue: Old thing (was due 2 days ago). Due: Essay tomorrow")
    assert "Far away" not in out
    assert "Far away" in notion.get_due("all")


def test_briefing_mentions_due_items_and_keeps_undated_todos(notion):
    notion.add_todo("essay", "today")
    notion.add_todo("water the plants")
    b = notion.daily_briefing()
    assert "Due today: Essay." in b
    assert "Open to-dos: Water the plants." in b


def test_heads_up_the_evening_before(notion, memory, monkeypatch):
    reminders = Reminders(memory, on_due=lambda r: None)
    notion.add_todo("essay", "tomorrow")
    evening = dt.datetime.combine(dt.date.today(), dt.time(19)).timestamp()
    monkeypatch.setattr("Engines.NotionEngine.time.time", lambda: evening - 3600)
    notion.sync_event_reminders(reminders)
    due = reminders.pending(("due",))
    assert [(r["text"], round(r["due"])) for r in due] == [("Essay", round(evening))]
    assert Reminders.announcement(due[0]) == "Heads up: Essay is due tomorrow."

    notion.check_off("essay")
    notion.sync_event_reminders(reminders)
    assert reminders.pending(("due",)) == []
