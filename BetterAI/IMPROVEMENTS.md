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
| 15 | **Real-model checks** | Opt-in `pytest -m model` (ARIA_MODEL_TESTS=1): 15 commands must call the right tool and 3 small-talk lines must sound like a friend. 18/18 in 4 of 5 runs; the claim check now also catches "lowering it now"-style replies. | `tests/test_model.py` |
| 16 | **Checking Wi-Fi without switching it** | "Is Wi-Fi on?" used to call `set_wifi` (which switches it). A read-only `network_status` now answers: network name, Bluetooth and connected devices. Added to the real-model checks: 19/19. | `tests/test_laptop_files_web.py`, `tests/test_model.py` |

## Things I noticed along the way

- **The personality change had quietly broken some commands.** Aria said "I'll turn the volume down" without doing
  it. The new real-model checks (#15) caught it, and #14 fixed it. Run `ARIA_MODEL_TESTS=1 .venv/bin/python -m pytest -m model`
  after changing her instructions.
- **Tool descriptions filled two thirds of the model's context** on every turn. Routing (#14) brings that down to
  1,300–2,300 tokens.
- **Kokoro mispronounced** "C#", "MyNotion" and "VS Code". I could only check this through its phonemes, not by
  listening, so tell me if something still sounds wrong.

## Left for later (they need you)

- **Spotify likes and playlists** ("like this song", "add to my study playlist"): need extra Spotify permissions,
  so you'd have to log in to Spotify again once.
- **Search in MyNotion**: the sidebar is where it belongs, and you have uncommitted work there I didn't want to touch.
- **German**: Whisper could understand it, but Kokoro has no German voice, so Aria would answer in English.
- **Pushing to GitHub**: blocked for me. Run `git push origin main` in both repos when you want it online.
- **The new shortcut** (Ctrl+Alt+N): run `./install_desktop.sh` once to register it.
- **Weather**: tell Aria once where you live ("I live in Vienna").

## Numbers

- Tests: 215 fast ones (~14 s) + 19 opt-in real-model checks (~40 s).
- Tool prompt per turn: 5,487 → 1,278 tokens (small talk) / 2,297 (lists).
- Screen look: never worked (model missing) → ~9 s.

## Night run with Codex (2026-11-18)

Built on my own with Codex as the ideas partner and reviewer (Codex ran read-only and never wrote files). Ranked by
what you value: detailed animation, how alive she feels, how human, how useful. Nothing here is committed.

| # | Improvement | What it does | What Codex did | Tests |
|---|---|---|---|---|
| 1 | **Tucking her hair behind her ear** | A new idle gesture (also on a window): head tips first, elbow-led reach, fingertips sweep from temple to behind her ear while her head leans into her hand, a small smile, elbow drops first, fingers relax last. Arm fitted on her model by measuring fingertips against her head. | Picked it as the top idea and set the timing; the review caught a glance that went up instead of down, and that the head's anticipation was hidden behind the arm's blend weight (now gestures can lead with some bones: `weights`). | `logic.test.mjs` (tucking her hair…) |
| 2 | **She has weight when you drag her** | Picked up: legs hang loose, toes down, arms out for balance; dragged sideways her legs trail and her back counter-leans, swinging through on a turn and settling when you stop; put down, her knees give. | Proposed it (second pick) with the timing; the review caught that the swing went the wrong way (feet led the push), that a lost mouse release would leave her carried forever, a crouch in mid-air when grabbed again right after a drop, and a stroll that kept walking while she dangled. All fixed. | `logic.test.mjs` (carried: …), `tests/test_avatar.py` (drag, lost release) |
| 3 | **Tired late at night, and nodding off** | From 22:00 heavier lids, slower blinks, slower idle and breath, more yawns; now and then she nods off and starts awake (chest, neck, head, eyes wide, two blinks, a sheepish smile). | Narrowed my bigger idea to this first version (one rare doze, idle only, long cooldown, recovery from the chest up). The review caught that the doze replaced her sitting pose instead of adding to it (now gestures can add on top: `adds`) and that her usual blinks could hide the wake-up (now the doze owns her blinks). | `logic.test.mjs` (tired…, nodding off…) |
| 4 | **An almost-sneeze** | Rare idle moment: chin up, eyes squint, a cupped hand over her nose, two breaths in, a frozen beat... nothing; relief, the elbow drops first, fingers open last. | Proposed it with the beat-by-beat timing (stillness, second inhale, uncertain hold, relaxed release). The review found that made-up names sent to `act()` would pile up in the cooldown record; fixed. | `logic.test.mjs` (an almost-sneeze…) |
| 5 | **Crossing her ankles on a window** | On an ordinary window edge her swing dies away, one knee lifts to clear, the foot crosses in front of the other ankle, a rest with a toe wiggle, then back to swinging. | Proposed it (fifth pick) with the clearance lift and trailing toes, and scoped it to ordinary edges. The review caught that a crossing kept going through a hop down or a lost seat; now one rule (`crossFits`) both refuses and fades it. | `logic.test.mjs` (crossing her ankles…) |

**Ideas we dropped:** humming/swaying silently (Codex: without sound it's only a sway, which `rock` and the idle
sway already cover); noticing the cursor near her (mostly exists: her eyes and head already follow the mouse);
heel taps on the window (a variation of the leg swing, needs contact fitting); a startle when a window opens next to
her (good, but the overlay doesn't yet tell her about new windows nearby; a later idea).

## Second run with Codex (2026-11-18, afternoon)

Same setup as the night run: Codex proposed and reviewed read-only, Claude built. This time Codex steered away from
more one-off fidgets toward her reacting to what really happens. Nothing here is committed.

| # | Improvement | What it does | What Codex did | Tests |
|---|---|---|---|---|
| 1 | **Breaking off a fidget in order** | Interrupted mid-fidget, she no longer fades everything at once: eyes to you at once, head and neck, then chest; arms from the shoulder out, fingers last; a hand at her face comes away first; a doze wakes from the chest up. She lets go of the pose she was in (the gesture's clock stops at the cut). | Top pick, with the timing. Seen by eye: with the elbow opening well before the arm dropped she held a straight arm out sideways, so the two now overlap. | `logic.test.mjs` (broken off…, woken from a doze…) |
| 2 | **A window beside her makes her flinch** | An app window opened or moved right beside her while she stands still: eyes there with a blink, near shoulder up, chest back and away, forearm up, then she looks it over and relaxes with a small smile. At most every 20 s; her own walking doesn't count. | Revived its dropped idea with a tight scope. The review caught that her body leaned *toward* the window (sign of the tilt) and that a window moved across her to the other side was missed. | `logic.test.mjs` (a window come up beside her…), `tests/test_desktop_windows.py` |
| 3 | **Watching you type** | With the text box open each key brings her eyes, then her head, down to the box and she leans in; 1.5 s after your last key she looks back at you; in a long pause one glance aside. She's told only that a key was typed. | Proposed it with the timing and the "empty box isn't typing" rule. | `logic.test.mjs` (typing to her…) |
| 4 | **Listening nods at your pauses** | Instead of a nod on a 7.7 s clock: one small dip (or, every other time, a tilt) when you pause after saying something, at most every 7 s. | Proposed it. The review caught that each new turn forgot the last nod, so quick back-and-forth got a nod every turn and never the tilt. | `presence.test.mjs` (listening…, between turns…) |
| 5 | **Getting into music and noticing it stop** | Head joins after a second of beat, shoulders (leading her head by 80 ms) and body after; fuller and lighter over a 12 s phrase; a song she was into stopping gets a puzzled "huh?" tilt. | Proposed it. The review caught that the "huh?" also played when the music came back during a walk, or on top of walking, carrying or a duet. | `logic.test.mjs` (getting into music…) |

**Left open:** the built-in figure has no shoulder bones, so the shoulder parts of #2, #4 and #5 only show on the VRM
(Codex's review point; she normally runs as the VRM). Seen by eye: #1, #2 and #3. Not seen: #4 needs a real
microphone, and in the film for #5 she went for an idle walk mid-song. Tell me how they feel.

## Third run with Codex (2026-11-18, evening)

Same setup: Codex proposed and reviewed read-only, Claude built. Nothing here is committed.

| # | Improvement | What it does | What Codex did | Tests |
|---|---|---|---|---|
| 1 | **Gestures for a whole thought** | Speaking, her arm makes one point per phrase around a stressed vowel (upper arm first, elbow after, a beat on the vowel, held to the phrase end, wrist let go last), replacing an arm offer on a 6.8 s clock. Decided from her voice's timeline, never from meaning. | Top pick, with the timing. The review caught that the last gesture vanished when the timeline ended, that a new gesture could pop up during the last one's release, and that it kept going while she was carried. | `logic.test.mjs` (speaking…, one hand lets go…) |
| 2 | **Trying to catch the mouse pointer** | The pointer still beside her within reach: eyes on it, an IK reach that stops just short with her index finger out and a small smile; if it moves away her hand follows a split second, a moment's surprise, and she lets go. Once per visit, every 90 s at most. | Proposed it. The review caught that measuring her arm overwrote where her hand had gone, so the hand dropped instead of letting go over a second. | `logic.test.mjs` (the pointer…), `tests/test_avatar.py` |
| 3 | **Brushing a speck off her sleeve** | Rare (8 min), standing: looks at a forearm, lifts it, the other hand brushes along the sleeve twice (long, lift, short) by IK on her own arm, arms down in order, head last. | Proposed it with beat-by-beat timing. | `logic.test.mjs` (brushing…) |
| 4 | **A breath after a longer walk** | After a walk of 4 s or more she finished: one fuller breath (chest, spine, head), a slow breath out, her own breathing quiet meanwhile. | Proposed it (small). The review caught that it went on under a gesture, the piano or being carried. | `logic.test.mjs` (after a longer walk…) |
| 5 | **When you click her** | A blink, a little give backward with her head trailing, forward a touch, a head tilt (0.8 s); a drag doesn't count, repeated clicks don't make her bounce. | Proposed it (small) with the event rules (click only, never replayed). | `logic.test.mjs` (clicked…), `tests/test_avatar.py`, `tests/test_overlay.py` |

**Seen by eye:** #1 (small, readable), #2 (reach, finger, smile) and #3 (reads as brushing). **Not seen:** #4 is too subtle
for stills, and #5 and the pointer escape only by numbers. Tell me how they feel.


## Fourth run, built by Codex (2026-11-18, night)

Three additions, chosen and implemented autonomously under the owner's authorization. Nothing committed.
Existing neck easing and quiet glances were also checked so these do not repeat them.

| # | Improvement | What it does | Tests |
|---|---|---|---|
| 1 | **Spreading her fingers** | Looks down, lifts one hand in stages, turns the wrist, fans index through little finger with the thumb last, holds, curls back and lowers the arm with the wrist trailing. Standing only, after 25 s quiet, at most every 4 min. | `logic.test.mjs`: part order, finger order, hold and return, picker thresholds/history/cooldown, mirrored motion, continuity at 30/60/144 Hz, interruption and posture gates. |
| 2 | **Easing an ankle on a window** | Quiets the swing, lifts one shin, makes two ankle circles (second smaller), relaxes the foot before lowering the shin, returns to swinging. Ordinary edges only, after 25 s seated, at most every 3 min. Hips and thighs stay seated. | `logic.test.mjs`: clearance before rotation, two circles, smaller second circle, foot before shin release, seat/corner/panel gates, cooldown, continuity and cancellation. |
| 3 | **Letting a long thought go** | After at least 6 s thinking and the end of her answer: gentle eye closure, chin dip, softened shoulders, head following through past level, eyes open and a small smile, wrists last. Only at an idle ending; busy endings are discarded, new input clears the pending reaction, long answers expire it, 60 s cooldown across turns. | `logic.test.mjs`: duration threshold, speech deferral, expiry, busy discard, no replay, reset and cooldown across turns at three frame rates, movement order, continuity and cancellation. |

**Implementation:** `logic.mjs`: `GESTURES`, `FIDGETS`, `IDLE`, `PERCHED_FIDGETS`, `chooseIdle`,
`gesture`, new `detailFits` and `thoughtStep`. `avatar.js`: `move` feeds the thought tracker and eligibility gate,
`start` checks physical eligibility; ordinary `cutShort` handles release. No Python changes. Eight new Node tests,
including a real built-in figure smoke test through both sides of all three gestures: missing shoulders, fingers
and feet never throw or produce invalid transforms. The ankle test applies the actual seated base pose.

**Validation:** `node --test ui/avatar/logic.test.mjs ui/avatar/presence.test.mjs ui/avatar/claudelogic.test.mjs`
passes. `avatar.js` also passes the module syntax check. The required `.venv/bin/python -m pytest -q` was attempted:
collection stopped with 19 X11 connection errors (`Operation not permitted`). A second run with
`PYSTRAY_BACKEND=dummy QT_QPA_PLATFORM=offscreen` reached the end, but the app-bridge tests failed because the
sandbox denies binding Unix sockets. This is not a passing full Python suite; it needs a rerun outside this sandbox.

**Not checked by eye:** I cannot watch her move here. The VRM's palm orientation and finger silhouette, the ankle
circles' clearance from the ledge/skirt, and the subtle thought release's pacing need visual review. The built-in
figure has neither individual fingers nor foot bones: only the supporting arm/wrist or shin movement is visible.
No VRM mesh/contact fitting was performed. Use these commands from the project folder (add `--figure` for the
built-in figure; use `:-1` instead of `:1` for the other side):

```bash
.venv/bin/python tools/avatar_look.py fourth-fingers 'window.aria.setState("idle");window.aria.act("fingerFan:1")|3500|' '|3800|fingers*32'
.venv/bin/python tools/avatar_look.py fourth-ankle --seat 1050,380,420,620 'window.aria.setState("idle");window.aria.act("perch")|3500|' 'window.aria.act("ankleEase:1")|7500|' '|7800|ankle*34'
.venv/bin/python tools/avatar_look.py fourth-thought 'window.aria.setState("thinking")|3500|' 'window.aria.setState("speaking")|10500|' 'window.aria.setState("idle")|12500|' '|12500|release*20'
```

For the ankle preview, choose seat coordinates within your display and let her finish reaching the edge before
starting the gesture. To preview just the thought motion without its trigger, use
`window.aria.setState("idle");window.aria.act("thoughtRelease:1")` at 3500 ms. Check interruptions during the hold
as well as natural endings; numbers establish continuity, not how comfortable a movement looks.

## Refinement pass (2026-11-18, late)

- Fixed entry sequencing separately from `armRelease`: upper arm leads elbow by 0.12 s in tuckHair, brace, almostSneeze, checkWrist and the sleeve pose; brushing and pointer IK use forward `armEntry` weights, while fingerFan and phraseGesture retain their existing delayed elbows. Lowered brushSleeve's receiving upper arm to [-0.35, -0.35, -1.25] rad and elbow to 1.35 rad, with `above` at 0.025–0.05 m; mirrored entry/exit geometry tests keep the target below chest height.
- Moved fingerFan away from the face: upper arm [-0.9, -0.35, -0.85] rad, elbow 1.8 rad, inward wrist -0.4 rad; preserved eyes/head/arm/wrist/sequential-finger timing. A representative 30/25 cm articulated arm places the wrist 32 cm forward of the shoulder and 11 cm above it; angle and mirrored geometry regressions pass with all three requested Node suites (owner-VRM visual confirmation still needed).

- Added `armRelease`: upper arm down first, elbow held until at least 60% lowered, wrist and fingers last. Used by hair tuck, brace, almost-sneeze, wrist check, sleeve brush (both arms, including IK), finger fan, phrase gestures and interruption. Face-level interruptions clear forward 0.1 rad before dropping.
- Brought the hair tuck forward with soft sweeping fingers; brace now folds protectively across her chest (1.9 rad elbow); sneeze lifts the chin 0.18 then 0.25 rad with both shoulders and keeps the sleeve below her eyes. Sleeve brushing folds the receiving arm across her stomach (1.75 rad elbow); finger fanning sits forward with the palm inward.
- Made clicks visible: 0.07 rad chest recoil, 0.06 head trail, 0.05 shoulder hitch, surprise then smile and a curious lean/tilt. Thought release now drops shoulders 0.06, settles chest 0.04 and tilts the head 0.05 rad, with a longer smile.
- Speaking brings the upper arm forward 0.35 rad with 0.9 extra elbow bend, sequentially opening fingers, a turning palm and a 0.2 rad vowel beat. The renderer applies returned `bones`, `hands` and tap `face` values.
- Pointer catching reaches farther forward with a lower elbow and passes a normalized wrist-to-pointer direction to IK. Typing eyes move right 0.015 per key (maximum 0.25), resetting after 0.6 s without a key.
- Updated timing/API assertions and added regressions for release order, mirrored face clearance, pose bounds, breath peaks, expressions, finger sequencing, typing reset, pointer direction and IK bend retention. The three requested Node suites pass. Visual filming was attempted on the owner's VRM but unavailable: desktop Qt cannot connect to display :0; offscreen Qt/WebEngine fails OpenGL/context and sandbox startup. These revised poses still need visual review on that model.

## Refinement pass 2 (2026-11-19, Codex, completed after resuming)

Codex filmed about 20 behaviours on the VRM (sheets in the session scratchpad, `codexrefine/`) and judged them itself.
Left unchanged because they read well: crossing ankles, ankle circles on a window, being carried, tuckHair,
almostSneeze, doze, brushSleeve, thoughtRelease. Changed: **fingerFan** (measured: wrist lower and further out, about
y 0.64 / x 0.11 instead of 0.705 / 0.056, most of the palm's roll from the forearm, so the spread fingers read beside
her chest and the hand closes before the arm lowers) and **brace** (the hand fitted below her mouth, elbow 1.7 instead
of 1.9). Tests pinning both were added.

**Completed on resuming:** filmed and inspected all four remaining behaviours on the owner VRM, then repeated
with fixed animation intervals (`aria.pause` / `aria.advance`, page snapshots) to avoid repeated desktop captures.
No further movement changes were justified:
- **Music:** twelve beat reports one second apart at 120 BPM, engaged throughout. The head joins first, shoulders
  and body follow without a pop; the small sway supports the nod. After reports expire the bob fades and the
  brief upward/sideways puzzled tilt reads clearly, then settles. Kept `grooveStep`, `bobMotion`, `afterMusic`.
- **Listening:** two-second bouts at mic level 0.05, then 0.005, eight seconds apart. The first pause gets a small
  dip with a trailing neck/shoulders; the next gets a restrained tilt. Kept `listenStep` / `listenNod`. The preview
  must also supply the mic prop: `setState("listening")` alone correctly stays idle when the mic is closed.
- **Typing:** filmed repeated keys and the pause, including a face close-up. The small eye steps and return to
  the start read as a saccade; the gaze/head return and later aside are comfortable. Kept `typingEyeStep`,
  `typingKeyCount`, `typingAttention`.
- **After a walk:** filmed `act("trip")` with room for a 4.145 s route, then the full 2.8 s recovery. The chest opens,
  chin follows and arms soften before she returns to ordinary breathing; mild rather than panting. Kept
  `settles` / `settleBreath`. Do not set engagement for this preview: it cancels the breath.

**Evidence refreshed on 2026-11-20:** re-filmed and inspected all four behaviours because the earlier scratchpad
was unavailable. Final frames and contact sheets are in `/home/lala/.cache/aria-codex/films/{music,listen,typing,trip}-confirm/`.
`film_remaining.py` in that folder's parent reproduces them from the project directory; `README.txt` describes
the inputs. These previews pause the page and advance one animation clock explicitly, disabling the filming
helper's additional locked-screen catch-up only in the preview subprocess. The preliminary folders without
`-confirm` are not timing evidence. Listening uses `setProps([{kind:"mic"}])`; the trip temporarily fixes its
random route choice to 0.99, producing a 4.145 s walk followed by the full recovery.

No further movement changes were justified, so no new motion rules or tests were added. Existing regressions
cover music sequencing and interruption, listening thresholds/cooldown, typing steps/reset, and breath order,
bounds and eligibility. `FEATURES.md` still describes these retained behaviours accurately. Both required
commands passed again: `.venv/bin/python -m pytest -q` and `node --test ui/avatar/*.test.mjs` (159 Node tests).
Visual checks used scripted inputs, not a live microphone or music source.
Aria was restarted and verified afterwards: PID 245509, started 2026-11-20 03:18:47 local time;
the fresh log confirms Kokoro ready, 106 tools and MyNotion's app bridge, with no startup traceback.
