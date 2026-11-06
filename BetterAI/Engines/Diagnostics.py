"""
A log of how fast Aria answers and of what went wrong, so fixes are based on what really happens.

Kept in ~/.cache/aria/diagnostics.jsonl (one JSON object per line, the last MAX_LINES kept), never sent anywhere.

  timing  — per spoken turn: the silence wait that ends your sentence, transcription, the model's first sentence,
            and when her voice starts. "starts_after" is from the moment you stopped talking.
  problem — misheard (she had to ask "did you say…?"), woke_for_nothing (woke up, nobody said anything),
            corrected (you said "no, I said…" / "that's wrong"), claimed_no_tool, missing_tool, rewritten,
            empty_reply, tool_error, crash.

    ./aria.sh --report            the last 7 days
    python -m Engines.Diagnostics 30
"""

import json
import os
import statistics
import sys
import threading
import time
from collections import Counter

LOG_FILE = os.path.join(os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")), "aria", "diagnostics.jsonl")
MAX_LINES = 5000

PROBLEM_NAMES = {
    "misheard": "unsure what you said (asked 'did you say…?')",
    "woke_for_nothing": "woke up but nobody said anything",
    "corrected": "you corrected her",
    "claimed_no_tool": "said she did something without doing it (retried)",
    "missing_tool": "said she can't, retried with all tools",
    "rewritten": "stock or repeated reply, rewritten",
    "empty_reply": "the model said nothing",
    "tool_error": "a tool failed",
    "crash": "something crashed",
}

_lock = threading.Lock()


def _write(entry: dict):
    entry = {"at": round(time.time(), 1), **entry}
    try:
        with _lock:
            os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
            with open(LOG_FILE, "a") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            if os.path.getsize(LOG_FILE) > MAX_LINES * 400:          # trim now and then
                with open(LOG_FILE) as f:
                    lines = f.readlines()[-MAX_LINES:]
                with open(LOG_FILE, "w") as f:
                    f.writelines(lines)
    except OSError:
        pass


def timing(**parts):
    """parts in seconds: silence_wait, transcribe, first_sentence, first_audio (the last two from the turn start)."""
    t = {k: round(v, 2) for k, v in parts.items() if isinstance(v, (int, float))}
    if "first_audio" in t:
        t["starts_after"] = round(t.get("silence_wait", 0) + t.get("transcribe", 0) + t["first_audio"], 2)
    _write({"type": "timing", **t, **{k: v for k, v in parts.items() if not isinstance(v, (int, float))}})


def problem(kind: str, detail: str = "", **extra):
    _write({"type": "problem", "kind": kind, "detail": (detail or "")[:300], **extra})


def read(days=7):
    since = time.time() - days * 86400
    out = []
    try:
        with open(LOG_FILE) as f:
            for line in f:
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if e.get("at", 0) >= since:
                    out.append(e)
    except OSError:
        pass
    return out


def _fmt(values):
    if not values:
        return "–"
    values = sorted(values)
    p90 = values[min(len(values) - 1, int(len(values) * 0.9))]
    return f"{statistics.median(values):.1f} s typical, {p90:.1f} s slow"


def report(days=7) -> str:
    entries = read(days)
    times = [e for e in entries if e["type"] == "timing"]
    probs = [e for e in entries if e["type"] == "problem"]
    lines = [f"Aria, the last {days} days: {len(times)} spoken replies, {len(probs)} problems."]
    if times:
        lines.append("")
        lines.append("Speed (from when you stop talking):")
        lines.append(f"  her voice starts   {_fmt([t['starts_after'] for t in times if 'starts_after' in t])}")
        lines.append(f"  silence wait       {_fmt([t['silence_wait'] for t in times if 'silence_wait' in t])}")
        lines.append(f"  understanding you  {_fmt([t['transcribe'] for t in times if 'transcribe' in t])}")
        lines.append(f"  first sentence     {_fmt([t['first_sentence'] for t in times if 'first_sentence' in t])}")
        slow = sorted((t for t in times if t.get("starts_after")), key=lambda t: -t["starts_after"])[:3]
        if slow:
            lines.append("  slowest: " + "; ".join(
                f"{t['starts_after']:.1f} s ({', '.join(t.get('tools') or []) or 'no tools'})" for t in slow))
    if probs:
        lines.append("")
        lines.append("Problems:")
        for kind, n in Counter(p["kind"] for p in probs).most_common():
            lines.append(f"  {n:3}× {PROBLEM_NAMES.get(kind, kind)}")
        lines.append("")
        lines.append("Latest:")
        for p in probs[-10:]:
            when = time.strftime("%a %H:%M", time.localtime(p["at"]))
            lines.append(f"  {when}  {p['kind']}: {p.get('detail', '')}")
    return "\n".join(lines)


if __name__ == "__main__":
    print(report(int(sys.argv[1]) if len(sys.argv) > 1 else 7))
