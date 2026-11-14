"""
School from WebUntis (HTL Leonding: htl-leonding.webuntis.com, school "htl-leonding"): the timetable with
cancellations, room changes and substitutions, homework, and tests. Read-only.

The login (your normal WebUntis username and password) lives only in the system keyring, service "Aria WebUntis";
set it up once with ./aria.sh --untis. Another school: UNTIS_SERVER and UNTIS_SCHOOL in Engines/.env.

WebUntis API: JSON-RPC (/WebUntis/jsonrpc.do) for the login and the timetable, and the web app's REST endpoints
(/WebUntis/api/homeworks/lessons, /WebUntis/api/exams) with the same session for homework and tests.
"""
import base64
import datetime as dt
import os
import time

try:
    import secretstorage
except ImportError:                     # pragma: no cover
    secretstorage = None

from Engines.NotionEngine import fmt_day, parse_day

KEYRING_SERVICE = "Aria WebUntis"
SERVER = os.environ.get("UNTIS_SERVER", "htl-leonding.webuntis.com")
SCHOOL = os.environ.get("UNTIS_SCHOOL", "htl-leonding")
CACHE_S = 15 * 60          # the timetable changes during the day, but not by the minute
AHEAD_DAYS = 21            # homework and tests this far ahead
BRIEF_TEST_DAYS = 7        # the morning briefing mentions tests this close
MERGE_GAP = 10             # minutes: the same subject again after a short break counts as one double lesson
NOT_SET_UP = "WebUntis isn't set up yet. Run ./aria.sh --untis once to connect it."
BAD_LOGIN = "WebUntis didn't accept the login. Set it up again with: ./aria.sh --untis"
OFFLINE = "I couldn't reach WebUntis right now."


class LoginError(Exception):
    pass


def load_login():
    """(username, password) from the keyring, or None."""
    if secretstorage is None:
        return None
    try:
        col = secretstorage.get_default_collection(secretstorage.dbus_init())
        if col.is_locked():
            col.unlock()
        for item in col.search_items({"service": KEYRING_SERVICE}):
            secret = item.get_secret()
            return item.get_attributes().get("username"), secret.decode() if isinstance(secret, bytes) else secret
    except Exception as e:
        print(f"[Untis] keyring not available: {e}")
    return None


def save_login(username, password):
    col = secretstorage.get_default_collection(secretstorage.dbus_init())
    if col.is_locked():
        col.unlock()
    for item in col.search_items({"service": KEYRING_SERVICE}):
        item.delete()
    col.create_item("WebUntis login for Aria", {"service": KEYRING_SERVICE, "username": username}, password.encode())


def _date(n: int) -> dt.date:
    return dt.date(n // 10000, n // 100 % 100, n % 100)


def _num(d: dt.date) -> int:
    return int(d.strftime("%Y%m%d"))


def _clock(n: int) -> str:
    return f"{n // 100}:{n % 100:02d}"


def _minutes(n: int) -> int:
    return n // 100 * 60 + n % 100


def _names(items, key="name"):
    return ", ".join(i.get(key) or i.get("name") or "" for i in items or [] if i.get(key) or i.get("name"))


class Untis:
    def __init__(self, session=None, today=dt.date.today, server=SERVER, school=SCHOOL):
        if session is None:
            import requests
            session = requests.Session()
        self.http, self.today, self.server, self.school = session, today, server, school
        self._sid = None
        self._me = None                 # {"id", "type"} of the logged-in student
        self._cache = {}

    # ── talking to WebUntis ──

    def _cookies(self):
        return {"JSESSIONID": self._sid, "schoolname": '"_' + base64.b64encode(self.school.encode()).decode() + '"'}

    def _rpc(self, method, params, retry=True):
        if self._sid is None and method != "authenticate":
            self._login()
        r = self.http.post(f"https://{self.server}/WebUntis/jsonrpc.do", params={"school": self.school},
                           json={"id": "aria", "method": method, "params": params, "jsonrpc": "2.0"},
                           cookies=self._cookies() if self._sid else None, timeout=15)
        data = r.json()
        err = data.get("error")
        if err:
            if err.get("code") == -8520 and retry:          # the session ran out: log in again once
                self._sid = None
                return self._rpc(method, params, retry=False)
            if method == "authenticate":
                raise LoginError(err.get("message"))
            raise RuntimeError(f"WebUntis {method}: {err.get('message')}")
        return data.get("result")

    def _login(self):
        login = load_login()
        if not login:
            raise LoginError(NOT_SET_UP)
        user, password = login
        res = self._rpc("authenticate", {"user": user, "password": password, "client": "Aria"})
        self._sid = res["sessionId"]
        self._me = {"id": res["personId"], "type": res["personType"]}

    def _rest(self, path, params):
        if self._sid is None:
            self._login()
        r = self.http.get(f"https://{self.server}/WebUntis/api/{path}", params=params, cookies=self._cookies(),
                          timeout=15)
        r.raise_for_status()
        return (r.json() or {}).get("data") or {}

    def _cached(self, key, fetch):
        hit = self._cache.get(key)
        if hit and time.time() - hit[0] < CACHE_S:
            return hit[1]
        value = fetch()
        self._cache[key] = (time.time(), value)
        return value

    def _lessons(self, day: dt.date) -> list:
        def fetch():
            if self._me is None:
                self._login()
            raw = self._rpc("getTimetable", {"options": {
                "element": self._me, "startDate": _num(day), "endDate": _num(day),
                "showSubstText": True, "showInfo": True,
                "subjectFields": ["name", "longname"], "roomFields": ["name"], "klasseFields": ["name"]}}) or []
            return sorted(raw, key=lambda l: l["startTime"])
        return self._cached(("day", day), fetch)

    def _homework(self) -> list:
        today = self.today()

        def fetch():
            data = self._rest("homeworks/lessons", {"startDate": _num(today - dt.timedelta(days=14)),
                                                   "endDate": _num(today + dt.timedelta(days=AHEAD_DAYS))})
            subjects = {l["id"]: l.get("subject", "") for l in data.get("lessons", [])}
            return [dict(h, subject=subjects.get(h.get("lessonId"), "")) for h in data.get("homeworks", [])]
        return self._cached(("homework", today), fetch)

    def _exams(self) -> list:
        today = self.today()

        def fetch():
            if self._me is None:
                self._login()
            data = self._rest("exams", {"startDate": _num(today), "endDate": _num(today + dt.timedelta(days=AHEAD_DAYS)),
                                        "studentId": self._me["id"], "klasseId": -1})
            return sorted(data.get("exams", []), key=lambda e: (e["examDate"], e.get("startTime", 0)))
        return self._cached(("exams", today), fetch)

    def _safely(self, fn):
        """fn()'s answer, or what to say when WebUntis can't be used. Never the error text itself (it may hold
        the login)."""
        try:
            return fn()
        except LoginError as e:
            return NOT_SET_UP if str(e) == NOT_SET_UP else BAD_LOGIN
        except Exception as e:
            print(f"[Untis] {type(e).__name__}")
            return OFFLINE

    # ── a day ──

    def _blocks(self, lessons):
        """[(start, end, subject, room, lesson), …]: double lessons merged, cancelled ones left out."""
        blocks = []
        for l in lessons:
            if l.get("code") == "cancelled":
                continue
            su, ro = _names(l.get("su")), _names(l.get("ro"))
            last = blocks[-1] if blocks else None
            if last and last[2] == su and last[3] == ro and \
                    _minutes(l["startTime"]) - _minutes(last[1]) <= MERGE_GAP:
                blocks[-1] = (last[0], l["endTime"], su, ro, last[4])
            else:
                blocks.append((l["startTime"], l["endTime"], su, ro, l))
        return blocks

    @staticmethod
    def _changes(lessons):
        out = []
        for l in lessons:
            su, at = _names(l.get("su")), _clock(l["startTime"])
            if l.get("code") == "cancelled":
                out.append(f"{su} at {at} is cancelled")
                continue
            moved = [r for r in l.get("ro") or [] if r.get("orgid")]
            if moved:
                out.append(f"{su} at {at} is in {_names(moved)} instead of {_names(moved, 'orgname')}")
            elif l.get("code") == "irregular" or l.get("substText"):
                out.append(f"{su} at {at}: {l.get('substText') or 'changed'}")
        return out

    def school_day(self, when="today") -> str:
        day = parse_day(when or "today", self.today())
        if not day:
            return f"I couldn't understand the day '{when}'."

        def answer():
            lessons = self._lessons(day)
            blocks = self._blocks(lessons)
            label = fmt_day(day, self.today())
            if not lessons:
                return f"No school {label}." if label in ("today", "tomorrow") else f"No school on {label}."
            changes = self._changes(lessons)
            if not blocks:
                return f"All lessons {label} are cancelled: " + "; ".join(changes) + "."
            text = f"School {label}: {_clock(blocks[0][0])} to {_clock(blocks[-1][1])}."
            if changes:
                text += " Changes: " + "; ".join(changes) + "."
            text += " " + "; ".join(f"{su} {_clock(a)} to {_clock(b)}" + (f" in {ro}" if ro else "")
                                    for a, b, su, ro, _ in blocks) + "."
            return text
        return self._safely(answer)

    def day_line(self, when) -> str:
        """For calendar answers about one day ("what do I have tomorrow?"): the school hours and changes, or ""."""
        w = (when or "").strip().lower()
        if not w or "week" in w or "month" in w or "weekend" in w:
            return ""
        day = parse_day(w, self.today())
        if not day or not load_login():
            return ""
        try:
            lessons = self._lessons(day)
        except Exception as e:
            print(f"[Untis] {type(e).__name__}")
            return ""
        blocks = self._blocks(lessons)
        if not blocks:
            return ""
        changes = self._changes(lessons)
        return (f"School {fmt_day(day, self.today())}: {_clock(blocks[0][0])} to {_clock(blocks[-1][1])}"
                + (" (" + "; ".join(changes) + ")" if changes else "") + ".")

    # ── homework and tests ──

    def _open_homework(self):
        today = self.today()
        hw = [h for h in self._homework() if not h.get("completed") and _date(h["dueDate"]) >= today]
        return sorted(hw, key=lambda h: h["dueDate"])

    def school_homework(self) -> str:
        def answer():
            hw = self._open_homework()
            if not hw:
                return "No open homework in WebUntis."
            return "Homework: " + "; ".join(
                f"{h['subject']} for {fmt_day(_date(h['dueDate']), self.today())}: {h.get('text', '').strip()}"
                for h in hw[:8]) + "."
        return self._safely(answer)

    def _exam_text(self, e, with_time=True):
        kind = e.get("examType") or e.get("name") or "Test"
        text = f"{kind} in {e.get('subject', '')} on {fmt_day(_date(e['examDate']), self.today())}"
        if with_time and e.get("startTime"):
            text += f" at {_clock(e['startTime'])}"
        if with_time and (e.get("text") or "").strip():
            text += f" ({e['text'].strip()})"
        return text

    def school_exams(self) -> str:
        def answer():
            exams = self._exams()
            if not exams:
                return "No tests in the next 3 weeks."
            return "Tests: " + "; ".join(self._exam_text(e) for e in exams[:6]) + "."
        return self._safely(answer)

    def upcoming_tests(self, days: int = 7) -> list:
        """Tests in the next `days` days as plain records, nearest first. [] without a saved login; errors from
        WebUntis are the caller's to handle."""
        if not load_login():
            return []
        today = self.today()
        out = []
        for e in self._exams():
            day = _date(e["examDate"])
            subject = (e.get("subject") or "").strip()
            if not subject or (day - today).days > days:
                continue
            out.append({"id": f"{e['examDate']}-{subject}-{e.get('startTime') or 0:04d}", "subject": subject,
                        "kind": e.get("examType") or e.get("name") or "Test", "date": day,
                        "topic": (e.get("text") or "").strip()})
        return out

    # ── the morning briefing ──

    def briefing_line(self) -> str:
        if not load_login():
            return ""
        try:
            today = self.today()
            parts = []
            lessons = self._lessons(today)
            blocks = self._blocks(lessons)
            if blocks:
                changes = self._changes(lessons)
                parts.append(f"School today {_clock(blocks[0][0])} to {_clock(blocks[-1][1])}"
                             + (", " + "; ".join(changes) if changes else "") + ".")
            due = [h for h in self._open_homework() if _date(h["dueDate"]) == today]
            if due:
                parts.append("Homework due today: " + "; ".join(
                    f"{h['subject']}: {h.get('text', '').strip()}" for h in due) + ".")
            soon = [e for e in self._exams() if (_date(e["examDate"]) - today).days <= BRIEF_TEST_DAYS]
            if soon:
                parts.append("; ".join(self._exam_text(e, with_time=False) for e in soon) + ".")
            return " ".join(parts)
        except Exception as e:
            print(f"[Untis] briefing: {type(e).__name__}")
            return ""


def setup():
    """./aria.sh --untis: asks for the WebUntis login, checks it, and keeps it in the keyring."""
    import getpass
    print(f"WebUntis for {SCHOOL} ({SERVER}).")
    user = input("WebUntis username: ").strip()
    password = getpass.getpass("WebUntis password (not shown): ")
    u = Untis()
    try:
        res = u._rpc("authenticate", {"user": user, "password": password, "client": "Aria"})
    except LoginError:
        print("WebUntis didn't accept that login. Nothing was saved.")
        return 1
    except Exception as e:
        print(f"Couldn't reach WebUntis ({type(e).__name__}). Nothing was saved.")
        return 1
    u._sid = res["sessionId"]
    try:
        u._rpc("logout", {})
    except Exception:
        pass
    save_login(user, password)
    print("Connected. Aria can now tell you your timetable, homework and tests (restart Aria once).")
    return 0


if __name__ == "__main__":
    raise SystemExit(setup())
