"""
Heavy text work goes to a bigger model: Claude, through the Claude Code program already signed in on this laptop
(`claude -p`, so it runs on Lala's subscription and needs no API key).

Which tasks go there is decided in code, never by the small model: organising and rewriting notes, the study
buttons and "Explain" in MyNotion, quiz questions, and anything asked with "ask the big model …" / "frag die große
KI …". Everything else stays on the laptop, and so do mail, Telegram, the calendar, Aria's memory and the camera.

Claude gets the text of that one task and gives text back. It is started with no tools, no settings, no MCP
servers and in an empty folder, so it can't read or change a file. Each call is logged (what for, how much, how
long) in ~/.cache/aria/big_model.log. When it can't be reached, the caller gets None and uses the local model.

Engines/.env:  ARIA_BIG_MODEL=0 turns it off · ARIA_BIG_MODEL_NAME (default "sonnet") · ARIA_BIG_CMD (path of claude)
"""

import glob
import json
import os
import re
import shutil
import subprocess
import threading
import time

MARK = "(via Claude)"            # ends every reply the big model helped with
TIMEOUT_S = 120
RETRY_AFTER_S = 120              # after a failure (offline, limit reached) the local model answers for a while
SYSTEM = ("You do one text task for Aria, a student's desk assistant. Reply with the result only: no greeting, no "
          "comment about the task, no offer to do more. You have no tools and no files.")
# "ask the big model why …" / "frag die große KI, was …": the rest of the message is the question
ASK_RE = re.compile(r"^\s*(?:aria,?\s*)?(?:please\s+|bitte\s+)?(?:ask|frag(?:e)?)\s+(?:mal\s+)?(?:the\s+|die\s+)?"
                    r"(?:big(?:ger)?\s+(?:model|ai)|gro(?:ß|ss)e\s+ki|claude)\b\s*[,:]?\s*(.+)$", re.I | re.S)
CHAT_SYSTEM = ("You answer a question for Lala, a student, through their desk assistant Aria. Answer in the "
               "language of the question, clearly and to the point, in plain text (short lists with '- ' are fine, "
               "formulas as $…$). You have no tools and no files.")


def _log_file():
    return os.path.join(os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")), "aria", "big_model.log")


def find_command():
    """Where the claude program is. Aria started from the menu doesn't have nvm's folder on its PATH."""
    named = os.environ.get("ARIA_BIG_CMD", "").strip()
    if named:
        return named if os.path.isfile(os.path.expanduser(named)) else None
    found = shutil.which("claude")
    if found:
        return found
    for pattern in ("~/.nvm/versions/node/*/bin/claude", "~/.local/bin/claude", "~/.claude/local/claude"):
        hits = sorted(glob.glob(os.path.expanduser(pattern)))
        if hits:
            return hits[-1]
    return None


def wanted(text: str):
    """The question in "ask the big model …", or None when the message isn't one."""
    m = ASK_RE.match(text or "")
    return m.group(1).strip() if m else None


class BigModel:
    """`ask(prompt) -> text or None`. `run` is subprocess.run (replaced in tests)."""

    def __init__(self, command=None, model=None, run=None, enabled=None):
        self.enabled = os.environ.get("ARIA_BIG_MODEL", "1") != "0" if enabled is None else enabled
        self.command = command or (find_command() if self.enabled else None)
        self.model = model or os.environ.get("ARIA_BIG_MODEL_NAME", "sonnet")
        self.run = run or subprocess.run
        self.calls = 0                  # answered calls; a turn that raised it gets MARK (see marked())
        self._down_until = 0.0
        self._lock = threading.Lock()

    @property
    def available(self) -> bool:
        return bool(self.enabled and self.command and time.time() >= self._down_until)

    def ask(self, prompt: str, label: str = "task", system: str = SYSTEM):
        """Claude's answer to this text, or None (off, not installed, offline, limit reached, empty answer)."""
        if not self.available or not (prompt or "").strip():
            return None
        started = time.time()
        text, why = self._call(prompt, system)
        took = round(time.time() - started, 1)
        if text:
            with self._lock:
                self.calls += 1
        else:
            self._down_until = time.time() + RETRY_AFTER_S
            print(f"[Big model] no answer ({why}); the local model takes over")
        self._log(label, prompt, took, why)
        return text or None

    def _call(self, prompt, system):
        folder = os.path.join(os.path.dirname(_log_file()), "big_model_cwd")      # empty: nothing to read in it
        env = {k: v for k, v in os.environ.items() if not k.startswith(("ANTHROPIC_", "CLAUDECODE", "CLAUDE_CODE_"))}   # → the subscription, not an API key
        env["PATH"] = os.path.dirname(self.command) + os.pathsep + env.get("PATH", "")
        args = [self.command, "-p", "--model", self.model, "--tools", "", "--strict-mcp-config",
                "--setting-sources", "", "--no-session-persistence", "--disable-slash-commands",
                "--system-prompt", system, "--output-format", "json"]
        try:
            os.makedirs(folder, exist_ok=True)
            done = self.run(args, input=prompt, capture_output=True, text=True, timeout=TIMEOUT_S, cwd=folder, env=env)
        except subprocess.TimeoutExpired:
            return "", "timeout"
        except Exception as e:
            return "", f"{type(e).__name__}: {e}"
        try:
            data = json.loads(done.stdout or "")
        except ValueError:
            return "", f"exit {done.returncode}: {(done.stderr or done.stdout or '').strip()[:200]}"
        if done.returncode or data.get("is_error") or not isinstance(data.get("result"), str):
            return "", str(data.get("result") or data.get("subtype") or f"exit {done.returncode}")[:200]
        return data["result"].strip(), ""

    def _log(self, label, prompt, took, why):
        try:
            path = _log_file()
            os.makedirs(os.path.dirname(path), exist_ok=True)
            start = " ".join(prompt.split())[:160]
            with open(path, "a") as f:
                f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {label}  {len(prompt)} chars sent  {took}s  "
                        f"{'FAILED: ' + why if why else 'ok'}  | {start}\n")
        except OSError:
            pass

    def or_local(self, local, label="note"):
        """An `ask(prompt, history=(), temperature=…)` like NoteWriter's: Claude first, the local model otherwise."""
        def ask(prompt, history=(), temperature=0.3):
            said = [f"{'You' if m['role'] == 'assistant' else 'Request'}:\n{m['content']}" for m in history]
            text = self.ask("\n\n".join(said + [prompt]) if said else prompt, label)
            return text if text else local(prompt, history=history, temperature=temperature)
        return ask

    def marked(self, reply: str, calls_before: int) -> str:
        """The reply, ending in MARK when the big model answered since `calls_before`."""
        if self.calls > calls_before and reply and MARK not in reply:
            return f"{reply.rstrip()}\n\n{MARK}"
        return reply
