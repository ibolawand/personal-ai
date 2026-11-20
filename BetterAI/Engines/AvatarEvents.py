"""Small visual acknowledgements, selected from completed tool results, never model prose."""

SUCCESS = {
    "set_timer": (("Timer set for ",), "timerSaved"),
    "set_reminder": (("I'll remind you to ",), "timerSaved"),
    "add_note": (("Added to ", "Created the note ", "Noted —"), "noteSaved"),
    "save_as_note": (("Added to ", "Created the note "), "noteSaved"),
    "add_to_list": (("Added ",), "taskDone"),
    "add_todo": (("Added ",), "taskDone"),
    "check_off": (("Ticked off ",), "taskDone"),
}


def action_for(name, result):
    prefixes, action = SUCCESS.get(name, ((), None))
    return action if isinstance(result, str) and result.startswith(prefixes) else None


def focus_scene(timers, now):
    """Expired/paused blocks do not leave a desk behind. Work wins during a block handover."""
    active = {item.get("kind") for item in timers if item.get("kind") in ("focus", "focusbreak")
              and isinstance(item.get("due"), (int, float)) and item["due"] > now}
    return "work" if "focus" in active else "break" if "focusbreak" in active else "off"
