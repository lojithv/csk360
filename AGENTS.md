# CSK360 for agents and scripts

This file is for coding agents (Claude Code, Codex, Antigravity) working **on**
CSK360, and for scripts that **use** it inside Blender.

## Working on the code

* Blender 5.3 is the only supported version for now; keep code on the slotted-action
  API (`action.slots`, `layers`, `channelbags`). There is no `action.fcurves`.
* Run `./tools/test.ps1` (Windows) or `./tools/test.sh` (macOS/Linux) (headless, ~10 s) after every change; add a test for
  every behaviour change. Tests live in `tests/test_*.py` and use fixtures in
  `tests/helpers.py`.
* Only `compiler.py` writes animation data. UI code calls `operators`, which call
  `commands`. Never add a feature that keys the rig directly from an operator.
* Never import onnxruntime, numpy-heavy or ML packages in the extension itself.
  Speech lives in `csk360/voice_service/` and runs in its own venv
  (`~/.csk360/venv`) as a subprocess; `voice.py` is the only client.
* User-facing errors raise `commands.CSKError` with a plain-English message.
* Naming: operators `csk360.*`, classes `CSK360_OT_*` / `CSK360_PT_*`, sidebar tab `CSK360`.

## Building a scene from a script (cheapest for agents)

Write one scene script and build it headless; don't drive Blender step by step.

```yaml
cast:
  leo:  {character: leo, voice: kokoro/am_michael}     # created as a starter character if missing
  maya: {character: maya, voice: supertonic/F1}
timeline:
  - {at: 0, who: maya, do: wave, for: 2}               # clip: asset, start, duration
  - {at: 0, who: leo, move_to: [0.6, -1.5], then: sit} # or move_to: <object name>
  - {at: 4, who: leo, say: "Morning!"}                 # voiced + lip-synced
  - {after: prev, who: maya, say: "Hi.", gesture: arms_crossed}  # gesture follows the line
output: {size: 1080p, fps: 24}                         # 1080p, 720p, 4k, 9:16, square
objects:                                               # optional labels
  Crate: {liftable: true, weight: 12, jump_onto: true}
```

Cast entries also take abilities: `{character: leo, strength: 40, jump: 0.6, weight: 70}`
(kg, metres, kg).

```
blender -b [scene.blend] -P csk360/csk360_build.py -- scene.yaml --validate --json
blender -b [scene.blend] -P csk360/csk360_build.py -- scene.yaml --save out.blend --json
```

Entry keys: at, after (prev), who, do, for, mode (loop/once/pose), layer, move_to,
then, say, voice, gesture, face. Starter assets: idle, walk, wave, arms_crossed, sit.
Validation errors name the entry and suggest the closest valid id; fix the text and rebuild.
Frameling screenplays (`Name (expression, action): text`, `.txt`) also work.

## Driving CSK360 from Python

Inside Blender (installed as an extension the package is `bl_ext.user_default.csk360`;
in the tests it is plain `csk360`):

```python
import bpy
from bl_ext.user_default.csk360 import commands

scene = bpy.context.scene
leo = commands.add_cast(scene, bpy.data.objects["Leo"])          # -> "leo"
commands.add_clip(scene, leo, "wave", start=0, duration=2)       # seconds
commands.add_move(scene, leo, start=0, target="desk_chair", arrival="sit")
commands.add_move(scene, leo, point=(2, 1, 0), after_previous=True)  # starts when the last walk ends
commands.add_line(scene, leo, "Morning!", start=6,
                  audio_path="//voice/leo_01.wav",
                  visemes=[(0.0, "B"), (0.12, "C"), (0.4, "X")])
commands.add_line(scene, leo, "Did you see the numbers?", after_previous=True,
                  voice="supertonic/M1", generate=True)   # voiced + lip-synced now
commands.generate_lines(scene)    # voice every new or edited line (blocking)
print(commands.describe(scene))   # plain dict: cast (with abilities), objects (labels), clips, ...

from bl_ext.user_default.csk360 import world
world.detect(scene)                                   # guess labels for unlabelled meshes
world.label("Crate", liftable=True, weight=12)        # walkable, jump_onto, obstacle, liftable, weight
world.set_abilities(scene, leo, strength=40, jump_height=0.6, weight=70)
ok, why = world.can_lift(scene, leo, "Crate", helpers=["maya"])   # why is plain English
ok, why = world.can_jump_onto(scene, leo, "Table")
```

All functions recompile only the affected character. Unknown asset names raise
`CSKError` with close-match suggestions. Times are seconds from the scene's
first frame. Mouth shapes are Rhubarb's `X A B C D E F G H` (keyed as 0–8 on
the rig's `mouth` custom property).
