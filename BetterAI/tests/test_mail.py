import sqlite3
import time
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

import pytest

import main  # noqa: F401  (imported before the fixtures stub out subprocess)

from Engines.Confirm import Confirmer
from Engines.MailEngine import MailEngine
from tests.conftest import FakeLLM


def iso(minutes_ago=0):
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()


def add(db, gm, from_name, from_addr, subject, body="hello", unread=1, filtered=0, minutes_ago=10, uid=None,
        message_id=None):
    with sqlite3.connect(db) as c:
        c.execute("INSERT INTO mail_message (gm_msgid, uid, message_id, from_name, from_addr, to_addrs, subject, date,"
                  " preview, body_text, body_html, unread, filtered, filter_reason) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (gm, uid, message_id, from_name, from_addr, "lala@gmail.com", subject, iso(minutes_ago), body[:200],
                   body, "", unread, filtered, "newsletter" if filtered else None))


class FakeIMAP:
    """imaplib.IMAP4_SSL stand-in: a Gmail INBOX with raw messages by uid."""
    def __init__(self, messages=None, fail=None):
        self.messages = messages or {}
        self.fail = fail
        self.flags = []
        self.logged_in = False
        self.gm_uids = {}                 # Gmail id -> current uid (X-GM-MSGID search)
        self.uidvalidity = b"1"

    def __call__(self, host, port=993, **kw):
        if self.fail:
            raise self.fail
        return self

    def login(self, user, pw):
        self.logged_in = True
        return "OK", [b""]

    def select(self, box):
        return "OK", [str(len(self.messages)).encode()]

    def response(self, code):
        return code, [self.uidvalidity]

    def uid(self, cmd, *args):
        if cmd == "SEARCH" and args[0] == "X-GM-MSGID":
            uid = self.gm_uids.get(str(args[1]))
            return "OK", [str(uid).encode() if uid else b""]
        if cmd == "SEARCH":
            return "OK", [" ".join(str(u) for u in self.messages).encode()]
        if cmd == "FETCH":
            out = []
            for u in args[0].decode().split(",") if isinstance(args[0], bytes) else args[0].split(","):
                raw = self.messages[int(u)]
                out.append((f"{u} (UID {u} X-GM-MSGID {1000 + int(u)} X-GM-THRID 7 FLAGS () BODY[] {{{len(raw)}}}".encode(), raw))
                out.append(b")")
            return "OK", out
        if cmd == "STORE":
            self.flags.append(args)
            return "OK", [b""]
        raise AssertionError(cmd)

    def logout(self):
        return "BYE", [b""]


def raw(frm, subject, body, headers=()):
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = frm, "lala@gmail.com", subject
    m["Date"] = "Sat, 07 Nov 2026 10:00:00 +0100"
    m["Message-ID"] = f"<{abs(hash(subject))}@x>"
    for k, v in headers:
        m[k] = v
    m.set_content(body)
    return m.as_bytes()


@pytest.fixture
def mail(notion_db, notion):
    eng = MailEngine(notion_db, Confirmer(), notion=notion, llm=FakeLLM(chats=["He moved the deadline to Friday."]),
                     password=lambda addr: "pw", imap=FakeIMAP())
    eng._bg = lambda fn: fn()                      # Gmail updates run in-line in tests
    with sqlite3.connect(notion_db) as c:
        c.execute("INSERT INTO mail_state (key, value) VALUES ('address', 'lala@gmail.com'), ('last_sync', ?)", (iso(1),))
    return eng


def test_check_mail_lists_new(mail, notion_db):
    add(notion_db, "a", "Mr Huber", "huber@school.example", "Project deadline")
    add(notion_db, "b", "Sara K", "sara@gmail.com", "friday?")
    add(notion_db, "c", "Medium", "noreply@medium.com", "Stories", filtered=1)
    add(notion_db, "d", "Old", "old@x.example", "read already", unread=0)
    assert mail.check_mail() == "Two new: one from Sara K about friday?, one from Mr Huber about Project deadline."


def test_nothing_new(mail):
    assert mail.check_mail() == "Nothing new."


def test_read_mail_by_sender_marks_it_read(mail, notion_db):
    add(notion_db, "a", "Mr Huber", "huber@school.example", "Project deadline", body="The deadline is Friday now.", uid=4)
    mail.imap.gm_uids = {"a": 4}
    out = mail.read_mail("huber")
    assert out == "From Mr Huber, about Project deadline: The deadline is Friday now."
    with sqlite3.connect(notion_db) as c:
        assert c.execute("SELECT unread FROM mail_message").fetchone()[0] == 0
    assert mail.imap.flags and mail.imap.flags[0][0] == "4"            # read on Gmail too


def test_long_mail_is_summarised(mail, notion_db):
    add(notion_db, "a", "Mr Huber", "huber@school.example", "Update", body="word " * 300)
    assert mail.read_mail("latest") == "From Mr Huber, about Update. He moved the deadline to Friday. Want all of it?"
    assert mail.read_mail("latest", full=True).startswith("From Mr Huber, about Update: word word")


def test_ambiguous_or_missing_sender(mail, notion_db):
    add(notion_db, "a", "Sara K", "sara@gmail.com", "friday?")
    add(notion_db, "b", "Sara Meier", "sara.meier@school.example", "homework")
    assert mail.read_mail("sara") == "Which Sara: Sara K or Sara Meier?"
    assert mail.read_mail("tom") == "I don't see an email from tom."


def test_search_mail(mail, notion_db):
    add(notion_db, "a", "Sara K", "sara@gmail.com", "friday?", body="cinema at 7?")
    add(notion_db, "b", "Mr Huber", "huber@school.example", "Project", body="deadline")
    assert mail.search_mail("cinema").startswith("Found one: from Sara K about friday?")


def test_fresh_check_when_mynotion_idle(mail, notion_db):
    with sqlite3.connect(notion_db) as c:
        c.execute("UPDATE mail_state SET value = ? WHERE key = 'last_sync'", (iso(10),))
    mail.imap.messages = {5: raw("Mr Huber <huber@school.example>", "Grades", "Your grade is in."),
                          6: raw("News <news@medium.com>", "Digest", "x", [("List-Unsubscribe", "<mailto:u@x>")])}
    assert mail.check_mail() == "One new: from Mr Huber about Grades."
    with sqlite3.connect(notion_db) as c:
        assert c.execute("SELECT filtered FROM mail_message WHERE subject = 'Digest'").fetchone()[0] == 1


def test_offline_says_last_checked(mail, notion_db):
    with sqlite3.connect(notion_db) as c:
        c.execute("UPDATE mail_state SET value = ? WHERE key = 'last_sync'", (iso(10),))
    mail.imap.fail = OSError("Network is unreachable")
    add(notion_db, "a", "Sara K", "sara@gmail.com", "friday?")
    out = mail.check_mail()
    assert out.startswith("One new: from Sara K about friday?.") and "couldn't reach Gmail" in out


def test_not_set_up(notion_db, notion):
    eng = MailEngine(notion_db, Confirmer(), password=lambda a: None, imap=FakeIMAP())
    assert eng.check_mail() == "Email isn't set up yet. Open the Inbox in MyNotion and connect your Gmail there."


class FakeSMTP:
    def __init__(self, fail=None):
        self.sent = []
        self.fail = fail

    def __call__(self, host, port=465, **kw):
        return self

    def login(self, user, pw):
        if self.fail:
            raise self.fail

    def send_message(self, msg):
        self.sent.append(msg)

    def quit(self):
        pass


@pytest.fixture
def writer(mail):
    mail.smtp = FakeSMTP()
    mail._sleep = lambda s: None
    mail.llm = FakeLLM(chats=["Hi Mr Huber,\n\nI'll be there at 3.\n\nLala"])
    return mail


def outbox(db):
    with sqlite3.connect(db) as c:
        return c.execute("SELECT state, to_addrs, subject, created_by FROM mail_outbox").fetchall()


def test_reply_needs_a_yes(writer, notion_db):
    add(notion_db, "a", "Mr Huber", "huber@school.example", "Meeting", message_id="<m1@school>")
    out = writer.draft_reply("huber", "I'll be there at 3")
    assert out.startswith("NEEDS CONFIRMATION: Here's the reply to Mr Huber: Hi Mr Huber,")
    assert writer.smtp.sent == [] and outbox(notion_db) == []
    assert "Say \"undo\"" in writer.confirm.resolve("yes")
    [msg] = writer.smtp.sent
    assert (msg["To"], msg["Subject"], msg["In-Reply-To"], msg["From"]) == (
        "huber@school.example", "Re: Meeting", "<m1@school>", "lala@gmail.com")
    assert "I'll be there at 3." in msg.get_content()
    assert outbox(notion_db) == [("sent", "huber@school.example", "Re: Meeting", "aria")]


def test_no_means_nothing_sent(writer, notion_db):
    add(notion_db, "a", "Mr Huber", "huber@school.example", "Meeting")
    writer.draft_reply("huber", "yes")
    assert writer.confirm.resolve("no") == "Okay, cancelled."
    assert writer.smtp.sent == [] and outbox(notion_db) == []


def test_undo_within_ten_seconds(writer, notion_db):
    add(notion_db, "a", "Mr Huber", "huber@school.example", "Meeting")
    later = []
    writer._bg = later.append                          # the 10 s wait hasn't passed yet
    writer.draft_reply("huber", "ok")
    writer.confirm.resolve("yes")
    assert writer.cancel_send() == "Okay, I won't send it."
    for fn in later:
        fn()
    assert writer.smtp.sent == []
    assert outbox(notion_db)[0][0] == "cancelled"
    assert writer.cancel_send() is None                 # nothing waiting any more: normal undo takes over


def test_new_mail_to_someone_who_wrote_before(writer, notion_db):
    add(notion_db, "a", "Sara K", "sara@gmail.com", "friday?")
    assert "NEEDS CONFIRMATION: Here's the email to Sara K" in writer.draft_mail("sara", "the cinema plan")
    writer.confirm.resolve("yes")
    assert writer.smtp.sent[0]["To"] == "sara@gmail.com"
    assert writer.smtp.sent[0]["Subject"] == "The cinema plan"


def test_unknown_or_ambiguous_recipient_asks(writer, notion_db):
    assert writer.draft_mail("tom", "hi") == "I don't have an address for tom. Say it or type it?"
    add(notion_db, "a", "Sara K", "sara@gmail.com", "x")
    add(notion_db, "b", "Sara Meier", "sara.meier@school.example", "y")
    assert writer.draft_mail("sara", "hi") == "Which Sara: Sara K or Sara Meier?"
    assert writer.draft_mail("tom@example.com", "hi").startswith("NEEDS CONFIRMATION: Here's the email to tom@example.com")


def test_archive_sets_label_and_row(writer, notion_db):
    add(notion_db, "a", "Medium", "x@medium.example", "Stories", uid=9)
    writer.imap.gm_uids = {"a": 9}
    assert writer.archive_mail("medium") == "Archived the email from Medium. It's still in All Mail."
    assert writer.imap.flags[-1] == ("9", "-X-GM-LABELS", "(\\Inbox)")
    with sqlite3.connect(notion_db) as c:
        assert c.execute("SELECT archived FROM mail_message").fetchone()[0] == 1


def test_mark_read(writer, notion_db):
    add(notion_db, "a", "Sara K", "sara@gmail.com", "x", uid=3)
    writer.imap.gm_uids = {"a": 3}
    assert writer.mark_mail_read("sara") == "Marked the email from Sara K as read."
    assert writer.imap.flags[-1] == ("3", "+FLAGS", "(\\Seen)")


def test_send_failure_is_spoken(writer, notion_db):
    said = []
    writer.on_announce = said.append
    writer.smtp = FakeSMTP(fail=Exception("535 bad credentials for pw"))
    add(notion_db, "a", "Mr Huber", "huber@school.example", "Meeting")
    writer.draft_reply("huber", "ok")
    writer.confirm.resolve("yes")
    assert said and said[0].startswith("Couldn't send the email to Mr Huber: 535") and "pw" not in said[0].split(": ", 1)[1].replace("535 bad credentials for ***", "")
    assert outbox(notion_db)[0][0] == "failed"


def test_undo_stops_a_waiting_mail_first(writer, notion_db):
    from Engines.Tool_Engine import ToolEngine
    undo_calls = []
    tools = ToolEngine(mail=writer, undo=type("U", (), {"undo": lambda self: undo_calls.append(1) or "undid"})())
    add(notion_db, "a", "Mr Huber", "huber@school.example", "Meeting")
    writer._bg = lambda fn: None
    writer.draft_reply("huber", "ok")
    writer.confirm.resolve("yes")
    assert tools.execute("undo_last", {}) == "Okay, I won't send it."
    assert tools.execute("undo_last", {}) == "undid" and undo_calls == [1]


def test_mail_todo_uses_due_dates(writer, notion_db, notion):
    add(notion_db, "a", "Mr Huber", "huber@school.example", "Project")
    out = writer.mail_todo("huber")
    assert out.startswith("Added 'Answer Mr Huber about Project' to your To-do list, due")
    assert "Answer Mr Huber about Project" in notion.read_note("to-do")


def test_mail_to_event_confirms_first(writer, notion_db, notion):
    add(notion_db, "a", "Sara K", "sara@gmail.com", "cinema", body="cinema on 2026-11-13 at 19:00?")
    writer.llm = FakeLLM(chats=['{"title": "Cinema with Sara", "date": "2026-11-13", "time": "19:00"}'])
    out = writer.mail_to_event("sara")
    assert out.startswith("NEEDS CONFIRMATION: Add 'Cinema with Sara' on Friday 13 November at 19:00")
    assert writer.confirm.resolve("yes").startswith("Added")
    assert "Cinema with Sara" in notion.get_events("2026-11-13")


def test_mail_to_event_without_a_date(writer, notion_db):
    add(notion_db, "a", "Sara K", "sara@gmail.com", "hi", body="hello!")
    writer.llm = FakeLLM(chats=['{"title": "", "date": "", "time": ""}'])
    assert writer.mail_to_event("sara") == "I couldn't find a date in that email."


def test_briefing_mentions_mail(writer, notion_db):
    assert writer.briefing_line() == ""
    add(notion_db, "a", "Mr Huber", "huber@school.example", "Project")
    add(notion_db, "b", "Sara K", "sara@gmail.com", "friday?")
    assert writer.briefing_line() == "2 new emails: from Sara K and Mr Huber."


def test_important_sender_announced_once(writer, notion_db):
    add(notion_db, "a", "Sara K", "sara@gmail.com", "old one", unread=0)
    assert writer.mark_sender_important("sara") == "Okay, I'll tell you when Sara K emails."
    add(notion_db, "b", "Sara K", "sara@gmail.com", "friday?")
    add(notion_db, "c", "Mr Huber", "huber@school.example", "Project")
    assert writer.important_news() == ["Sara K just emailed: friday?."]
    assert writer.important_news() == []


def test_important_mail_said_only_at_the_desk(aria, writer, notion_db):
    said = []
    aria.mail = writer
    aria._announce = said.append
    add(notion_db, "z", "Sara K", "sara@gmail.com", "old", unread=0)
    writer.mark_sender_important("sara")
    add(notion_db, "b", "Sara K", "sara@gmail.com", "friday?")
    aria._at_desk = lambda: False
    aria._mail_news()
    assert said == []                               # away: kept for later
    aria._at_desk = lambda: True
    aria._mail_news()
    assert said == ["Sara K just emailed: friday?."]



def test_actions_use_the_current_uid_not_a_stale_one(writer, notion_db):
    add(notion_db, "a", "Medium", "x@medium.example", "Stories", uid=9)     # Gmail renumbered: it's 12 now
    writer.imap.gm_uids = {"a": 12}
    writer.archive_mail("medium")
    assert writer.imap.flags[-1][0] == "12"


def test_uidvalidity_change_forgets_old_uids(mail, notion_db):
    add(notion_db, "a", "Sara K", "sara@gmail.com", "old", uid=5)
    with sqlite3.connect(notion_db) as c:
        c.execute("INSERT INTO mail_state (key, value) VALUES ('uidvalidity', '1')")
        c.execute("UPDATE mail_state SET value = ? WHERE key = 'last_sync'", (iso(10),))
    mail.imap.uidvalidity = b"2"
    mail.imap.messages = {5: raw("Mr Huber <huber@school.example>", "New one", "hi")}   # new mail with an old number
    assert "from Mr Huber about New one" in mail.check_mail()


def test_one_odd_email_does_not_stop_the_check(mail, notion_db):
    with sqlite3.connect(notion_db) as c:
        c.execute("UPDATE mail_state SET value = ? WHERE key = 'last_sync'", (iso(10),))
    odd = raw("A <a@x.example>", "Odd", "hello").replace(b'charset="utf-8"', b'charset="x-unknown-8bit"')
    mail.imap.messages = {1: odd, 2: raw("Mr Huber <huber@school.example>", "Grades", "in")}
    out = mail.check_mail()
    assert "Mr Huber about Grades" in out and "couldn't reach" not in out


def test_two_senders_with_the_same_name(mail, notion_db):
    add(notion_db, "a", "Sara K", "sara@gmail.com", "x")
    add(notion_db, "b", "Sara K", "sara.k@school.example", "y")
    assert mail.read_mail("sara") == "Which Sara: Sara K at gmail.com or Sara K at school.example?"
    assert mail.read_mail("school.example").startswith("From Sara K, about y")


def test_undo_after_it_went_says_too_late(writer, notion_db):
    add(notion_db, "a", "Mr Huber", "huber@school.example", "Meeting")
    writer.draft_reply("huber", "ok")
    writer.confirm.resolve("yes")                     # sent right away in tests (no wait)
    assert writer.cancel_send() == "Too late, it already went out."


def test_yes_with_changes_does_not_send(writer, notion_db):
    add(notion_db, "a", "Mr Huber", "huber@school.example", "Meeting")
    writer.draft_reply("huber", "I'll be there at 3")
    assert writer.confirm.resolve("yes but make it 4") is None     # back to the model to rewrite it
    assert writer.smtp.sent == [] and outbox(notion_db) == []


def test_offline_send_waits_and_goes_out_later(writer, notion_db):
    said = []
    writer.on_announce = said.append
    later = []
    writer._bg = later.append
    add(notion_db, "a", "Mr Huber", "huber@school.example", "Meeting")
    writer.draft_reply("huber", "ok")
    writer.confirm.resolve("yes")
    writer.smtp = FakeSMTP(fail=OSError("[Errno -3] Temporary failure in name resolution"))
    later.pop(0)()                                    # first try: offline
    assert outbox(notion_db)[0][0] == "queued"
    assert said == ["No internet right now, so the email to Mr Huber waits. It goes out once I'm back online."]
    writer.smtp = FakeSMTP()
    later.pop(0)()                                    # the retry
    assert outbox(notion_db)[0][0] == "sent" and len(writer.smtp.sent) == 1


def test_send_errors_are_said_plainly(writer, notion_db):
    said = []
    writer.on_announce = said.append
    import smtplib
    writer.smtp = FakeSMTP(fail=smtplib.SMTPAuthenticationError(535, b"5.7.8 Username and Password not accepted"))
    add(notion_db, "a", "Mr Huber", "huber@school.example", "Meeting")
    writer.draft_reply("huber", "ok")
    writer.confirm.resolve("yes")
    assert said == ["Couldn't send the email to Mr Huber: Gmail didn't accept the app password. "
                    "Connect again in MyNotion's Inbox."]


def test_sent_mail_has_date_and_id(writer, notion_db):
    add(notion_db, "a", "Mr Huber", "huber@school.example", "Meeting")
    writer.draft_reply("huber", "ok")
    writer.confirm.resolve("yes")
    msg = writer.smtp.sent[0]
    assert msg["Date"] and msg["Message-ID"]


def test_marking_important_later_does_not_announce_old_mail(writer, notion_db):
    add(notion_db, "a", "Sara K", "sara@gmail.com", "x", unread=0)
    writer.mark_sender_important("sara")
    add(notion_db, "b", "Tom", "tom@x.example", "old unread")
    writer.mark_sender_important("tom")
    assert writer.important_news() == []
    add(notion_db, "c", "Tom", "tom@x.example", "new")
    assert writer.important_news() == ["Tom just emailed: new."]


def test_reply_goes_to_reply_to(writer, notion_db):
    add(notion_db, "a", "Class bot", "noreply@school.example", "Group work")
    with sqlite3.connect(notion_db) as c:
        c.execute("UPDATE mail_message SET reply_to = 'class@school.example'")
    writer.draft_reply("class bot", "count me in")
    writer.confirm.resolve("yes")
    assert writer.smtp.sent[0]["To"] == "class@school.example"


def test_archive_offline_is_remembered_for_mynotion(writer, notion_db):
    add(notion_db, "a", "Medium", "x@medium.example", "Stories", uid=9)
    writer.imap.fail = OSError("Network is unreachable")
    writer.archive_mail("medium")
    with sqlite3.connect(notion_db) as c:
        assert c.execute("SELECT value FROM mail_state WHERE key = 'pending_archive'").fetchone()[0] == '["a"]'


def test_old_database_gets_new_columns(tmp_path):
    db = tmp_path / "old.db"
    from Engines.MailEngine import MAIL_SCHEMA
    with sqlite3.connect(db) as c:                     # the first version's tables, before reply_to existed
        c.executescript(MAIL_SCHEMA.replace("  reply_to TEXT,\n", ""))
    MailEngine(str(db), Confirmer(), password=lambda a: None)
    with sqlite3.connect(db) as c:
        assert "reply_to" in [r[1] for r in c.execute("PRAGMA table_info(mail_message)")]


def test_to_line_matches_mynotion(mail, notion_db):
    with sqlite3.connect(notion_db) as c:
        c.execute("UPDATE mail_state SET value = ? WHERE key = 'last_sync'", (iso(10),))
    m = raw("Sara K <sara@gmail.com>", "hi", "x")
    m = m.replace(b"To: lala@gmail.com", b"To: Lala <lala@gmail.com>, bob@x.example")
    mail.imap.messages = {1: m}
    mail.check_mail()
    with sqlite3.connect(notion_db) as c:
        assert c.execute("SELECT to_addrs FROM mail_message").fetchone()[0] == "Lala <lala@gmail.com>, bob@x.example"
