import pytest

from Engines.Tool_Engine import ToolEngine


class Any:
    menu = None

    def __getattr__(self, name):
        return lambda *a, **k: None


@pytest.fixture(scope="module")
def tools():
    a = Any()
    return ToolEngine(spotify=a, arduino=a, vision=a, ha=a, reminders=a, focus=a, screen=a, laptop=a, files=a,
                      notion=a, initiative=a, memory_note=a, activity=a, weather=a, undo=a, recall=a, health=a, posture=a, quiz=a, face_learner=lambda name='': 'ok', mail=a)


def names(tools, text, recent=()):
    return {s["function"]["name"] for s in tools.schemas_for(text, recent)}


@pytest.mark.parametrize("text,needed", [
    ("play no excuses by NF", "play_song"), ("pause the music", "pause_music"), ("open packet tracer", "open_app"),
    ("turn the volume up a bit", "change_laptop_volume"), ("find the pdf about gear trains", "search_file_contents"),
    ("what's this error on my screen?", "look_at_screen"), ("start a pomodoro on c#", "start_focus"),
    ("add eggs to my shopping list", "add_to_list"), ("move the dentist to friday", "move_event"),
    ("I bought the eggs", "check_off"), ("what did we talk about yesterday?", "recall_conversation"),
    ("forget that I'm bored", "forget_about_me"), ("this is my good posture", "remember_good_posture"), ("quiz me on my c# note", "start_quiz"), ("learn my face", "learn_my_face"), ("restore my c# note from yesterday", "restore_note"), ("how many miles is 42 km", "convert_units"),
    ("split the bill between 3", "split_bill"), ("are your systems okay?", "system_check"),
    ("remind me at 6 to call mum", "set_reminder"), ("do I need a jacket tomorrow?", "get_weather"),
    ("dim the lights", "set_led_brightness"), ("I live in Vienna", "set_home_city"),
    ("any new emails?", "check_mail"), ("read the one from Mr Huber", "read_mail"),
    ("what did Sara write about friday", "search_mail"), ("reply that I'll be there at 3", "draft_reply"),
    ("write an email to Mr Huber saying I'm sick", "draft_mail"), ("archive that email", "archive_mail"),
    ("mark the mail from Sara as read", "mark_mail_read"), ("remind me to answer that email tomorrow", "mail_todo"),
    ("turn that email into an event", "mail_to_event"), ("always tell me when Sara emails", "mark_sender_important"),
])
def test_the_needed_tool_is_offered(tools, text, needed):
    assert needed in names(tools, text)


def test_small_talk_gets_only_the_core(tools):
    got = names(tools, "how are you?")
    assert got <= ToolEngine.CORE and len(got) < 15


def test_follow_ups_keep_the_recent_group(tools):
    assert "open_file" in names(tools, "the second one", recent={"find_files"})


def test_routing_saves_most_of_the_context(tools):
    import json
    full = len(json.dumps(tools.schemas))
    small = len(json.dumps(tools.schemas_for("add eggs to my shopping list")))
    assert small < full * 0.4


def test_missing_tool_reply_retries_with_everything(aria):
    calls = []

    def fake(prompt, history, system, tools, execute, **_):
        calls.append(len(tools))
        return ("Sorry, I can't do that.", []) if len(calls) == 1 else ("Opened it.", [("open_app", "Opening x.")])
    full = [{"function": {"name": f"t{i}"}} for i in range(20)]
    aria.tools = type("T", (), {"schemas": full, "execute": lambda self, n, a: "",
                                "schemas_for": lambda self, text, recent: full[:5]})()
    aria.llm.chat_with_tools = fake
    reply, used = aria.handle_turn("do the thing", check_state=False)
    assert calls == [5, 20] and reply == "Opened it."


def test_claimed_action_without_tool_is_retried(aria):
    calls = []

    def fake(prompt, history, system, tools, execute, **_):
        calls.append(prompt)
        if len(calls) == 1:
            return "I'll turn the volume down a bit.", []
        return "Turned it down.", [("change_laptop_volume", "Volume 40%.")]
    aria.llm.chat_with_tools = fake
    reply, used = aria.handle_turn("turn the volume down", check_state=False)
    assert len(calls) == 2 and "must call the right tool" in calls[1] and used[0][0] == "change_laptop_volume"


def test_small_talk_is_not_retried(aria):
    aria.llm.replies = [("Pretty good! How are you?", [])]
    aria.handle_turn("how are you", check_state=False)
    assert len(aria.llm.prompts) == 1


def test_led_tools_only_while_the_strip_is_plugged_in():
    """The Arduino controller always exists (it keeps retrying in the background), so Aria offered to change
    the desk lights with nothing plugged in."""
    import types
    strip = types.SimpleNamespace(is_connected=False)
    t = ToolEngine(arduino=strip)
    assert "set_led_color" not in names(t, "make the lights blue")
    strip.is_connected = True                      # plugged in later
    assert "set_led_color" in names(t, "make the lights blue")
