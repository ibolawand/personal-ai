import datetime as dt
import threading
import time

import pytest

from Engines.Reminders import Reminders, describe_repeat, next_occurrence, parse_repeat


@pytest.fixture
def reminders(memory):
    return Reminders(memory, on_due=lambda r: None)


@pytest.mark.parametrize("text,expected", [
    ("daily", "daily"), ("every day", "daily"), ("every morning", "daily"),
    ("weekdays", "weekdays"), ("every weekday", "weekdays"),
    ("weekly", "weekly"), ("monthly", "monthly"),
    ("every monday and thursday", "mon,thu"), ("mondays", "mon"), ("sundays", "sun"),
    ("", None), ("once", None), ("every fortnight", False),
])
def test_parse_repeat(text, expected):
    assert parse_repeat(text) == expected


def test_describe_repeat():
    assert describe_repeat("mon,thu") == "every Monday and Thursday"
    assert describe_repeat("monthly:31") == "every month"
    assert describe_repeat(None) == ""


def test_next_occurrence_weekdays_skips_weekend():
    friday = dt.datetime(2026, 11, 6, 9, 0)
    assert next_occurrence("weekdays", friday) == dt.datetime(2026, 11, 9, 9, 0)


def test_next_occurrence_weekday_set():
    thursday_evening = dt.datetime(2026, 11, 5, 19, 0)
    assert next_occurrence("mon,thu", thursday_evening) == dt.datetime(2026, 11, 9, 19, 0)


def test_monthly_on_31st_keeps_its_day():
    d = dt.datetime(2026, 1, 31, 9, 0)
    seen = []
    for _ in range(3):
        d = next_occurrence("monthly:31", d)
        seen.append(d.date())
    assert seen == [dt.date(2026, 2, 28), dt.date(2026, 3, 31), dt.date(2026, 4, 30)]


def test_reminder_on_another_day_defaults_to_nine(reminders):
    msg = reminders.set_reminder("water the plants", day="tomorrow")
    assert "09:00" in msg and "tomorrow" in msg
    due = dt.datetime.fromtimestamp(reminders.pending()[0]["due"])
    assert due.date() == dt.date.today() + dt.timedelta(days=1) and (due.hour, due.minute) == (9, 0)


def test_unknown_day_is_refused(reminders):
    assert "couldn't understand the day" in reminders.set_reminder("x", day="blursday")
    assert reminders.pending() == []


def test_repeating_reminder_reschedules_when_it_fires(reminders, memory):
    reminders.set_reminder("take vitamins", repeat="daily", at_time="08:00")
    r = reminders.pending()[0]
    assert r["repeat"] == "daily"
    # make it due now and let the loop fire it once
    conn = memory._connect()
    conn.execute("UPDATE reminders SET due = ? WHERE id = ?", (time.time() - 1, r["id"]))
    conn.commit()
    conn.close()
    fired = []
    reminders.on_due = fired.append
    reminders._running = True
    t = threading.Thread(target=reminders._loop, daemon=True)
    t.start()
    time.sleep(1.5)
    reminders._running = False
    assert [f["text"] for f in fired] == ["take vitamins"]
    nxt = reminders.pending()
    assert len(nxt) == 1 and nxt[0]["repeat"] == "daily" and nxt[0]["due"] > time.time()


def test_weekday_repeat_ignores_weekday_given_as_start_day(reminders):
    # the model often passes day='thursday' along with repeat='monday and thursday'
    reminders.set_reminder("gym", at_time="19:00", day="thursday", repeat="monday and thursday")
    due = dt.datetime.fromtimestamp(reminders.pending()[0]["due"])
    assert due.weekday() in (0, 3)
    assert due - dt.datetime.now() < dt.timedelta(days=4, hours=1)


def test_cancelling_a_repeating_reminder_stops_the_series(reminders):
    reminders.set_reminder("call mum", repeat="every sunday", at_time="18:00")
    assert "won't come back" in reminders.cancel_reminder("call mum")
    assert reminders.pending() == []
