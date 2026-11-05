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
| 9 | **Birthdays & special days** | Birthdays/anniversaries become yearly all-day events by themselves, get a heads-up at 09:00 the day before, and the briefing counts down to them. Before, they were one-off events and all-day events never got any heads-up. | `tests/test_notion.py` |
| 10 | **Text box history** | ↑ / ↓ in the text box bring back earlier messages, like a terminal. Also the first overlay tests (rendered off-screen): history, quick capture mode, ticking a card checkbox. | `tests/test_overlay.py` |
| 11 | **Weekly recap** | The Sunday review ends with the week's focus time and top tasks before what's coming up. | `tests/test_conversation.py` |
| 12 | **Pronunciation fixes** | Checked Kokoro's phonemes: "C#" lost its "#", "MyNotion" was "mi-NO-tion", "VS Code" was "viz code", "km" was "K M". A pronunciation list fixes these and spells out units, °C, € and "e.g.". | `tests/test_conversation.py` |
| 13 | **Low battery warning** | On battery at 15% and 7%, Aria tells you to plug in, once per level; resets when charging. | `tests/test_battery.py` |
| 14 | **Tool routing + no fake actions** | All 78 tool descriptions used 5,487 of 8,192 context tokens per turn; now each message gets only the relevant groups (1,278 tokens for small talk), with a retry using all tools if she says she can't. Testing it revealed a regression from the personality change: she *said* "I'll turn the volume down" without doing it. Fixed by putting the tool rules first, correcting an example, and retrying commands whose reply claims an action without a tool call. 16/16 everyday commands correct, personality unchanged. | `tests/test_routing.py` |
