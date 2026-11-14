# Aria aware of the apps on the screen: design

2026-11-14. Status: proposed.

## Why

The avatar (`ui/avatar/`) moves about the screen and has many idle movements, but she isn't aware of what is around
her and can't interact with it: apart from sitting on top of a window, the open apps and the mouse don't exist for
her. The user wants her to treat apps (and the mouse) as real things in her space, starting with **showing up from
behind an open app**. More ideas are welcome, built **one at a time**, each finished and checked before the next.

## Goals

1. **Peeking from behind an app** (built first, designed in full below).
2. **Leaning on an app**: standing beside a window, she rests a hand or shoulder against its side edge.
3. **Windows moving near her**: dragging the window she sits on makes her sway and hold on; dragging a window into
   her makes her step aside or duck.
4. **The mouse as a thing**: poking her gets a reaction, shaking the cursor fast near her makes her dizzy, a cursor
   left still a long time may get a visit.

Items 2–4 get their own short design when their turn comes; the order is the one above.

## Non-goals and anti-goals

- No camera (it stays off) and nothing that makes her wake by herself.
- She never reads what is *in* other windows (titles, contents): only where they are.
- Never in the way: her text box, bubbles and cards are never hidden or cut; clicks on the app in front of her go
  to the app.
- No popping: being hidden and coming out are smooth, like every other movement.

## Approaches (for "behind")

- **A. Cut her out (chosen).** She stays on top of everything; wherever the app she is behind covers her box, her
  picture isn't drawn. Independent of the window manager, and her bubbles and text box stay visible.
- **B. Put her window under the app's in the window stack.** Truly behind, but Cinnamon may refuse or reorder it,
  and her bubbles and text box would be hidden with her.

The user chose A.

## Design: peeking from behind an app

**What she does.**
- *On her own (idle):* when a window stands on her "floor" line next to her (it covers the height of her box and
  has a free side edge within walking reach), she may walk toward it and go behind it: past its edge she
  disappears. Just behind the edge she stops, turns to face you, leans out sideways so her head and a shoulder show
  past the edge, looks at you (a blink, a small smile, sometimes a little wave), leans back in, and walks back out
  the way she came.
- *As a reaction:* when you open or raise a window over her (it covers the middle of her box while she stands
  there), she is behind it: hidden, she walks to its nearer side edge and peeks out the same way, then walks out.
  Talking to her while she's behind brings her out at once (she steps out from the nearer edge).

**Cut-out.** The overlay knows the window she is behind (`ui/desktop_windows.open_windows`) and her box on the
screen; while she is behind one it sends the page that window's rectangle relative to her box, every tick (her
window and the app can both move). The page applies it as a CSS `clip-path` on her canvas (the whole box minus that
rectangle), so exactly the covered part isn't drawn. Clicks: the covered part of her outline is taken out of the
overlay's X input shape, so those clicks reach the app.

**Who decides what.**
- Overlay (`ui/overlay.py`): finds windows she could go behind (side edges within reach on her floor line, the
  window reaching from above her head to below her feet; not maximized/fullscreen/minimized, as for seats), notices
  a window raised over her, sends both to the page, sends the cut-out rectangle while she is behind, and moves her
  window as the page reports (the existing `Travel`).
- Page logic (`ui/avatar/logic.mjs`, pure and tested): choosing an edge and the walk to just behind it, the lean-out
  pose (spine and neck bending sideways toward the edge, head tilted, eyes on you), its timing, and coming back out.
- Page (`ui/avatar/avatar.js`): runs it, applies the clip, reports travel.

**Checked by:** logic tests (where she stops relative to the edge, the lean puts her head past it and her body
behind it, smooth timing), overlay tests with fake windows (behind-window detection, cut-out rectangle, input
shape), and screenshots with a test window (`tools/avatar_look.py --seat`, extended) at each step.

## Left to the builder

The exact lean pose (fitted on her model as before), timings, how far behind the edge she stops, how often she does
it, and the idle weight.
