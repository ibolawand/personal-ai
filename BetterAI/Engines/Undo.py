"""
"Undo that" for Aria's changes to MyNotion (notes, lists, events) and reminders.

Before a changing action runs, the notes, events and pending reminders are snapshotted; afterwards the
difference is kept. Undo puts back exactly that difference: new rows are removed, changed notes get their
old text back, deleted notes/events come back with their old id, new reminders are cancelled and
cancelled ones re-added. Only the last change can be undone, and only for UNDO_FOR_S.
"""

import time

UNDO_FOR_S = 15 * 60


class Undo:
    def __init__(self, notion=None, reminders=None):
        self.notion = notion
        self.reminders = reminders
        self.last = None            # {"label", "at", "notes": (before, after), "events": ..., "reminders": ...}

    # ── snapshots ──

    def _snapshot(self):
        snap = {"notes": {}, "events": {}, "reminders": {}}
        if self.notion:
            with self.notion._conn() as c:
                snap["notes"] = {r["id"]: dict(r) for r in c.execute("SELECT * FROM notes")}
                snap["events"] = {r["id"]: dict(r) for r in c.execute("SELECT * FROM EVENTS")}
        if self.reminders:
            snap["reminders"] = {r["id"]: r for r in self.reminders.pending(("reminder", "timer"))}
        return snap

    def around(self, label, fn):
        """Run fn() and remember how to undo whatever it changed. label: text, or fn(result) -> text."""
        try:
            before = self._snapshot()
        except Exception as e:
            print(f"[Undo] snapshot failed: {e}")
            return fn()
        result = fn()
        try:
            after = self._snapshot()
            if any(before[k] != after[k] for k in before):
                text = label(result) if callable(label) else label
                self.last = {"label": text, "at": time.time(), "before": before, "after": after}
        except Exception as e:
            print(f"[Undo] snapshot failed: {e}")
        return result

    # ── tool ──

    def undo(self):
        last = self.last
        if not last or time.time() - last["at"] > UNDO_FOR_S:
            return "There's nothing I can undo right now."
        before, after = last["before"], last["after"]
        if self.notion:
            with self.notion._conn() as c:
                self._restore(c, "notes", before["notes"], after["notes"])
                self._restore(c, "EVENTS", before["events"], after["events"])
        if self.reminders:
            for rid in after["reminders"].keys() - before["reminders"].keys():
                self.reminders.cancel_id(rid)
            for rid in before["reminders"].keys() - after["reminders"].keys():
                r = before["reminders"][rid]
                if r["due"] > time.time():
                    self.reminders.add(r["text"], r["kind"], r["due"], r.get("repeat"))
        self.last = None
        return f"Undone: {last['label']}"

    @staticmethod
    def _restore(c, table, before, after):
        for rid in after.keys() - before.keys():                     # created -> remove
            c.execute(f"DELETE FROM {table} WHERE id = ?", (rid,))
        for rid in before.keys() - after.keys():                     # deleted -> bring back
            row = before[rid]
            cols = ", ".join(row)
            c.execute(f"INSERT INTO {table} ({cols}) VALUES ({', '.join('?' * len(row))})", tuple(row.values()))
        for rid in before.keys() & after.keys():                     # changed -> old version
            if before[rid] != after[rid]:
                row = before[rid]
                sets = ", ".join(f"{k} = ?" for k in row if k != "id")
                c.execute(f"UPDATE {table} SET {sets} WHERE id = ?",
                          tuple(v for k, v in row.items() if k != "id") + (rid,))
