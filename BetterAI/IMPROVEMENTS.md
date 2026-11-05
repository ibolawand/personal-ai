# Autonomous improvements

A log of the improvements I made on my own, one at a time: each one built, tested (`pytest` plus a check with the
real model where it matters) and committed separately. The full feature overview is in [FEATURES.md](FEATURES.md).

| # | Improvement | What it does | Tests |
|---|---|---|---|
| 1 | **Weather** | "Do I need a jacket tomorrow?", "weather in Berlin", "I live in Vienna"; one line in the morning briefing. Open-Meteo, no API key. Clothing advice is decided in code, because the model called 3–9 °C "mild, no jacket needed". | `tests/test_weather.py` |
| 2 | **Undo** | "Undo that" takes back Aria's last change to notes, lists, events or reminders, also confirmed deletes. Snapshot before/after each change, so it puts back exactly what changed. | `tests/test_undo.py` |
| 3 | **Calendar clash warnings** | Adding or moving an event that overlaps another one: "Heads up: that overlaps with Meeting at 15:00." | `tests/test_notion.py` |
