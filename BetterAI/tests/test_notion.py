import datetime as dt

import pytest

from Engines.NotionEngine import card_items, parse_day, parse_time, task_item


def test_add_to_list_creates_a_checklist(notion):
    assert "Added eggs, oat milk" in notion.add_to_list("shopping", "eggs, oat milk")
    n = notion._list_note("shopping", create=False)
    assert n["title"] == "Shopping list"
    assert [i["text"] for i in card_items(n["content"])] == ["eggs", "oat milk"]
    assert all(i["checked"] is False for i in card_items(n["content"]))


def test_lists_never_write_into_ordinary_notes(notion):
    # regression: "packing list" items once went into the note "c#" ("c" is inside "packing")
    notion._create_note("c#", "<p>delegates and events</p>")
    notion.add_to_list("packing", "socks")
    c_sharp = notion._find_note("c#")
    assert "socks" not in c_sharp["content"]
    assert notion._list_note("packing", create=False)["title"] == "Packing list"


def test_check_off_with_different_wording(notion):
    notion.add_to_list("to-do", "pay rent, call the landlord")
    assert notion.check_off("I paid the rent") == "Ticked off pay rent."
    items = {i["text"]: i["checked"] for i in card_items(notion._list_note("to-do", False)["content"])}
    assert items == {"pay rent": True, "call the landlord": False}


def test_set_item_checked_from_card(notion):
    notion.add_to_list("to-do", "water the plants")
    n = notion._list_note("to-do", False)
    assert notion.set_item_checked(n["id"], "water the plants", True)
    assert card_items(notion._note_by_id(n["id"])["content"])[0]["checked"] is True
    assert not notion.set_item_checked(n["id"], "not on the list", True)


def test_cards_are_emitted(notion):
    cards = []
    notion.on_card = cards.append
    notion.add_to_list("shopping", "bread")
    notion.get_events("this week")
    assert [c["type"] for c in cards] == ["list", "agenda"]


def test_repeating_event_shows_on_matching_days(notion):
    today = dt.date.today()
    notion.add_event("Gym", today.isoformat(), "18:00", 1, repeat="weekly")
    days = notion._events_between(today, today + dt.timedelta(days=14))
    assert [e["date"] for e in days] == [(today + dt.timedelta(days=d)).isoformat() for d in (0, 7, 14)]


def test_two_weekdays_make_two_events(notion):
    msg = notion.add_event("Gym", "monday and thursday", "18:00")
    assert msg.startswith("Added 'Gym' every Monday and Thursday")


def test_clear_list_asks_first(notion):
    notion.add_to_list("shopping", "eggs")
    assert notion.clear_list("shopping").startswith("NEEDS CONFIRMATION")
    assert card_items(notion._list_note("shopping", False)["content"])     # still there
    assert notion.confirm.resolve("yes") == "Cleared your Shopping list."


@pytest.mark.parametrize("text,days", [("today", 0), ("tomorrow", 1), ("in 3 days", 3)])
def test_parse_day_relative(text, days):
    assert parse_day(text) == dt.date.today() + dt.timedelta(days=days)


def test_parse_day_absolute():
    assert parse_day("12.11.", dt.date(2026, 11, 5)) == dt.date(2026, 11, 12)
    assert parse_day("12 november", dt.date(2026, 11, 5)) == dt.date(2026, 11, 12)
    assert parse_day("blursday") is None


@pytest.mark.parametrize("text,hours", [("15:00", 15), ("3pm", 15), ("9.30", 9.5), ("7 am", 7)])
def test_parse_time(text, hours):
    assert parse_time(text) == hours


def test_card_items_marks_plain_bullets():
    html = "<ul><li><p>plain</p></li></ul>" + '<ul data-type="taskList">' + task_item("done", True) + "</ul>"
    assert card_items(html) == [{"text": "plain", "checked": None}, {"text": "done", "checked": True}]


def test_overlapping_events_are_flagged(notion):
    day = (dt.date.today() + dt.timedelta(days=1)).isoformat()
    notion.add_event("Meeting", day, "15:00", 1)
    assert "Heads up: that overlaps with Meeting at 15:00." in notion.add_event("Dentist", day, "15:30", 1)
    assert "Heads up" not in notion.add_event("Gym", day, "16:30", 1)          # Dentist ends 16:30
    assert "Heads up" not in notion.add_event("Birthday", day)                 # all day never clashes


def test_moving_into_a_clash_is_flagged(notion):
    day = (dt.date.today() + dt.timedelta(days=1)).isoformat()
    notion.add_event("Meeting", day, "15:00", 1)
    notion.add_event("Dentist", day, "10:00", 1)
    notion.move_event("dentist", new_time="15:15")
    assert "overlaps with Meeting" in notion.confirm.resolve("yes")


def test_birthdays_repeat_yearly_and_are_all_day(notion):
    msg = notion.add_event("Lina's birthday", "3 march")
    assert "every year" in msg and "all-day" in msg


def test_day_ahead_heads_up_and_briefing(notion, memory):
    import time
    from Engines.Reminders import Reminders
    reminders = Reminders(memory, on_due=lambda r: None)
    in2 = dt.date.today() + dt.timedelta(days=2)
    notion.add_event("Lina's birthday", in2.isoformat())
    notion.sync_event_reminders(reminders)
    day_ahead = reminders.pending(("dayahead",))
    assert [r["text"] for r in day_ahead] == ["Lina's birthday"]
    assert dt.datetime.fromtimestamp(day_ahead[0]["due"]) == dt.datetime.combine(in2 - dt.timedelta(days=1), dt.time(9))
    notion.sync_event_reminders(reminders)                        # idempotent
    assert len(reminders.pending(("dayahead",))) == 1
    assert "Special days ahead: Lina's birthday in 2 days" in notion.daily_briefing()
    assert Reminders.announcement(day_ahead[0]) == "Heads up: tomorrow is Lina's birthday."


def test_todays_note_matches_mynotion_and_takes_additions(notion):
    from Engines.NotionEngine import daily_title
    assert daily_title(dt.date(2026, 11, 7)) == "Saturday, 7 November 2026"     # same as MyNotion's Ctrl+D note
    assert notion.read_note("today") == "There's no note for today yet."
    assert notion.add_note("call the bank", title="today's note") == "Added to today's note."
    notion.add_note("buy stamps", title="today")
    n = notion._find_note(daily_title())
    assert n["content"].count("<h2>Notes</h2>") == 1 and n["content"].endswith("<p>call the bank</p><p>buy stamps</p>")
    assert "call the bank" in notion.read_note("my daily note")


# ── older versions from MyNotion's daily backups ──

def _backup(notion, day):
    import os
    import shutil
    folder = os.path.join(os.path.dirname(notion.db_path), "backups")
    os.makedirs(folder, exist_ok=True)
    shutil.copy(notion.db_path, os.path.join(folder, f"noted-{day.isoformat()}.db"))


def test_restore_an_older_version(notion):
    today = dt.date.today()
    notion._create_note("C# delegates", "<p>A delegate holds a reference to a method. Events wrap delegates.</p>")
    _backup(notion, today - dt.timedelta(days=1))
    n = notion._find_note("C# delegates")
    notion._set_content(n["id"], "<p>oops</p>")
    ask = notion.restore_note("c# delegates")
    assert ask.startswith("NEEDS CONFIRMATION") and "(1 words now)" in ask and "(11 words)" in ask
    assert notion._find_note("C# delegates")["content"] == "<p>oops</p>"            # nothing changed yet
    assert notion.confirm.resolve("yes").startswith("Restored 'C# delegates' to how it was on")
    assert "reference to a method" in notion._find_note("C# delegates")["content"]


def test_bring_back_a_deleted_note(notion):
    notion._create_note("Trip ideas", "<p>Hallstatt, Graz</p>")
    _backup(notion, dt.date.today())
    with notion._conn() as c:
        c.execute("DELETE FROM notes WHERE title = 'Trip ideas'")
    assert "bring back the deleted note 'Trip ideas'" in notion.restore_note("trip ideas", "today")
    assert notion.confirm.resolve("yes").startswith("Brought back 'Trip ideas'")
    assert notion._find_note("Trip ideas")["content"] == "<p>Hallstatt, Graz</p>"


def test_restore_when_nothing_changed_or_no_backups(notion):
    assert notion.restore_note("anything") == "There are no backups yet (MyNotion makes one a day when it's open)."
    notion._create_note("Gym plan", "<p>legs</p>")
    _backup(notion, dt.date.today() - dt.timedelta(days=1))
    assert notion.restore_note("gym plan").startswith("I couldn't find an older version of 'Gym plan'")


def test_backups_are_never_written(notion, monkeypatch):
    import sqlite3
    opened = []
    real = sqlite3.connect

    def spy(path, *a, **kw):
        opened.append(str(path))
        return real(path, *a, **kw)
    notion._create_note("Gym plan", "<p>legs</p>")
    _backup(notion, dt.date.today() - dt.timedelta(days=1))
    monkeypatch.setattr(sqlite3, "connect", spy)
    notion.restore_note("gym plan")
    backups = [p for p in opened if "/backups/" in p]
    assert backups and all(p.startswith("file:") and p.endswith("?mode=ro") for p in backups)


def test_formulas_are_read_as_latex():
    from Engines.NotionEngine import html_to_text
    note = ('<p>Energy: <span data-latex="E = mc^2" data-type="inline-math"></span> is famous.</p>'
            '<div data-latex="x = \\frac{-b \\pm \\sqrt{b^2-4ac}}{2a}" data-type="block-math"></div><p>done</p>')
    assert html_to_text(note) == ("Energy: $E = mc^2$ is famous.\n$$x = \\frac{-b \\pm \\sqrt{b^2-4ac}}{2a}$$\n"
                                  "done")


def test_tables_toggles_and_scripts_are_read_in_order():
    from Engines.NotionEngine import html_to_text
    note = ('<p>Marks</p><div class="tableWrapper"><table style="min-width: 200px;"><colgroup><col style="width: 120px;"><col></colgroup>'
            '<tbody><tr><th colspan="1" rowspan="1"><p>Fach</p></th><th colspan="1" rowspan="1"><p>Note</p></th></tr>'
            '<tr><td colspan="1" rowspan="1"><p>Bio</p></td><td colspan="1" rowspan="1"><p>5.5</p><p>(Test)</p></td></tr></tbody></table></div>'
            '<details open=""><summary>Question</summary><div data-type="detailsContent"><p>Answer</p></div></details>'
            '<p>H<sub>2</sub>O and m<sup>2</sup></p>')
    assert html_to_text(note) == "Marks\nFach | Note\nBio | 5.5 (Test)\nQuestion\nAnswer\nH2O and m^2"
