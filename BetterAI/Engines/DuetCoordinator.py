"""Conversation choreography and scheduling for Aria/Claude duets.

Kept separate from the main turn handler; methods use Aria's UI and conversation services.
"""
import random
import time

from Engines import Diagnostics, Duet, VoiceStyle, Desk


class DuetCoordinatorMixin:
    def _duet(self, user_input):
        """A few rounds of Claude and Aria talking, with Lala jumping in when she likes. Claude is sent only the
        topic and this conversation's lines (Duet.claude_prompt)."""
        big = getattr(self, "big", None)
        if not big or not big.available:
            self.speak("Claude can't join right now, I can't reach him.")
            return
        subject, how = Duet.topic(user_input), Duet.mode(user_input)
        print(f"[Duet] {how}: {subject}")
        self.ui.claude("enter")
        try:
            self._duet_rounds(user_input, subject, how, big)
        finally:
            self.ui.claude("leave")

    def _duet_rounds(self, user_input, subject, how, big):
        lines, stopped, mine = [("Lala", user_input)], False, None
        for turn in range(Duet.MAX_ROUNDS):
            self.ui.set_state("thinking")
            said = Duet.clean_line(big.ask(Duet.claude_prompt(subject, how, lines), "duet", system=Duet.CLAUDE_SYSTEM))
            if not said:
                self.speak("Hm, Claude went quiet." if turn else "Claude isn't answering right now, sorry.")
                return
            lines.append(("Claude", said))
            self._say_as("claude", said)
            stopped = self._duet_heard(lines)
            if stopped:
                break
            mine = self._aria_line(subject, how, lines)
            stopped = self._duet_heard(lines)
            if stopped:
                break
        if stopped:
            mine = "Okay, back to just us."
            self._say_as("aria", mine)
        elif how == "ideas":
            wrap = Duet.clean_line(self._tidy_reply(self.llm.chat(Duet.summary_prompt(subject, lines), [],
                                                            self._base_prompt()) or ""))
            if wrap:
                mine = wrap
                self._say_as("aria", wrap)
        # into her history, so "what did Claude say?" or "the second idea" has context
        self.remember_said(f"(Claude and I just talked with you about {subject}.) " + (mine or ""))

    def _aria_line(self, subject, how, lines, quiet=False, cancel=None):
        """Her next line in a duet, said (or shown) and added to `lines`; None when the model gave nothing usable."""
        self.ui.set_state("thinking")
        mine = Duet.clean_line(self._tidy_reply(self.llm.chat(Duet.aria_prompt(subject, how, lines), [],
                                                        self._base_prompt()) or ""))
        if cancel and cancel():
            return None
        if mine:
            lines.append(("Aria", mine))
            self._say_as("aria", mine, quiet)
        return mine

    def _chat_loop(self):
        """Now and then, at a random time, she and Claude chat by themselves (Engines/Duet.py)."""
        rand = random.random
        while not getattr(self, "_shutting_down", False):
            deadline = time.monotonic() + Duet.next_chat_in(rand)
            while time.monotonic() < deadline:
                if getattr(self, "_shutting_down", False):
                    return
                time.sleep(min(1, max(0, deadline - time.monotonic())))
            try:
                self._chat_with_claude()
            except Exception as e:
                print(f"[Duet] their chat failed: {type(e).__name__}: {e}")
                Diagnostics.problem("duet", f"{type(e).__name__}: {e}")

    def _chat_with_claude(self):
        """A short chat of their own on a light topic, with Haiku. Never over a conversation with Lala: not while
        she's awake, a turn is running or Lala is typing; it stops as soon as Lala types or wakes her. Spoken only
        when Lala talked to her in the last 10 minutes, otherwise bubbles and their figures. Claude gets the topic
        and their lines, nothing about Lala."""
        big = getattr(self, "big", None)
        if not big or not big.available or self._background_chat_cancelled():
            return False
        lock = self._turn_lock()
        if not lock.acquire(blocking=False):
            return False
        lock.release()
        recent = getattr(self, "_chat_topics", [])
        subject = Duet.random_topic(random.random, recent)
        self._chat_topics = (recent + [subject])[-6:]
        quiet = time.time() - getattr(self, "last_talked", 0) > 600
        before = getattr(self, "_ui_state", None)
        print(f"[Duet] chatting with Claude about {subject}{' (quietly)' if quiet else ''}")
        self.ui.set_state("idle")
        self.ui.claude("enter")
        lines, mine = [], None
        try:
            for _ in range(Duet.CHAT_ROUNDS):
                said = Duet.clean_line(big.ask(Duet.claude_prompt(subject, "fun", lines), "duet chat",
                                               system=Duet.CLAUDE_SYSTEM, model=Duet.CHAT_MODEL,
                                               cancel=self._background_chat_cancelled))
                if not said or self._background_chat_cancelled():
                    break
                lines.append(("Claude", said))
                self._say_as("claude", said, quiet)
                if self._background_chat_cancelled():
                    break
                mine = self._aria_line(subject, "fun", lines, quiet,
                                       cancel=self._background_chat_cancelled) or mine
                if self._background_chat_cancelled():
                    break
        finally:
            self.ui.claude("leave")
            if not self.awake:
                self.ui.set_state(before if before in ("sleeping", "companion") else "sleeping")
        if lines:
            self.remember_said(f"(Claude and I chatted about {subject}.) " + (mine or ""))
        return bool(lines)

    def _background_chat_cancelled(self):
        return (self._woken() or getattr(self, "_shutting_down", False)
                or not getattr(self, "autonomous_chats", True)
                or not getattr(getattr(self, "big", None), "enabled", True)
                or Desk.in_quiet_hours())

    def _woken(self) -> bool:
        """Lala typed something or woke her: a chat of their own gives way at once."""
        wake = getattr(self, "_wake_event", None)
        return self._lala_busy() or bool(wake and wake.is_set()) or bool(self.awake)

    def _say_as(self, who, text, quiet=False):
        """A duet line: a bubble in the speaker's colour and, with the voice on (and not `quiet`), the speaker's own
        voice. While Claude talks she listens (her mouth stays still)."""
        print(f"{'Claude' if who == 'claude' else 'Aria'}: {text}")
        self.ui.message(who, text)
        if who == "claude":
            self.ui.claude("talk", VoiceStyle.emotion(text))
        else:
            self.ui.claude("listen")
        self.ui.set_state("listening" if who == "claude" else "speaking")
        if self.voice and not self.muted and not quiet:
            self.voice.speak(text, speaker=who)
        else:
            time.sleep(min(5.0, 1.0 + len(text) / 30))     # time to read before the next bubble
        if who == "claude":
            self.ui.claude("listen")

    def _duet_heard(self, lines) -> bool:
        """What Lala typed or said since the last line joins the conversation. True when it ends it."""
        heard = []
        inputs = getattr(self, "text_inputs", None)
        while inputs is not None and not inputs.empty():
            heard.append(inputs.get())
        if not heard and self._uses_mic():
            self.ui.set_state("listening")
            said = self.stt.listen(start_timeout=1.5)
            if said:
                heard.append(said)
        for text in heard:
            self.ui.message("user", text)
            if Duet.wants_stop(text):
                return True
            lines.append(("Lala", text))
        return False

