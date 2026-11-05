"""How Aria talks: filters, rewrites of repeated/stock replies, the weekly review, conversation starters."""

import datetime as dt
import time
import types

import pytest

import main
from main import SentenceStreamer, matches_phrase, tidy_reply


# ── text filters ──

def test_tidy_reply_drops_stock_lines_and_emojis():
    assert tidy_reply("I'm here and ready to help. The meeting is at 3. 😊") == "The meeting is at 3."
    assert tidy_reply("Done! Let me know if you need anything else.") == "Done!"
    assert tidy_reply("I’m just a desk AI. Sure thing.") == "Sure thing."     # curly apostrophe


@pytest.mark.parametrize("text,match", [("go to sleep", True), ("Aria, please go to sleep", True),
                                        ("remind me to sleep at 11", False), ("quit spotify", False)])
def test_sleep_phrases_need_the_whole_message(text, match):
    assert matches_phrase(main.SLEEP_PHRASES + main.SHUTDOWN_PHRASES, text) is match


def test_regexes():
    assert main.CHAT_BRUSH_OFF_RE.match("eh fine") and not main.CHAT_BRUSH_OFF_RE.match("yeah i made carbonara")
    assert main.CONFUSED_RE.match("what?") and main.CONFUSED_RE.match("huh") and not main.CONFUSED_RE.match("what time is it")
    assert main.NOT_NOW_RE.match("not now") and main.NOT_NOW_RE.match("I'm busy") and not main.NOT_NOW_RE.match("notes")


def stream(text, previous=()):
    out = []
    s = SentenceStreamer(out.append, previous=previous)
    for i in range(0, len(text), 7):      # arrives in small chunks, like from the model
        s.feed(text[i:i + 7])
    s.flush()
    return out, s


def test_streamer_splits_sentences_and_skips_code():
    out, s = stream("First one. Here's code:\n```py\nprint(1)\n```\nAnd done.")
    assert out == ["First one.", "Here's code:", "And done."] and s.saw_code


def test_streamer_never_speaks_a_repeat():
    out, s = stream("I see. Have a great evening!", previous=["I see. Have a great evening!"])
    assert out == [] and s.count == 0


def test_streamer_releases_held_sentences_once_the_reply_differs():
    out, _ = stream("I see. That's actually great news!", previous=["I see. Have a great evening!"])
    assert out == ["I see.", "That's actually great news!"]


def test_streamer_holds_everything_after_a_stock_opener():
    out, s = stream("I'm here and ready to help. How are you?")
    assert out == [] and s.robotic_start


# ── handle_turn rewrites ──

def test_repeated_reply_is_rewritten(aria):
    aria._recent.append([{"role": "user", "content": "i see"},
                         {"role": "assistant", "content": "I see. Have a great evening!"}])
    aria.llm.replies = [("I see. Have a great evening!", [])]
    aria.llm.chats = ["Haha, okay. Anything fun planned tonight?"]
    reply, _ = aria.handle_turn("no", check_state=False)
    assert reply == "Haha, okay. Anything fun planned tonight?"


def test_stock_reply_is_rewritten(aria):
    aria.llm.replies = [("I'm here and ready to help.", [])]
    aria.llm.chats = ["Pretty good! Quiet evening so far. How are you?"]
    reply, _ = aria.handle_turn("how are u", check_state=False)
    assert reply == "Pretty good! Quiet evening so far. How are you?"


def test_failed_rewrites_fall_back_to_a_line_from_code(aria):
    aria._recent.append([{"role": "user", "content": "x"}, {"role": "assistant", "content": "I'm here to help."}])
    aria.llm.replies = [("I'm here to help.", [])]
    aria.llm.chats = ["I'm here to help.", "I'm here to help."]
    reply, _ = aria.handle_turn("hate u", check_state=False)
    assert reply == "Ouch. Alright, what did I do?"


def test_repeat_after_a_tool_call_is_fine(aria):
    aria._recent.append([{"role": "user", "content": "volume up"},
                         {"role": "assistant", "content": "Volume is at 60%."}])
    aria.llm.replies = [("Volume is at 60%.", [("change_laptop_volume", "Volume is at 60%.")])]
    reply, _ = aria.handle_turn("a bit louder", check_state=False)
    assert reply == "Volume is at 60%." and aria.llm.chats == []


def test_open_my_calendar_goes_to_mynotion_in_code(aria, _never_launch_anything, monkeypatch):
    import Engines.NotionEngine as N
    monkeypatch.setattr(N.os.path, "exists", lambda p: True)
    reply, used = aria.handle_turn("open my calendar", check_state=False)
    assert used[0][0] == "open_mynotion" and aria.llm.prompts == []
    assert _never_launch_anything[-1][1] == "--open=calendar"


def test_confused_gets_a_rephrase_instruction(aria):
    aria._recent.append([{"role": "user", "content": "hi"}, {"role": "assistant", "content": "Long day?"}])
    aria.llm.replies = [("I asked whether your day was long.", [])]
    aria.handle_turn("what?", check_state=False)
    assert "didn't get what you just said" in aria.llm.prompts[0]


def test_confirmation_is_decided_in_code(aria):
    done = []
    aria.confirm.request("delete the event", lambda: done.append(1) or "Deleted.")
    reply, used = aria.handle_turn("yes", check_state=False)
    assert reply == "Deleted." and done == [1] and aria.llm.prompts == []


# ── weekly review ──

def test_weekly_review_answers_are_handled_in_code(aria, notion):
    notion.add_to_list("to-do", "pay rent, call the landlord, book train tickets, water the plants")
    items = notion.open_todo_items()
    aria._review = {"items": items, "i": 0, "coming": ""}
    r1, _ = aria.handle_turn("done", check_state=False)
    r2, _ = aria.handle_turn("drop that one", check_state=False)
    r3, _ = aria.handle_turn("remind me about it on monday at 10", check_state=False)
    r4, _ = aria.handle_turn("keep it", check_state=False)
    assert r1.startswith("Ticked off pay rent.") and r2.startswith("Dropped call the landlord.")
    assert aria.reminders.calls == [("book train tickets", {"at_time": "10", "day": "monday"})]
    assert r4.startswith("Keeping it. That's all of them.") and aria._review is None
    left = [t for _, t in notion.open_todo_items()]
    assert left == ["book train tickets", "water the plants"]
    assert aria.llm.prompts == []        # the model was never asked


def test_weekly_review_can_be_stopped(aria, notion):
    notion.add_to_list("to-do", "a thing")
    aria._review = {"items": notion.open_todo_items(), "i": 0, "coming": ""}
    reply, _ = aria.handle_turn("let's stop", check_state=False)
    assert reply == "Okay, we'll leave the rest for now." and aria._review is None


# ── conversation starters ──

@pytest.fixture
def initiative(aria, monkeypatch, tmp_path):
    import Engines.Initiative as I
    monkeypatch.setattr(I, "STATE_FILE", str(tmp_path / "initiative.json"))
    for name in ("screen_locked", "fullscreen_app", "mic_in_use_by_others"):
        monkeypatch.setattr(I, name, lambda: False)
    aria.vision = types.SimpleNamespace(_camera_index=0, _running=True, is_present=True)
    aria.focus = types.SimpleNamespace(active=False)
    aria._shutting_down = False
    aria.activity = None
    aria.followups = None
    monkeypatch.setattr(I, "in_quiet_hours", lambda now=None: False)
    ini = I.Initiative(aria)
    ini._present_since = time.time() - 3600
    aria.initiative = ini
    return ini


def test_quiet_hours_wrap_midnight():
    import Engines.Initiative as I
    assert I.in_quiet_hours(dt.datetime(2026, 1, 1, 23, 0))
    assert I.in_quiet_hours(dt.datetime(2026, 1, 1, 7, 0))
    assert not I.in_quiet_hours(dt.datetime(2026, 1, 1, 12, 0))


def test_initiative_blocking_rules(initiative, aria):
    now = time.time()
    assert initiative._blocked(now, True) == ""
    assert initiative._blocked(now, False) == "nobody here"
    aria.muted = True
    assert initiative._blocked(now, True) == "muted"
    aria.muted = False
    aria.focus.active = True
    assert initiative._blocked(now, True) == "focus session"
    aria.focus.active = False
    aria.last_talked = now
    assert initiative._blocked(now, True) == "talked recently"
    aria.last_talked = 0
    initiative._present_since = now
    assert initiative._blocked(now, True) == "just arrived"


def test_watching_something_blocks(initiative, aria):
    initiative._present_since = time.time() - 3600
    aria.activity = types.SimpleNamespace(watching=lambda: True)
    assert initiative._blocked(time.time(), True) == "watching something"


def test_ignored_chats_back_off(initiative):
    initiative.finished("chat", answered=False)
    initiative.finished("chat", answered=False)
    assert initiative.state["ignored"] == 2
    initiative.finished("chat", answered=True)
    assert initiative.state["ignored"] == 0
    initiative.finished("chat", answered=True, snoozed=True)
    assert initiative.state["snooze_until"] > time.time() + 2 * 3600


def test_break_nudge_after_a_long_stretch(initiative, aria):
    act = types.SimpleNamespace(stretch_minutes=lambda: 100, stretch_main_app=lambda: "PyCharm")
    aria.activity = act
    op = initiative._break_nudge()
    assert op["kind"] == "break" and "1 hour 40 minutes" in op["prompt"] and "PyCharm" in op["prompt"]
    assert initiative._break_nudge() is None          # not again right away


def test_chat_topics_vary(initiative, aria):
    aria.memory = types.SimpleNamespace(get_memories=lambda n=30: ["Plays guitar", "Studies C#", "Likes pasta"])
    kinds = []
    for _ in range(12):
        initiative._chat_prompt([])
        kinds.append(initiative.state["last_topic"])
    assert all(a != b or a == "fact" for a, b in zip(kinds, kinds[1:]))       # never the same kind twice in a row
    # no fact twice before all three were used (the list keeps the last 8, so look at a fresh run)
    initiative.state = {}
    for _ in range(60):
        initiative._chat_prompt([])
        if len(initiative.state.get("recent_facts", [])) >= 3:
            break
    used = initiative.state["recent_facts"]
    assert len(set(used)) == 3


# ── voice input she isn't sure about ──

def test_unsure_voice_input_is_asked_back(aria):
    said = []
    aria.speak = said.append
    assert aria._check_heard("no pitch", 0.3) is None
    assert said == ["Sorry, did you say: no pitch?"]
    assert aria._check_heard("yes", 0.9) == "no pitch"          # confirmed: act on it


def test_unsure_then_no_asks_to_repeat(aria):
    said = []
    aria.speak = said.append
    aria._check_heard("open packed racer", 0.2)
    assert aria._check_heard("no", 0.9) is None and said[-1] == "Okay, say it again?"
    assert aria._check_heard("open packet tracer", 0.9) == "open packet tracer"


def test_confident_input_passes_and_sleep_is_never_questioned(aria):
    aria.speak = lambda t: None
    assert aria._check_heard("what's the time", 0.8) == "what's the time"
    assert aria._check_heard("go to sleep", 0.2) == "go to sleep"


def test_whisper_hallucinations_are_recognised():
    from speech_to_text import HALLUCINATIONS
    for t in ["Thanks for watching!", "Thank you.", "you", "Please subscribe", "Alright, have a great week."]:
        assert HALLUCINATIONS.match(t), t
    for t in ["thank you, that helped", "open youtube", "subscribe me to the newsletter please"]:
        assert not HALLUCINATIONS.match(t), t


# ── voice tone per sentence ──

@pytest.mark.parametrize("sentence,tone", [
    ("Aw, I'm sorry to hear that.", "soft"), ("That sounds rough.", "soft"), ("Take your time.", "soft"),
    ("Haha, you caught me!", "playful"), ("Wow, rude.", "playful"), ("Done, milk's on the list!", "playful"),
    ("The meeting is at three.", "neutral"), ("What's on your mind?", "neutral"),
])
def test_sentence_tone(sentence, tone):
    from Engines.voice_engine import sentence_tone
    assert sentence_tone(sentence) == tone


def test_due_reminder_shows_a_card_and_snooze_works(aria, memory):
    import queue, threading
    from Engines.Reminders import Reminders
    cards, msgs = [], []
    aria.ui.show_card = cards.append
    aria.ui.message = lambda role, text: msgs.append(text)
    aria.ui.set_state = lambda s: None
    aria.reminders = Reminders(memory, on_due=lambda r: None)
    aria.focus = types.SimpleNamespace(finish=lambda: "", end_break=lambda: "")
    aria.ha = None
    aria.vision = types.SimpleNamespace(is_present=True)
    aria.announcements, aria._wake_event = queue.Queue(), threading.Event()
    r = {"id": 1, "text": "call mum", "kind": "reminder", "due": time.time(), "created": time.time()}
    aria.reminders.last_fired = r
    aria._on_reminder_due(r)
    assert cards == [{"type": "reminder", "title": "Reminder", "text": "Call mum."}]
    aria.snooze_from_card(10)
    assert msgs == ["Snoozed 'call mum' for 10 min."] or msgs[0].startswith("Snoozed 'call mum'")
    assert len(aria.reminders.pending()) == 1


# ── quick capture ──

def test_capture_falls_back_to_the_inbox(aria):
    msgs = []
    aria.ui.message = lambda role, text: msgs.append(text)
    aria.llm.replies = [("", [])]                       # the model filed nothing
    aria.quick_capture("idea: a plant-watering robot")
    assert msgs == ["✓ Saved to your Inbox."]
    assert "plant-watering robot" in aria.notion.read_note("Inbox")


def test_capture_only_offers_filing_tools(aria):
    seen = {}

    def fake(prompt, history, system, tools, execute, **_):
        seen["tools"] = [t["function"]["name"] for t in tools]
        return "Added.", [("add_to_list", "Added batteries to your Shopping list.")]
    aria.tools = types.SimpleNamespace(schemas=[{"function": {"name": n}} for n in
                                                ("add_to_list", "add_event", "play_song", "close_app")],
                                       execute=lambda n, a: "")
    aria.llm.chat_with_tools = fake
    aria.ui.message = lambda role, text: None
    assert aria.quick_capture("buy batteries") == "Added batteries to your Shopping list."
    assert seen["tools"] == ["add_to_list", "add_event"]


def test_capture_ideas_and_links_go_to_the_inbox_directly(aria):
    aria.ui.message = lambda role, text: None
    assert aria.quick_capture("idea: aria could water my plants") == "Saved to your Inbox."
    assert aria.quick_capture("https://example.com/recipe") == "Saved to your Inbox."
    inbox = aria.notion.read_note("Inbox")
    assert "water my plants" in inbox and "example.com/recipe" in inbox and aria.llm.prompts == []


def test_weekly_review_ends_with_a_recap(aria, notion, memory):
    import Engines.FocusMode as F
    aria.focus = F.FocusMode(types.SimpleNamespace(pending=lambda kinds=None: []), memory=memory)
    memory.log_focus(50, "c#")
    memory.log_focus(30, "databases")
    notion.add_to_list("to-do", "one thing")
    aria._review = {"items": notion.open_todo_items(), "i": 0, "coming": "tomorrow 15:00 Dentist"}
    reply, _ = aria.handle_turn("done", check_state=False)
    assert reply == ("Ticked off one thing. That's all of them. This week you put in 1 h 20 min of focus in 2 blocks, "
                     "mostly c# (50 min), databases (30 min) — nice. Coming up: tomorrow 15:00 Dentist.")
