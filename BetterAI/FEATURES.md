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

`./aria.sh --quit` stops Aria. `./aria.sh --chat`, `--review` or `--event` makes her start that kind of conversation right now, to try it out. `./install_desktop.sh --remove` undoes the setup. Logs go to `~/.cache/aria/aria.log`.
To launch in voice mode, put `ARIA_ARGS=--voice` in `Engines/.env`. For another hotkey, run `ARIA_HOTKEY='<Super>j' ./install_desktop.sh`.

Only one Aria runs at a time (`ui/instance.py`): launching her again just opens the text box of the running one.
That way two copies never fight over the camera and mic.

Settings live in `Engines/.env` (gitignored): `DB_PATH`, Spotify keys, `ARIA_OWNER`, `FILE_ROOTS`,
`CAMERA_INDEX`, `VISION_MODEL`, `LLM_NUM_CTX`, and the conversation settings below (`ARIA_INITIATIVE`, `ARIA_QUIET`, …).

---

## Brain

- **Personality: a warm friend** (`BASE_PROMPT` in `main.py`). Aria is casual and curious, reacts to what you say,
  asks back, and brings up things she remembers about you. She teases back when you tease her, and is softer when
  you're down. Commands still get a quick confirmation, sometimes with a small personal touch.
  Short example conversations in her instructions set the tone, because a small model follows those better than rules.
  - "How are you?" gets a real answer based on her actual day (how much you've talked today, the time of day), not invented events.
  - Stock assistant lines ("I'm here to help", "How can I assist you", "As an AI"…) are never spoken. A reply that
    starts with one is rewritten, and if two rewrites fail she says a short line written in code instead.
  - "What?" / "huh?" makes her say her last message again, more simply.
  - After she asks you something, she waits 2 minutes for your answer instead of 1 before dozing off.

- **Model:** Ollama `qwen3:8b` with native tool calling (`llm_engine.py`), thinking off for speed, 8192-token context.
- **Tool routing** (`ToolEngine.schemas_for`): all ~78 tool descriptions took 5,487 of the model's 8,192 context
  tokens on every turn. Now each message gets a core set (reminders, notes, weather, maths…) plus only the groups it's
  about (music, laptop, files, notes & calendar, screen, focus, memory, home, misc), and groups used in the last two
  turns. Small talk: 1,278 tokens; "add eggs to my list": 2,297. If the model says it can't do something without
  trying a tool, the turn is retried with every tool. Tested: 16/16 everyday commands pick the right tool.
- **No fake actions:** if your message is a command and her reply claims it ("I'll turn the volume down") but no
  tool was called, she gets one retry that insists on the tool. The tool rules also come first in her instructions now.
- **Tool-call memory:** the real tool calls and results of the last 6 turns stay in the conversation, so Aria
  keeps using tools instead of making up answers. Tested: tool use went from 4/8 to 12/12.
- **Long-term memory:** after a conversation, lasting facts about you are saved in SQLite (`database.py`).
  The model "thinks" first, which runs in the background, so it skips commands, passing moods ("I'm tired"),
  calendar contents and facts it already knows.
- **Remembering conversations** (`Engines/Recall.py`): "what did we talk about yesterday?" (or on Monday, 3 days ago)
  and "when did I mention Packet Tracer?" look through her message history (the last 3000 messages; it used to keep 200).
- **You can see and fix what Aria remembers** (`Engines/MemoryNote.py`):
  - The MyNotion note **"What Aria knows about me"** lists every fact, one per line. Delete or change a line and she
    forgets it or uses your version; add a line and she knows it. Synced every minute in both directions.
    If both sides changed at once, your edits win and her new facts are added on top.
  - "What do you know about me?" (also shows them as a card), "forget that I'm bored", "remember that I'm vegetarian",
    "forget everything about me" (asks first).
  - **Clean-up:** "clean up your memory" makes her go through everything she saved (thinking first), show what isn't a
    real fact ("asked to play a song", "is bored", "has a meeting tomorrow"), and forget it after your yes.
    She offers this once by herself.
- **Context:** current date and time (HH:MM), who is at the desk, and saved facts are added to every prompt (`ContextBuilder.py`).
- **Mood check-ins** (`Engines/UserStateEngine.py`), **off by default** (`ARIA_MOOD_CHECK=1` turns them on): a second
  model call after each message decides whether to check in on how you are, and the result is used on your *next*
  message (only within 3 minutes). It was switched off because in real use a stale result made Aria answer "pitch" with
  "Just breathe — you don't have to do this alone", and the extra call competes with replies for the GPU. Her persona
  already reacts to how you sound. `MOOD_USE_CAMERA=1` adds the camera.
- **Clean replies:** filler like "Let me know if you need anything else!" and leftover markdown are removed.
- **No tacked-on offers:** "Want me to…?", "Should I…?" and "I can also… if you want" at the end of a reply are cut in code (spoken and written). They stay only when the offer is the whole reply, or while she is asking you to confirm something.
- **No parroting:** if a reply comes out word-for-word like one of her last two (small models do that after "no"
  or "what"), it's rewritten before it's spoken. Sentences that match her previous answer are held back while she
  streams, so a repeat is never said out loud. Replies after a tool call may repeat ("Opening your calendar" twice is fine).
- **No made-up offers:** she only offers what she has tools for, and searches for a file before saying where it is.
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
- Text input: click the orb, type, press Enter. Esc hides it. **↑ / ↓** bring back what you typed before.
- **Quick capture (Ctrl+Alt+N):** a green box. Type "buy batteries", "dentist friday 3pm" or "remind me to call mum at 6"
  and it's filed on a list, in the calendar or as a reminder, confirmed in a bubble, without a conversation or speech.
  Lines starting with "idea:" / "note:" and links go to the Inbox note, and so does anything the model can't place.
  (Run `./install_desktop.sh` again once to get the shortcut; `ARIA_CAPTURE_HOTKEY` changes it.)
- Drag the orb to move it; its position is remembered.
- Right-click menu: type a message, go to sleep, mute voice, let Aria start conversations (on/off), clear bubbles, quit.
- Countdown ring around the orb while a timer or focus session runs.
- **Cards** above the orb, so you can see and click instead of only listening:
  - **Lists** ("what's on my shopping list?", "add eggs…", "I bought the eggs"): the list with checkboxes.
    Ticking one updates MyNotion right away. The card also says how many are left; "Open" shows the list in MyNotion.
  - **Calendar** ("what do I have this week?", and the morning briefing): a mini agenda grouped by day,
    repeating events marked ↻. Click an event or "Open calendar" to open MyNotion's calendar.
  - **Yes/no questions** (clear a list, move or delete an event, close an app…): **Yes** / **No** buttons.
    Typing or saying yes/no still works; the card disappears once it's answered.
  - **Reminders and timers** that go off: **Snooze 5 min**, **10 min** or **Done**.
  - A card fades out after 45 seconds (yes/no after 90), but stays while the mouse is over it. ✕ closes it.

---

## Voice — `speech_to_text.py`, `wakeworddetector.py`, `Engines/voice_engine.py`

- Wake word, speech-to-text with live mic level shown on the orb, text-to-speech with the voice level driving the orb.
- **Hears you right** (`speech_to_text.py`):
  - voice activity detection cuts silence and noise before transcribing, so no more phantom "Thanks for watching!"
    (tested: silence, room noise and louder noise used to give "Thank you very much.", "You", "Thanks for watching!"; now nothing)
  - a word list with Aria, MyNotion, app names and the names in her memory and note titles: "MyNotion" was heard as
    "Minotian" and "Lina" as "Lena"; both come out right now
  - when she isn't sure what she heard, she asks "Sorry, did you say: …?". "Yes" acts on it, "no" makes her ask
    you to repeat it, anything else is taken as new input. "Go to sleep" is never questioned.
- **Pronunciation fixes** (`PRONOUNCE` in `voice_engine.py`, checked with Kokoro's phonemes): "C#" is "C sharp"
  (the hash used to be dropped), "MyNotion" is "My Notion" (was "mi-NO-tion"), "VS Code" is "V S Code" (was "viz code"),
  units are said in full ("42 kilometers", "3 degrees Celsius", "1 hour 20 minutes", "12 euros"), "e.g." is "for example".
- **Tone per sentence:** comforting sentences ("Aw, that sounds rough") come a bit slower and softer with a longer
  pause; playful ones ("Haha, rude!") a bit quicker and brighter. Your mood still sets her overall pace.
- **Talks while thinking:** replies are streamed. Aria starts speaking the first sentence after about 0.6 s,
  while the rest is still being written. Code blocks are never read out (they go to the clipboard).
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
- Other days too: "remind me on Monday at 10 to book the train", "remind me tomorrow to water the plants" (09:00 if no time is given)
- **Repeating:** "remind me every day at 8 to take my vitamins", "every weekday at 9:30", "every Monday and Thursday at 7pm",
  "every month on the 1st to pay rent". When one goes off, the next is scheduled straight away. Cancelling stops the series.
  A monthly reminder on the 31st goes off on the last day of shorter months.
- "What reminders do I have?", "cancel the pasta timer", "snooze that for 5 minutes"
- Saved in SQLite, so they survive a restart. When one is due: the orb flashes, the LEDs animate, Aria speaks it,
  and your phone gets a notification if you're not at the desk.

## Aria starts conversations — `Engines/Initiative.py`

While she's asleep, Aria sometimes speaks up first:
- **Follow-ups:** mention something coming up ("I have my math exam tomorrow", "Lina's visiting this weekend") and she
  asks about it afterwards: "So, how did the math exam go?" It's picked up when she saves facts after a conversation,
  asked from 17:00 that day (or the next morning for late things), either in her greeting or as a conversation she starts.
  Unasked ones are dropped after 3 days, and timed calendar events are left to the event check-in below.
- **Breaks:** after 90 minutes at the laptop without a 5-minute break, a warm "you've been coding for ages, stretch
  for a minute?". If you keep going, she asks again an hour later at most.
- **After an event:** shortly after a calendar event ends, "How did the dentist go?". If you tell her something
  worth keeping ("come back in 3 weeks"), it goes into a "Dentist notes" note. Repeating events (gym, classes) are skipped.
- **Weekly review**, Sunday from 18:00: she goes through your open to-dos one at a time. Answer "done" (ticks it off),
  "keep", "drop it" (removes it), "remind me Monday at 10" or "later" (a reminder), or "stop". These answers are
  handled in code, so a tick-off really happens. At the end she sums up your week's focus time ("1 h 20 min of
  focus in 2 blocks, mostly C#") and mentions what's coming up.
- **Morning:** after the daily briefing she asks what you want to get done today. What you name goes on your to-do list.
- **Casual chats:** now and then a normal conversation, not about tasks: what you're up to ("how's the coding
  going?" after a while in PyCharm), something she knows about you, your day, the day of the week, or a fun question.
  She picks a different topic each time.
  During these chats she only uses tools when you clearly ask ("can you…", "remind me…", "look at my screen"),
  so she won't look at your screen or save small talk into notes on her own.

**When she won't:** if nobody is at the desk (camera, or no keyboard/mouse use for 5 minutes when there's no camera),
in the first 10 minutes after you sit down, within 20 minutes of you talking to her, during quiet hours, in a focus
session, while muted, when the screen is locked, when something is fullscreen (films, games), while you're watching
something (YouTube, Netflix, VLC…), or when another app is using the microphone (calls). There's at least half an hour between two openers.

**Backing off:** "not now", "later" or "I'm busy" snoozes her for 3 hours. A short "ok" or "fine" to a casual chat,
or no answer at all, means she waits twice as long before the next one. Turn it off with the right-click menu or
"stop starting conversations".

Settings in `Engines/.env`: `ARIA_INITIATIVE=0` (off), `ARIA_QUIET=22:30-08:30`, `ARIA_CHAT_EVERY_MIN=45`,
`ARIA_CHATS_PER_DAY=6`, `ARIA_REVIEW_DAY=6` (0 = Monday), `ARIA_REVIEW_HOUR=18`, `ARIA_BREAK_MIN=90`.
To try one right now: `./aria.sh --chat`, `--followup`, `--break`, `--review` or `--event`. Her bookkeeping lives in `~/.cache/aria/initiative.json`.

## What you're doing — `Engines/Activity.py`

- Every 20 seconds Aria notes which app is in front and whether you're using the keyboard/mouse. That gives her
  "PyCharm for 50 minutes", your time at the laptop without a break, and whether you're watching something.
- **Only in memory:** app names and minutes, never written to disk, gone when she quits. Window titles are only
  checked in the moment, to tell whether you're watching a video.
- "How long have I been on the laptop today?", "what did I do today?" gives minutes per app since she started, and
  your current stretch without a break.

## Focus mode — `Engines/FocusMode.py`

- "Start a 45 minute focus session on databases". Works with just the laptop:
  - Cinnamon's notification popups are paused during the session and restored afterwards (left off if they were off)
  - lo-fi on Spotify, plus amber LEDs and phone Do-Not-Disturb when those are set up
  - a countdown ring around the orb: orange for work, green for breaks
- **Pomodoro:** "4 rounds of pomodoro on C#" gives 25 minutes of work and 5 of break, repeating on its own.
  Music pauses during breaks, and she calls you back when a break is over. She may chat during breaks, never during work.
- **Distraction nudge:** if Discord, YouTube, a game or another video is in front for 2+ minutes during a work block,
  she reminds you once per round: "Psst, it's still focus time — Discord can wait 12 more minutes."
- **Stats:** every finished block is logged. "How much did I focus this week?" gives the total, the number of blocks and
  the top tasks.
- **Away from the desk:** if the camera doesn't see you for 3 minutes during a work block (and the keyboard is idle),
  the block pauses from the moment you left, and lo-fi stops. When you're back (camera or typing) it continues:
  "Welcome back! I paused your focus on databases while you were away, 12 minutes to go." Time away isn't counted
  in the stats. After 2 hours away the session ends quietly.
- "How long is left?", "stop focus".

## Screen & clipboard — `Engines/ScreenEngine.py`

- "What's this error on my screen?" takes a screenshot and sends it to a local vision model. Needs `ollama pull qwen2.5vl:3b`
  (it wasn't installed before, so this never worked). About 9 seconds per look:
  - the chat model and the vision model don't fit on an 8 GB card together, so each look swaps them. The 3B vision
    model loads quickly, and screenshots are shrunk to 1280 px (1600 px was four times slower and not more accurate)
  - the vision model answers you directly instead of passing its description back to the chat model, which reloads
    in the background while she speaks. Measured: ~9 s per look, against ~15 s (and ~40 s right after boot) with the 7B model.
- "Explain what I copied": the clipboard is attached automatically when you mention it.
- Code blocks in Aria's replies are copied to your clipboard instead of being read aloud.

---

## Laptop control — `Engines/LaptopEngine.py`

- **Apps:** open, switch to, close (asks first), list open windows. Works with **every app in the Mint menu**
  ("open Packet Tracer", "open Discord", "open Writer", even "open the web browser"). Apps are started the way the
  menu starts them (`gtk-launch`), and an app that's already open is brought to the front instead.
  "Where is my Packet Tracer?" / "do I have Discord?" says whether it's installed and offers to open it.
- **Sound:**
  - set, raise or lower the volume; mute
  - list audio outputs and switch between them ("switch to my headphones")
- **Media:** play, pause, next and previous for any player (Spotify, YouTube in Chrome, VLC…) via MPRIS.
- **System:**
  - "How's my laptop?" gives battery, CPU/GPU temperature, RAM and free disk space
  - lock the screen
  - **low battery warning** (`Engines/Battery.py`): on battery at 15% and again at 7%, she tells you to plug in
    (and wakes up to say it). Resets once the charger is connected.
  - suspend, shutdown and restart (asks first)
- **Connections:**
  - "Is Wi-Fi on?" / "are my earbuds connected?" only *checks* (it used to switch Wi-Fi instead)
  - Wi-Fi on/off (turning it off asks first)
  - Bluetooth on/off
  - "connect my earbuds" (connects a paired device)
- **Web:** "open github", or search anything in the browser.
- **Desktop notifications.**

## Quiz me — `Engines/Quiz.py`

- "Quiz me on my C# note", "test me on the gear trains PDF", "quiz me on databases, 8 questions".
  The material comes from a MyNotion note or a document in your folders. For long ones a random part is used, so
  every quiz is a bit different.
- The model writes short questions whose answers you can say out loud (no code or symbols). After that everything is
  handled in code: she asks one question at a time, and each reply is your answer. If it contains the expected words
  it's right straight away; otherwise the model decides whether you meant the same thing ("3NF" for "third normal form").
- Say "skip" or "I don't know" to hear the answer, "hint" for the first letter, "repeat" for the question again, and
  "stop" to end. You get your score at the end.
- Missed questions are kept: "quiz me on my mistakes" asks them again, and the ones you get right are dropped.

## Files & school work — `Engines/FilesEngine.py`

- "Find my plsql pdf", "find powerpoints from this week". Results are numbered, newest first.
- **Search inside documents:** "find the pdf about gear trains", "which document talks about four-bar linkages".
  Aria keeps a text index of your PDFs, Word/PowerPoint/LibreOffice files, notes and notebooks (`~/.cache/aria/file_index.db`,
  updated every 30 minutes; PDFs up to 300 pages). If no file *name* matches, or nothing is in your MyNotion notes,
  she automatically looks inside documents too. Results come with a short quote from where it's mentioned.
- "Summarise the first one", then "save that as a note called …" keeps the summary in MyNotion.
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
- **Lists are checklists:**
  - "add oat milk and eggs to my shopping list", "what's on my packing list?"
  - "I bought the eggs" / "I paid the rent" ticks it off; "untick it" undoes that.
  - "remove the eggs" deletes an item; "clear my shopping list" asks first.
  - You can tick items yourself in MyNotion too, using the ☑ To-do button in the editor.
  - Any list works: shopping, to-do, packing, films to watch. A new one is created the first time you mention it.
  - List commands only ever change notes that are lists, so your other notes are never touched.
- **Ask your notes:** "when is Sara's birthday?", "what did I note about the landlord?" Aria searches your notes and answers from them.
  You can also read a note ("read my birthdays note") or list them ("which notes do I have?").
- **Calendar:**
  - "what do I have tomorrow / this week / on friday?"
  - "put dentist on friday at 15:00"
  - "move the dentist to 16:30" and "delete the team meeting" ask first
  - Dates can be said naturally: "tomorrow", "next monday", "in 3 days", "12.11.", "20 november".
  - **Repeating events:** "gym every monday and thursday at 6pm", "mum's birthday on 14 march every year".
    You can repeat daily, weekly, monthly or yearly, and MyNotion's calendar has a matching "Repeat" option.
    Deleting a repeating event deletes the whole series (Aria asks first).
  - Aria's events show in purple. MyNotion's week view only shows 08:00–23:00.
- **Event heads-up:** 15 minutes before every timed event, Aria flashes the orb and says "Dentist starts in 15 minutes".
  It follows edits you make in MyNotion, so a moved or deleted event moves or drops its heads-up.
- **Daily briefing:** the first time Aria greets you each day, she sums up the day: the time, today's events,
  what's coming this week, today's reminders, open to-dos, and the latest Inbox note. "Brief me" or "what's my day like?" works anytime.
- **Open things in MyNotion:** "open my calendar", "show me my shopping list", "open the birthdays note", "open MyNotion".
  Aria starts MyNotion or brings it to the front on that page. "What's on my shopping list?" reads it aloud instead.
  "Open/show <calendar or an existing note>" is handled in code, so it's instant and reliable; anything else ("open vs code") goes to the model as usual.
- **Birthdays & special days:** "Lina's birthday is on 3 March" becomes a yearly all-day event automatically
  (also anniversaries). You get a heads-up at 09:00 the day before ("tomorrow is Lina's birthday"), and the morning
  briefing counts down special days in the next two weeks.
- **Clash warnings:** adding or moving a timed event that overlaps another one ends with "Heads up: that overlaps
  with Meeting at 15:00." (all-day events never clash).
- **Undo** (`Engines/Undo.py`): "undo that" / "that was wrong" takes back her last change to notes, lists, events or
  reminders, including confirmed ones like a deleted event or a cleared list (it comes back with the same id).
  Works for 15 minutes after the change. If you edited the same note in MyNotion since then, undo puts back the
  version from before Aria's change.
- Note, list and calendar reading tools are protected by the optional `ARIA_OWNER` face lock.

## MyNotion app (`../MyNotion`)

- A real desktop app in the Mint menu: `./build_app.sh` builds it, and `./install_desktop.sh` adds the menu entry.
- **No login:** it's a local app for one person, so it opens straight to your notes.
- Data lives in `~/.config/MyNotion/noted.db`, with a **daily backup** in `~/.config/MyNotion/backups/` (the last 14 are kept).
- Only one copy runs at a time. `MyNotion --open=calendar|note:<id>|home` shows that page (Aria uses this).
- Refreshes live when Aria changes notes or events.
- **The editor:** type `/` for a menu of blocks (headings, to-do list, lists, quote, code, divider, today's date),
  each with its Markdown shortcut next to it (`#`, `[ ]`, `-`, `>`, …). Selecting text shows a small bar with bold,
  italic, underline, strike, code, four highlights and links (Ctrl+K). Note text is in a serif in a centred column;
  the "Aa" switch in the footer changes it to sans-serif. The footer also shows words and reading time.
  Links open in your normal browser.
- **Search:** Ctrl+P (or clicking "Search all notes…") searches all titles and note text as you type, shows where it
  matched, and opens the note with Enter. Empty, it shows your recent notes.
- **Today's note:** Ctrl+D (or the first row of the search) opens a note called e.g. "Saturday, 7 November 2026",
  made with a small Plan / Notes template the first time each day. Aria uses the same note: "add call the bank to
  today's note", "what's in today's note?".

## Music & home

- **Spotify** (`Controller/Spotify_controll.py`):
  - picks the song that actually matches: "NF No Excuses" used to play "DROP!" by Forrest Frank because it was more
    popular. Now title and artist words decide, remixes only when asked, and "X by Y" works. If nothing really
    matches, she says so instead of playing something random.
  - if Spotify isn't open anywhere, she starts it on the laptop and waits for it, then plays
  - Spotify errors become sentences ("Spotify only lets apps control playback with a Premium account").
  - play a song, artist, playlist or genre
  - pause, skip, previous
  - what's playing
  - music volume
- **Desk LEDs** (`Controller/arduino_controller.py`): colour, effect (solid, breathe…), brightness, off.
- **Home Assistant** (`Controller/homeController.py`):
  - phone: notify, battery level, location, Do Not Disturb
  - TV: on/off and volume
- **Maths and units** (`Engines/Calc.py`): exact answers instead of the model's mental arithmetic. "What's 17% of
  2340?", "split 87.40 between 3 with a 15% tip" (33.50 each), "42 km in miles", "20 C in F", "2 cups in ml".
  Expressions are parsed safely (no `eval`): only numbers, operators and a few maths functions.
- **Weather** (`Engines/Weather.py`, Open-Meteo, free, no key): "what's the weather?", "do I need a jacket tomorrow?",
  "will it rain the day after tomorrow?", "weather in Berlin". Tell her once "I live in Vienna" (or set `ARIA_LOCATION`).
  Clothing advice (coat, jacket, umbrella) is decided in code from the temperature and rain chance, and the
  morning briefing includes today's weather.
- **Web search** (`Engines/WebSearch.py`), with no accounts or API keys:
  - **Wikipedia** (no key needed): facts, people, places, how things work. Aria answers in a sentence or two and says where it's from.
  - **DuckDuckGo instant answers** (no key needed).
  - **SearXNG** for news, prices and anything recent: a search engine running on this computer in Docker,
    no account or API key (`cd searxng && ./start.sh` once; see `searxng/README.md`). Aria also reads the top
    result's page. When it isn't running, she says when the sources don't cover something recent instead of guessing.

---

## Camera & faces — `vision/vision.py`

- Notices when someone sits down or leaves, and greets known faces by name.
- "What do you see?" describes the camera view. Uses the same vision model as screen reading.
- When an unknown face shows up, Aria asks for the person's name and learns their face (40 samples). You can also use `vision/setupface.py`.
- **Picks the camera automatically:** uses the first device that actually gives a picture, because on Linux `/dev/video1` is
  usually only a metadata node. Set `CAMERA_INDEX` to force one.
- One shared camera connection: snapshots reuse the running camera instead of opening it a second time, which fails on Linux.
  If the camera is unplugged or taken by another app, Aria reconnects.
- **Posture nudges** (`Engines/Posture.py`): from where your face is in the picture, worked out in code (no vision
  model, so no slowdown). If you sit clearly closer to the screen than usual (face 25% bigger) or lower in the chair
  (slouching) for 8 of the last 10 minutes, she says one short line, like "Posture check: you're sliding down in your chair."
  At most every 30 minutes and 6 times a day, and not in quiet hours, while muted, mid-conversation, during a video or call.
  "Usual" is learnt from the first minutes after you sit down; say "this is my good posture" while sitting well to set it
  yourself. `ARIA_POSTURE=0` turns it off.

---

## Tests — `tests/`

- About 100 tests, run in about 7 seconds: `.venv/bin/python -m pytest` (install once with `pip install -r requirements-dev.txt`).
- They cover reminders and repeats, follow-up timing, the memory note sync, lists and the calendar, the weekly review,
  the reply filters (stock lines, repeats, "what?"), conversation-starter rules, app matching, file search and web search parsing.
- No model, camera, microphone or network needed. They only use temporary databases: opening the real
  `aria_memory.db` or MyNotion's database fails the test, and app or MyNotion launches are recorded instead of run.

## Self-check — `Engines/Health.py`

- "Are your systems okay?" / "why can't you see my screen?" checks the language and vision models, MyNotion,
  Spotify login, camera, microphone, voice, weather city, web search and the document index, and says how to fix
  whatever is missing. The same check is written to the log (`[Health] ✓/✗ …`) every time Aria starts.
  It also says how quickly her voice starts after you stop talking, and whether speech recognition runs on the GPU.

## Speed & problem log — `Engines/Diagnostics.py`

- **Speed** (measured on this laptop, RTX 4070):
  - Speech recognition runs on the GPU: 0.2 s per sentence instead of 2.6 s on the CPU, same accuracy
    (`STT_DEVICE=cpu` to force the CPU).
  - The end of what you say is 1.2 s of quiet instead of 2 s (`STT_SILENCE_S` to change it).
  - The chat model stays loaded and every call uses the same context size. Before, it unloaded after 5 quiet minutes
    (3.3 s to load again) and reloaded whenever the background mood check ran with a different context size
    (3.2 s, on most turns). `ARIA_KEEP_ALIVE` (seconds) if you ever want it to unload.
- **The log** (`~/.cache/aria/diagnostics.jsonl`, stays on this computer): for every spoken reply, how long each step
  took; and every problem: misheard words she had to ask about, waking up when nobody spoke, you correcting her
  ("no, I said…"), claimed-but-not-done actions, retries, rewritten replies, failed tools and crashes.
- `./aria.sh --report` (or `--report 30`) shows typical and slow times, the slowest replies, problem counts and the
  latest problems. Bring it to a fixing session.

- **Checks with the real model** (`tests/test_model.py`, opt-in): `ARIA_MODEL_TESTS=1 .venv/bin/python -m pytest -m model`
  runs 19 everyday commands and 3 small-talk lines through qwen3 (devices are stand-ins) in about 40 seconds. Run it
  after changing the system prompt or tools. Expect an occasional single miss: the model isn't fully deterministic.

## Safety

- Aria can only run actions that are written in code. The model never gets a shell.
- **Risky actions ask first** (closing apps, power, turning Wi-Fi off, tidying files). Your yes/no is checked by code, not by
  the model (`Engines/Confirm.py`), and a pending question expires after 90 seconds.
- **Optional owner lock:** set `ARIA_OWNER=<face profile name>`. File, clipboard, phone and power tools are then refused when
  the camera sees someone else (`Engines/Tool_Engine.py`, `PROTECTED`).
- File access is limited to the allowed folders.
