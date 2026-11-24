# CSK360 for agents and scripts

This file is for coding agents (Claude Code, Codex, Antigravity) working **on**
CSK360, and for scripts that **use** it inside Blender.

## Working on the code

* Blender 5.3 is the only supported version for now; keep code on the slotted-action
  API (`action.slots`, `layers`, `channelbags`). There is no `action.fcurves`.
* Run `./tools/test.ps1` (headless, ~2 s) after every change; add a test for
  every behaviour change. Tests live in `tests/test_*.py` and use fixtures in
  `tests/helpers.py`.
* Only `compiler.py` writes animation data. UI code calls `operators`, which call
  `commands`. Never add a feature that keys the rig directly from an operator.
* User-facing errors raise `commands.CSKError` with a plain-English message.
* Naming: operators `csk360.*`, classes `CSK360_OT_*` / `CSK360_PT_*`, sidebar tab `CSK360`.

## Driving CSK360 from a script

Inside Blender (installed as an extension the package is `bl_ext.user_default.csk360`;
in the tests it is plain `csk360`):

```python
import bpy
from bl_ext.user_default.csk360 import commands

scene = bpy.context.scene
leo = commands.add_cast(scene, bpy.data.objects["Leo"])          # -> "leo"
commands.add_clip(scene, leo, "wave", start=0, duration=2)       # seconds
commands.add_move(scene, leo, start=0, target="desk_chair", arrival="sit")
commands.add_line(scene, leo, "Morning!", start=6,
                  audio_path="//voice/leo_01.wav",
                  visemes=[(0.0, "B"), (0.12, "C"), (0.4, "X")])
print(commands.describe(scene))   # plain dict: cast, clips, moves, lines, library, warnings
```

All functions recompile only the affected character. Unknown asset names raise
`CSKError` with close-match suggestions. Times are seconds from the scene's
first frame. Mouth shapes are Rhubarb's `X A B C D E F G H` (keyed as 0–8 on
the rig's `mouth` custom property).
