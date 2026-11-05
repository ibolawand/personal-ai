# Autonomous improvements

A log of the improvements I made on my own, one at a time: each one built, tested (`pytest` plus a check with the
real model where it matters) and committed separately. The full feature overview is in [FEATURES.md](FEATURES.md).

| # | Improvement | What it does | Tests |
|---|---|---|---|
| 1 | **Weather** | "Do I need a jacket tomorrow?", "weather in Berlin", "I live in Vienna"; one line in the morning briefing. Open-Meteo, no API key. Clothing advice is decided in code, because the model called 3–9 °C "mild, no jacket needed". | `tests/test_weather.py` |
| 2 | **Undo** | "Undo that" takes back Aria's last change to notes, lists, events or reminders, also confirmed deletes. Snapshot before/after each change, so it puts back exactly what changed. | `tests/test_undo.py` |
| 3 | **Calendar clash warnings** | Adding or moving an event that overlaps another one: "Heads up: that overlaps with Meeting at 15:00." | `tests/test_notion.py` |
| 4 | **Calculator, bill splitter, unit converter** | Exact maths instead of guesses. The model first split a bill wrong (tip only, 4.37 each), so bill splitting got its own tool with the formula in code (33.50 each). Safe parser, no `eval`. | `tests/test_calc.py` |
| 5 | **Reminder card** | A reminder or timer going off shows a card with Snooze 5 min / 10 min / Done. | `tests/test_conversation.py` |
| 6 | **Remembering conversations** | "What did we talk about yesterday?", "when did I mention Packet Tracer?" search her message history, now 3000 messages instead of 200. Past days ("monday", "3 days ago") get their own parser, since the calendar's only looks ahead. | `tests/test_recall.py` |
| 7 | **Self-check** | "Are your systems okay?" checks models, MyNotion, Spotify, camera, mic, voice, weather, search and the file index, with fixes; also logged at startup. Prompted by the vision model having been missing unnoticed. | `tests/test_health.py` |
| 8 | **Quick capture (Ctrl+Alt+N)** | Type a line, it's filed on a list, in the calendar, as a reminder or in the Inbox, with a bubble and no conversation. Ideas and links go to the Inbox in code (the model once put an idea on the to-do list); nothing typed is lost. Needs `./install_desktop.sh` once for the shortcut. | `tests/test_conversation.py` |
