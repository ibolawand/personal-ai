"""The 'What Aria knows about me' note and follow-ups."""

import datetime as dt
import time

import pytest

from Engines.Followups import Followups, ask_time
from Engines.MemoryNote import NOTE_TITLE, MemoryNote, parse, render


@pytest.fixture
def mn(memory, notion, monkeypatch, tmp_path):
    import Engines.MemoryNote as M
    monkeypatch.setattr(M, "STATE_FILE", str(tmp_path / "memory_note.json"))
    return MemoryNote(memory, notion, notion.confirm)


def note_facts(mn):
    return parse(mn._note()["content"])


def test_first_sync_creates_the_note(mn, memory):
    memory.save_memory("Plays guitar")
    mn.sync()
    assert note_facts(mn) == ["Plays guitar"]


def test_edits_in_the_note_reach_aria(mn, memory, notion):
    memory.save_memory("Plays guitar")
    memory.save_memory("Is bored")
    mn.sync()
    notion._set_content(mn._note()["id"], render(["Plays guitar", "Is vegetarian"]))
    mn.sync()
    assert sorted(memory.get_memories()) == ["Is vegetarian", "Plays guitar"]


def test_new_facts_reach_the_note(mn, memory):
    mn.sync()
    memory.save_memory("Sister Lina loves climbing")
    mn.sync()
    assert "Sister Lina loves climbing" in note_facts(mn)


def test_both_changed_user_edits_win_and_new_facts_are_added(mn, memory, notion):
    memory.save_memory("A")
    memory.save_memory("B")
    mn.sync()
    notion._set_content(mn._note()["id"], render(["A"]))         # Lala deletes B
    memory.save_memory("C")                                       # Aria learns C meanwhile
    mn.sync()
    assert sorted(memory.get_memories()) == ["A", "C"]
    assert sorted(note_facts(mn)) == ["A", "C"]


def test_deleted_note_is_recreated_without_losing_memory(mn, memory, notion):
    memory.save_memory("Plays guitar")
    mn.sync()
    conn = notion._conn
    with conn() as c:
        c.execute("DELETE FROM notes WHERE title = ?", (NOTE_TITLE,))
    mn.sync()
    assert memory.get_memories() == ["Plays guitar"] and note_facts(mn) == ["Plays guitar"]


def test_forget_matches_loose_wording(mn, memory):
    memory.save_memory("User is bored")
    memory.save_memory("Plays guitar")
    assert mn.forget("that I'm bored") == "Forgotten: User is bored."
    assert memory.get_memories() == ["Plays guitar"]


def test_forget_everything_asks_first(mn, memory):
    memory.save_memory("Plays guitar")
    assert mn.forget("everything").startswith("NEEDS CONFIRMATION")
    assert memory.get_memories() == ["Plays guitar"]


# ── follow-ups ──

NOW = dt.datetime(2026, 11, 5, 13, 0)      # a Thursday


@pytest.mark.parametrize("when,expected", [
    ("tomorrow", dt.datetime(2026, 11, 6, 17, 0)),
    ("friday at 3 pm", dt.datetime(2026, 11, 6, 17, 0)),
    ("today", dt.datetime(2026, 11, 5, 16, 0)),
    ("this weekend", dt.datetime(2026, 11, 8, 17, 0)),
    ("next week", dt.datetime(2026, 11, 12, 17, 0)),
])
def test_ask_time(when, expected):
    assert dt.datetime.fromtimestamp(ask_time(when, NOW)) == expected


def test_late_today_waits_for_the_morning():
    late = dt.datetime(2026, 11, 5, 21, 30)
    assert dt.datetime.fromtimestamp(ask_time("tonight", late)) == dt.datetime(2026, 11, 6, 9, 0)


def test_unparseable_when_is_skipped():
    assert ask_time("whenever", NOW) is None


def test_followups_dedupe_and_due(memory, notion):
    f = Followups(memory, notion)
    item = {"about": "the math exam", "when": "tomorrow", "question": "How did the math exam go?"}
    assert f.add_from_extraction([item]) == 1
    assert f.add_from_extraction([dict(item, about="math exam")]) == 0     # same thing again
    assert f.due() is None                                                 # not yet
    fid = memory.pending_followups()[0]["id"]
    conn = memory._connect()
    conn.execute("UPDATE followups SET ask_after = ? WHERE id = ?", (time.time() - 1, fid))
    conn.commit()
    conn.close()
    due = f.due()
    assert due["question"] == "How did the math exam go?"
    f.asked(due)
    assert f.due() is None


def test_followup_skipped_when_it_is_a_calendar_event(memory, notion):
    tomorrow = dt.date.today() + dt.timedelta(days=1)
    notion.add_event("Dentist appointment", tomorrow.isoformat(), "15:00")
    f = Followups(memory, notion)
    assert f.add_from_extraction([{"about": "dentist appointment", "when": "tomorrow",
                                   "question": "How was the dentist?"}]) == 0


def test_clean_up_asks_then_forgets_only_the_junk(mn, memory):
    for f in ["Plays guitar", "User asked to play a song", "User is bored"]:
        memory.save_memory(f)
    facts = memory.get_memories()
    junk = {"User asked to play a song", "User is bored"}
    mn.llm = type("L", (), {"find_junk_facts": lambda self, fs: [i for i, f in enumerate(fs) if f in junk]})()
    out = mn.clean_up()
    assert out.startswith("NEEDS CONFIRMATION: forget 2 saved things")
    assert sorted(memory.get_memories()) == sorted(facts)            # nothing gone before "yes"
    assert mn.confirm.resolve("yes").startswith("Done, I forgot those 2")
    assert memory.get_memories() == ["Plays guitar"]
    assert note_facts(mn) == ["Plays guitar"]


def test_clean_up_with_nothing_to_remove(mn, memory):
    memory.save_memory("Plays guitar")
    mn.llm = type("L", (), {"find_junk_facts": lambda self, fs: []})()
    assert mn.clean_up().startswith("I went through everything")
