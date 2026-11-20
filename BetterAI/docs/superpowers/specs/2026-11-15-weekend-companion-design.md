# Weekend companion: Aria starts chats on free days

## Why

On weekends, at the laptop, Lala is bored. On free days Aria should feel more alive and sometimes motivate them to
do things. Today the companion (`Engines/Companion.py`) is deliberately quiet: she greets once, makes a gesture
about every 5 min, and shows a fixed line in a bubble about every 30 min. She never speaks and never runs the model.

## Goals

- On free days she **starts conversations** now and then in a speech bubble. You can ignore it, or click her and
  type to answer.
- Some of those openers **nudge** you towards something real: a test coming up, an event or reminder today, or a
  break from a long video or game stretch.
- She **moves more** on free days.

## Non-goals / anti-goals

- No speaking out loud and no microphone: the bubble only (approach B was rejected).
- Never on school days before school ends, never in quiet hours, during fullscreen, a call, a game, or with the
  screen locked. Same guards as the companion.
- It must not nag. Ignored openers make her back off, and nudges are at most every other opener.
- No stock-assistant lines ("How can I help you today?"). An opener is a remark or a question a friend would make.
- Nothing goes to the big model (calendar and reminders are involved). Local model only.

## Approaches

- **A. Bubble openers, topic picked in code, wording by the local model (picked).** It's light on the laptop, and
  it fits the project's habit of deciding in code and leaving only the wording to the model.
- B. Spoken openers that listen for a reply. More alive, but they interrupt music and videos and talk when people
  are around.
- C. The model decides everything. The most varied, but it runs the heavy model often, and the small model drifts
  into stock-assistant lines.

## Design

**Free day:** WebUntis shows no lessons today (`school_span` is `None`, which also covers holidays), or it's
Saturday or Sunday when the timetable can't be read. A pure function `free_day(now, span)`.

**When an opener comes** (pure function, tested):
- She is on as the companion, and you are at the laptop (input in the last 10 s).
- The app in front has been there at least a minute, and it isn't a call or game, fullscreen or quiet hours.
- At least 10 min after her wake greeting, then one every 25–45 min (random).
- When you didn't answer the last two, the gap doubles, up to 2 h. Answering resets it.
- At most 8 a day.

**What it's about** (picked in code, recorded so the same topic doesn't come twice in a row):
- *Nudges* (at most every other opener): a test in the next 3 days (TestPrep cards), an event or reminder still
  ahead today (`reminders.pending`), or 60+ min in a video or game app.
- *Small talk*: the app in front (the existing kinds), the time of day (lunch, evening), the weather, music
  playing, or a random light topic from a short list.

**Wording:** one local-model call (`LLMEngine`, no tools, a short dedicated prompt with the picked topic and its
facts) asks for one casual sentence, at most ~20 words. It goes through `tidy_reply` and `ROBOTIC_RE`.
- On failure, a robotic reply or the model being busy, she uses a fixed template for that topic instead.
- The call happens only while Aria is asleep, with the turn lock free (otherwise the opener waits for the next tick).

**Showing it:**
- `ui.message("aria", text)`, with a gesture that fits the topic.
- It is saved to history the same way as announcements (`memory.save_message`, `_session_convo`, `_recent`), so
  if you click her and type, she knows what you're answering.
- A reply counts as "answered" for the back-off.

**More alive:** on free days her app gestures come every 2.5 min instead of 5.

**Switch:** `ARIA_WEEKEND_CHAT=0` in `Engines/.env` turns the openers off.

**Where:** rules and topic picking go in `Engines/Companion.py` (or a small `Engines/Openers.py` if it grows),
and the model call is passed in as a callable. Tests follow `tests/` patterns with no model. `FEATURES.md` gets
updated.

## Left to the builder

- The exact template lines and small-talk topics.
- The gesture for each topic.
- How "answered" is detected: a user turn within 10 min of the opener.
