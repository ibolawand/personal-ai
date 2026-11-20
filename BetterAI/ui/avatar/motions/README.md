# Her motion clips

`clips.glb` is `Unreal-Godot/UAL1_Standard.glb` from Quaternius' **Universal Animation Library** (Standard, v3.0,
16 June 2026), unchanged: https://quaternius.itch.io/universal-animation-library. Licence: CC0 1.0 (`LICENSE.txt`).
Downloaded 2026-11-20.

`../motions.mjs` retargets the clips it names in `SOURCES` onto her VRM when the page loads: sitting idle and talking while she sits on a window's edge or the floor (body above the hips only). The file holds 43 clips (idle,
talking, sitting, walking, jog, dance, jumps, …); to use another one, add it to `SOURCES`.

## Mixamo walks

`walk.fbx` ("Female Walk", Mixamo's "Female Normal Walk") and `catwalk.fbx` ("Catwalk Walk Forward") were downloaded
from mixamo.com on 2026-11-20 with Lala's Adobe account: FBX Binary, Without Skin, 30 fps, In Place. Mixamo's terms
allow using them royalty-free in a project like this one, but not handing the animation files on by themselves (as a
pack or in a public repository): keep them out of anything published. `walk` is what she walks with; to try the other
one in the page, `window.ariaWalkAs = 'catwalk'`.
