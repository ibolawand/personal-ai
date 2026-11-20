# Aria reacts to your day: waking after school, noticing apps, props, music

Status: design, approved approaches (2026-11-14). Build one piece at a time, in the order below; report after each.

## Why

Aria's avatar can walk, sit on windows and peek from behind apps, but everything she *knows* (WebUntis tests,
weather, music, what you're doing) only reaches the user as text or speech. The user wants her to feel present:
notice what they have open and react now and then, show what she knows with her body (a card for a test, an
umbrella before rain, bobbing to music), and greet them herself once they're home from school.

Earlier (2026-11-13) self-waking was removed because it was annoying **in school**; the laptop is used in class.
The user now wants self-waking back, but only outside school hours, decided from their WebUntis timetable.

## Goals

1. **Quiet wake after school.** Once the day's last lesson is over (or on a day with no lessons: weekend, holiday),
   when the user starts using the laptop, she wakes herself: the orb turns into her, she stretches, waves and puts
   one line in her speech bubble (e.g. "school's done! Maths test Thursday, btw"). **Never spoken.** At most once per
   afternoon, plus when the user comes back after ≥ 2 h without touching keyboard or mouse. Never during a lesson,
   never while a fullscreen app (game, film) is up. If ignored, she goes back to sleep after a short while.
2. **App awareness.** She notices which app is in front (VS Code, a browser on YouTube, MyNotion, a game, …) and now
   and then reacts: body language (glances at it, leans toward a video, …) **plus one short line in the bubble**,
   never spoken. Lines are hand-written in code (approach A), a bank per kind of app with blanks filled in
   ("coding again? don't forget to commit 👀"), recently used lines not repeated. At most one line about every
   30 min; body reactions may be more frequent but still occasional.
3. **Test card.** When a WebUntis test is near, she holds up a small paper card with the subject and when
   ("Maths, Thursday") in both hands for a few seconds, as an occasional idle while awake.
4. **Umbrella.** When rain is likely in the next hours (the weather engine's forecast), she pulls an umbrella from
   behind her back, opens it with a little snap and rests it on her shoulder for a while.
5. **Bob to music.** While music plays on the laptop (any app), she bobs on the actual beat (approach A): beat found
   locally from the system audio's volume pulses; stops when the music stops.
6. **Then:** polish the existing animations (a separate round, its own review).

## Non-goals

- No camera (it stays off; don't build on it).
- No spoken reactions or spoken self-wake greeting.
- No LLM-written lines for reactions (approach B rejected: GPU time, odd output).
- Nothing about the user's screen, apps, titles or audio leaves the laptop or is stored long-term.
- No downloaded 3D assets: props are built in code.

## Anti-goals (would make it a failure even if it "works")

- She wakes or pops up a line during a lesson, a call, a film or a game.
- She comments too often, or repeats the same line; she reads as a nagging notification.
- A bob off the beat (worse than none), or props that look pasted on rather than part of her style.
- Quiet wake turning into a spoken greeting through the existing wake path (the current wake path always generates
  and speaks an LLM greeting).

## Constraints from the project

- **Decide in code**, not with the model (project pattern). All "may she act now?" rules live in Python and are
  unit-tested without X, audio or network.
- The avatar is only on screen while Aria is awake (`Overlay._shows_avatar()`); asleep she is the orb. Reactions
  happen only while she's visible.
- Today waking goes through `Aria._wake_event` → `run()` → greeting via `self.llm.chat` + `self.speak`, and she
  sleeps after `SLEEP_TIMEOUT = 60` s idle. A quiet wake needs its own path: no LLM greeting, no speech, the line goes
  to the bubble (`ui.message("aria", ...)` or the overlay bubble), and its own longer stay-awake time.
- WebUntis: `Engines/Untis.py` `_lessons(day)` returns the day's lessons with `startTime`/`endTime` (HHMM ints),
  cached; `_exams()` returns upcoming tests. `TestPrep.py` already picks tests in the next 7 days.
- Weather: `Engines/Weather.py` `get_weather(...)` / `_forecast(place)` (Open-Meteo, home city).
- Windows: `ui/desktop_windows.py` already reads X through python-xlib; the active window is `_NET_ACTIVE_WINDOW`,
  its app from `WM_CLASS`, title from `_NET_WM_NAME`. Keyboard/mouse idle time: the X screensaver extension
  (`Xlib.ext.screensaver`, available in the venv). Fullscreen: `_NET_WM_STATE_FULLSCREEN`.
- Audio: PipeWire with a sink monitor source (`pactl list short sources` shows `…sink.monitor`). Beat detection reads
  it with `parec`/`pw-record` at a low rate, computes an onset envelope and tempo/phase; nothing is recorded to disk.
- Avatar page: moves are played through `window.aria.act(...)` (`ui/avatar_view.AvatarLink`), gestures in
  `logic.mjs` `GESTURES`; pure logic tested with `node --test`. Props must use the model's toon look (MToon-like flat
  shading + outline) and attach to hand bones so they follow walking/sitting.
- `FEATURES.md` updated for every piece; `CLAUDE.md` architecture note if a new module is added.

## Approaches considered

**Where the reaction lines come from**
- **A (chosen): hand-written lines in code**, per app kind with blanks, no-repeat memory. Instant, always in her
  voice, never weird, no GPU.
- B: local model writes each line. More variety, but 1–3 s of GPU next to the chat model and occasional odd output.

**Music bob**
- **A (chosen): real beat from the system audio monitor.** Bobs on the beat for any player; cheap; local.
- B: fixed-tempo bob whenever an MPRIS player says "playing". Simpler, but off-beat bobbing looks wrong.

**Where decisions live:** Python decides (timing, school hours, cooldowns, what to react to); the page only plays
moves. (One sensible way: it keeps the rules testable and next to the data.)

## Design per piece

### 1. Quiet wake + app awareness (shared "may she act on her own" rules)

A new module (e.g. `Engines/Nearby.py` or `ui/aware.py`, builder's call) with pure functions:

- `school_over(now, lessons)`: True when no lesson remains today (after the last `endTime`), or there were none.
  If the timetable can't be read (offline / not set up): weekdays before 16:00 count as school (safe side);
  weekends count as free. *(my call)*
- `may_self_wake(now, lessons, idle_s, last_self_wake, last_input_gap, fullscreen)`: school over, user active (input
  within the last ~10 s), not fullscreen, and either no self-wake yet this afternoon/evening or the user was away
  ≥ 2 h before this activity.
- `app_kind(wm_class, title)`: maps the active window to a kind: code, browser-video (YouTube/Netflix/Twitch in the
  title), browser, mynotion, terminal, game/fullscreen, music, chat, docs, other.
- `pick_reaction(kind, now, history)`: body move and maybe a line; rules: a line at most every ~30 min, the same kind
  not commented twice in a row, lines not repeated until the bank is used up, nothing while she's talking/listening,
  hiding, or within the first minute of a new app (the user may just be passing through), nothing for fullscreen.

A loop (in `main.py` next to the other background loops, or in the overlay; builder's call) polls every few seconds:
idle time and fullscreen state from X, the active window, and today's lessons (cached by Untis). It triggers a
quiet wake through a new path (e.g. `_wake_event` with a `quiet` flag) that skips the LLM greeting and speech; the
greeting line is chosen in code from: time of day, the next test (TestPrep), rain, and a plain "school's done!".
**Companion (user's choice):** a quiet wake stays on screen as long as the user uses the laptop (any keyboard or
mouse input counts, including typing in other apps), sitting, wandering and peeking, reacting now and then, and
falls asleep after ~10 min with no input. A typed message turns it into a normal conversation; after that
conversation she returns to companion mode instead of sleeping after 60 s, while outside school hours.

Body reactions are page acts: glance/turn toward where the active window is (she knows window rects already),
lean in for a video, a small cheer for MyNotion, a sleepy stretch after long coding, etc. The line shows in her
speech bubble, never through `speak`.

### 2. Test card

A prop built in three.js: a paper-coloured rounded rectangle with a slight bend and an outline, text drawn on a
canvas texture (subject + "Thursday"/"tomorrow"/"in 3 days"). Held in both hands (new pose fitted the same way
the knee hug was), raised to chest height, a small tilt and a look at the viewer, ~4 s, then put away. Offered as an
idle while awake when a test is within 7 days, not more than about once an hour; the text comes from Python
(`set_props({test: {...}})`, replayed like other state).

### 3. Umbrella

Prop: canopy from 8 ribbed segments (slightly scalloped edge), thin shaft, J-handle; colour picked to suit her
palette (pink/purple). Animation: reach behind her back, bring it forward closed, open with a quick overshoot
("snap"), rest on her shoulder, twirl now and then; closes and goes away after a while. Shown when the forecast
says rain probability ≥ ~60 % in the next 3 h *(threshold my call)*; refreshed from the weather engine at most every
30 min.

### 4. Bob to music

A small Python reader on the sink monitor (low sample rate, mono) computes an onset envelope, estimates tempo
(60–180 BPM) and beat phase, and sends `{bpm, phase, confidence}` to the page a few times a second. The page bobs
(head nod + slight knee bounce, shoulders) on the beat when confidence is high; fades out when audio stops or
confidence drops. Not while she's talking (her own voice would count as music; mute the reader while speaking).

### 5. Polish existing animations

Separate round after 1–4, with its own review.

## Settled after review (my calls, open to correction)

- **During lessons** (school hours by the timetable) no reactions at all, even if the user woke her by hand: no
  bubble lines, no app body reactions, no props, no music bob. She behaves as today.
- **Calls** count like fullscreen (no reactions, no self-wake): the active window is a call app (Zoom, Teams, Discord,
  Meet/Jitsi in a browser title), or another app is recording the microphone. That check only lists which apps
  record (`pactl list source-outputs`); it never reads audio.
- **Music bob** needs both: a player reporting "playing" over MPRIS (`playerctl status`; Spotify, browsers) and a
  confident beat. A talk video reports "playing" but has no steady beat, so she doesn't bob.
- **Pace of building:** one piece at a time; after each the user tries it and says go before the next (as with the
  window awareness). Commit only when asked; FEATURES.md each piece.

## Left to the builder

Module names and where the loops live, exact cooldown numbers within the ranges above, the line bank text (in her
playful voice, English, short, no more than ~8 words, emoji sparingly), prop geometry details, and how poses for
holding props are fitted (same in-page fitting as earlier poses).
