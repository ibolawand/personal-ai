"""
Email for Aria: reads the Gmail mail MyNotion keeps in noted.db (its Inbox, see MyNotion/note/src/mail), and talks to
Gmail herself to mark mail read, to archive, to send, and to check for new mail when MyNotion hasn't synced lately.
The app password comes from the system keyring entry MyNotion made (MailAccount.py); nothing here stores it.
"""
import imaplib
import re
import smtplib
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import getaddresses, parseaddr, parsedate_to_datetime

from Engines.MailAccount import mail_password
from Engines.MailFilter import filter_reason

# the same tables MyNotion creates (note/src/mail/schema.ts; tests/test_mail_filter.py checks they match)
MAIL_SCHEMA = """
CREATE TABLE IF NOT EXISTS mail_message (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  gm_msgid TEXT NOT NULL UNIQUE,
  gm_thrid TEXT,
  uid INTEGER,
  message_id TEXT,
  from_name TEXT,
  from_addr TEXT,
  to_addrs TEXT,
  cc TEXT,
  subject TEXT,
  date TEXT,
  preview TEXT,
  body_text TEXT,
  body_html TEXT,
  has_attachments INTEGER NOT NULL DEFAULT 0,
  unread INTEGER NOT NULL DEFAULT 1,
  archived INTEGER NOT NULL DEFAULT 0,
  filtered INTEGER NOT NULL DEFAULT 0,
  filter_reason TEXT
);
CREATE INDEX IF NOT EXISTS mail_message_date ON mail_message(date);
CREATE TABLE IF NOT EXISTS mail_attachment (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  message_id INTEGER NOT NULL REFERENCES mail_message(id) ON DELETE CASCADE,
  filename TEXT,
  mime TEXT,
  size INTEGER,
  part_id TEXT,
  cached_path TEXT
);
CREATE TABLE IF NOT EXISTS mail_outbox (
  client_id TEXT PRIMARY KEY,
  to_addrs TEXT NOT NULL,
  cc TEXT,
  subject TEXT,
  body TEXT,
  in_reply_to INTEGER,
  attachments TEXT,
  state TEXT NOT NULL DEFAULT 'queued',
  error TEXT,
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  send_after TEXT NOT NULL,
  sent_at TEXT
);
CREATE TABLE IF NOT EXISTS mail_sender_rule (
  addr TEXT NOT NULL,
  rule TEXT NOT NULL,
  PRIMARY KEY (addr, rule)
);
CREATE TABLE IF NOT EXISTS mail_state (
  key TEXT PRIMARY KEY,
  value TEXT
);
"""

IMAP_HOST = "imap.gmail.com"
SMTP_HOST = "smtp.gmail.com"
UNDO_SEND_S = 10                       # Aria's mail waits this long in the outbox, so "undo" can still stop it
PRIMARY_QUERY = "category:primary newer_than:90d"
FRESH_FOR = timedelta(minutes=5)       # MyNotion syncs every 2 min; older than this and she checks Gmail herself
LONG_WORDS = 120                       # longer mails get a summary first
NUMBERS = ["No", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten"]
LATEST_RE = re.compile(r"^(?:the\s+)?(?:latest|last|newest|new|recent|most recent|it|that|this|that one|the last one)?$", re.I)
FILLER_RE = re.compile(r"\b(?:the|one|email|e-mail|mail|message|from|by|that|which|about)\b", re.I)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _content(part) -> str:
    """A text part's content, even with a charset Python doesn't know."""
    try:
        return part.get_content()
    except Exception:
        return (part.get_payload(decode=True) or b"").decode("utf-8", "replace")


def _labels(people: dict) -> list[str]:
    """{address: name} -> names to say, with the address's domain when two people share a name."""
    names = list(people.values())
    return sorted(f"{n} at {a.split('@')[-1]}" if names.count(n) > 1 else n for a, n in people.items())


def _or_list(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " or " + items[-1]


def _html_to_text(html: str) -> str:
    html = re.sub(r"<(style|script)[\s\S]*?</\1>", " ", html, flags=re.I)
    html = re.sub(r"<br\s*/?>|</p>|</div>", "\n", html, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", html)
    for a, b in (("&nbsp;", " "), ("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&#39;", "'"), ("&amp;", "&")):
        text = text.replace(a, b)
    return text


class MailEngine:
    def __init__(self, db_path: str, confirm, notion=None, llm=None, password=mail_password, imap=imaplib.IMAP4_SSL,
                 smtp=smtplib.SMTP_SSL, system_prompt="", sender_name="Lala"):
        self.db_path = db_path
        self.confirm = confirm
        self.notion = notion
        self.llm = llm
        self.password = password
        self.imap = imap
        self.smtp = smtp
        self.system_prompt = system_prompt
        self.sender_name = sender_name
        self.current = None              # the mail last read / talked about ("reply to that", "archive it")
        self.on_announce = None          # set by Aria: says something later (a send that failed)
        self._waiting = None             # client_id of the mail in its undo window
        self._bg = lambda fn: threading.Thread(target=fn, daemon=True).start()
        self._sleep = time.sleep
        with self._conn() as c:
            c.executescript(MAIL_SCHEMA)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path, timeout=5)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _state(self, key):
        with self._conn() as c:
            row = c.execute("SELECT value FROM mail_state WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def _set_state(self, key, value):
        with self._conn() as c:
            c.execute("INSERT INTO mail_state (key, value) VALUES (?, ?) "
                      "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))

    def _account(self):
        address = self._state("address")
        pw = self.password(address) if address else None
        return (address, pw) if address and pw else None

    # ── Gmail ─────────────────────────────────────────────────────────────────

    def _gmail(self, fn):
        """Runs fn(imap) logged in with INBOX selected. Raises on connection/login problems."""
        address, pw = self._account()
        m = self.imap(IMAP_HOST, 993)
        try:
            m.login(address, pw)
            m.select("INBOX")
            return fn(m)
        finally:
            try:
                m.logout()
            except Exception:
                pass

    def _fresh(self) -> str:
        """If MyNotion hasn't synced lately, fetch new Primary mail from Gmail. Returns a note for the answer
        when Gmail couldn't be reached ('' otherwise)."""
        last = max(filter(None, [_parse_iso(self._state("last_sync")), _parse_iso(self._state("aria_last_check"))]),
                   default=None)
        if last and datetime.now(timezone.utc) - last < FRESH_FOR:
            return ""
        try:
            self._gmail(self._fetch_new)
            self._set_state("aria_last_check", _iso(datetime.now(timezone.utc)))
            return ""
        except Exception as e:
            print(f"[Mail] couldn't reach Gmail: {e}")
            when = last.astimezone().strftime("%H:%M") if last else "never"
            return f" (I couldn't reach Gmail, so that's as of {when}.)" if last else " (I couldn't reach Gmail.)"

    def _fetch_new(self, m):
        validity = (m.response("UIDVALIDITY")[1] or [None])[0]
        validity = validity.decode() if isinstance(validity, bytes) else (str(validity) if validity else None)
        if validity and validity != self._state("uidvalidity"):
            if self._state("uidvalidity"):
                with self._conn() as c:          # Gmail renumbered the inbox: old uids mean nothing now
                    c.execute("UPDATE mail_message SET uid = NULL")
            self._set_state("uidvalidity", validity)
        typ, data = m.uid("SEARCH", "X-GM-RAW", f'"{PRIMARY_QUERY}"')
        uids = [int(u) for u in (data[0] or b"").split()]
        with self._conn() as c:
            known = {r["uid"] for r in c.execute("SELECT uid FROM mail_message WHERE uid IS NOT NULL")}
            keep = {r["addr"] for r in c.execute("SELECT addr FROM mail_sender_rule WHERE rule = 'always_show'")}
        new = [u for u in uids if u not in known]
        for i in range(0, len(new), 25):
            typ, parts = m.uid("FETCH", ",".join(map(str, new[i:i + 25])), "(UID X-GM-MSGID X-GM-THRID FLAGS BODY.PEEK[])")
            for part in parts:
                if isinstance(part, tuple):
                    try:
                        self._store(part[0].decode(errors="replace"), part[1], keep)
                    except Exception as e:         # one mail that can't be read doesn't stop the others
                        print(f"[Mail] couldn't read a message: {e}")

    def _store(self, head: str, raw: bytes, keep: set):
        num = lambda key: (re.search(key + r" (\d+)", head) or [None, None])[1]
        flags = (re.search(r"FLAGS \(([^)]*)\)", head) or [None, ""])[1]
        msg = BytesParser(policy=policy.default).parsebytes(raw)
        name, addr = parseaddr(str(msg.get("From", "")))
        headers = {k.lower(): str(v) for k, v in msg.items()}
        plain = msg.get_body(("plain",))
        html_part = msg.get_body(("html",))
        html = _content(html_part) if html_part else ""
        text = (_content(plain) if plain else "").strip() or _html_to_text(html).strip()
        try:
            date = _iso(parsedate_to_datetime(str(msg.get("Date"))))
        except Exception:
            date = _iso(datetime.now(timezone.utc))
        reason = filter_reason(headers, addr, keep)
        atts = [p for p in msg.iter_attachments()]
        with self._conn() as c:
            c.execute(
                "INSERT INTO mail_message (gm_msgid, gm_thrid, uid, message_id, from_name, from_addr, to_addrs, cc,"
                " subject, date, preview, body_text, body_html, has_attachments, unread, archived, filtered, filter_reason)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?,?) ON CONFLICT(gm_msgid) DO UPDATE SET uid = excluded.uid",
                (num("X-GM-MSGID") or f"uid:{num('UID')}", num("X-GM-THRID"), int(num("UID") or 0),
                 str(msg.get("Message-ID", "")) or None, name or addr, addr.lower(),
                 ", ".join(a for _, a in getaddresses([str(msg.get("To", ""))])),
                 ", ".join(a for _, a in getaddresses([str(msg.get("Cc", ""))])),
                 str(msg.get("Subject", "")).strip() or "(no subject)", date, " ".join(text.split())[:200],
                 text, html, 1 if atts else 0, 0 if "\\Seen" in flags else 1, 1 if reason else 0, reason))

    @staticmethod
    def _uid_for(m, gm_msgid) -> str | None:
        """The current uid of a mail, by its Gmail id (a stored uid is stale after Gmail renumbers the inbox)."""
        if not gm_msgid or str(gm_msgid).startswith("uid:"):     # no Gmail id known (fallback key)
            return None
        typ, data = m.uid("SEARCH", "X-GM-MSGID", str(gm_msgid))
        uids = (data[0] or b"").split() if data else []
        return uids[0].decode() if uids else None

    def _on_gmail(self, row, *store_args):
        """UID STORE on the mail's current uid, in the background."""
        if not self._account():
            return
        gm = row["gm_msgid"]

        def run():
            try:
                def act(m):
                    uid = self._uid_for(m, gm)
                    if uid:
                        m.uid("STORE", uid, *store_args)
                self._gmail(act)
            except Exception as e:
                print(f"[Mail] couldn't update Gmail: {e}")
        self._bg(run)

    def _flag(self, row, seen: bool):
        """Read/unread on Gmail too (in the background: it's a network round trip)."""
        self._on_gmail(row, "+FLAGS" if seen else "-FLAGS", "(\\Seen)")

    # ── finding mail ──────────────────────────────────────────────────────────

    def _rows(self, where="", args=(), limit=200):
        with self._conn() as c:
            return [dict(r) for r in c.execute(
                f"SELECT * FROM mail_message WHERE archived = 0 AND filtered = 0 {where} ORDER BY date DESC LIMIT ?",
                (*args, limit))]

    def _find(self, which: str):
        """(rows, question): the mail meant by "the one from Sara" / "the latest" / "that", newest first. When it
        could be two different people, rows is empty and question asks which."""
        which = (which or "").strip()
        if self.current and re.fullmatch(r"(?:it|that|this|that one|this one|the one|that email|this email)?", which, re.I):
            with self._conn() as c:
                row = c.execute("SELECT * FROM mail_message WHERE id = ?", (self.current,)).fetchone()
            if row:
                return [dict(row)], None
        if LATEST_RE.match(which):
            return self._rows(limit=1), None
        words = " ".join(FILLER_RE.sub(" ", which).split()).lower()
        if not words:
            return self._rows(limit=1), None
        rows = self._rows()
        by_sender = [r for r in rows if words in (r["from_name"] or "").lower() or words in (r["from_addr"] or "").lower()]
        if by_sender:
            people = {}
            for r in by_sender:
                people.setdefault(r["from_addr"], r["from_name"] or r["from_addr"])
            if len(people) > 1:
                return [], f"Which {words.title()}: " + _or_list(_labels(people)) + "?"
            return by_sender, None
        by_subject = [r for r in rows if words in (r["subject"] or "").lower()]
        return by_subject, None

    # ── tools ─────────────────────────────────────────────────────────────────

    def check_mail(self) -> str:
        """"Any new emails?": who wrote, about what."""
        if not self._account() and not self._state("last_sync"):
            return "Email isn't set up yet. Open the Inbox in MyNotion and connect your Gmail there."
        note = self._fresh() if self._account() else ""
        new = self._rows("AND unread = 1")
        if not new:
            return "Nothing new." + note
        count = NUMBERS[len(new)] if len(new) < len(NUMBERS) else str(len(new))
        if len(new) == 1:
            r = new[0]
            return f"One new: from {r['from_name']} about {r['subject']}." + note
        if len(new) <= 4:
            return f"{count} new: " + ", ".join(f"one from {r['from_name']} about {r['subject']}" for r in new) + "." + note
        names = list(dict.fromkeys(r["from_name"] for r in new))
        return f"{count} new, from {', '.join(names[:3])} and {len(names) - 3} more." + note if len(names) > 3 \
            else f"{count} new, from {' and '.join(names)}." + note

    def read_mail(self, which: str = "latest", full: bool = False) -> str:
        """Reads one email aloud (a summary first when it's long)."""
        rows, question = self._find(which)
        if question:
            return question
        if not rows:
            who = " ".join(FILLER_RE.sub(" ", which or "").split())
            return f"I don't see an email from {who}." if who else "There's no email in your inbox."
        r = rows[0]
        self.current = r["id"]
        if r["unread"]:
            with self._conn() as c:
                c.execute("UPDATE mail_message SET unread = 0 WHERE id = ?", (r["id"],))
            self._flag(r, seen=True)
        body = " ".join((r["body_text"] or _html_to_text(r["body_html"] or "")).split())
        head = f"From {r['from_name']}, about {r['subject']}"
        if len(body.split()) > LONG_WORDS and not full and self.llm:
            summary = self.llm.chat(
                "Summarise this email in one or two spoken sentences for the person it was sent to. Just the "
                f"content, no intro.\n\nFrom: {r['from_name']}\nSubject: {r['subject']}\n\n{body[:4000]}",
                [], self.system_prompt).strip()
            return f"{head}. {summary} Want all of it?"
        return f"{head}: {body}"

    def search_mail(self, query: str) -> str:
        q = (query or "").strip().lower()
        hits = [r for r in self._rows(limit=500)
                if q in " ".join([r["subject"] or "", r["body_text"] or "", r["from_name"] or "", r["from_addr"] or ""]).lower()]
        if not hits:
            return f"No email mentions {query}."
        said = [f"from {r['from_name']} about {r['subject']} ({datetime.fromisoformat(r['date'].replace('Z', '+00:00')).astimezone().strftime('%-d %b')})"
                for r in hits[:3]]
        self.current = hits[0]["id"]
        count = NUMBERS[len(hits)].lower() if len(hits) < len(NUMBERS) else str(len(hits))
        return f"Found {count}: " + "; ".join(said) + ("." if len(hits) <= 3 else f"; and {len(hits) - 3} more.")

    # ── writing ───────────────────────────────────────────────────────────────

    def _write(self, to_name: str, gist: str, original: dict | None = None) -> str:
        context = (f"\n\nThe email you're answering, from {original['from_name']}, subject {original['subject']}:\n"
                   f"{(original['body_text'] or '')[:2000]}") if original else ""
        return self.llm.chat(
            f"Write a short plain-text email from {self.sender_name} to {to_name}. What {self.sender_name} wants to "
            f"say: {gist}. Friendly and natural, in {self.sender_name}'s voice, no subject line, no placeholders, "
            f"sign it '{self.sender_name}'. Only the email text.{context}", [], self.system_prompt).strip()

    def _recipient(self, to: str):
        """(address, display name, question): from a full address, or someone who emailed before."""
        to = (to or "").strip()
        if re.fullmatch(r"[^@\s]+@[^@\s]+\.\w+", to):
            return to, to, None
        words = " ".join(FILLER_RE.sub(" ", to).split()).lower()
        with self._conn() as c:
            rows = c.execute("SELECT from_name, from_addr FROM mail_message WHERE lower(from_name) LIKE ? "
                             "OR lower(from_addr) LIKE ? ORDER BY date DESC", (f"%{words}%", f"%{words}%")).fetchall()
        people = {}
        for r in rows:
            people.setdefault(r["from_addr"], r["from_name"] or r["from_addr"])
        if not people:
            return None, None, f"I don't have an address for {to}. Say it or type it?"
        if len(people) > 1:
            return None, None, f"Which {words.title()}: " + _or_list(_labels(people)) + "?"
        addr, name = next(iter(people.items()))
        return addr, name, None

    def draft_reply(self, which: str, gist: str) -> str:
        """Writes a reply in Lala's voice; nothing is sent until they say yes."""
        rows, question = self._find(which)
        if question:
            return question
        if not rows:
            return "I don't know which email to answer."
        r = rows[0]
        self.current = r["id"]
        body = self._write(r["from_name"], gist, r)
        subject = r["subject"] if re.match(r"\s*re:", r["subject"] or "", re.I) else f"Re: {r['subject']}"
        return self.confirm.request(f"Here's the reply to {r['from_name']}: {body} Send it?",
                                    lambda: self._queue(r["from_addr"], r["from_name"], subject, body, r["id"]),
                                    strict=True)

    def draft_mail(self, to: str, gist: str, subject: str = "") -> str:
        """A new email to someone who emailed before (or a full address); asks before sending."""
        addr, name, question = self._recipient(to)
        if question:
            return question
        body = self._write(name, gist)
        subject = subject.strip() or (gist.strip()[:1].upper() + gist.strip()[1:60])
        return self.confirm.request(f"Here's the email to {name}: {body} Send it?",
                                    lambda: self._queue(addr, name, subject, body, None), strict=True)

    def _queue(self, to_addr, to_name, subject, body, reply_to_id):
        client_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        with self._conn() as c:
            c.execute("INSERT INTO mail_outbox (client_id, to_addrs, cc, subject, body, in_reply_to, attachments, state,"
                      " created_by, created_at, send_after) VALUES (?,?,?,?,?,?,'[]','queued','aria',?,?)",
                      (client_id, to_addr, "", subject, body, reply_to_id, _iso(now),
                       _iso(now + timedelta(seconds=UNDO_SEND_S))))
        self._waiting = client_id
        self._last_queued = (client_id, time.time())

        def later():
            self._sleep(UNDO_SEND_S)
            self._flush(client_id, to_name)
        self._bg(later)
        return f'Sending it to {to_name} in {UNDO_SEND_S} seconds. Say "undo" to stop it.'

    def cancel_send(self) -> str | None:
        """"Undo" / "don't send it" during the wait. None when nothing is waiting (normal undo applies)."""
        cid, self._waiting = self._waiting, None
        last_id, at = getattr(self, "_last_queued", (None, 0))
        cid = cid or (last_id if time.time() - at < 60 else None)
        if not cid:
            return None
        with self._conn() as c:
            n = c.execute("UPDATE mail_outbox SET state = 'cancelled' WHERE client_id = ? AND state = 'queued'",
                          (cid,)).rowcount
            state = c.execute("SELECT state FROM mail_outbox WHERE client_id = ?", (cid,)).fetchone()
        self._last_queued = (None, 0)
        if n:
            return "Okay, I won't send it."
        return "Too late, it already went out." if state and state["state"] in ("sending", "sent") else None

    def _flush(self, client_id: str, to_name: str):
        """Sends one queued mail, if it's still queued (MyNotion may have sent it, or it was cancelled)."""
        with self._conn() as c:
            claimed = c.execute("UPDATE mail_outbox SET state = 'sending' WHERE client_id = ? AND state = 'queued'",
                                (client_id,)).rowcount
            row = c.execute("SELECT * FROM mail_outbox WHERE client_id = ?", (client_id,)).fetchone()
            orig = c.execute("SELECT message_id FROM mail_message WHERE id = ?",
                             (row["in_reply_to"],)).fetchone() if row and row["in_reply_to"] else None
        if self._waiting == client_id:
            self._waiting = None
        if not claimed:
            return
        account = self._account()
        try:
            if not account:
                raise RuntimeError("email isn't set up")
            address, pw = account
            msg = EmailMessage()
            msg["From"], msg["To"], msg["Subject"] = address, row["to_addrs"], row["subject"]
            if orig and orig["message_id"]:
                msg["In-Reply-To"] = msg["References"] = orig["message_id"]
            msg.set_content(row["body"])
            server = self.smtp(SMTP_HOST, 465)
            try:
                server.login(address, pw)
                server.send_message(msg)
            finally:
                try:
                    server.quit()
                except Exception:
                    pass
            with self._conn() as c:
                c.execute("UPDATE mail_outbox SET state = 'sent', sent_at = ? WHERE client_id = ?",
                          (_iso(datetime.now(timezone.utc)), client_id))
        except Exception as e:
            error = str(e)
            if account:
                error = error.replace(account[1], "***")
            with self._conn() as c:
                c.execute("UPDATE mail_outbox SET state = 'failed', error = ? WHERE client_id = ?", (error, client_id))
            if self.on_announce:
                self.on_announce(f"Couldn't send the email to {to_name}: {error[:120]}")

    # ── archive / read ────────────────────────────────────────────────────────

    def archive_mail(self, which: str = "that") -> str:
        """Takes it out of the inbox (Gmail keeps it in All Mail). Never deletes."""
        rows, question = self._find(which)
        if question or not rows:
            return question or "I don't know which email you mean."
        r = rows[0]
        with self._conn() as c:
            c.execute("UPDATE mail_message SET archived = 1 WHERE id = ?", (r["id"],))
        self._on_gmail(r, "-X-GM-LABELS", "(\\Inbox)")
        return f"Archived the email from {r['from_name']}. It's still in All Mail."

    def mark_mail_read(self, which: str = "that", read: bool = True) -> str:
        rows, question = self._find(which)
        if question or not rows:
            return question or "I don't know which email you mean."
        r = rows[0]
        with self._conn() as c:
            c.execute("UPDATE mail_message SET unread = ? WHERE id = ?", (0 if read else 1, r["id"]))
        self._flag(r, seen=read)
        return f"Marked the email from {r['from_name']} as {'read' if read else 'unread'}."

    # ── mail into the rest of MyNotion ────────────────────────────────────────

    def mail_todo(self, which: str = "that", due: str = "tomorrow") -> str:
        """"Remind me to answer that tomorrow": a to-do with a due date, in MyNotion."""
        rows, question = self._find(which)
        if question or not rows:
            return question or "I don't know which email you mean."
        r = rows[0]
        self.current = r["id"]
        return self.notion.add_todo(f"Answer {r['from_name']} about {r['subject']}", due=due or "tomorrow")

    def mail_to_event(self, which: str = "that") -> str:
        """Date and time from the email into the calendar, after a yes."""
        import json
        rows, question = self._find(which)
        if question or not rows:
            return question or "I don't know which email you mean."
        r = rows[0]
        self.current = r["id"]
        today = datetime.now().strftime("%A %Y-%m-%d")
        raw = self.llm.chat(
            f"Today is {today}. From this email, get the event it's about as JSON: "
            '{"title": short title, "date": "YYYY-MM-DD" or "", "time": "HH:MM" 24h or ""}. Only the JSON.\n\n'
            f"From: {r['from_name']}\nSubject: {r['subject']}\n\n{(r['body_text'] or '')[:3000]}", [], "")
        try:
            ev = json.loads(re.search(r"\{.*\}", raw, re.S).group(0))
            day = datetime.strptime(ev.get("date") or "", "%Y-%m-%d")
        except Exception:
            return "I couldn't find a date in that email."
        title = (ev.get("title") or r["subject"]).strip()
        time_ = (ev.get("time") or "").strip()
        when = f"{day.strftime('%A')} {day.day} {day.strftime('%B')}" + (f" at {time_}" if time_ else "")
        return self.confirm.request(f"Add '{title}' on {when} to your calendar?",
                                    lambda: self.notion.add_event(title, day.strftime("%Y-%m-%d"), time_))

    def briefing_line(self) -> str:
        """For the morning briefing: "2 new emails: from Sara K and Mr Huber." ('' when there's none)."""
        new = self._rows("AND unread = 1")
        if not new:
            return ""
        names = list(dict.fromkeys(r["from_name"] for r in new))
        if len(names) > 3:
            names = names[:3] + [f"{len(names) - 3} more"]
        who = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
        return f"{len(new)} new email{'s' if len(new) > 1 else ''}: from {who}."

    def mark_sender_important(self, who: str) -> str:
        """"Always tell me when Sara emails"."""
        addr, name, question = self._recipient(who)
        if question:
            return question.replace("Say it or type it?", "They need to have emailed you once first.")
        with self._conn() as c:
            c.execute("INSERT OR IGNORE INTO mail_sender_rule (addr, rule) VALUES (?, 'important')", (addr.lower(),))
            last = c.execute("SELECT COALESCE(MAX(id), 0) FROM mail_message").fetchone()[0]
        if not self._state("important_seen_id"):
            self._set_state("important_seen_id", str(last))
        return f"Okay, I'll tell you when {name} emails."

    def important_news(self) -> list[str]:
        """New unread mail from senders marked important, each said once."""
        seen = int(self._state("important_seen_id") or 0)
        with self._conn() as c:
            rows = c.execute(
                "SELECT m.id, m.from_name, m.subject FROM mail_message m JOIN mail_sender_rule r "
                "ON r.addr = m.from_addr AND r.rule = 'important' WHERE m.id > ? AND m.unread = 1 AND m.archived = 0 "
                "ORDER BY m.id", (seen,)).fetchall()
        if rows:
            self._set_state("important_seen_id", str(rows[-1]["id"]))
        return [f"{r['from_name']} just emailed: {r['subject']}." for r in rows]
