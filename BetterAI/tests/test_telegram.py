"""Texting Aria from the phone (a private Telegram bot): only Lala's chat is answered, and only with the phone tools."""
import types

import pytest

from Engines import Telegram as T

TOKEN = "123456:SECRET-token"


class FakeTelegram:
    def __init__(self, updates=()):
        self.updates = list(updates)
        self.sent = []
        self.offsets = []

    def get(self, url, params=None, timeout=None):
        assert url.startswith(f"https://api.telegram.org/bot{TOKEN}/")
        self.offsets.append((params or {}).get("offset"))
        batch, self.updates = self.updates, []
        return Resp({"ok": True, "result": batch})

    def post(self, url, json=None, timeout=None):
        assert url == f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        self.sent.append((json["chat_id"], json["text"]))
        return Resp({"ok": True, "result": {}})


class Resp:
    def __init__(self, data):
        self.data = data
        self.status_code = 200

    def json(self):
        return self.data


def msg(update_id, chat, text, name="Lala"):
    return {"update_id": update_id, "message": {"chat": {"id": chat, "type": "private"},
                                                "from": {"id": chat, "first_name": name}, "text": text}}


@pytest.fixture
def bot():
    def build(updates, answer=lambda text: f"echo: {text}"):
        fake = FakeTelegram(updates)
        return T.TelegramBot(TOKEN, owner=42, answer=answer, session=fake), fake
    return build


def test_only_lalas_chat_is_answered(bot):
    b, fake = bot([msg(1, 42, "add milk to my shopping list"), msg(2, 99, "hi aria", name="Stranger")])
    b.poll_once()
    assert fake.sent == [(42, "echo: add milk to my shopping list")]


def test_messages_are_not_handled_twice(bot):
    b, fake = bot([msg(7, 42, "one")])
    b.poll_once()
    b.poll_once()
    assert fake.offsets == [None, 8] and len(fake.sent) == 1


def test_long_answers_are_split(bot):
    b, fake = bot([msg(1, 42, "long")], answer=lambda text: "word " * 1500)
    b.poll_once()
    assert len(fake.sent) == 2 and all(len(t) <= 4096 for _, t in fake.sent)


def test_the_token_never_shows_up_in_errors(bot, capsys):
    class Down(FakeTelegram):
        def get(self, url, params=None, timeout=None):
            raise ConnectionError(f"HTTPSConnectionPool(host='api.telegram.org'): Max retries exceeded with url: "
                                  f"/bot{TOKEN}/getUpdates")
    b = T.TelegramBot(TOKEN, owner=42, answer=str, session=Down())
    assert b.poll_once() is False
    assert "SECRET" not in capsys.readouterr().out


def test_a_failing_answer_is_said_not_crashed(bot):
    def boom(text):
        raise RuntimeError("model gone")
    b, fake = bot([msg(1, 42, "hi")], answer=boom)
    b.poll_once()
    assert fake.sent == [(42, "Something went wrong on my side. Try again in a moment.")]


def test_pairing_takes_the_first_private_chat():
    fake = FakeTelegram([msg(3, 42, "hello", name="Lala")])
    assert T.first_chat(TOKEN, session=fake) == (42, "Lala", 4)


# ── what Aria may do from the phone ──

def phone_tools():
    from Engines.Tool_Engine import ToolEngine

    class Any:
        menu = None

        def __getattr__(self, name):
            return lambda *a, **k: f"{name} done"
    a = Any()
    return ToolEngine(spotify=a, arduino=a, vision=a, ha=a, reminders=a, focus=a, screen=a, laptop=a, files=a, notion=a,
                      memory_note=a, activity=a, weather=a, undo=a, recall=a, health=a, posture=a, quiz=a,
                      face_learner=lambda name='': 'ok', mail=a, untis=a, owner_check=lambda: False)


def test_phone_turns_only_offer_phone_tools():
    t = phone_tools()
    with t.phone():
        offered = {s["function"]["name"] for s in t.schemas_for("lock my laptop and open my notes and play music")}
        assert "lock_screen" not in offered and "play_song" not in offered and "look_at_screen" not in offered
        assert {"add_to_list", "set_reminder", "get_events"} <= {s["function"]["name"] for s in t.schemas_for("hi")} | offered
        assert t.execute("lock_screen", {}).startswith("Refused")
        # the camera can't confirm it's Lala, but her own Telegram chat does
        assert t.execute("read_note", {"title": "x"}) != t.execute("lock_screen", {})
        assert not t.execute("read_note", {"title": "x"}).startswith("Refused")
    assert t.execute("read_note", {"title": "x"}).startswith("Refused")      # back at the desk: the camera decides


def test_a_phone_message_is_a_normal_turn_without_voice(aria):
    aria.tools = phone_tools()
    offered = []
    real = aria.tools.schemas_for
    aria.tools.schemas_for = lambda text, recent=(): offered.extend(s["function"]["name"] for s in real(text, recent)) or real(text, recent)
    aria.llm.replies = [("Added milk.", [("add_to_list", "Added milk to your shopping list.")])]
    assert aria.answer_phone("add milk to my shopping list and lock the laptop") == "Added milk."
    assert "add_to_list" in offered and "lock_screen" not in offered
    assert not aria.tools._phone                       # back to normal afterwards


def test_reminders_reach_the_phone_when_nobody_is_at_the_desk(aria):
    import types
    sent = []
    aria.telegram = types.SimpleNamespace(send=lambda text: sent.append(text))
    aria.vision = types.SimpleNamespace(is_present=False, _camera_index=0)
    aria.focus = types.SimpleNamespace()
    aria.ha = aria.arduino = None
    import queue, threading
    aria.announcements, aria._wake_event = queue.Queue(), threading.Event()
    aria._on_reminder_due({"kind": "reminder", "text": "call mum", "due": 0})
    assert sent and "call mum" in sent[0]
    aria.vision.is_present = True
    aria._on_reminder_due({"kind": "reminder", "text": "water plants", "due": 0})
    assert len(sent) == 1
