"""School timetable, homework and tests from WebUntis (HTL Leonding), against a fake WebUntis in the real API's format."""
import datetime as dt
import json

import pytest

from Engines import Untis as U

MON = dt.date(2026, 11, 9)


class FakeUntis:
    """Answers like htl-leonding.webuntis.com: JSON-RPC for login and the timetable, REST for homework and tests."""
    def __init__(self, lessons=(), homework=(), exams=(), password="s3cret-pw"):
        self.lessons, self.homework, self.exams, self.password = list(lessons), list(homework), list(exams), password
        self.logins = 0
        self.expire_next = False
        self.cookies = {}
        self.calls = []

    def post(self, url, params=None, json=None, cookies=None, timeout=None):
        method = json["method"]
        self.calls.append(method)
        if method == "authenticate":
            if json["params"]["password"] != self.password:
                return Resp({"jsonrpc": "2.0", "id": json["id"], "error": {"code": -8504, "message": "bad credentials"}})
            self.logins += 1
            return Resp({"jsonrpc": "2.0", "id": json["id"],
                         "result": {"sessionId": f"S{self.logins}", "personType": 5, "personId": 4711, "klasseId": 12}})
        if self.expire_next:
            self.expire_next = False
            return Resp({"jsonrpc": "2.0", "id": json["id"], "error": {"code": -8520, "message": "not authenticated"}})
        if method == "getTimetable":
            o = json["params"]["options"]
            assert o["element"] == {"id": 4711, "type": 5}
            day = [l for l in self.lessons if o["startDate"] <= l["date"] <= o["endDate"]]
            return Resp({"jsonrpc": "2.0", "id": json["id"], "result": day})
        return Resp({"jsonrpc": "2.0", "id": json["id"], "result": None})

    def get(self, url, params=None, cookies=None, timeout=None):
        self.calls.append(url.rsplit("/api/", 1)[1])
        if "homeworks" in url:
            return Resp({"data": {"homeworks": self.homework,
                                  "lessons": [{"id": 1, "subject": "AM"}, {"id": 2, "subject": "E"}]}})
        return Resp({"data": {"exams": self.exams}})


class Resp:
    def __init__(self, data):
        self.data = data
        self.status_code = 200

    def json(self):
        return self.data

    def raise_for_status(self):
        pass


def lesson(start, end, su, ro="E201", day=MON, code=None, orgroom=None, subst=None):
    room = {"id": 1, "name": ro}
    if orgroom:
        room["orgname"] = orgroom
        room["orgid"] = 9
    out = {"id": start, "date": int(day.strftime("%Y%m%d")), "startTime": start, "endTime": end,
           "su": [{"id": 1, "name": su, "longname": su}], "ro": [room], "kl": [{"id": 12, "name": "3AHIF"}], "te": []}
    if code:
        out["code"] = code
    if subst:
        out["substText"] = subst
    return out


@pytest.fixture
def make(monkeypatch):
    def build(fake, today=MON, password="s3cret-pw"):
        monkeypatch.setattr(U, "load_login", lambda: ("lala", password))
        return U.Untis(session=fake, today=lambda: today)
    return build


def test_a_day_with_double_lessons_merged(make):
    fake = FakeUntis([lesson(800, 850, "AM"), lesson(850, 940, "AM"), lesson(955, 1045, "E", ro="E105")])
    assert make(fake).school_day("today") == ("School today: 8:00 to 10:45. AM 8:00 to 9:40 in E201; "
                                              "E 9:55 to 10:45 in E105.")


def test_changes_are_said_first(make):
    fake = FakeUntis([lesson(800, 850, "AM"), lesson(955, 1045, "E", code="cancelled"),
                      lesson(1100, 1150, "POS", ro="E204", orgroom="E201"),
                      lesson(1200, 1250, "D", code="irregular", subst="Supplierung")])
    out = make(fake).school_day("today")
    assert out.startswith("School today: 8:00 to 12:50. Changes: E at 9:55 is cancelled; POS at 11:00 is in E204 "
                          "instead of E201; D at 12:00: Supplierung.")
    assert "E 9:55" not in out.split("Changes:")[1].split(".", 1)[1]        # a cancelled lesson isn't listed again


def test_no_school(make):
    assert make(FakeUntis()).school_day("saturday") == "No school on Saturday."


def test_homework_due_soon(make):
    hw = [{"id": 1, "lessonId": 1, "date": 20261105, "dueDate": 20261110, "text": "Exercise 4 to 7", "completed": False},
          {"id": 2, "lessonId": 2, "date": 20261105, "dueDate": 20261112, "text": "Essay", "completed": True},
          {"id": 3, "lessonId": 2, "date": 20261105, "dueDate": 20261130, "text": "Read chapter 3", "completed": False}]
    assert make(FakeUntis(homework=hw)).school_homework() == (
        "Homework: AM for tomorrow: Exercise 4 to 7; E for Monday 30 November: Read chapter 3.")


def test_tests_coming_up(make):
    exams = [{"examType": "Schularbeit", "name": "SA 2", "examDate": 20261112, "startTime": 800, "endTime": 940,
              "subject": "AM", "rooms": ["E201"], "teachers": [], "text": "Integrals"}]
    assert make(FakeUntis(exams=exams)).school_exams() == "Tests: Schularbeit in AM on Thursday at 8:00 (Integrals)."
    assert make(FakeUntis()).school_exams() == "No tests in the next 3 weeks."


def test_briefing_mentions_only_what_matters(make):
    fake = FakeUntis([lesson(800, 850, "AM"), lesson(955, 1045, "E", code="cancelled")],
                     homework=[{"id": 1, "lessonId": 1, "date": 20261105, "dueDate": 20261109, "text": "Ex 4",
                                "completed": False}],
                     exams=[{"examType": "Test", "name": "", "examDate": 20261111, "startTime": 800, "endTime": 850,
                             "subject": "E", "rooms": [], "teachers": [], "text": ""}])
    assert make(fake).briefing_line() == ("School today 8:00 to 8:50, E at 9:55 is cancelled. Homework due today: "
                                          "AM: Ex 4. Test in E on Wednesday.")


def test_the_session_is_kept_and_renewed_when_it_runs_out(make):
    fake = FakeUntis([lesson(800, 850, "AM")])
    u = make(fake)
    u.school_day("today")
    u.school_day("tomorrow")
    assert fake.logins == 1
    fake.expire_next = True
    u._cache.clear()
    assert "AM" in u.school_day("today")
    assert fake.logins == 2


def test_a_day_is_cached_for_a_while(make):
    fake = FakeUntis([lesson(800, 850, "AM")])
    u = make(fake)
    u.school_day("today")
    u.school_day("today")
    assert fake.calls.count("getTimetable") == 1


def test_wrong_password_and_no_login(make, monkeypatch):
    assert make(FakeUntis(), password="wrong").school_day("today") == (
        "WebUntis didn't accept the login. Set it up again with: ./aria.sh --untis")
    monkeypatch.setattr(U, "load_login", lambda: None)
    u = U.Untis(session=FakeUntis(), today=lambda: MON)
    assert u.school_day("today") == "WebUntis isn't set up yet. Run ./aria.sh --untis once to connect it."
    assert u.briefing_line() == ""


def test_password_never_in_what_she_says(make):
    class Broken(FakeUntis):
        def post(self, *a, **k):
            raise ConnectionError("connection to htl-leonding.webuntis.com failed for password=s3cret-pw")
    out = make(Broken()).school_day("today")
    assert "s3cret" not in out and out == "I couldn't reach WebUntis right now."


def test_calendar_answers_include_school(make):
    u = make(FakeUntis([lesson(800, 850, "AM", day=MON + dt.timedelta(days=1))]))
    assert u.day_line("tomorrow") == "School tomorrow: 8:00 to 8:50."
    assert u.day_line("this week") == ""


def test_calendar_tool_adds_the_school_day():
    from Engines.Tool_Engine import ToolEngine

    class Fake:
        menu = None

        def __init__(self, **k):
            self.__dict__.update(k)

        def __getattr__(self, name):
            return lambda *a, **k: None
    notion = Fake(get_events=lambda when="this week": "Calendar tomorrow: Dentist at 16:00.")
    untis = Fake(day_line=lambda when: "School tomorrow: 8:00 to 13:00." if when == "tomorrow" else "")
    t = ToolEngine(notion=notion, untis=untis)
    assert t.execute("get_events", {"when": "tomorrow"}) == "Calendar tomorrow: Dentist at 16:00. School tomorrow: 8:00 to 13:00."
    assert t.execute("get_events", {"when": "this week"}) == "Calendar tomorrow: Dentist at 16:00."


def test_the_morning_briefing_includes_school(aria):
    import types
    aria.weather = types.SimpleNamespace(brief=lambda: "Rain later.")
    aria.mail = types.SimpleNamespace(briefing_line=lambda: "1 new email: from Sara.")
    aria.untis = types.SimpleNamespace(briefing_line=lambda: "School today 8:00 to 13:00.")
    assert aria._briefing_extras() == "Rain later. 1 new email: from Sara. School today 8:00 to 13:00."
    aria.untis = None
    assert aria._briefing_extras() == "Rain later. 1 new email: from Sara."
