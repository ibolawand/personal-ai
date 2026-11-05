"""
Confirmation gate for risky actions (closing apps, suspend, moving files...).

A tool calls confirmer.request("close Chrome", fn) instead of acting. Aria asks,
and the user's next message is checked *in code* (not by the LLM) for yes/no,
so a misheard or hallucinated "yes" can't trigger anything.
"""

import re
import time

YES_RE = re.compile(r"^\s*(yes|yeah|yep|yup|sure|do it|go ahead|confirm|confirmed|ok|okay|please do|yes please)\b", re.I)
NO_RE = re.compile(r"^\s*(no|nope|cancel|stop|don'?t|never ?mind|wait)\b", re.I)
EXPIRE_SECONDS = 90


class Confirmer:
    def __init__(self):
        self.pending = None  # (description, fn, timestamp)
        self.on_change = None  # set by Aria: called with the question, or None once it's answered/dropped

    def _notify(self, description):
        if self.on_change:
            try:
                self.on_change(description)
            except Exception as e:
                print(f"[Confirm] card failed: {e}")

    def request(self, description: str, fn) -> str:
        self.pending = (description, fn, time.time())
        self._notify(description)
        return (f"NEEDS CONFIRMATION: {description}. Ask Lala to confirm with yes or no. "
                f"It has NOT been done yet — do not say it's done.")

    def resolve(self, user_text: str):
        """Returns the action result / cancel message if this message answered a pending
        confirmation, otherwise None (and drops the pending action if they moved on)."""
        if not self.pending:
            return None
        description, fn, ts = self.pending
        self._notify(None)
        if time.time() - ts > EXPIRE_SECONDS:
            self.pending = None
            return None
        if YES_RE.match(user_text):
            self.pending = None
            try:
                result = fn()
                return str(result) if result is not None else "Done."
            except Exception as e:
                return f"That failed: {e}"
        self.pending = None
        if NO_RE.match(user_text):
            return "Okay, cancelled."
        return None  # they changed the subject — treat as a normal message
