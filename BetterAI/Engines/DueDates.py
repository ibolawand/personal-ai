"""
Due dates on checklist items: "finish the essay by friday" -> a to-do  "Finish the essay · due Fri 13 Nov".

The date is plain text at the end of the item, so it stays readable and editable in MyNotion (which shows it as a
coloured chip and puts the task on its calendar) and can be typed there by hand: "due 13 Nov", "due 13.11.",
"due 2026-11-13" all work. MyNotion turns "due friday" / "due tomorrow" into a date while you type, because a
relative day written into a note would mean something else next week.

The same rules are in MyNotion (note-frontend/src/app/text-editor/due-dates.ts); keep the two in step.
"""

import datetime as dt
import re

MONTHS3 = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
DAYS3 = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
_MON = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*"

# " · due Fri 13 Nov", " due 13.11.", " - due 2026-11-13", "(due 13 november 2027)" at the end of the item
DUE_RE = re.compile(
    r"\s*(?:[·•—–\-|,(]\s*)?\bdue\s+(?:on\s+)?(?:(?:mon|tue|wed|thu|fri|sat|sun)[a-z]*,?\s+)?"
    rf"(?P<date>\d{{1,2}}(?:st|nd|rd|th)?\s+{_MON}(?:\s+\d{{4}})?|\d{{1,2}}\.\d{{1,2}}\.(?:\d{{2,4}})?|\d{{4}}-\d{{1,2}}-\d{{1,2}})"
    r"\s*\)?\s*$", re.I)

EVENING_HOUR = 19          # the heads-up the evening before something is due
SOON_DAYS = 7              # "due this week" in the briefing


def _closest_year(month: int, day: int, today: dt.date):
    """A date written without a year: the one nearest to today, so last week's overdue task stays last week's."""
    best = None
    for y in (today.year - 1, today.year, today.year + 1):
        try:
            d = dt.date(y, month, day)
        except ValueError:
            continue
        if best is None or abs((d - today).days) < abs((best - today).days):
            best = d
    return best


def parse_due_text(s: str, today: dt.date = None) -> dt.date | None:
    """The date part of a due tag: '13 Nov', '13 november 2027', '13.11.', '13.11.27', '2026-11-13'."""
    today = today or dt.date.today()
    s = s.strip().lower()
    try:
        m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)
        if m:
            return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        m = re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{2,4})?", s)
        if m:
            day, month, year = int(m.group(1)), int(m.group(2)), m.group(3)
            if year:
                y = int(year)
                return dt.date(y + 2000 if y < 100 else y, month, day)
            return _closest_year(month, day, today)
        m = re.fullmatch(rf"(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MON})(?:\s+(\d{{4}}))?", s)
        if m:
            month = MONTHS3.index(m.group(2)[:3]) + 1
            if m.group(3):
                return dt.date(int(m.group(3)), month, int(m.group(1)))
            return _closest_year(month, int(m.group(1)), today)
    except ValueError:
        return None
    return None


def split_due(text: str, today: dt.date = None):
    """'Finish the essay · due Fri 13 Nov' -> ('Finish the essay', date(…, 11, 13)); no tag -> (text, None)."""
    m = DUE_RE.search(text or "")
    if not m:
        return (text or "").strip(), None
    day = parse_due_text(m.group("date"), today)
    if not day:
        return (text or "").strip(), None
    return text[:m.start()].strip(), day


def due_tag(day: dt.date, today: dt.date = None) -> str:
    """'due Fri 13 Nov', with the year only when it wouldn't be clear without it."""
    today = today or dt.date.today()
    tag = f"due {DAYS3[day.weekday()]} {day.day} {MONTHS3[day.month - 1].capitalize()}"
    if _closest_year(day.month, day.day, today) != day:
        tag += f" {day.year}"
    return tag


def with_due(text: str, day: dt.date | None, today: dt.date = None) -> str:
    """The item text with its due tag replaced (or removed when day is None)."""
    base, _ = split_due(text, today)
    return f"{base} · {due_tag(day, today)}" if day else base


def say_due(day: dt.date, today: dt.date = None) -> str:
    """For speech: 'today', 'tomorrow', 'on Friday', 'on Friday 20 November', 'yesterday', '3 days ago'."""
    today = today or dt.date.today()
    n = (day - today).days
    if n == 0:
        return "today"
    if n == 1:
        return "tomorrow"
    if n == -1:
        return "yesterday"
    if n < 0:
        return f"{-n} days ago"
    if n < 7:
        return f"on {day.strftime('%A')}"
    return f"on {day.strftime('%A')} {day.day} {day.strftime('%B')}"


def strip_by_phrase(text: str):
    """'finish the essay by friday' -> ('finish the essay', 'friday'); also 'until', 'before', 'due', 'for'.
    Returns (text, None) when there's no such phrase; the day words are parsed by the caller."""
    m = re.search(r"\s+(?:by|until|till|before|due(?: on)?|for)\s+(?:the\s+)?((?:next\s+)?(?:today|tonight|tomorrow|"
                  r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|day after tomorrow|in \d+ (?:days?|weeks?)|"
                  r"\d{1,2}[./]\d{1,2}\.?(?:\d{2,4})?|\d{1,2}(?:st|nd|rd|th)?(?: of)? [a-z]+|[a-z]+ \d{1,2}(?:st|nd|rd|th)?))\s*[.!]?$",
                  text or "", re.I)
    if not m:
        return (text or "").strip(), None
    return text[:m.start()].strip(), m.group(1)
