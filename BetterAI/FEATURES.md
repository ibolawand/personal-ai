# Aria — Feature Overview

Everything Aria can do, grouped by area, with example phrases and the file that implements it.
Keep this file updated whenever a feature is added or changed.

---

## Running Aria

| Command | What you get |
|---|---|
| `python main.py` | Floating overlay orb + text input (default) |
| `python main.py --voice` | Overlay + wake word + microphone |
| `python main.py --no-ui` | Terminal only |
| `python -m ui.overlay` | Overlay demo mode (no AI attached, for testing the look) |

**Everyday use (no PyCharm needed):** run `./install_desktop.sh` once. It adds:
- **Aria in the Mint menu**, with the orb as its icon
- **Start on login** (8 seconds after you log in)
- **Ctrl+Alt+Space from any app:** opens the text box, or hides it if it's open. If Aria isn't running, it starts her.

`./aria.sh --quit` stops Aria. `./install_desktop.sh --remove` undoes the setup. Logs go to `~/.cache/aria/aria.log`.
To launch in voice mode, put `ARIA_ARGS=--voice` in `Engines/.env`. For another hotkey, run `ARIA_HOTKEY='<Super>j' ./install_desktop.sh`.

Only one Aria runs at a time (`ui/instance.py`): launching her again just opens the text box of the running one.
That way two copies never fight over the camera and mic.

Settings live in `Engines/.env` (gitignored): `DB_PATH`, Spotify keys, `ARIA_OWNER`, `FILE_ROOTS`,
`CAMERA_INDEX`, `VISION_MODEL`, `LLM_NUM_CTX`.

---

## Brain

- **Model:** Ollama `qwen3:8b` with native tool calling (`llm_engine.py`), thinking off for speed, 8192-token context.
- **Tool-call memory:** the real tool calls and results of the last 6 turns stay in the conversation, so Aria
  keeps using tools instead of making up answers. Tested: tool use went from 4/8 to 12/12.
- **Long-term memory:** facts and topics are pulled out of conversations and saved in SQLite (`database.py`).
- **Context:** current date and time (HH:MM), who is at the desk, and saved facts are added to every prompt (`ContextBuilder.py`).
- **Mood check-ins** (`Engines/UserStateEngine.py`): if you sound stressed or tired, Aria briefly checks in, at most once
  every 5 minutes. The check runs in the background after each reply, so it never slows down answers. Its result is used
  on your next message. Set `MOOD_USE_CAMERA=1` to include the camera; it's off by default because the vision model pushes
  the chat model out of graphics-card memory.
- **Clean replies:** filler like "Let me know if you need anything else!" and leftover markdown are removed.
- **Only working devices are offered:** Home Assistant (phone/TV), the LEDs and RVC voice conversion are skipped when
  they aren't set up (`HA_TOKEN`, a connected Arduino, `RVC_ENABLED=1`). That means fewer tools for the model to choose from,
  faster prompts and no startup warnings.
- **Snappier wake-up:** no greeting is generated when you wake Aria by typing a question or a reminder wakes her.
  In text mode she dozes off silently after a minute of quiet.

---

## Overlay UI — `ui/overlay.py`

- Transparent, frameless, always-on-top orb in the bottom-right corner. Clicks pass through everywhere except the orb, bubbles and input.
- **Animated orb per state:**
  - **sleeping:** dim breathing, dust drifting up, floating "z"s
  - **listening:** cyan orb, equaliser spikes and particles pulled inward, both following your mic volume
  - **thinking:** spiky blob, three comets with tails, a spinning dashed halo, particles swirling in
  - **speaking:** sparks thrown outward and shockwave rings on loud syllables, all following Aria's voice
  - **all states:** a coloured plasma swirl inside the orb and a slowly hue-shifting glow
  - **alerts** (reminder due, unknown face): colour flash, particle burst and double shockwave
  - **clicking the orb:** ripple and spark burst
- Speech bubbles for you and Aria. Hover over the orb to see the last few messages and a status caption.
- Text input: click the orb, type, press Enter. Esc hides it.
- Drag the orb to move it; its position is remembered.
- Right-click menu: type a message, go to sleep, mute voice, clear bubbles, quit.
- Countdown ring around the orb while a timer or focus session runs.

---

## Voice — `speech_to_text.py`, `wakeworddetector.py`, `Engines/voice_engine.py`

- Wake word, speech-to-text with live mic level shown on the orb, text-to-speech with the voice level driving the orb.
- **Voice engine:** Kokoro (`af_heart` voice) runs on the CPU, about 4x faster than real time. That leaves the whole
  graphics card to the language model, which before had to run 62% on the CPU next to Chatterbox.
  - `KOKORO_VOICE` in `Engines/.env` changes the voice, e.g. `af_bella`, `af_nicole`, `bf_emma` (British).
  - `TTS_ENGINE=chatterbox` switches back to Chatterbox, which copies the voice in `Engines/ref_voice.wav` but needs about 4 GB of graphics-card memory.
  - Mood changes the speaking pace slightly (slower when sad, a bit quicker when excited).
- Aria goes back to sleep after a period of silence. "Go to sleep" works too.
- **Easy on the ears:** every sentence is cleaned up before it plays (`polish_audio` in `voice_engine.py`):
  - every sentence is levelled to the same loudness, and peaks are softly capped
  - low rumble, harsh highs and sharp "s" sounds are reduced
  - silence is trimmed and the edges fade in and out, so nothing clicks
  - calm delivery: subdued moods, a relaxed pace, and longer pauses between sentences
  - `VOICE_GAIN` in `Engines/.env` sets the overall volume (e.g. `0.7` is quieter)
- **Sleep that sticks:** after "go to sleep", the camera only wakes Aria if you were away from the desk for at least 2 minutes.
  Looking away or down for less than 20 seconds doesn't count as leaving.

---

## Timers & reminders — `Engines/Reminders.py`

- "Set a timer for 10 minutes", "remind me to call mum at 18:30", "remind me in 20 minutes to stretch"
- "What reminders do I have?", "cancel the pasta timer", "snooze that for 5 minutes"
- Saved in SQLite, so they survive a restart. When one is due: the orb flashes, the LEDs animate, Aria speaks it,
  and your phone gets a notification if you're not at the desk.

## Focus mode — `Engines/FocusMode.py`

- "Start a 45 minute focus session on databases"
- One command sets up the whole desk: amber breathing LEDs, a lo-fi playlist on Spotify, phone on Do Not Disturb, and a countdown ring.
- "How long is left?", "stop focus". When it ends, everything is restored and Aria suggests a break.

## Screen & clipboard — `Engines/ScreenEngine.py`

- "What's this error on my screen?" takes a screenshot and sends it to a local vision model. Needs `ollama pull qwen2.5vl:7b`.
- "Explain what I copied": the clipboard is attached automatically when you mention it.
- Code blocks in Aria's replies are copied to your clipboard instead of being read aloud.

---

## Laptop control — `Engines/LaptopEngine.py`

- **Apps:** open, switch to, close (asks first), list open windows. Works with VS Code, PyCharm, Chrome, Firefox,
  Spotify, Files, Terminal, Settings and Calculator.
- **Sound:**
  - set, raise or lower the volume; mute
  - list audio outputs and switch between them ("switch to my headphones")
- **Media:** play, pause, next and previous for any player (Spotify, YouTube in Chrome, VLC…) via MPRIS.
- **System:**
  - "How's my laptop?" gives battery, CPU/GPU temperature, RAM and free disk space
  - lock the screen
  - suspend, shutdown and restart (asks first)
- **Connections:**
  - Wi-Fi on/off (turning it off asks first)
  - Bluetooth on/off
  - "connect my earbuds" (connects a paired device)
- **Web:** "open github", or search anything in the browser.
- **Desktop notifications.**

## Files & school work — `Engines/FilesEngine.py`

- "Find my plsql pdf", "find powerpoints from this week". Results are numbered, newest first.
- "Open the second one", "summarise the first one". Reads PDF, Word, PowerPoint, ODT, Jupyter notebooks,
  code and text files (up to 6000 characters).
- "Open my school folder"
- "Tidy my Downloads" sorts files into folders by type. It shows a preview and asks first; "undo the tidy" puts everything back.
- Only these folders are allowed: `~/Desktop/school`, `~/Documents`, `~/Downloads` and `~/Desktop`. Change the list with `FILE_ROOTS`.

---

## MyNotion: notes, lists & calendar — `Engines/NotionEngine.py`

Aria reads and writes the same database as your MyNotion app (`DB_PATH` in `Engines/.env`).
MyNotion watches that file and refreshes itself, so whatever Aria adds shows up there right away.

- **Quick notes:** "note that I need to call the landlord" adds a timestamped line to the **Inbox** note.
  "Add to my trip ideas: Lisbon in spring" adds to a named note, creating it if needed.
- **Save answers:** "save that as a note called pancakes" saves Aria's previous answer, such as a recipe, an explanation or a plan.
- **Lists:**
  - "add oat milk and eggs to my shopping list", "what's on my packing list?"
  - "I bought the eggs" (removes it), "clear my shopping list" (asks first)
  - Any list works: shopping, to-do, packing, films to watch. A new one is created the first time you mention it.
  - List commands only ever change notes that are lists, so your other notes are never touched.
- **Ask your notes:** "when is Sara's birthday?", "what did I note about the landlord?" Aria searches your notes and answers from them.
  You can also read a note ("read my birthdays note") or list them ("which notes do I have?").
- **Calendar:**
  - "what do I have tomorrow / this week / on friday?"
  - "put dentist on friday at 15:00"
  - "move the dentist to 16:30" and "delete the team meeting" ask first
  - Dates can be said naturally: "tomorrow", "next monday", "in 3 days", "12.11.", "20 november".
  - Aria's events show in purple. MyNotion's week view only shows 08:00–23:00.
- **Event heads-up:** 15 minutes before every timed event, Aria flashes the orb and says "Dentist starts in 15 minutes".
  It follows edits you make in MyNotion, so a moved or deleted event moves or drops its heads-up.
- **Daily briefing:** the first time Aria greets you each day, she sums up the day: the time, today's events,
  what's coming this week, today's reminders, and the latest Inbox note. "Brief me" or "what's my day like?" works anytime.
- **Open things in MyNotion:** "open my calendar", "show me my shopping list", "open the birthdays note", "open MyNotion".
  Aria starts MyNotion or brings it to the front on that page. "What's on my shopping list?" reads it aloud instead.
  "Open/show <calendar or an existing note>" is handled in code, so it's instant and reliable; anything else ("open vs code") goes to the model as usual.
- Note, list and calendar reading tools are protected by the optional `ARIA_OWNER` face lock.

## Music & home

- **Spotify** (`Controller/Spotify_controll.py`):
  - play a song, artist, playlist or genre
  - pause, skip, previous
  - what's playing
  - music volume
- **Desk LEDs** (`Controller/arduino_controller.py`): colour, effect (solid, breathe…), brightness, off.
- **Home Assistant** (`Controller/homeController.py`):
  - phone: notify, battery level, location, Do Not Disturb
  - TV: on/off and volume
- **Web search** for live information.

---

## Camera & faces — `vision/vision.py`

- Notices when someone sits down or leaves, and greets known faces by name.
- "What do you see?" describes the camera view. Uses the same vision model as screen reading.
- When an unknown face shows up, Aria asks for the person's name and learns their face (40 samples). You can also use `vision/setupface.py`.
- **Picks the camera automatically:** uses the first device that actually gives a picture, because on Linux `/dev/video1` is
  usually only a metadata node. Set `CAMERA_INDEX` to force one.
- One shared camera connection: snapshots reuse the running camera instead of opening it a second time, which fails on Linux.
  If the camera is unplugged or taken by another app, Aria reconnects.

---

## Safety

- Aria can only run actions that are written in code. The model never gets a shell.
- **Risky actions ask first** (closing apps, power, turning Wi-Fi off, tidying files). Your yes/no is checked by code, not by
  the model (`Engines/Confirm.py`), and a pending question expires after 90 seconds.
- **Optional owner lock:** set `ARIA_OWNER=<face profile name>`. File, clipboard, phone and power tools are then refused when
  the camera sees someone else (`Engines/Tool_Engine.py`, `PROTECTED`).
- File access is limited to the allowed folders.
