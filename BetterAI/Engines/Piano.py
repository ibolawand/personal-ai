"""Aria plays the piano on her avatar while piano music plays on Spotify ("play some piano music", "play a piano
playlist", "spiel Klaviermusik"). Decided in code from the Spotify tool she just used, never by the model:

  - a play tool (song, artist, playlist, genre) with "piano" / "klavier" in what was asked or in what it answered
    ("Playing piano music", "Playing playlist 'Peaceful Piano'") → on
  - any other play tool → off (different music), and pause → off: `pause_music`, or `media_control` stopping or
    pausing (the model used that for "stop it", and her keyboard kept going)
  - while she plays, a short "stop it" / "pause" / "enough" → off, even when the model called no tool
  - while on, Spotify is checked every 30 s; once nothing has been playing for two checks in a row, or after
    MAX_S, she stops.
"""
import re
import threading
import time

PLAY_TOOLS = {"play_song", "play_artist", "play_playlist", "play_genre"}
PIANO_RE = re.compile(r"\b(piano|klavier|pianist)", re.I)
HALT_RE = re.compile(r"\b(paus\w*|stop\w*|halt)\b", re.I)
# a short command to stop, while she plays ("stop it", "stop the piano", "pause", "enough", "hör auf")
STOP_SAID_RE = re.compile(r"^\W*(?:(?:hey|aria|please|ok(?:ay)?)\W+)*(?:stop|pause|enough|halt|quiet|shh+|hör auf|stopp)\b"
                          r"(?:[\s\w']{0,30})[.!]*$", re.I)
CHECK_S = 30
MAX_S = 90 * 60


def wanted(used, user_input="") -> bool | None:
    """True / False when this turn's music tools say she should (not) play, None when it played no music."""
    say = None
    for name, args in used or ():
        if name in PLAY_TOOLS:
            # (a turn keeps what the tool answered, "Playing piano music", as text; a dict of arguments works too)
            shown = " ".join(str(v) for v in args.values()) if isinstance(args, dict) else str(args or "")
            words = f"{user_input or ''} {shown}"
            say = bool(PIANO_RE.search(words))
        elif name == "pause_music":
            say = False
        elif name == "media_control":
            shown = " ".join(str(v) for v in args.values()) if isinstance(args, dict) else str(args or "")
            if HALT_RE.search(f"{user_input or ''} {shown}"):
                say = False
    return say


class PianoMode:
    """Turns her keyboard on and off (`show(bool)`, the UI's set_piano) and watches Spotify while it's on."""

    def __init__(self, show, is_playing, clock=time.monotonic, sleep=time.sleep):
        self.show, self.is_playing, self.clock, self.sleep = show, is_playing, clock, sleep
        self.on = False
        self._run = 0                     # each start gets a number: an older watcher stops when it sees a newer one

    def update(self, used, user_input=""):
        say = wanted(used, user_input)
        if say is None and self.on and STOP_SAID_RE.match(user_input or ""):
            say = False                   # "stop it" while she plays, whatever the model did with it
        if say is True:
            self.start()
        elif say is False:
            self.stop()

    def start(self):
        self.on = True
        self._run += 1
        self.show(True)
        threading.Thread(target=self._watch, args=(self._run,), daemon=True).start()

    def stop(self):
        if self.on:
            self.on = False
            self._run += 1
            self.show(False)

    def _watch(self, run):
        started, quiet = self.clock(), 0
        while run == self._run and self.on:
            self.sleep(CHECK_S)
            if run != self._run or not self.on:
                return
            try:
                quiet = 0 if self.is_playing() else quiet + 1
            except Exception:
                quiet += 1
            if quiet >= 2 or self.clock() - started > MAX_S:
                self.stop()
                return
