"""
Aria starting conversations on her own, without being a nuisance.

Three kinds, checked once a minute while she's asleep:
  event   — an event in MyNotion just ended: "How did the dentist go? Anything to note?"
  review  — Sunday evening: go through the open to-dos one by one (done / keep / drop / later)
  chat    — now and then, a normal conversation: a question or remark tied to what she knows
            about Lala, the time of day, or what they've been up to. Not about tasks.

She only speaks up when it's a good moment: Lala is at the desk (camera, or recent keyboard/mouse
activity when there's no camera), the screen isn't locked, nothing is fullscreen (films, games),
no other app is using the microphone (calls), no focus session, not muted, outside quiet hours.
Ignored openers make her wait longer; "not now" snoozes her for a few hours.

Settings (Engines/.env):
  ARIA_INITIATIVE=0          switch it off completely (also in the orb's right-click menu)
  ARIA_QUIET=22:30-08:30     quiet hours
  ARIA_CHAT_EVERY_MIN=90     minimum gap between two casual chats
  ARIA_CHATS_PER_DAY=3       at most this many casual chats a day
  ARIA_REVIEW_DAY=6          weekly review day (0 = Monday … 6 = Sunday), from ARIA_REVIEW_HOUR=18
"""

import datetime as dt
import json
import os
import random
import re
import subprocess
import threading
import time

STATE_FILE = os.path.join(os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")), "aria", "initiative.json")

QUIET = os.environ.get("ARIA_QUIET", "22:30-08:30")
CHAT_EVERY_MIN = float(os.environ.get("ARIA_CHAT_EVERY_MIN", 90))
CHATS_PER_DAY = int(os.environ.get("ARIA_CHATS_PER_DAY", 3))
REVIEW_DAY = int(os.environ.get("ARIA_REVIEW_DAY", 6))
REVIEW_HOUR = int(os.environ.get("ARIA_REVIEW_HOUR", 18))

MIN_GAP_AFTER_TALK_S = 20 * 60     # not right after Lala talked to her anyway
MIN_GAP_ANY_S = 30 * 60            # between any two openers
PRESENT_FOR_S = 10 * 60            # don't pounce the moment someone sits down (that's the greeting's job)
EVENT_FOLLOWUP_WINDOW_MIN = 20     # ask about an event up to this long after it ended
NOT_NOW_SNOOZE_S = 3 * 3600
CHAT_CHANCE_PER_MIN = 0.12         # once allowed, a chat starts after ~8 min on average, not like clockwork

NOT_NOW_RE = re.compile(
    r"^\s*(?:aria,?\s*)?(?:not now|later|maybe later|i'?m busy|busy|not right now|leave me alone|"
    r"can'?t (?:talk|now)|no time|another time|stop)\b", re.I)


def _parse_quiet(spec):
    try:
        a, b = spec.split("-")
        h1, m1 = map(int, a.split(":"))
        h2, m2 = map(int, b.split(":"))
        return h1 * 60 + m1, h2 * 60 + m2
    except Exception:
        return None


def in_quiet_hours(now: dt.datetime = None) -> bool:
    q = _parse_quiet(QUIET)
    if not q:
        return False
    now = now or dt.datetime.now()
    m = now.hour * 60 + now.minute
    start, end = q
    return start <= m < end if start < end else (m >= start or m < end)


def _run(cmd, timeout=2):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except Exception:
        return ""


def screen_locked() -> bool:
    out = _run(["dbus-send", "--session", "--print-reply", "--dest=org.cinnamon.ScreenSaver",
                "/org/cinnamon/ScreenSaver", "org.cinnamon.ScreenSaver.GetActive"])
    return "boolean true" in out


def idle_seconds() -> float | None:
    out = _run(["gdbus", "call", "--session", "--dest", "org.cinnamon.Muffin.IdleMonitor",
                "--object-path", "/org/cinnamon/Muffin/IdleMonitor/Core",
                "--method", "org.cinnamon.Muffin.IdleMonitor.GetIdletime"])
    m = re.search(r"(\d+)", out)
    return int(m.group(1)) / 1000 if m else None


def fullscreen_app() -> bool:
    win = re.search(r"window id # (0x[0-9a-f]+)", _run(["xprop", "-root", "_NET_ACTIVE_WINDOW"]))
    if not win or win.group(1) == "0x0":
        return False
    return "_NET_WM_STATE_FULLSCREEN" in _run(["xprop", "-id", win.group(1), "_NET_WM_STATE"])


def mic_in_use_by_others() -> bool:
    """A call or recording in another app (Aria's own microphone use doesn't count)."""
    try:
        streams = json.loads(_run(["pactl", "-f", "json", "list", "source-outputs"]) or "[]")
    except ValueError:
        return False
    me = str(os.getpid())
    for s in streams:
        props = s.get("properties", {})
        if props.get("application.process.id") == me or s.get("corked"):
            continue
        name = (props.get("media.name", "") + " " + props.get("application.id", "")).lower()
        if "peak detect" in name or "pavucontrol" in name:     # volume meters, not a call
            continue
        return True
    return False


class Initiative:
    def __init__(self, aria):
        self.aria = aria
        self.enabled = os.environ.get("ARIA_INITIATIVE", "1") != "0"
        self.state = self._load()
        if "enabled" in self.state:
            self.enabled = bool(self.state["enabled"]) and self.enabled
        self._present_since = None
        self._last_reason = ""

    # ── persistence ──

    def _load(self):
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def _save(self):
        try:
            os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
            with open(STATE_FILE, "w") as f:
                json.dump(self.state, f, indent=1)
        except OSError:
            pass

    def set_enabled(self, on: bool):
        self.enabled = on
        self.state["enabled"] = on
        self._save()

    # ── called by Aria ──

    def start(self):
        threading.Thread(target=self._loop, daemon=True).start()

    def finished(self, kind: str, answered: bool, snoozed: bool = False):
        """After an opener: was it answered? Ignored openers double the wait for the next chat."""
        st = self.state
        if snoozed:
            st["snooze_until"] = time.time() + NOT_NOW_SNOOZE_S
        if kind == "chat":
            st["ignored"] = 0 if answered else min(3, st.get("ignored", 0) + 1)
        self._save()

    # ── the loop ──

    def _loop(self):
        time.sleep(90)    # let startup and the first greeting happen first
        while not self.aria._shutting_down:
            try:
                self._tick()
            except Exception as e:
                print(f"[Initiative] {e}")
            time.sleep(60)

    def _tick(self):
        now = time.time()
        present = self._present()
        if present:
            self._present_since = self._present_since or now
        else:
            self._present_since = None
        why = self._blocked(now, present)
        if why:
            if why != self._last_reason:
                self._last_reason = why
            return
        self._last_reason = ""
        opener = self._event_followup() or self._weekly_review() or self._chat(now)
        if opener:
            self.state["last_any"] = now
            self._save()
            print(f"[Initiative] starting a conversation: {opener['kind']}")
            self.aria.start_initiative(opener)

    def _present(self) -> bool:
        vision = self.aria.vision
        if getattr(vision, "_camera_index", None) is not None and getattr(vision, "_running", False):
            return bool(vision.is_present)
        idle = idle_seconds()       # no camera: recent keyboard/mouse use counts as being here
        return idle is not None and idle < 5 * 60

    def _blocked(self, now, present) -> str:
        a = self.aria
        if not self.enabled:
            return "off"
        if a.awake or a._shutting_down:
            return "awake"
        if a.muted:
            return "muted"
        if not present:
            return "nobody here"
        if now - (self._present_since or now) < PRESENT_FOR_S:
            return "just arrived"
        if in_quiet_hours():
            return "quiet hours"
        if now < self.state.get("snooze_until", 0):
            return "snoozed"
        if now - self.state.get("last_any", 0) < MIN_GAP_ANY_S:
            return "too soon"
        if now - a.last_talked < MIN_GAP_AFTER_TALK_S:
            return "talked recently"
        if a.focus.active:
            return "focus session"
        if screen_locked():
            return "locked"
        if fullscreen_app():
            return "fullscreen"
        if mic_in_use_by_others():
            return "mic busy"
        return ""

    def force(self, kind: str):
        """aria.sh --chat / --review / --event: start that conversation now, skipping the timing rules."""
        if kind == "chat":
            opener = {"kind": "chat", "prompt": self._chat_prompt(self.state.get("recent_openers", [])[-6:]),
                      "hint": self._chat_hint()}
        elif kind == "review":
            saved = (REVIEW_DAY, REVIEW_HOUR, self.state.pop("review_week", None))
            globals().update(REVIEW_DAY=dt.date.today().weekday(), REVIEW_HOUR=0)
            try:
                opener = self._weekly_review()
            finally:
                globals().update(REVIEW_DAY=saved[0], REVIEW_HOUR=saved[1])
                if saved[2]:
                    self.state["review_week"] = saved[2]
            if not opener:
                self.aria.ui.message("aria", "No open to-dos to review.")
                return
        else:
            opener = self._event_followup(any_today=True)
            if not opener:
                self.aria.ui.message("aria", "No event today to ask about.")
                return
        if self.aria.awake:
            self.aria.ui.message("aria", "Ask me again when I'm asleep — I'm in a conversation.")
            return
        print(f"[Initiative] starting a conversation (forced): {kind}")
        self.aria.start_initiative(opener)

    # ── kinds ──

    def _event_followup(self, any_today=False):
        notion = self.aria.notion
        if not notion:
            return None
        today = dt.date.today()
        now = dt.datetime.now()
        done = self.state.setdefault("followed_up", [])
        for e in notion._events_between(today, today):
            if e["allDay"] or e["startHour"] is None or e.get("repeat"):
                continue        # repeating things (gym, classes) would get asked about every time
            end_h = float(e["startHour"]) + float(e["duration"] or 1)
            ended = dt.datetime.combine(today, dt.time()) + dt.timedelta(hours=end_h)
            key = f"{e['id']}:{today.isoformat()}"
            if not any_today and (key in done or
                                  not (0 <= (now - ended).total_seconds() / 60 <= EVENT_FOLLOWUP_WINDOW_MIN)):
                continue
            done.append(key)
            self.state["followed_up"] = done[-30:]
            t = e["title"]
            return {
                "kind": "event",
                "prompt": (f"[You are starting the conversation; Lala hasn't said anything.] Lala's calendar event "
                           f"'{t}' just ended. In one short, natural sentence, ask how it went or whether there's "
                           f"anything worth noting. Don't mention the calendar or that you're checking in."),
                "hint": (f"You asked Lala about '{t}', which just ended. If they tell you something worth keeping "
                         f"(results, follow-ups, dates, names), save it with add_note titled '{t} notes'. "
                         f"Don't save small talk. If they need to do something later, offer a reminder."),
            }
        return None

    def _weekly_review(self):
        """Only the opener comes from the model; the answers (done/drop/keep/stop) are handled in code
        by Aria (main.py: _review_answer), because the model tends to *say* "ticked off" without doing it."""
        notion = self.aria.notion
        now = dt.datetime.now()
        if not notion or now.weekday() != REVIEW_DAY or now.hour < REVIEW_HOUR:
            return None
        week = now.strftime("%G-W%V")
        if self.state.get("review_week") == week:
            return None
        self.state["review_week"] = week
        items = notion.open_todo_items()[:10]
        start = dt.date.today() + dt.timedelta(days=1)
        _, nxt = notion._split_daily(notion._events_between(start, start + dt.timedelta(days=6)))
        coming = "; ".join(notion._fmt_event(e) for e in nxt[:4])
        if not items:
            return None
        first = items[0][1]
        return {
            "kind": "review",
            "items": items,
            "coming": coming,
            "prompt": (f"[You are starting the conversation; Lala hasn't said anything.] It's time for the short "
                       f"weekly review of Lala's to-do list. In one or two spoken sentences: say there "
                       f"{'is 1 open to-do' if len(items) == 1 else f'are {len(items)} open to-dos'} to go through quickly, "
                       f"then ask about the first one, '{first}': is it done, should it stay, be dropped, or do they "
                       f"want a reminder for it? Don't list the others."),
        }

    def _chat(self, now):
        st = self.state
        today = dt.date.today().isoformat()
        if st.get("chat_day") != today:
            st["chat_day"], st["chats_today"] = today, 0
        if st["chats_today"] >= CHATS_PER_DAY:
            return None
        gap = CHAT_EVERY_MIN * 60 * (2 ** st.get("ignored", 0))   # ignored openers -> wait longer
        if now - st.get("last_chat", 0) < gap or random.random() > CHAT_CHANCE_PER_MIN:
            return None
        st["last_chat"] = now
        st["chats_today"] += 1
        recent = st.get("recent_openers", [])[-6:]
        return {
            "kind": "chat",
            "prompt": self._chat_prompt(recent),
            "hint": self._chat_hint(),
        }

    @staticmethod
    def _chat_hint():
        return ("You started this conversation yourself, just to talk. Keep it a real, relaxed conversation: "
                "react to what Lala says, share a brief opinion or a related thought, ask a follow-up now and "
                "then — but don't interrogate, and don't turn it into a task or offer help. Short spoken replies. "
                "Don't use tools unless Lala asks for something. If they answer briefly ('ok', 'yeah', 'fine'), "
                "they probably don't feel like talking: reply with a few relaxed words and no question.")

    def _chat_prompt(self, recent):
        """The topic is picked here, not by the model: left alone it asks about the same fact every time."""
        a = self.aria
        now = dt.datetime.now()
        today_bits = []
        try:
            notion = a.notion
            if notion:
                today = dt.date.today()
                past = [e for e in notion._events_between(today, today)
                        if not e["allDay"] and e["startHour"] is not None
                        and float(e["startHour"]) + float(e["duration"] or 1) <= now.hour + now.minute / 60]
                if past:
                    today_bits.append("Earlier today Lala had: " + ", ".join(e["title"] for e in past[:3]) + ".")
                tomorrow = notion._events_between(today + dt.timedelta(days=1), today + dt.timedelta(days=1))
                if tomorrow:
                    today_bits.append("Tomorrow Lala has: " + ", ".join(e["title"] for e in tomorrow[:3]) + ".")
        except Exception:
            pass
        try:
            facts = list(a.memory.get_memories(30))
        except Exception:
            facts = []
        used = self.state.get("recent_facts", [])
        fresh = [f for f in facts if f not in used] or facts

        options = [("fun", None), ("time", None)]
        options += [("fact", f) for f in random.sample(fresh, min(2, len(fresh)))]
        if today_bits and self.state.get("last_topic") != "day":
            options.append(("day", None))
        options = [o for o in options if o[0] != self.state.get("last_topic") or o[0] == "fact"]
        kind, fact = random.choice(options)
        self.state["last_topic"] = kind
        if fact:
            self.state["recent_facts"] = (used + [fact])[-8:]

        if kind == "fact":
            topic = f"this thing you know about Lala: \"{fact}\" — ask something specific and curious about it"
        elif kind == "day":
            topic = "their day: " + " ".join(today_bits)
        elif kind == "time":
            topic = (f"it being {now.strftime('%A')} {('morning' if now.hour < 12 else 'afternoon' if now.hour < 18 else 'evening')}"
                     " — e.g. how the week is going, or plans for later")
        else:
            topic = random.choice([
                "a fun would-you-rather question", "what they've been into lately (music, shows, games, food)",
                "a small opinion question (best snack for studying, favourite season, a hot take)",
                "something they're looking forward to"])
        avoid = ("\nIt must be clearly different from these earlier openers: " + " | ".join(recent)) if recent else ""
        return (f"[You are starting a conversation on your own; Lala hasn't said anything and is just at their desk.] "
                f"It's {now.strftime('%A %H:%M')}.\n"
                f"Say one or two natural spoken sentences to start a casual chat about {topic}. "
                f"End with an open question. Not about tasks, reminders, productivity or offering help. "
                f"No greeting like 'hey there', no 'just checking in', no 'I was wondering'. Only use facts given "
                f"here or in what you know about Lala. Never claim anything you weren't told: no weather or news, "
                f"nothing someone said or did, no 'again', 'still' or 'lately'.{avoid}")

    def remember_opener(self, text):
        recent = self.state.setdefault("recent_openers", [])
        recent.append(text[:140])
        self.state["recent_openers"] = recent[-10:]
        self._save()
