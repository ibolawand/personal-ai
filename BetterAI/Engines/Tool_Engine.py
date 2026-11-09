"""
ToolEngine — native Ollama tool calling.

Each tool is declared once (schema + handler) and only offered to the LLM
when its backend (Spotify, Arduino, Home Assistant, ...) is actually
available, so the model can't pick a tool that doesn't exist.
"""

import contextlib
import os
from pathlib import Path

import requests
from dotenv import load_dotenv


load_dotenv(Path(__file__).parent / ".env")


def _ok(success, msg, fail="The device didn't respond."):
    return msg if success else fail


def _tool(tool_name, description, handler, optional=(), **params):
    """params: name -> (json_type, description). Required unless listed in `optional`."""
    return {
        "schema": {
            "type": "function",
            "function": {
                "name": tool_name,
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        p: {"type": t, "description": d} for p, (t, d) in params.items()
                    },
                    "required": [p for p in params if p not in optional],
                },
            },
        },
        "handler": handler,
    }


class ToolEngine:
    def __init__(self, spotify=None, arduino=None, vision=None, ha=None,
                 reminders=None, focus=None, screen=None, laptop=None, files=None, notion=None,
                 owner_check=None, memory_note=None, activity=None, weather=None, undo=None,
                 recall=None, health=None, posture=None, quiz=None, face_learner=None, mail=None, untis=None,
                 writer=None):
        self.spotify = spotify
        self.arduino = arduino
        self.vision = vision
        self.ha = ha
        self.reminders = reminders
        self.focus = focus
        self.screen = screen
        self.laptop = laptop
        self.files = files
        self.notion = notion
        self.owner_check = owner_check or (lambda: True)
        self.memory_note = memory_note
        self.activity = activity
        self.weather = weather
        self.undo = undo
        self.recall = recall
        self.health = health
        self.posture = posture
        self.quiz = quiz
        self.face_learner = face_learner
        self.mail = mail
        self.untis = untis
        self.writer = writer
        self._registry = {t["schema"]["function"]["name"]: t for t in self._build()}

    # Tools that touch the laptop, files, clipboard/screen or phone — gated by owner_check
    PROTECTED = {
        "close_app", "power", "set_wifi", "lock_screen", "read_file", "open_file", "find_files", "open_folder",
        "search_file_contents",
        "tidy_downloads", "undo_tidy_downloads", "look_at_screen", "read_clipboard", "copy_to_clipboard",
        "check_phone_location", "check_phone_battery", "notify_phone",
        "read_note", "search_notes", "list_notes", "get_events", "move_event", "delete_event",
        "clear_list", "get_due", "daily_briefing", "what_you_know_about_me", "forget_about_me",
        "recall_conversation", "search_conversations",
        "check_mail", "read_mail", "search_mail", "draft_reply", "draft_mail", "archive_mail", "mark_mail_read",
        "mail_todo", "mail_to_event", "mark_sender_important",
        "school_day", "school_homework", "school_exams",
        "organize_note", "edit_note",
    }

    # Changes "undo that" can take back (Engines/Undo.py)
    UNDOABLE = {"restore_note", "add_note", "save_as_note", "add_to_list", "remove_from_list", "check_off", "add_event",
                "add_todo", "set_due", "write_note", "organize_note", "edit_note",
                "set_reminder", "set_timer"}

    # ── Tool routing ──────────────────────────────────────────────────────────
    # All ~75 tool descriptions take ~5,500 of the model's 8,192 context tokens. So each turn gets the core set plus
    # only the groups the message is about (and groups used in the last turns, for follow-ups). Tools that are in
    # no group are always offered. If the model then says it can't do something, main.py retries with all tools.
    _phone = False      # True while a message from Lala's Telegram chat is handled: phone tools only
    CORE = {"calculate", "web_search", "set_timer", "set_reminder", "list_reminders", "cancel_reminder",
            "snooze_reminder", "add_note", "add_to_list", "add_todo", "get_events", "search_notes", "undo_last", "get_weather"}
    GROUPS = {
        "music": (r"\b(play|music|song|spotify|pause|resume|skip|next|previous|track|playlist|artist|album|listen|"
                  r"what'?s playing|lo-?fi|genre)\b",
                  {"play_song", "play_artist", "play_playlist", "play_genre", "pause_music", "skip_track",
                   "previous_track", "now_playing", "set_music_volume", "media_control"}),
        "laptop": (r"\b(open|close|quit|launch|start|app|apps|window|windows|switch|volume|louder|quieter|mute|sound|"
                   r"audio|headphones?|speakers?|earbuds|wi-?fi|internet|bluetooth|lock|shut ?down|restart|reboot|"
                   r"suspend|battery|cpu|temperature|laptop|computer|website|browser|google|youtube|github|install|"
                   r"installed|notification|program)\b",
                   {"open_app", "find_app", "switch_to_app", "close_app", "list_open_windows", "set_laptop_volume",
                    "change_laptop_volume", "mute_laptop", "switch_audio_output", "media_control", "lock_screen",
                    "power", "laptop_status", "network_status", "set_wifi", "set_bluetooth", "connect_bluetooth",
                    "open_website",
                    "notify_desktop", "open_mynotion"}),
        "files": (r"\b(files?|pdfs?|docs?|documents?|folders?|downloads?|slides?|powerpoint|word|summari[sz]e|"
                  r"read|assignment|notebook|homework|worksheet|tidy|where is|where'?s|find|open (?:the|it|that)|"
                  r"first|second|third|last one)\b",
                  {"find_files", "search_file_contents", "open_file", "read_file", "open_folder", "tidy_downloads",
                   "undo_tidy_downloads", "save_as_note"}),
        "notion": (r"\b(notes?|lists?|calendar|events?|schedule|meeting|appointment|to-?do|tasks?|tick|check(?:ed)? off|"
                   r"bought|got the|done with|briefing|plan|plans|agenda|week|weekend|tomorrow|today|tonight|"
                   r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|birthday|inbox|remove|clear|move|"
                   r"delete|cancel|shopping|packing|mynotion|notion|save that|day like|restore|older version|"
                   r"old version|bring back|undelete|recover|backup|due|deadline|overdue|by (?:mon|tue|wed|thu|fri|sat|sun)\w*|"
                   r"hand in|submit|write|wrote|organi[sz]e|tidy|structure|sort|summary|summari[sz]e|translate|"
                   r"spelling|typos?|grammar|section|part|heading|study sheet|cheat sheet|rewrite|reformat|format|"
                   r"table|shorter|longer|simpler)\b",
                   {"write_note", "organize_note", "edit_note", "add_note", "save_as_note", "read_note", "search_notes", "list_notes", "add_to_list",
                    "remove_from_list", "check_off", "clear_list", "get_events", "add_event", "move_event",
                    "delete_event", "open_mynotion", "daily_briefing", "restore_note", "add_todo", "set_due", "get_due"}),
        "screen": (r"\b(screen|see|look|looking|copied|clipboard|this error|error|camera|who'?s|who is|in front)\b",
                   {"look_at_screen", "look", "read_clipboard", "copy_to_clipboard"}),
        "quiz": (r"\b(quiz|test me|ask me (?:some )?questions|revise|revision|flash ?cards?|study with me)\b",
                 {"start_quiz"}),
        "faces": (r"\b(face|faces|recogni[sz]e me|who am i)\b", {"learn_my_face"}),
        "school": (r"\b(school|class(?:es)?|lessons?|timetable|stundenplan|homework|hausübung\w*|hausaufgabe\w*|"
                   r"tests?|exams?|schularbeit\w*|teachers?|rooms?|cancell?ed|subjects?|supplier\w*|periods?|untis|"
                   r"webuntis)\b",
                   {"school_day", "school_homework", "school_exams"}),
        "mail": (r"\b(e-?mails?|mails?|inbox|wrote|written|write|replied|reply|answer(?:ed)?|sent me|message from|"
                 r"gmail|archive|the (?:one|thing) from|from (?:mr|mrs|ms|dr|prof)\.?)\b",
                 {"check_mail", "read_mail", "search_mail", "draft_reply", "draft_mail", "archive_mail",
                  "mark_mail_read", "mail_todo", "mail_to_event", "mark_sender_important"}),
        "posture": (r"\b(posture|slouch\w*|sitting|sit (?:up|straight|like this)|how i'?m sitting)\b",
                    {"remember_good_posture"}),
        "focus": (r"\b(focus|pomodoro|study|studying|deep work|concentrat\w*|how long|screen time|break|rounds?)\b",
                  {"start_focus", "stop_focus", "focus_status", "focus_stats", "screen_time"}),
        "memory": (r"\b(remember|forget|know about me|memory|talk(?:ed)? about|mention(?:ed)?|said|yesterday|"
                   r"last time|ago)\b",
                   {"what_you_know_about_me", "remember_about_me", "forget_about_me", "clean_up_memory",
                    "recall_conversation", "search_conversations"}),
        "home": (r"\b(lights?|leds?|lamp|colou?r|bright|dim|phone|tv|television)\b",
                 {"set_led_color", "set_led_effect", "set_led_brightness", "led_off", "notify_phone",
                  "check_phone_battery", "check_phone_location", "turn_on_tv", "turn_off_tv", "set_tv_volume"}),
        "misc": (r"\b(systems?|working|status|okay|convert|bill|tip|split|miles?|km|kilo\w*|kg|"
                 r"pounds?|celsius|fahrenheit|inch\w*|feet|cups?|units?|city|live in)\b",
                 {"system_check", "split_bill", "convert_units", "set_home_city"}),
    }

    def schemas_for(self, text: str, recent_tools=()) -> list:
        """The schemas for this message: core + matching groups + groups of recently used tools + ungrouped."""
        import re
        grouped = set().union(*(names for _, names in self.GROUPS.values()))
        wanted = set(self.CORE)
        recent = set(recent_tools)
        for pattern, names in self.GROUPS.values():
            if re.search(pattern, text or "", re.I) or names & recent:
                wanted |= names
        hidden = self._unplugged()
        if self._phone:
            from Engines.Telegram import PHONE_TOOLS
            hidden = hidden | (set(self._registry) - PHONE_TOOLS)
        picked = [(n, s) for n, s in ((t["schema"]["function"]["name"], t["schema"]) for t in self._registry.values())
                  if (n in wanted or n not in grouped) and n not in hidden]
        # the tools every message gets come first, always in the same order, so the prompt starts the same each turn
        # and Ollama can reuse what it already read; the message's extra groups follow
        always = lambda n: n in self.CORE or n not in grouped
        return [s for n, s in picked if always(n)] + [s for n, s in picked if not always(n)]

    LED_TOOLS = {"set_led_color", "set_led_effect", "set_led_brightness", "led_off"}

    def _unplugged(self) -> set:
        """Tools for hardware that isn't plugged in right now. The Arduino controller exists even without a
        board (it keeps retrying), so its tools are hidden until it actually connects."""
        return set() if getattr(self.arduino, "is_connected", True) else self.LED_TOOLS

    # ── Public API ────────────────────────────────────────────────────────────

    @property
    def schemas(self) -> list:
        return [t["schema"] for t in self._registry.values()]

    @contextlib.contextmanager
    def phone(self):
        """While a message from Lala's phone is handled: only PHONE_TOOLS, and no camera check."""
        self._phone = True
        try:
            yield
        finally:
            self._phone = False

    def execute(self, name: str, args: dict) -> str:
        tool = self._registry.get(name)
        if not tool:
            return f"Unknown tool '{name}'."
        if self._phone:
            from Engines.Telegram import PHONE_TOOLS
            if name not in PHONE_TOOLS:
                return "Refused: that only works at the desk, not from the phone."
        elif name in self.PROTECTED and not self.owner_check():     # from the phone, her own chat proves it's Lala
            return "Refused: only Lala can use that, and I don't recognise who's at the desk."
        try:
            if self.undo and name in self.UNDOABLE:
                result = self.undo.around(lambda r: str(r), lambda: tool["handler"](**(args or {})))
            else:
                result = tool["handler"](**(args or {}))
            return str(result) if result is not None else "Done."
        except Exception as e:
            print(f"[Tools] {name} failed: {e}")
            from Engines import Diagnostics
            Diagnostics.problem("tool_error", f"{name}: {e}")
            return f"{name} failed: {e}"

    # ── Registry ──────────────────────────────────────────────────────────────

    def _build(self) -> list:
        tools = [
            _tool("calculate", "Exact maths — use it for ANY arithmetic, percentages, tips or splitting a bill, "
                  "never calculate in your head ('17% of 2340', '46.8 * 1.18 / 3', 'sqrt(2)').",
                  __import__("Engines.Calc", fromlist=["calculate"]).calculate,
                  expression=("string", "the maths, e.g. '18% of 46.80' or '(12 + 7) * 3'")),
            _tool("split_bill", "Split a bill, optionally with a tip: what each person pays. Use this (not "
                  "calculate) for any bill/tip/split question.",
                  __import__("Engines.Calc", fromlist=["split_bill"]).split_bill, optional=("people", "tip_percent"),
                  total=("number", "the bill amount"), people=("integer", "how many people pay"),
                  tip_percent=("number", "tip in percent, 0 if none")),
            _tool("convert_units", "Convert between units: length, weight, volume, speed, data, time, and "
                  "temperature (C/F/K). E.g. 5 km to miles, 180 cm to feet, 20 C to F.",
                  __import__("Engines.Calc", fromlist=["convert"]).convert,
                  value=("number", "the amount"), from_unit=("string", "unit to convert from"),
                  to_unit=("string", "unit to convert to")),
            _tool("web_search", "Look things up: facts, people, places, how things work, and (when available) "
                  "news, prices and anything recent. Use it instead of guessing.",
                  self.web_search, query=("string", "a short search query, e.g. '2022 world cup final result'")),
        ]

        if self.reminders:
            rm = self.reminders
            tools += [
                _tool("set_timer", "Start a countdown timer (e.g. 'timer for 10 minutes', 'tea timer 4 min').",
                      rm.set_timer, optional=("label",),
                      minutes=("number", "length in minutes; use decimals for seconds, e.g. 0.5"),
                      label=("string", "short name, e.g. 'tea'")),
                _tool("set_reminder",
                      "Remind the user about something later. Give EITHER in_minutes OR at_time (plus day for another day). "
                      "Use this for 'remind me in/at ...' — not notify_phone.",
                      rm.set_reminder, optional=("in_minutes", "at_time", "day", "repeat"),
                      text=("string", "what to remind about, phrased as an action, e.g. 'call mom'"),
                      in_minutes=("number", "minutes from now"),
                      at_time=("string", "24h clock time HH:MM, e.g. '14:30'"),
                      day=("string", "only for another day: 'tomorrow', 'monday', '12.11.' (with at_time, or 09:00)"),
                      repeat=("string", "only for repeating reminders: 'daily', 'weekdays', 'weekly', 'monthly', "
                                        "or weekdays like 'monday and thursday'")),
                _tool("list_reminders", "List pending timers and reminders.", rm.list_reminders),
                _tool("cancel_reminder", "Cancel a timer or reminder.", rm.cancel_reminder,
                      which=("string", "'last', 'all', or words from its text, e.g. 'tea'")),
                _tool("snooze_reminder", "Snooze the reminder or timer that just went off.",
                      rm.snooze, optional=("minutes",), minutes=("number", "default 5")),
            ]

        if self.focus:
            fm = self.focus
            tools += [
                _tool("start_focus",
                      "Start a focus/deep-work session: pauses notifications, plays lo-fi, dims the LEDs, and "
                      "announces when time is up. For Pomodoro ('4 rounds', 'pomodoro') set rounds; breaks "
                      "between rounds start and end on their own.",
                      fm.start, optional=("minutes", "task", "music", "rounds", "break_minutes"),
                      minutes=("number", "length of one work block, default 25"),
                      task=("string", "what the user is working on"),
                      music=("boolean", "play lo-fi music, default true"),
                      rounds=("integer", "number of work blocks, default 1 (Pomodoro usually 4)"),
                      break_minutes=("number", "break between rounds, default 5")),
                _tool("stop_focus", "End the current focus session early.", fm.stop),
                _tool("focus_status", "How much time is left in the focus session or break.", fm.status),
                _tool("focus_stats", "How much Lala focused ('how much did I focus this week/today?').",
                      fm.stats, optional=("period",), period=("string", "'today', 'week' or 'month'")),
            ]

        if self.untis:
            u = self.untis
            tools += [
                _tool("school_day", "Lala's school timetable from WebUntis for one day: lessons, times, rooms, and "
                      "what changed (cancelled, room changes, substitutions). Use for 'what lessons do I have "
                      "tomorrow', 'when does school end', 'is English cancelled'.",
                      u.school_day, optional=("when",),
                      when=("string", "'today', 'tomorrow', 'friday', '12.11.'. Default: today")),
                _tool("school_homework", "Lala's open homework from WebUntis, with when it's due.", u.school_homework),
                _tool("school_exams", "Lala's upcoming tests and Schularbeiten from WebUntis (next 3 weeks).",
                      u.school_exams),
            ]

        if self.mail:
            m = self.mail
            tools += [
                _tool("check_mail", "New email in Lala's Gmail inbox (Primary only, no ads): who wrote and about what. "
                      "For 'any new emails?', 'did anyone write to me?'.", m.check_mail),
                _tool("read_mail", "Read one email aloud: by sender ('the one from Mr Huber'), subject words, 'latest', "
                      "or 'that' for the one just mentioned. Long ones get a summary first; full=true reads all of it.",
                      m.read_mail, optional=("which", "full"),
                      which=("string", "sender name, subject words, 'latest' or 'that'"),
                      full=("boolean", "true to read the whole email after a summary")),
                _tool("search_mail", "Search Lala's emails for words ('what did Sara write about friday').",
                      m.search_mail, query=("string", "the words to look for")),
                _tool("draft_reply", "Reply to an email ('reply that I'll be there at 3'). Writes it in Lala's voice and "
                      "asks before sending; pass what Lala wants to say, not a finished email.",
                      m.draft_reply, optional=("which",), which=("string", "which email: 'that', sender or subject"),
                      gist=("string", "what the reply should say")),
                _tool("draft_mail", "Write a new email ('email Mr Huber that I'm sick'). To someone who emailed before, "
                      "or a full address. Asks before sending.", m.draft_mail, optional=("subject",),
                      to=("string", "name or email address"), gist=("string", "what the email should say"),
                      subject=("string", "subject, if Lala said one")),
                _tool("archive_mail", "Archive an email (out of the inbox, kept in All Mail). Never deletes.",
                      m.archive_mail, optional=("which",), which=("string", "'that', sender or subject")),
                _tool("mark_mail_read", "Mark an email read, or unread with read=false.", m.mark_mail_read,
                      optional=("which", "read"), which=("string", "'that', sender or subject"),
                      read=("boolean", "false to mark unread")),
                _tool("mail_todo", "'Remind me to answer that (tomorrow)': a to-do 'Answer X about Y' with a due date.",
                      m.mail_todo, optional=("which", "due"), which=("string", "'that', sender or subject"),
                      due=("string", "when, e.g. 'tomorrow', 'friday'; default tomorrow")),
                _tool("mail_to_event", "'Turn that into an event': the date/time from the email into the calendar "
                      "(asks first).", m.mail_to_event, optional=("which",),
                      which=("string", "'that', sender or subject")),
                _tool("mark_sender_important", "'Always tell me when Sara emails': Aria says it when their mail arrives.",
                      m.mark_sender_important, who=("string", "the sender's name or address")),
            ]

        if self.writer:
            wr = self.writer
            tools += [
                _tool("write_note",
                      "WRITE a new, well formatted MyNotion note on a topic (headings, lists, tables, formulas): "
                      "'write a study sheet on the French Revolution', 'make a note with the circle formulas', "
                      "'write that up as a note' (from_last_answer). For a quick line or thought use add_note instead.",
                      wr.write_note, optional=("language", "from_last_answer"),
                      title=("string", "a short title for the note"),
                      about=("string", "what it should cover, in Lala's words, with any wishes (length, examples…)"),
                      language=("string", "only if Lala names a language, e.g. 'German'"),
                      from_last_answer=("boolean", "true to turn your previous answer into the note")),
                _tool("organize_note",
                      "Reorganise an existing MyNotion note: groups what belongs together, adds headings, lists, "
                      "to-dos and tables; never removes words ('organise this note', 'tidy up my biology note', "
                      "'structure my notes on the war'). 'this' = the note open in MyNotion.",
                      wr.organize_note, optional=("title",),
                      title=("string", "the note's title, or 'this' for the note open in MyNotion")),
                _tool("edit_note",
                      "Change part of an existing MyNotion note. change: 'add' (write a new part: 'add a section about "
                      "mitosis'), 'summary' (summary at the top), 'fix_spelling', 'translate' (needs language), "
                      "'rewrite' (change one part as asked: 'make the intro shorter', 'turn the dates into a table'). "
                      "'this' = the note open in MyNotion.",
                      wr.edit_note, optional=("title", "instruction", "section", "language"),
                      change=("string", "add | summary | fix_spelling | translate | rewrite"),
                      title=("string", "the note's title, or 'this' for the note open in MyNotion"),
                      instruction=("string", "for add/rewrite: what to write or change, in Lala's words"),
                      section=("string", "the heading of the part to change or to add after, if Lala names one"),
                      language=("string", "for translate: the language to translate into")),
            ]

        if self.quiz:
            tools += [_tool("start_quiz",
                            "Quiz Lala out loud on one of their notes or documents ('quiz me on my C# note', 'test me "
                            "on the gear trains PDF', 'quiz me on my mistakes'). Asks short questions one at a time; "
                            "their answers are checked for you.",
                            self.quiz.start, optional=("count",),
                            topic=("string", "the note or document title or subject, or 'mistakes' to retry missed "
                                             "questions"),
                            count=("integer", "how many questions, default 5"))]

        if self.face_learner:
            tools += [_tool("learn_my_face",
                            "Learn Lala's face from the camera so you can greet them by name ('learn my face', "
                            "'remember my face'). Takes about ten seconds.",
                            self.face_learner, optional=("name",),
                            name=("string", "the person's name, only if they say it"))]

        if self.posture:
            tools += [_tool("remember_good_posture",
                            "Lala is sitting the way they want to sit ('this is my good posture', 'remember how I'm "
                            "sitting'): remember it from the camera, so you can tell them when they slouch or lean "
                            "in too close.", self.posture.set_reference)]

        if self.screen:
            sc = self.screen
            tools += [
                _tool("look_at_screen",
                      "Take a screenshot of the user's computer screen and analyse it. Use for "
                      "'what's on my screen', 'explain this error', 'what am I looking at'.",
                      sc.look_at_screen, optional=("question",),
                      question=("string", "what to find out about the screen")),
                _tool("read_clipboard",
                      "Read the text the user has copied. Use for 'what I copied', 'fix this code I copied', "
                      "'summarise my clipboard'.", sc.read_clipboard),
                _tool("copy_to_clipboard", "Put text (e.g. fixed code) on the user's clipboard.",
                      sc.copy_to_clipboard, text=("string", "the exact text to copy")),
            ]

        if self.laptop:
            lp = self.laptop
            tools += [
                _tool("open_app", "Open (or bring up) any app installed on the laptop — everything in the Mint "
                      "menu, e.g. VS Code, Packet Tracer, Discord, LibreOffice Writer. "
                      "For MyNotion, the calendar or a note use open_mynotion instead.",
                      lp.open_app, app=("string", "app name as Lala says it")),
                _tool("find_app", "Check whether a program/app is installed ('where is my packet tracer?', "
                      "'do I have discord?'). For documents and other files use find_files.",
                      lp.find_app, app=("string", "app name")),
                _tool("switch_to_app", "Bring an open app or window to the front.",
                      lp.switch_to_app, app=("string", "app name or words from the window title")),
                _tool("close_app", "Close an app's windows (asks the user to confirm).",
                      lp.close_app, app=("string", "app name")),
                _tool("list_open_windows", "List the windows open on the laptop.", lp.list_open_windows),
                _tool("set_laptop_volume", "Set the laptop's system volume (not Spotify's).",
                      lp.set_laptop_volume, level=("integer", "0-100")),
                _tool("change_laptop_volume", "Turn the laptop volume up or down by an amount.",
                      lp.change_laptop_volume, amount=("integer", "e.g. 10 or -10")),
                _tool("mute_laptop", "Mute or unmute the laptop.", lp.mute_laptop,
                      mute=("boolean", "true to mute, false to unmute")),
                _tool("switch_audio_output", "Switch laptop audio to another output, e.g. headphones or a bluetooth speaker.",
                      lp.switch_audio_output, device=("string", "output name")),
                _tool("media_control", "Control whatever media is playing on the laptop (YouTube, VLC, Spotify app...).",
                      lp.media_control, action=("string", "play_pause, play, pause, next, previous or stop")),
                _tool("lock_screen", "Lock the laptop screen.", lp.lock_screen),
                _tool("power", "Suspend, shut down or restart the laptop (asks to confirm).",
                      lp.power, action=("string", "suspend, shutdown or restart")),
                _tool("laptop_status", "Laptop battery, temperatures, RAM and disk space.", lp.laptop_status),
                _tool("network_status", "Check (without changing anything) whether Wi-Fi and Bluetooth are on and "
                      "what's connected: 'is wifi on?', 'am I connected?', 'are my earbuds connected?'.",
                      lp.network_status),
                _tool("set_wifi", "Turn laptop Wi-Fi on or off — only when Lala asks to switch it, not to check it.",
                      lp.set_wifi, on=("boolean", "true = on")),
                _tool("set_bluetooth", "Turn laptop Bluetooth on or off.", lp.set_bluetooth, on=("boolean", "true = on")),
                _tool("connect_bluetooth", "Connect a paired Bluetooth device, e.g. earbuds.",
                      lp.connect_bluetooth, device=("string", "device name")),
                _tool("open_website", "Open a website or a web search in the browser.",
                      lp.open_website, site=("string", "site name (github, youtube, gmail...), URL, or search words")),
                _tool("notify_desktop", "Show a desktop notification on the laptop.",
                      lp.notify_desktop, message=("string", "text")),
            ]

        if self.files:
            fl = self.files
            tools += [
                _tool("find_files", "Search Lala's school/documents/downloads folders for files by name.",
                      fl.find_files, optional=("kind", "days"),
                      query=("string", "words from the file name or folder, e.g. 'c# assignment'"),
                      kind=("string", "pdf, document, slides, spreadsheet, code, image, audio, video or archive"),
                      days=("number", "only files modified in the last N days")),
                _tool("search_file_contents",
                      "Find documents (pdf, Word, slides, notes) by what's INSIDE them, e.g. 'the pdf about "
                      "normalization', 'where did I read about subnetting'. Use find_files for names.",
                      fl.search_contents,
                      query=("string", "the topic words, e.g. 'normalization third normal form'")),
                _tool("open_file", "Open a file in its default app.", fl.open_file,
                      which=("string", "number from the last find_files result, or a file name")),
                _tool("read_file",
                      "Read a file's text (pdf, docx, pptx, code, notes) so you can summarise it, answer "
                      "questions about it, or make flashcards.", fl.read_file,
                      which=("string", "number from the last find_files result, or a file name")),
                _tool("open_folder", "Open a folder in the file manager.", fl.open_folder,
                      name=("string", "folder name, e.g. 'school' or 'nscs'")),
                _tool("tidy_downloads", "Sort the Downloads folder into subfolders by type (asks to confirm).",
                      fl.tidy_downloads),
                _tool("undo_tidy_downloads", "Undo the last Downloads tidy.", fl.undo_tidy_downloads),
            ]

        if self.notion:
            nt = self.notion
            tools += [
                # notes & lists (MyNotion)
                _tool("add_note",
                      "Save a note in MyNotion. Without a title it goes into the Inbox note "
                      "(quick thoughts, 'note that…', 'remember to…' for later). With a title it creates/extends that note.",
                      nt.add_note, optional=("title",),
                      text=("string", "the note text, in Lala's words"),
                      title=("string", "only if Lala names a note, e.g. 'Birthdays', 'Trip ideas', or 'today' for "
                                       "today's note")),
                _tool("save_as_note",
                      "ONLY when Lala explicitly asks to save something ('save that', 'put that in my notes'): "
                      "saves your PREVIOUS answer as a MyNotion note. Never call it while answering a question.",
                      nt.save_as_note, optional=("text",),
                      title=("string", "short title for the note"),
                      text=("string", "leave empty to save your previous answer exactly")),
                _tool("restore_note",
                      "Bring back an older version of a MyNotion note, or a deleted note, from the daily backups "
                      "('restore my C# note from yesterday', 'bring back the note I deleted'). Asks Lala first.",
                      nt.restore_note, optional=("day",),
                      title=("string", "the note's title"),
                      day=("string", "which day's version: 'yesterday' (default), 'monday', '5 november'…")),
                _tool("read_note", "Read one MyNotion note or list ALOUD, e.g. 'what's on my shopping list', 'read my packing list'. "
                      "If Lala says OPEN / show / pull up a note, use open_mynotion instead.", nt.read_note,
                      title=("string", "note or list name, e.g. 'shopping list'")),
                _tool("search_notes",
                      "Search Lala's MyNotion notes. Use for questions about Lala's own life or things they wrote down "
                      "(birthdays, plans, passwords hints, exam topics, ideas) before saying you don't know.",
                      self._search_notes, query=("string", "key words, e.g. 'Sara birthday'")),
                _tool("list_notes", "Only for 'which notes do I have': lists note titles. To see what is IN a note or list, use read_note.", nt.list_notes),
                _tool("add_to_list", "Add items to a list note (shopping list, packing list, films to watch…). For tasks or "
                      "anything with a deadline use add_todo.",
                      nt.add_to_list,
                      list_name=("string", "which list, e.g. 'shopping' or 'to-do'"),
                      items=("string", "the items, comma-separated, e.g. 'oat milk, eggs'")),
                _tool("add_todo",
                      "Add ONE to-do (a task Lala has to do), with a due date when they say one: 'I have to finish "
                      "the essay by friday', 'remind me on my to-do list to call the bank', 'hand in the report "
                      "on 20 november'. Use this, not add_to_list, for tasks and anything with a deadline.",
                      nt.add_todo, optional=("due", "list_name"),
                      task=("string", "the task without the date, e.g. 'finish the essay'"),
                      due=("string", "when it's due, as Lala said it: 'friday', 'tomorrow', '20 november'; empty if none"),
                      list_name=("string", "only if Lala names a list other than the to-do list")),
                _tool("set_due", "Change or remove the due date of an existing to-do ('the essay is due monday "
                      "now', 'no deadline for the bank call').", nt.set_due, optional=("due",),
                      item=("string", "the to-do, e.g. 'essay'"),
                      due=("string", "the new date, or 'none' to remove it")),
                _tool("get_due", "What's due / deadlines / overdue to-dos ('what's due this week?', 'do I have "
                      "deadlines?', 'anything overdue?').", nt.get_due, optional=("when",),
                      when=("string", "'this week' (default), 'next week', 'tomorrow', 'friday', 'this month' or 'all'")),
                _tool("remove_from_list", "Delete items from a list entirely (only when Lala says remove/delete; "
                                          "for bought/done use check_off).", nt.remove_from_list,
                      list_name=("string", "which list"), items=("string", "items to remove, comma-separated")),
                _tool("check_off",
                      "Tick items off a checklist when Lala did/bought them ('I paid the rent', 'got the eggs', "
                      "'done with the essay'). Set done=false to untick.",
                      nt.check_off, optional=("list_name", "done"),
                      items=("string", "the item(s), comma-separated"),
                      list_name=("string", "which list, if Lala says it"),
                      done=("boolean", "true = tick (default), false = untick")),
                _tool("clear_list", "Remove everything from a list (asks to confirm).", nt.clear_list,
                      list_name=("string", "which list")),
                # calendar (MyNotion)
                _tool("get_events", "Read Lala's MyNotion calendar (and school hours that day, from WebUntis).",
                      self._events_with_school, optional=("when",),
                      when=("string", "'today', 'tomorrow', 'friday', '12.11.', 'this week', 'next week', "
                                      "'weekend' or 'this month'. Default: this week")),
                _tool("add_event", "Add an event to Lala's MyNotion calendar. Leave time empty for all-day events. "
                      "For things that repeat ('every monday', 'each week', birthdays) set repeat.",
                      nt.add_event, optional=("time", "duration_hours", "repeat"),
                      title=("string", "what, e.g. 'Dentist'"),
                      date=("string", "as Lala said it: 'tomorrow', 'friday', '12.11.', '20 november', "
                                      "or several weekdays in ONE call: 'monday and thursday'"),
                      time=("string", "start time HH:MM, e.g. '15:00'"),
                      duration_hours=("number", "length in hours, default 1"),
                      repeat=("string", "'daily', 'weekly', 'monthly' or 'yearly'; empty for a one-off")),
                _tool("move_event", "Move a calendar event to another day and/or time (asks to confirm).",
                      nt.move_event, optional=("new_date", "new_time", "date"),
                      title=("string", "the event, e.g. 'dentist'"),
                      new_date=("string", "new day, e.g. 'monday'"), new_time=("string", "new start time HH:MM"),
                      date=("string", "its current day, only if needed to tell events apart")),
                _tool("delete_event", "Delete a calendar event (asks to confirm).", nt.delete_event,
                      optional=("date",), title=("string", "the event"), date=("string", "its day, if needed")),
                _tool("open_mynotion",
                      "Open the MyNotion app on screen: the calendar, a specific note/list, or its home page. "
                      "Use for 'open my calendar', 'show me my shopping list', 'open MyNotion'.",
                      nt.open_mynotion, optional=("what",),
                      what=("string", "'calendar', a note or list name like 'shopping list', or empty for home")),
                _tool("daily_briefing", "Lala's day at a glance: today's and upcoming events, reminders, inbox. "
                                        "Use for 'what's my day like', 'brief me', 'what's coming up'.",
                      lambda: nt.daily_briefing(self.reminders)),
            ]

        if self.vision:
            tools.append(_tool(
                "look", "Use the camera to see who or what is in front of you.",
                self.vision.describe_current_frame,
            ))

        if self.spotify:
            sp = self.spotify
            tools += [
                _tool("play_song", "Play a specific song by title.",
                      sp.play_song, query=("string", "song title, optionally with artist")),
                _tool("play_artist", "Play top tracks by an artist. Use for any request naming an artist.",
                      sp.play_artist, artist=("string", "artist name")),
                _tool("play_playlist", "Search for and play a playlist.",
                      sp.play_playlist, query=("string", "playlist name")),
                _tool("play_genre", "Play music from a genre. Use genre 'pop' for vague requests like 'play something'.",
                      sp.play_genre, genre=("string", "genre name")),
                _tool("pause_music", "Pause Spotify.", lambda: sp.pause() or "Paused."),
                _tool("skip_track", "Skip to the next track.", lambda: sp.skip() or "Skipped."),
                _tool("previous_track", "Go back to the previous track.", lambda: sp.previous() or "Going back."),
                _tool("now_playing", "Say what's currently playing.", sp.now_playing),
                _tool("set_music_volume", "Set Spotify volume.",
                      lambda volume: sp.set_volume(int(volume)), volume=("integer", "0-100")),
            ]

        if self.arduino:
            ar = self.arduino
            tools += [
                _tool("set_led_color", "Set the desk LED strip color.",
                      lambda r, g, b: _ok(ar.set_rgb(int(r), int(g), int(b)), "Color set."),
                      r=("integer", "0-255"), g=("integer", "0-255"), b=("integer", "0-255")),
                _tool("set_led_effect", "Set the LED effect.",
                      lambda effect: _ok(ar.set_effect(effect), f"Effect set to {effect}."),
                      effect=("string", "one of: solid, breathe, pulse, flicker")),
                _tool("set_led_brightness", "Set LED brightness.",
                      lambda value: _ok(ar.set_brightness(int(value)), f"Brightness set to {value}."),
                      value=("integer", "0-255")),
                _tool("led_off", "Turn the LEDs off.", lambda: _ok(ar.off(), "LEDs off.")),
            ]

        if self.ha:
            tools += [
                _tool("notify_phone", "Send a push notification to Lala's phone (e.g. 'text me', 'remind me').",
                      self._notify_phone, message=("string", "notification text")),
                _tool("check_phone_battery", "Check phone battery level and charging state.",
                      self._check_phone_battery),
                _tool("check_phone_location", "Check whether Lala's phone is home or away.",
                      self._check_phone_location),
                _tool("turn_on_tv", "Turn the TV on.",
                      lambda: "Turned the TV on." if self.ha.turn_on_tv() else "Couldn't reach the TV."),
                _tool("turn_off_tv", "Turn the TV off.",
                      lambda: "Turned the TV off." if self.ha.turn_off_tv() else "Couldn't reach the TV."),
                _tool("set_tv_volume", "Set TV volume.",
                      lambda level: _ok(self.ha.set_tv_volume(float(level) / 100), f"TV volume set to {level}.", "Couldn't reach the TV."),
                      level=("integer", "0-100")),
            ]

        if self.memory_note:
            mn = self.memory_note
            tools += [
                _tool("what_you_know_about_me", "What Aria has saved about Lala (facts from past conversations). "
                      "For 'what do you know about me?' / 'what do you remember about me?'.", mn.what_you_know),
                _tool("remember_about_me", "Save a lasting fact about Lala when they ask you to remember it "
                      "('remember that I'm vegetarian'). Not for reminders at a time (set_reminder) or notes (add_note).",
                      mn.remember, fact=("string", "the fact, short, e.g. 'Is vegetarian'")),
                _tool("clean_up_memory", "Go through everything saved about Lala and suggest forgetting what isn't a "
                      "real lasting fact ('clean up your memory'). Lala confirms with yes/no.", mn.clean_up),
                _tool("forget_about_me", "Forget something saved about Lala ('forget that I study C#', "
                      "'forget everything about me').", mn.forget,
                      what=("string", "what to forget, in a few words, or 'everything'")),
            ]

        if self.health:
            tools.append(_tool("system_check", "Check that all of Aria's parts work (models, MyNotion, Spotify, camera, "
                               "microphone, weather, search) — 'are your systems okay?', 'why can't you see my "
                               "screen?', 'is everything working?'.", self.health.report))

        if self.recall:
            tools += [
                _tool("recall_conversation", "What you and Lala talked about on a day ('what did we talk about "
                      "yesterday?', '…on monday').", self.recall.conversations_on, optional=("day",),
                      day=("string", "'today', 'yesterday', a weekday or a date")),
                _tool("search_conversations", "Find when something came up in your conversations ('when did I "
                      "mention the exam?', 'what did I say about Lina?').", self.recall.search,
                      query=("string", "the key words")),
            ]

        if self.undo:
            def undo():
                # an email still in its 10-second wait is the most recent thing to take back
                stopped = self.mail.cancel_send() if self.mail else None
                return stopped or self.undo.undo()
            tools.append(_tool("undo_last", "Undo Aria's last change to notes, lists, the calendar or reminders, "
                               "or stop an email that's about to go out ('undo that', 'don't send it').", undo))

        if self.weather:
            tools += [
                _tool("get_weather", "Weather now, today, tomorrow or the day after ('do I need a jacket?', "
                      "'will it rain tomorrow?', 'weather in Berlin').", self.weather.get_weather,
                      optional=("when", "city"), when=("string", "'now', 'today', 'tomorrow' or 'day after tomorrow'"),
                      city=("string", "only if Lala names another city")),
                _tool("set_home_city", "Remember which city Lala lives in, for the weather ('I live in Vienna').",
                      self.weather.set_home_city, city=("string", "city name")),
            ]

        if self.activity:
            tools.append(_tool("screen_time", "How long Lala has used the laptop today and in which apps, and how long "
                               "since their last break ('how long have I been coding?', 'what did I do today?').",
                               self.activity.screen_time))

        return tools

    def _events_with_school(self, when: str = "this week"):
        """The calendar, plus the school hours for a single day ("what do I have tomorrow?")."""
        events = self.notion.get_events(when)
        school = self.untis.day_line(when) if self.untis else ""
        return f"{events} {school}" if school else events

    def _search_notes(self, query: str):
        """Notes first; if nothing's there, documents that mention it (people say 'document' for both)."""
        result = self.notion.search_notes(query)
        if result.startswith("Nothing in your notes") and self.files:
            inside = self.files.search_contents(query)
            if inside.startswith("Documents that mention"):
                return result + " But in your files: " + inside
        return result

    # ── Handlers ──────────────────────────────────────────────────────────────

    def web_search(self, query: str):
        if not hasattr(self, "_web"):
            from Engines.WebSearch import WebSearch
            self._web = WebSearch()
        return self._web.search(query)

    def _notify_phone(self, message: str):
        return "Sent to your phone." if self.ha.notify_phone(message) else "Couldn't reach your phone."

    def _check_phone_battery(self):
        level = self.ha.get_phone_battery()
        if level is None:
            return "Couldn't read phone battery."
        status = "charging" if self.ha.is_phone_charging() else "not charging"
        return f"Phone is at {level}% and {status}."

    def _check_phone_location(self):
        loc = self.ha.get_phone_location()
        if not loc:
            return "Couldn't read phone location."
        zone = loc["zone"]
        if zone == "home":
            return "Your phone is home."
        if zone == "not_home":
            return "Your phone is away from home."
        return f"Your phone is at {zone}."
