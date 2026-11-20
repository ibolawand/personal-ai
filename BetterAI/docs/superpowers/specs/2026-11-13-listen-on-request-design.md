# Listening only on request: short design

Date: 2026-11-13. Status: approach picked by Lala in conversation ("One conversation").

## Why

With `ARIA_ARGS=--voice` the microphone is always on: it waits for "Hey Aria" and, once she is awake, transcribes
whatever it hears. Lala wants her to stay quiet and deaf until they say so, the same wish that switched the
camera off. The microphone should open only when Lala types that she should listen.

## What Lala gets

- Aria starts in typing mode: the microphone is closed and the wake word doesn't run.
- Typing `listen` (also `listen to me`, `start listening`, `voice on`, `mic on`, `hör zu`, `hör mir zu`) in the
  orb's text box, the terminal or MyNotion's Aria panel opens the microphone. She answers "I'm listening." and
  from then on transcribes what is said and answers, as voice mode does. Typing keeps working meanwhile.
- The microphone closes when she goes back to sleep (about 20 seconds of silence, "go to sleep") or at once on
  `stop listening` (`voice off`, `mic off`, `hör auf zuzuhören`), typed or spoken. To talk again, type `listen`.

## Not wanted

- No wake word in this mode, and nothing that opens the microphone by itself.
- A message from the phone (Telegram) can never open the microphone.
- `listen` inside a longer sentence ("listen to this song") is an ordinary message.

## Approaches

1. **One conversation (picked).** `listen` opens the microphone until she sleeps. It can't be left on by accident.
2. Until `stop listening`: voice mode, wake word included, stays on. Less typing, but it is always-on again until
   switched off.
3. One spoken message per `listen`. Safest, but a spoken follow-up needs typing every time.

## How

- Matched in code in `Aria._handle_turn` (after a pending yes/no and a running quiz), never by the model: whole
  message only, punctuation and a leading "Aria," / "please" ignored.
- A flag `Aria._ears`; `Aria._uses_mic()` is true in `--voice` mode or while the flag is set. The main loop's input
  branch, its greeting and its "Going to sleep." line go by `_uses_mic()` instead of `--voice` alone.
  `_go_to_sleep` clears the flag. From the panel the flag also wakes the main loop, without a greeting.
- `--voice` keeps its meaning (always listening, wake word). `ARIA_ARGS` in Lala's `Engines/.env` loses `--voice`.
- In `--voice` mode the two phrases are ordinary messages.
- No tool, prompt or routing change. Tests: `tests/test_listen.py`. `FEATURES.md`: Voice section.

Left to the builder: exact regexes, the wording of "already off".
