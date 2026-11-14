# Aria as a 3D anime avatar: design

Date: 2026-11-13. Status: written from the conversation, waiting for Lala's review.

## Why

Aria is a flat painted orb. Lala wants her to be a character: 3D, animated, with things hovering around her. Asked
what kind, they chose a figure over a 3D orb, then an anime character, made by themselves in VRoid Studio.

Earlier the same day Lala had the camera switched off and the microphone made on-request, because Aria doing
things on her own was annoying. So the avatar is something that appears when Lala calls her, not something that
lives on the screen.

## What Lala decided

- Aria becomes a **figure**, an **anime character**, from **their own VRoid Studio avatar** (a `.vrm` file).
- While she is **asleep, the small orb stays as it is now**. The figure appears when she is awake.

- **Full-body motion** (2026-11-13, after the first design): "install only if it is fullbody motion". The avatar
  library exposes the whole skeleton (hips, legs, feet, arms, hands), so the condition holds, the two libraries
  were installed, and the design below shows and moves her whole body.

- **No VRoid avatar** (2026-11-13, later): "i have no experience designing such characters so see what u can do".
  So she is a figure built in code (`ui/avatar/figure.mjs`), with the same full-body movement. A `.vrm` is still
  loaded when one is given, but that path has never been tried on a real file. As built, see `FEATURES.md`
  (Overlay UI): where it differs from this document, `FEATURES.md` is right. Measured memory for the embedded
  browser is about 450 MB, more than the 200 to 300 MB estimated below.

- **A VRM after all** (2026-11-13, evening): Lala downloaded VRoid's sample "AvatarSample_B" and asked for it to
  be used. It is at `ui/avatar/aria.vrm` (not in git) and loads through `vrmrig.mjs`, which was tried on it: a
  VRM 0.x file needs its x and z bone angles negated after `rotateVRM0`. The built-in figure stays as the fallback.

Everything else below is my proposal.

## Goals

- When Aria wakes, the orb gives way to the avatar, about 300 × 400 pixels, standing with her whole body in view,
  in the corner where the orb sits. She waves hello as she appears. When she goes back to sleep, the avatar leaves and the orb is back.
- She looks alive without being busy, with her whole body: she blinks, breathes, shifts her weight from one leg
  to the other with her feet staying put, her arms swing a little, her hair and clothes move, and her eyes and
  head follow the mouse.
- Each state reads at a glance:
  - **listening** (microphone open): leans in slightly, head tilted, hands brought forward, small nods with the
    microphone's volume
  - **thinking**: looks up and to the side, weight on one leg, a hand toward her chin
  - **speaking**: mouth opens and closes with her voice's volume, forearms lifted a little, relaxed face
  - **alert** (a reminder goes off): eyes wide for a moment and a real hop: knees bend, she leaves the ground, lands
  - **awake and waiting for typing**: neutral idle
- **Things hovering around her mean something.** Small objects travel on a tilted ring around her, passing in
  front of and behind her:
  - a clock while a timer or focus session runs
  - a note while a reminder is waiting today
  - a microphone while she is listening
  - three dots while she is thinking
  Moving the mouse over one makes it grow and shows a short caption (the time left, the reminder's text).
- Everything the orb does today keeps working around the avatar: click her to type, drag her to move, right-click
  for the menu, hover for the last messages, speech bubbles, cards, the countdown.

## Non-goals

- Real lip sync by sound (mouth shapes per vowel). Volume-driven mouth only.
- Walking around the screen, sitting, dancing, motion-capture clips, outfit changes. Her movement is worked out in
  code (`logic.mjs`), not played from recorded animations.
- Her face showing the mood Aria's emotion engine works out. Possible later; not now.
- Making or choosing the avatar. Lala makes it; nothing is downloaded from model sites.
- Wayland. The laptop runs X11 (Cinnamon); the overlay's click-through is X11-only already.

## Anti-goals (this would make it a failure even if it works)

- She moves, renders or uses the processor while asleep or hidden.
- Aria fails to start, or the overlay breaks, because the avatar file, the 3D library or the graphics are missing.
- The avatar's rectangle swallows clicks meant for the window behind it.
- Starting Aria gets noticeably slower.

## Constraints and what is known

- A throwaway test on this laptop (2026-11-13) showed: WebGL in a `QWebEngineView` inside a frameless, translucent,
  always-on-top window renders hardware-accelerated at 61 fps on the built-in AMD Radeon 780M (not the NVIDIA card
  the language model uses); the background is see-through; a `setMask` on that window is honoured by X11.
- `setMask` sets the window's *bounding* shape: it clips what is drawn as well as where clicks land, with 1-bit
  edges. Fine for a round orb and rectangular bubbles, wrong for hair and soft outlines.
- PySide6 6.12 is installed with QtWebEngine. Node 24 is on the laptop (used for tests only).
- The 3D needs two open-source libraries, both MIT: `three` and `@pixiv/three-vrm`. Lala gave the OK on
  2026-11-13 on the condition above; `three` 0.187.0 and `@pixiv/three-vrm` 3.5.5 are in `ui/avatar/vendor/`
  (six files, 3.2 MB, listed in `VERSIONS.md`).
- VRoid Studio exports VRM 0.x or 1.0; `three-vrm` reads both and normalises them.
- The overlay's embedded browser costs roughly 200 to 300 MB of memory while Aria runs.
- The project's rules: a missing device only disables its feature (`Aria._try`); tests need no display hardware,
  network or model; `FEATURES.md` is updated with every feature.

## Approaches

1. **three.js and three-vrm in a `QWebEngineView` inside the existing overlay window (picked).** VRM is a web-first
   format: this pair gives expressions, eye and head look-at, and hair physics out of the box. The orb, bubbles,
   cards and text box stay the Qt code they are. Cost: the embedded browser's memory, and a JavaScript part in a
   Python project.
2. **Qt Quick 3D, native.** No browser. But Qt has no VRM support: the file would have to be converted to glTF and
   expressions, look-at and hair physics rebuilt by hand. Weeks more work for a worse result.
3. **A separate avatar program** (its own window and process) that Aria talks to over a socket. Isolated, but two
   windows have to be kept aligned, dragged together and stacked correctly, and it is the heaviest.

Lala left the how to me; I picked 1.

## Design

### Where the avatar file lives

- `ARIA_AVATAR` in `Engines/.env` is the path of the `.vrm`. Default: `ui/avatar/aria.vrm`.
- `*.vrm` is gitignored (my call: it is 10 to 30 MB and Lala's own art; they can decide to commit it).
- `ARIA_AVATAR=0` turns the avatar off. No file, no QtWebEngine, the libraries missing, or WebGL failing → Aria
  runs with the orb only, and the self-check (`Engines/Health.py`) says which of these it is.

### Parts

- **`ui/avatar/`** (new):
  - `avatar.html`: one transparent page with a canvas.
  - `avatar.js`: loads the model, runs the render loop, applies poses. Thin: it reads targets from `logic.mjs`.
  - `logic.mjs`: pure functions with no three.js in them: state → pose targets (bone angles, expression weights),
    blink timing, mouth weight from a volume, which props show, ring positions. Tested with `node --test`.
  - `vendor/`: the pinned builds of `three` and `three-vrm`, committed, with a `VERSIONS.md` saying which versions
    and where from. Loaded from disk; the page never touches the network.
- **`ui/avatar_view.py`** (new): `AvatarView(QWebEngineView)`.
  - `AvatarView.available(path) -> (bool, why)`: can it work at all (file, libraries, QtWebEngine import).
  - `set_state(state)`, `set_level(mic, out)`, `look_at(x, y)` (−1…1 from the avatar's centre), `set_props(list)`,
    `pause()`, `resume()`. Each is one `runJavaScript` call into a small `window.aria` API. Calls before the page
    is ready are kept and replayed, last value per kind.
  - The page reports `ready` or `failed: <why>` once through a `QWebChannel` or a polled value (builder's choice).
  - Mouse events are not handled by the view (`WA_TransparentForMouseEvents`): the `Overlay` widget keeps handling
    clicks, drags, the menu and hover exactly as for the orb.
- **`ui/overlay.py`** (changed):
  - Owns one `AvatarView`, created at startup only when `available()`; loaded hidden and paused.
  - A single rule, `Overlay._shows_avatar()`: avatar is ready and the state is not `sleeping`, `booting` or `error`.
    When true the orb is not painted and the view is shown and resumed; when false the view is hidden and paused
    and the orb is painted as today. The switch is a 250 ms cross-fade (window opacity of the view).
  - The avatar's box is anchored where the orb is (bottom-right of the window). `WIN_W`/`WIN_H` grow as needed;
    bubbles, caption, text box and cards are laid out against the avatar's box when it shows and against the orb
    otherwise. Saved positions keep meaning "where the orb's centre is".
  - Feeds the view from what it already has: the state signal, `bridge.mic` / `bridge.out` levels (at most 20
    times a second), the mouse position (at most 15 times a second, only while the avatar shows), and the props
    worked out from `bridge.timers` and the state.
  - The existing hidden-start rule stays: started with `--hidden`, nothing is shown or rendered.
- **`main.py`** (small change): today the UI state is `listening` whenever she is awake, whether the microphone
  is open or she is only waiting for typing. The avatar has to tell these apart, so the UI interface (`NullUI`,
  `OverlayBridge`) gets `set_mic_open(bool)`, called wherever `Aria._uses_mic()` changes: on a typed `listen`,
  on `stop listening`, in `_go_to_sleep`, and once at start in `--voice` mode. The avatar's listening pose and the
  microphone prop show only while it is true; awake with the microphone closed is the neutral idle. The orb ignores
  it and behaves as today.
- **Clicks.** While the avatar shows, the overlay stops using `setMask` and sets the X11 *input* shape instead
  (XFixes `SetWindowShapeRegion` with `ShapeInput`, called through `ctypes`): the same rectangles as today for
  bubbles, text box, caption and card, plus an ellipse over the avatar's head and torso. The picture is not clipped;
  clicks beside her pass through. If the XFixes call isn't available, fall back to `setMask` with the avatar's
  whole rectangle and say so in the self-check. While the orb shows, `setMask` stays exactly as it is.

### How she moves (`avatar.js` with `logic.mjs`)

- On load: arms are lowered from the T-pose to a rest pose; the camera frames her whole body, feet to hair, with a
  little room above for the hop.
- Her body is driven through thirteen bones (`BONES` in `logic.mjs`: hips, spine, chest, neck, head, both upper
  and lower arms, both upper and lower legs). `poseFor(state)` gives the pose, `idleMotion(t)` is added on top,
  and a running `gesture('wave' | 'hop', t)` replaces bones by its weight and lifts her whole body.
- Always while shown: breathing (chest), a slow shift of weight (the legs lean against the hips so her feet stay
  where they are), blinking every 2 to 6 seconds, small eye movements, hair and
  clothes physics from the model's spring bones, look-at toward the mouse (eyes first, head follows partly).
- Per state: pose targets and expression weights from `logic.mjs`, eased over 300 ms so changes never snap.
- Speaking: the mouth expression's weight follows the playback level, smoothed, closed when the level is zero.
- Props: flat-shaded little 3D shapes on a tilted ring; each fades in and out; depth-tested so they pass behind her.
- Rendered at 30 fps. `pause()` stops the render loop completely; `resume()` restarts it.
- A model that lacks an expression or bone the code wants (models differ) is tolerated: that movement is skipped.

### Errors

- The page fails to load the model or WebGL → it reports `failed`, the overlay never shows the view, and the
  problem is logged once with `Diagnostics.problem("avatar", why)`.
- The web process crashes while running → the overlay hides the view and uses the orb for the rest of the session.

## Tests

- `tests/test_avatar.py` (Python, off-screen, no web page): `available()` for each missing piece; `_shows_avatar()`
  per state and for a failed or absent view; what the overlay sends on a state change, on levels and on timers
  (against a fake view that records calls); queued calls replayed after `ready`; hidden start never resumes;
  the click regions computed for avatar and orb (as pure geometry, without calling X11).
- `ui/avatar/logic.test.mjs` (`node --test`): pose targets per state, blink schedule, mouth weight, prop list.
- Not covered by automatic tests: how she looks and moves. That is checked by Lala in the running overlay
  (`.venv/bin/python -m ui.overlay`, the demo mode that needs no AI), and the plan ends with that check.

## Order of work

1. The libraries (with Lala's OK to download), `logic.mjs` and its tests.
2. The page showing a model in rest pose with idle life. Needs a `.vrm`.
3. `AvatarView` and the overlay switching between orb and avatar, with fallbacks.
4. States, mouth, look-at.
5. Props on the ring, with hover captions.
6. Click regions through XFixes.
7. Self-check, `FEATURES.md`, the check in the running overlay.

## Open, and whose it is

- **The avatar file: Lala.** Steps 2 onward need it. Until it exists, step 1 and the Python side of step 3 can be
  built and tested; nothing can be seen.
- **VRoid Studio on Linux: unverified.** It has no Linux version; it may run through Steam's Proton, or on another
  Windows, Mac or iPad device.
- **The bone angles are untested on a real model.** `logic.mjs` fixes which way each pose goes and its tests pin
  that, but the numbers (how far an arm comes down, which axis bends an elbow on this model) can only be tuned by
  eye once there is a `.vrm`. Expect a round of tuning in step 2.
- **How a full character performs** on the AMD graphics: the test used a single triangle. Expected fine; measured
  in step 2. If it is too slow, the first lever is the render size, then hair physics.
- **XFixes input shape with a web view inside the window:** standard on X11, not yet tried here. Fallback above.

## Left to the builder

Exact bone angles and easing, ring size and tilt, prop shapes, how the page reports readiness, the library versions.
