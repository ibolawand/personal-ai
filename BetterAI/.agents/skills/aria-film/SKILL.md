---
name: aria-film
description: Use to see Aria's avatar without starting Aria: screenshots of a moment, a frame-by-frame contact sheet of a gesture, or measuring where her hand/head is to fit a pose. Needed to check any change in ui/avatar/ by eye.
---

# Filming and measuring Aria's avatar

Filming needs the X display: Claude runs you with full access (`--sandbox danger-full-access`) for these tasks. View
the PNGs you make yourself (your image viewing tool) and judge them; don't hand the looking back to Claude.

`tools/avatar_look.py` shows her page in a small window and runs timed steps (read its docstring):

    .venv/bin/python tools/avatar_look.py OUTDIR [--figure | --model FILE.vrm] [--seat X,Y,W,H] 'js|ms|name' ...

- A step is `javascript|milliseconds-from-start|name`; with a name it saves OUTDIR/name.png 350 ms later.
- Her model loads first: act after ~3000 ms. Start with `window.aria.setState("idle");window.aria.lookAt(0,0)|2800|`.
- Calls: `act("tuckHair:1")` (a gesture, `:1`/`:-1` side), `startle(-1)`, `tapped()`, `setState(...)`,
  `setLevel(mic,out)`, `setSpeech(segments, 0)`, `setPointer(x,y,moved)`, `setTyping(true)`, `typed()`,
  `setEngaged(true)`, `setBeat(bpm, nextIn, conf)`, `act("perch")` (with `--seat`), `debug()`.
- **Quit the real Aria first** (`./aria.sh --quit`): her own window shows up in screen grabs. Ask Claude/Lala before
  quitting it if the prompt didn't say you may; restart it afterwards (`aria-restart`).
- `ARIA_LOOK_SNAPSHOT=1` draws shots from the page itself (no window can cover them) but its timing is loose; for
  motion use the normal grabs.
- Avoid `name*N`: it grabs the whole screen area and catches other windows.

## A contact sheet of a gesture
Take named steps every 120–300 ms across the gesture (e.g. 16 frames), then tile them:

    .venv/bin/python - OUTDIR <<'PY'
    import sys, glob; from PIL import Image
    d = sys.argv[1]; fs = sorted(glob.glob(d + '/f*.png'))
    ims = [Image.open(f).crop((10, 40, 240, 340)) for f in fs]; w, h = ims[0].size; cols = 8
    s = Image.new('RGB', (w * cols, h * ((len(ims) + cols - 1) // cols)), 'white')
    for i, im in enumerate(ims): s.paste(im, ((i % cols) * w, (i // cols) * h))
    s.save(d + '/sheet.png')
    PY

Judge it as an animator (aria-avatar-animation's craft rules): paths of the hands, what leads and trails, arms
sticking out, hands crossing the face, things too small to see, pops between frames.

## Measuring a pose (fit before you code it)
`window.aria.tune({leftUpperArm: [x,y,z], leftLowerArm: [0,y,0]})` pins bones; `tune()` lets go.
`(window.ariaLog ||= []).push(window.aria.where("head", "leftHand"))` logs world positions (printed at the end).
On the VRM: head bone y ≈ 0.80, chest ≈ 0.63, hand at rest ≈ (0.10, 0.46, 0.01); z is toward the viewer. Try a few
candidate poses in one run (a step per pose, ~1.2 s apart), log the hand, save a shot of each, pick the one that lands
where it should, then use those numbers.
