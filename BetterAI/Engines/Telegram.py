"""
Text Aria from the phone: a private Telegram bot. Set up once with ./aria.sh --telegram (asks for the token from
@BotFather, then pairs with the first chat that messages the bot). Only that chat is ever answered; anyone else
who finds the bot gets nothing back.

From the phone she uses only notes, lists, reminders, calendar, mail, school and plain answers (PHONE_TOOLS):
never the laptop, screen, camera, files or music. The token is kept only in the system keyring ("Aria Telegram")
and is scrubbed from every error message (Telegram's URLs contain it).
"""
import threading
import time

try:
    import secretstorage
except ImportError:                     # pragma: no cover
    secretstorage = None

KEYRING_SERVICE = "Aria Telegram"
API = "https://api.telegram.org/bot{token}/{method}"
POLL_S = 50                 # long polling: Telegram holds the request open until a message comes
MAX_TEXT = 4096             # Telegram's limit per message
SORRY = "Something went wrong on my side. Try again in a moment."

PHONE_TOOLS = {
    # notes, lists, calendar
    "add_note", "add_to_list", "add_todo", "read_note", "search_notes", "list_notes", "remove_from_list", "check_off",
    "clear_list", "save_as_note", "restore_note", "set_due", "get_due", "check_solution",
    "get_events", "add_event", "move_event", "delete_event", "daily_briefing",
    # reminders
    "set_reminder", "list_reminders", "cancel_reminder", "snooze_reminder",
    # mail and school
    "check_mail", "read_mail", "search_mail", "draft_reply", "draft_mail", "archive_mail", "mark_mail_read",
    "mail_todo", "mail_to_event", "mark_sender_important",
    "school_day", "school_homework", "school_exams",
    # plain answers
    "calculate", "web_search", "get_weather", "convert_units", "split_bill", "undo_last",
    "recall_conversation", "search_conversations", "what_you_know_about_me", "remember_about_me",
}


def _keyring():
    col = secretstorage.get_default_collection(secretstorage.dbus_init())
    if col.is_locked():
        col.unlock()
    return col


def load_bot():
    """(token, owner chat id) from the keyring, or None."""
    if secretstorage is None:
        return None
    try:
        for item in _keyring().search_items({"service": KEYRING_SERVICE}):
            secret = item.get_secret()
            token = secret.decode() if isinstance(secret, bytes) else secret
            return token, int(item.get_attributes()["chat"])
    except Exception as e:
        print(f"[Telegram] keyring not available: {type(e).__name__}")
    return None


def save_bot(token, chat):
    col = _keyring()
    for item in col.search_items({"service": KEYRING_SERVICE}):
        item.delete()
    col.create_item("Telegram bot for Aria", {"service": KEYRING_SERVICE, "chat": str(chat)}, token.encode())


def _split(text, size=MAX_TEXT):
    out = []
    while len(text) > size:
        cut = text.rfind("\n", 0, size)
        cut = cut if cut > size // 2 else text.rfind(" ", 0, size)
        cut = cut if cut > 0 else size
        out.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    return out + [text] if text else out


def _session(session):
    if session is None:
        import requests
        session = requests.Session()
    return session


def first_chat(token, session=None, wait_s=POLL_S):
    """Pairing: (chat id, first name, next offset) of the first private message to the bot, or None."""
    http = _session(session)
    r = http.get(API.format(token=token, method="getUpdates"), params={"timeout": wait_s}, timeout=wait_s + 10).json()
    for u in r.get("result", []):
        m = u.get("message") or {}
        if (m.get("chat") or {}).get("type") == "private":
            return m["chat"]["id"], (m.get("from") or {}).get("first_name", ""), u["update_id"] + 1
    return None


class TelegramBot:
    def __init__(self, token, owner, answer, session=None):
        """answer: fn(text) -> reply, run for each of Lala's messages."""
        self.token, self.owner, self.answer = token, int(owner), answer
        self.http = _session(session)
        self.offset = None
        self._stop = threading.Event()

    def _url(self, method):
        return API.format(token=self.token, method=method)

    def _clean(self, e) -> str:
        return str(e).replace(self.token, "<token>")

    def send(self, text, chat=None):
        for part in _split(text or "") or ["…"]:
            try:
                self.http.post(self._url("sendMessage"), json={"chat_id": chat or self.owner, "text": part}, timeout=20)
            except Exception as e:
                print(f"[Telegram] couldn't send: {self._clean(e)}")
                return False
        return True

    def poll_once(self, wait_s=0) -> bool:
        """Fetch new messages and answer Lala's. False when Telegram couldn't be reached."""
        params = {"timeout": wait_s}
        if self.offset is not None:
            params["offset"] = self.offset
        try:
            data = self.http.get(self._url("getUpdates"), params=params, timeout=wait_s + 10).json()
        except Exception as e:
            print(f"[Telegram] not reachable: {self._clean(e)}")
            return False
        for u in data.get("result", []):
            self.offset = u["update_id"] + 1
            m = u.get("message") or {}
            text = (m.get("text") or "").strip()
            if (m.get("chat") or {}).get("id") != self.owner or not text:
                continue                     # not Lala: no answer at all
            print(f"[Telegram] You: {text}")
            try:
                reply = self.answer(text) or "Done."
            except Exception as e:
                print(f"[Telegram] answer failed: {type(e).__name__}: {self._clean(e)}")
                reply = SORRY
            print(f"[Telegram] Aria: {reply}")
            self.send(reply)
        return True

    def run(self):
        """Long-poll until stop(); waits longer after failures (offline, laptop asleep)."""
        backoff = 5
        while not self._stop.is_set():
            if self.poll_once(POLL_S):
                backoff = 5
            else:
                self._stop.wait(backoff)
                backoff = min(backoff * 2, 300)

    def start(self):
        threading.Thread(target=self.run, daemon=True, name="telegram").start()
        return self

    def stop(self):
        self._stop.set()


def setup():
    """./aria.sh --telegram: the bot token, then pairing with your chat."""
    import getpass
    print("1. In Telegram, message @BotFather, send /newbot and follow the steps.")
    token = getpass.getpass("2. Paste the token it gives you (not shown): ").strip()
    http = _session(None)
    try:
        me = http.get(API.format(token=token, method="getMe"), timeout=15).json()
    except Exception:
        print("Couldn't reach Telegram. Nothing was saved.")
        return 1
    if not me.get("ok"):
        print("Telegram didn't accept that token. Nothing was saved.")
        return 1
    name = me["result"].get("username")
    print(f"3. Now open t.me/{name} on your phone and send it any message. Waiting…")
    for _ in range(6):
        found = first_chat(token, session=http)
        if found:
            chat, first, offset = found
            if input(f"Message from {first or 'someone'} (chat {chat}). Is that you? [y/N] ").strip().lower() == "y":
                http.get(API.format(token=token, method="getUpdates"), params={"offset": offset}, timeout=15)
                save_bot(token, chat)
                TelegramBot(token, chat, answer=str, session=http).send(
                    "Hi, it's Aria! Text me things like 'add milk to my shopping list' or 'what do I have tomorrow?'")
                print("Paired. Restart Aria once, then text your bot.")
                return 0
            http.get(API.format(token=token, method="getUpdates"), params={"offset": offset}, timeout=15)
            print("Okay, waiting for your message instead…")
    print("No message arrived. Run ./aria.sh --telegram again.")
    return 1


if __name__ == "__main__":
    raise SystemExit(setup())
