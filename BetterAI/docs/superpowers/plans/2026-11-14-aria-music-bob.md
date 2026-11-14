# Music bob Implementation Plan

> Executed natively (as the earlier pieces). Spec: `docs/superpowers/specs/2026-11-14-aria-reacts-and-props-design.md`, piece 5 "Bob to music" (approach A: the real beat).

**Goal:** While another app plays music with a steady beat, her avatar nods and bounces on that beat; she stops when the music stops, the beat isn't clear, she speaks, or a lesson is on.

**Architecture:** `Engines/Beat.py`: pure `find_beat(envelope, fps) -> (bpm, phase, confidence)` (onset envelope → autocorrelation over 60–180 BPM → phase by comb), `others_playing(pactl_text, own_pids)`, and `BeatReader` (a thread: `parec` on the default sink's monitor, 8 kHz mono, rolling 8 s, every 0.5 s; reads nothing to disk) gated by `may_listen()` (her avatar is showing, she isn't speaking, no lesson, another app's stream is playing). It sends `ui.set_beat(bpm, next_beat_in, confidence)` (or `set_beat(0, 0, 0)` once when it stops) → overlay signal → `AvatarLink.set_beat` → `window.aria.setBeat(bpm, inS, conf)`. The page keeps its own beat clock and adds `bobMotion(phase, amount)` (logic.mjs) on top of idle/talk, faded by `amount`, only while she stands or sits, not walking/jumping/gesturing.

## Global Constraints
- Bob needs: another app's stream uncorked (`pactl list sink-inputs`, not Aria's own process; replaces MPRIS since playerctl isn't installed) AND confidence ≥ 0.35. Off-beat is worse than none.
- No audio stored or sent anywhere; only bpm/phase numbers reach the page.
- Muted while she speaks (her voice) and during lessons. Commit only when asked; FEATURES.md.

## Review Focus
1. Music pauses: bob fades out within ~1 s; no stuck nodding.
2. A podcast/talk video: low confidence → no bob.
3. parec missing / no monitor source: no bob, no crash, no busy loop.
4. Half/double tempo: bpm folded into 80–160 for the nod so it never looks frantic.
5. Page reload: beat flag isn't replayed stale (bob state is live only).

### Task 1: `find_beat` + `others_playing` (TDD, synthetic click tracks at 90/120/150 BPM, noise → low confidence)
### Task 2: `BeatReader` loop + `may_listen` + UI plumbing (`set_beat` on NullUI/bridge/link), tests with a fake reader
### Task 3: `bobMotion` in logic.mjs (node tests: head down on the beat, zero when amount 0), wired in avatar.js
### Task 4: Check by eye with real music, FEATURES.md, restart
