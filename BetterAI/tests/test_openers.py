"""Weekend openers: on free days the companion starts a chat now and then. Rules decided in code."""
import datetime as dt
import random

from Engines.Companion import UNKNOWN
from Engines.Openers import (free_day, Openers, Topic, clean_line, prompt_for, FIRST_S, MAX_GAP_S, PER_DAY,
                             MIN_GAP_S, MAX_BASE_GAP_S, NUDGES)

SAT = dt.datetime(2026, 11, 14, 15, 0)
MON = dt.datetime(2026, 11, 16, 15, 0)


def test_free_day_means_no_lessons_or_weekend_when_unknown():
    assert free_day(MON, None)                     # no lessons today (holiday)
    assert not free_day(MON, (755, 1325))
    assert free_day(SAT, UNKNOWN) and not free_day(MON, UNKNOWN)
    assert free_day(SAT, None)


def _facts(**kw):
    base = dict(kind="code", hour=15, test=None, today=[], watch_min=0, rain=False)
    return {**base, **kw}


def test_first_opener_ten_minutes_after_waking_then_gaps():
    o = Openers(random.Random(1))
    o.woke(1000)
    assert not o.due(1000 + FIRST_S - 1, SAT.date())
    assert o.due(1000 + FIRST_S, SAT.date())
    o.shown(5000, o.pick(_facts()), SAT.date())
    assert not o.due(5000 + MIN_GAP_S - 1, SAT.date())
    assert o.due(5000 + MAX_BASE_GAP_S, SAT.date())


def test_ignored_openers_back_off_and_an_answer_resets():
    o = Openers(random.Random(2))
    t = 0
    gaps = []
    for _ in range(5):
        o.shown(t, o.pick(_facts()), SAT.date())
        gaps.append(o.next_at - t)
        t = o.next_at
    assert gaps[0] <= MAX_BASE_GAP_S and gaps[1] <= MAX_BASE_GAP_S   # one ignored: no back-off yet
    assert gaps[2] >= 2 * MIN_GAP_S                                   # two ignored: the gap doubles
    assert max(gaps) <= MAX_GAP_S
    o.answered()
    o.shown(t, o.pick(_facts()), SAT.date())
    assert o.next_at - t <= MAX_BASE_GAP_S


def test_at_most_eight_a_day():
    o = Openers(random.Random(3))
    for i in range(PER_DAY):
        assert o.due(i * 10**5, SAT.date())
        o.shown(i * 10**5, o.pick(_facts()), SAT.date())
        o.answered()
    assert not o.due(10**9, SAT.date())
    assert o.due(10**9, (SAT + dt.timedelta(days=1)).date())         # a new day starts over


def test_nudges_come_from_real_things_and_never_twice_in_a_row():
    o = Openers(random.Random(4))
    facts = _facts(test={"subject": "Maths", "when": "tomorrow", "days": 1})
    kinds = []
    for _ in range(20):
        topic = o.pick(facts)
        kinds.append(topic.name)
        o.last = topic
    assert "test" in kinds
    for a, b in zip(kinds, kinds[1:]):
        assert not (a in NUDGES and b in NUDGES)
        assert a != b


def test_nudge_sources():
    o = Openers(random.Random(5))
    seen = set()
    facts = _facts(kind="video", watch_min=75, today=[("dentist", "16:30")],
                   test={"subject": "Bio", "when": "Monday", "days": 2})
    for _ in range(60):
        t = o.pick(facts)
        seen.add(t.name)
        o.last = t
    assert {"test", "today", "watch"} <= seen
    # nothing real to nudge about: only small talk
    o = Openers(random.Random(6))
    far = _facts(test={"subject": "Bio", "when": "next week", "days": 6}, watch_min=20)
    for _ in range(30):
        t = o.pick(far)
        assert t.name not in NUDGES
        o.last = t


def test_topics_carry_facts_and_a_fallback():
    o = Openers(random.Random(7))
    o.last = Topic("app", "", "x")
    t = None
    while t is None or t.name != "test":
        t = o.pick(_facts(test={"subject": "Maths", "when": "tomorrow", "days": 1}))
        o.last = Topic("app", "", "x")
    assert "Maths" in t.about and "Maths" in t.fallback
    assert "Maths" in prompt_for(t)


def test_clean_line_falls_back_on_bad_model_output():
    assert clean_line('"how was your day so far?"', "fb") == "how was your day so far?"
    assert clean_line("", "fb") == "fb"
    assert clean_line(None, "fb") == "fb"
    assert clean_line("How can I help you today?", "fb") == "fb"
    assert clean_line("a " * 60, "fb") == "fb"                       # far too long
    assert clean_line("one line\nand another thing\nand a third", "fb") == "fb"
