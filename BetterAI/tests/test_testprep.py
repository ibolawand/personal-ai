"""Test countdown: which tests are close, which notebook and notes belong to them, and the quiz it starts."""
import datetime as dt
import json
import random

import pytest

import Engines.TestPrep as T
import main  # noqa: F401  (imported at collection, before the subprocess guard is in place)

TODAY = dt.date(2026, 11, 12)                       # a Thursday
LONG = "<p>" + "Third normal form removes transitive dependencies between columns. " * 6 + "</p>"

class Untis:
    def __init__(self, tests=(), error=None): self.tests, self.error = list(tests), error
    def upcoming_tests(self, days=7):
        if self.error: raise self.error
        return self.tests

class Quiz:
    def __init__(self, misses=()): self.misses, self.started = list(misses), None
    def _load(self): return {"misses": self.misses}
    def start_mixed(self, title, old, sources):
        self.started = (title, old, sources)
        return "started"

def coming(subject="DBI", days=5, topic="", kind="Test", start="0800"):
    d = TODAY + dt.timedelta(days=days)
    return {"id": f"{d:%Y%m%d}-{subject}-{start}", "subject": subject, "kind": kind, "date": d, "topic": topic}

@pytest.fixture
def book(notion):
    """book(name, {title: html}, section={title: html}) → folder id"""
    def make(name, notes, section=None):
        with notion._conn() as c:
            fid = c.execute("INSERT INTO FOLDERS (name, userID) VALUES (?, ?)", (name, notion.user_id)).lastrowid
            sid = c.execute("INSERT INTO FOLDERS (name, parentID, userID) VALUES ('Part', ?, ?)",
                            (fid, notion.user_id)).lastrowid
        for where, group in ((fid, notes), (sid, section or {})):
            for title, html in group.items():
                nid = notion._create_note(title, html)
                with notion._conn() as c:
                    c.execute("UPDATE notes SET folderID = ? WHERE id = ?", (where, nid))
        return fid
    return make

@pytest.fixture
def prep(notion, monkeypatch, tmp_path):
    monkeypatch.setattr(T, "STATE_FILE", str(tmp_path / "test_prep.json"))
    now = [1000.0]
    def make(tests=(), misses=(), error=None):
        p = T.TestPrep(Untis(tests, error), notion, Quiz(misses), today=lambda: TODAY, rng=random.Random(1),
                       clock=lambda: now[0])
        p.now = now
        return p
    return make

def test_card_for_a_mapped_subject(prep, book):
    fid = book("Databases", {"Normal forms": LONG, "Joins": LONG}, section={"Keys": LONG})
    p = prep([coming()])
    assert p.set_notebook("DBI", fid) is True
    assert p.cards() == [{"id": "20261117-DBI-0800", "subject": "DBI", "kind": "Test", "date": "2026-11-17",
                          "when": "Tuesday", "days": 5, "topic": "", "headline": "DBI test on Tuesday · in 5 days",
                          "notebook": {"id": fid, "name": "Databases"}, "notes": 3}]

def test_headlines_for_today_tomorrow_and_other_kinds(prep):
    p = prep([coming(days=0), coming("AM", 1, kind="Schularbeit"), coming("E", 3)])
    assert [c["headline"] for c in p.cards()] == ["DBI test today", "AM Schularbeit tomorrow", "E test on Sunday · in 3 days"]
    assert [c["when"] for c in p.cards()] == ["today", "tomorrow", "Sunday"]

def test_at_most_three_cards(prep):
    assert len(prep([coming(s, i) for i, s in enumerate("ABCDE")]).cards()) == 3

def test_a_notebook_named_like_the_subject_needs_no_asking(prep, book):
    fid = book("dbi", {"Normal forms": LONG})
    assert prep([coming()]).cards()[0]["notebook"] == {"id": fid, "name": "dbi"}

def test_unmapped_subject_and_a_deleted_notebook(prep, book, notion):
    fid = book("Databases", {"Normal forms": LONG})
    p = prep([coming()])
    assert p.cards()[0]["notebook"] is None and p.cards()[0]["notes"] == 0
    p.set_notebook("DBI", fid)
    with notion._conn() as c:
        c.execute("DELETE FROM FOLDERS WHERE id = ?", (fid,))
    assert p.cards()[0]["notebook"] is None
    assert p.set_notebook("DBI", 999) is False

def test_a_renamed_notebook_keeps_its_subject(prep, book, notion):
    fid = book("Databases", {"Normal forms": LONG})
    p = prep([coming()]); p.set_notebook("DBI", fid)
    with notion._conn() as c:
        c.execute("UPDATE FOLDERS SET name = 'DB systems' WHERE id = ?", (fid,))
    assert p.cards()[0]["notebook"]["name"] == "DB systems"

def test_the_topic_picks_the_matching_notes(prep, book):
    fid = book("Databases", {"Normal forms": LONG, "Joins": "<p>" + "A join combines rows of two tables. " * 8 + "</p>"})
    p = prep([coming(topic="Transitive dependencies")]); p.set_notebook("DBI", fid)
    assert p.cards()[0]["notes"] == 1

@pytest.mark.parametrize("topic", ["", "SA 2", "§ 3", "Quantum chromodynamics"])
def test_no_usable_topic_or_no_match_means_the_whole_notebook(prep, book, topic):
    fid = book("Databases", {"Normal forms": LONG, "Joins": LONG})
    p = prep([coming(topic=topic)]); p.set_notebook("DBI", fid)
    assert p.cards()[0]["notes"] == 2

def test_short_notes_do_not_count(prep, book):
    fid = book("Databases", {"Normal forms": LONG, "Stub": "<p>todo</p>"})
    p = prep([coming()]); p.set_notebook("DBI", fid)
    assert p.cards()[0]["notes"] == 1

def test_webuntis_failing_gives_no_cards_and_logs_no_details(prep, monkeypatch):
    seen = []
    monkeypatch.setattr(T.Diagnostics, "problem", lambda kind, detail: seen.append((kind, detail)))
    p = prep(error=RuntimeError("login s3cret-pw refused"))
    assert p.cards() == [] and p.briefing_line() == ""
    assert seen == [("test_prep", "RuntimeError")] * len(seen) and seen

@pytest.mark.parametrize("content", [None, "{not json", '["a list"]'])
def test_a_missing_or_broken_map_file_counts_as_empty(prep, book, content, tmp_path):
    if content is not None:
        (tmp_path / "test_prep.json").write_text(content)
    fid = book("Databases", {"Normal forms": LONG})
    p = prep([coming()])
    assert p.cards()[0]["notebook"] is None
    assert p.set_notebook("DBI", fid) is True and p.cards()[0]["notebook"]["id"] == fid
    assert json.loads((tmp_path / "test_prep.json").read_text()) == {"subjects": {"DBI": fid}}

def test_the_old_flat_map_shape_counts_as_empty(prep, book, tmp_path):
    fid = book("Databases", {"Normal forms": LONG})
    (tmp_path / "test_prep.json").write_text(json.dumps({"DBI": fid}))
    assert prep([coming()]).cards()[0]["notebook"] is None

def test_a_map_file_that_cannot_be_written(prep, book, monkeypatch, tmp_path):
    fid = book("Databases", {"Normal forms": LONG})
    (tmp_path / "a_file").write_text("x")
    monkeypatch.setattr(T, "STATE_FILE", str(tmp_path / "a_file" / "test_prep.json"))   # a folder can't be made there
    p = prep([coming()])
    assert p.set_notebook("DBI", fid) is False and len(p.cards()) == 1

def test_start_quiz_asks_mistakes_first_then_new_ones(prep, book):
    fid = book("Databases", {"Normal forms": LONG, "Joins": LONG, "Keys": LONG, "Views": LONG})
    misses = [{"q": f"q{i}", "a": "a", "source": "Keys", "at": i} for i in range(6)]
    misses.append({"q": "other", "a": "a", "source": "Gear trains", "at": 99})
    p = prep([coming()], misses); p.set_notebook("DBI", fid)
    assert p.start_quiz("20261117-DBI-0800") == ("started", "DBI")
    title, old, sources = p.quiz.started
    assert title == "DBI test"
    assert [m["q"] for m in old] == ["q5", "q4", "q3", "q2"]
    assert [n for _, _, n in sources] == [2, 1, 1] and len({t for t, _, _ in sources}) == 3
    assert all(len(text.split()) >= 25 for _, text, _ in sources)

def test_start_quiz_with_one_note_and_no_mistakes(prep, book):
    fid = book("Databases", {"Normal forms": LONG})
    p = prep([coming()]); p.set_notebook("DBI", fid)
    p.start_quiz("20261117-DBI-0800")
    assert p.quiz.started[1] == [] and [(t, n) for t, _, n in p.quiz.started[2]] == [("Normal forms", 8)]

def test_start_quiz_picks_the_right_one_of_two_tests_of_a_subject(prep, book):
    fid = book("Databases", {"Normal forms": LONG, "Joins": "<p>" + "A join combines rows of two tables. " * 8 + "</p>"})
    p = prep([coming(start="0800", topic="join"), coming(start="1000", topic="transitive")]); p.set_notebook("DBI", fid)
    p.start_quiz("20261117-DBI-1000")
    assert [t for t, _, _ in p.quiz.started[2]] == ["Normal forms"]

def test_start_quiz_says_why_not(prep, book):
    fid = book("Databases", {"Stub": "<p>todo</p>"})
    p = prep([coming()])
    assert p.start_quiz("20261101-DBI-0800") == ("That test isn't coming up any more.", "")
    assert p.start_quiz("20261117-DBI-0800") == ("Tell me which notebook belongs to DBI first.", "DBI")
    p.set_notebook("DBI", fid)
    assert p.start_quiz("20261117-DBI-0800") == ("Your Databases notes don't have enough in them to quiz you on yet.", "DBI")
    assert p.quiz.started is None

def test_briefing_offers_the_nearest_test_that_can_be_quizzed(prep, book):
    fid = book("Databases", {"Normal forms": LONG})
    p = prep([coming("AM", 1), coming("DBI", 5)])
    assert p.briefing_line() == ""
    p.set_notebook("DBI", fid)
    assert p.briefing_line() == "I can quiz you on your Databases notes."

def test_briefing_looks_past_the_three_cards(prep, book):
    fid = book("Databases", {"Normal forms": LONG})
    p = prep([coming(s, i + 1) for i, s in enumerate(["A", "B", "C"])] + [coming("DBI", 6)])
    p.set_notebook("DBI", fid)
    assert len(p.cards()) == 3
    assert p.briefing_line() == "I can quiz you on your Databases notes."

class CountingUntis(Untis):
    calls = 0
    def upcoming_tests(self, days=7):
        self.calls += 1
        return super().upcoming_tests(days)

def test_a_failing_webuntis_is_not_asked_again_for_a_minute(prep, book):
    fid = book("Databases", {"Normal forms": LONG})
    p = prep([coming()], error=RuntimeError("down"))
    p.untis = CountingUntis([coming()], RuntimeError("down"))
    p.set_notebook("DBI", fid)
    assert p.cards() == [] and p.untis.calls == 1
    p.now[0] += 59
    assert p.cards() == [] and p.untis.calls == 1
    p.now[0] += 2
    assert p.cards() == [] and p.untis.calls == 2
    p.untis.error = None
    p.now[0] += 61
    assert len(p.cards()) == 1 and p.untis.calls == 3
    assert len(p.cards()) == 1 and p.untis.calls == 4      # the success cleared the memory

def test_start_quiz_says_when_webuntis_cannot_be_reached(prep):
    p = prep([coming()], error=RuntimeError("down"))
    assert p.start_quiz("20261117-DBI-0800") == ("I can't reach WebUntis right now.", "")
    assert p.quiz.started is None
