# CSK360 TODO

Work list for the roadmap in the design doc. Done items move to the bottom.
Status: `[ ]` to do, `[~]` in progress, `[x]` done, `[!]` blocked (reason given).

## Phase 1: MVP (current)

### Agent and scripting interface
- [x] Scene script (doc format) in JSON and YAML (built-in YAML-subset parser, no PyYAML in Blender) and Frameling's screenplay text format
- [x] `validate(script)`: check cast, assets, props, voices; precise errors with suggestions
- [x] `build(script)`: cast (starter character when the rig doesn't exist), clips, moves, lines, voices
- [x] CLI `csk360_build.py`: `blender -b [scene.blend] -P csk360/csk360_build.py -- script.yaml [--save out.blend] [--no-voices] [--validate] [--json]` plus `--render out.mp4 --engine --subtitles --frames`
- [x] Gestures given with a line follow that line when it moves or gets voiced
- [ ] Contact-sheet preview (`--preview sheet.png`): 12 frames with timestamps
- [ ] MCP server `csk360` (about 8 tools: list_library, validate, build, patch, preview, render, voices, describe_scene)

### Timeline and clip editing
- [x] Next / previous clip (`Alt+→` / `Alt+←`) jumps the playhead to clip boundaries
- [x] Split clip at the playhead (button and `csk360.split_clip`; the `K` key waits for the CSK360 workspace, since `K` is a Blender default)
- [ ] Coloured clip bars drawn over the Timeline / Dope Sheet (gpu module), one row per character and layer
- [ ] Clip name overlay above each character in the viewport

### Pose picker
- [x] Pie menu (`P`) of favourite poses and actions for the selected character
- [x] Full picker grid with category chips (Standing, Gestures, Sitting and kneeling, Lying, Motion keys) and search
- [ ] Thumbnails for library items (auto-rendered from the starter character)
- [ ] Save current pose to the library (`Ctrl+Shift+P`)

### Movement
- [x] Click-to-move modal tool (`M`, only while a character is active, so Blender's "Move to Collection" still works otherwise): floor gives a point, a prop gives the object (walks up to its edge, or to its `approach` child; `csk360_arrival` custom property sets the arrival action); Shift+click chains walks; Esc / right-click ends
- [x] Dashed path and destination ring drawn in the viewport (Movement panel toggle); live preview while picking
- [ ] Drag a destination ring to re-plan a walk
- [ ] Turn-in-place clip for turns over 90°

### Character life and dialogue
- [x] Blinks every 2–5 s (starter character eyelids + `blink` control)
- [x] Idle when no Body clip is active
- [x] Listeners turn their heads toward whoever is speaking
- [ ] Face layer expressions on the starter character (happy, sad, angry, surprised, worried, thinking)
- [ ] Optional "talking" gesture loop on the Gesture layer while speaking
- [x] Copy generated audio next to the .blend (`//csk360_audio/`) so projects are portable
- [!] Test Supertonic 3 voices end to end: blocked until Lojith accepts its OpenRAIL-M terms (Voices panel)

### Preview and render
- [x] Render presets: 1080p, 9:16, square; EEVEE or Workbench; MP4 with audio; automatic front camera and a simple stage when the scene has none
- [x] Subtitles from dialogue lines: SRT file and/or burned in (camera-parented text; sequencer text strips would hide the 3D scene)

### Quality
- [x] Headless draw test of every panel, list, menu and the picker (props, operators and operator properties exist)
- [ ] Click through every panel and operator in a live Blender 5.3 window (click-to-move done with `--enable-event-simulate`) (`blender --python tools/dev_load.py` runs the repo copy without installing)
- [ ] GitHub Actions: download Blender 5.3 and run the headless tests on each push
- [ ] Golden-frame render tests for key features

## Phase 1b: world and abilities (requested 2026-11-26, ranked by impact)

Core (in CSK360, because scripts, the compiler and the UI all need it):
- [x] More starter poses and actions (point, thinking, hands on hips, shrug, cheer, sad, kneel, lie down, clap, nod, shake head, look around, jump, run, talking hands)
- [x] Save your own pose or action to the library (`Ctrl+Shift+P`), plus a how-to in the docs
- [x] Object labels: walkable floor, can jump onto, obstacle, liftable, weight (kg), seat; Labels panel for the selected object
- [x] Detect labels automatically (floors, surfaces within jump height, small objects as liftable with weight from size); one click to confirm
- [x] Character abilities: weight, strength (max lift kg), jump height, walk speed; checks with plain-English reasons ("Leo can lift 25 kg; the fridge is 90 kg")
- [ ] Pick up / carry / put down an object (hand attachment keyed by the compiler); lift a person when strong enough
- [ ] Jump onto / off a surface (arc move, uses jump height)
- [ ] Spawn an object at a time (appears with a pop, or is "made" by a character)
- [ ] Scene-script keys for all of the above (`pick_up`, `put_down`, `jump_onto`, `spawn`) and validation that names the failed ability
- [ ] Teamwork: two or more characters lift something too heavy for one (combined strength)

Companion extension `csk360_agents` (separate add-on that drives CSK360's `commands` API):
- [ ] Builder and agent characters: goals and simple behaviours (fetch, carry, stack, build) planned into CSK360 clips and moves
- [ ] Build recipes: walls, towers, simple houses from blocks; several builders share the work
- [ ] Characters change the environment: place, move and remove objects over time
- [ ] Scripted agents for automated tasks in Blender (rule-based first; LLM/MCP-driven later via the MCP server)

## Phase 2+ (from the design doc)

- [ ] Interaction points on props (`seat`, `approach`, `hand_L/R`); Sit on / Stand up aligned to the seat
- [ ] Guess seat points on untagged props (ray casts at 40–55 cm), one-click confirm
- [ ] A* path planning around obstacles; characters reserve path time slots
- [ ] Walk into / bump / fall canned reactions
- [ ] Spring bones for hair and clothes; foot IK on stairs and slopes
- [ ] Asset Browser library and drag-drop characters into the viewport
- [ ] CSK360 Application Template and workspace (scoped shortcuts `M`, `I`, `D`, `E`, `K`)
- [ ] Character creator: part swapping, colours, build and height
- [ ] `cutout_2d` rig with view swapping (Frameling part packs)
- [ ] `biped_real` (MPFB2), `quadruped`, `blob` rigs
- [ ] Prop physics (rigid body, baked)
- [ ] Voice cloning (needs an Apache/MIT model)
- [ ] Support Blender versions other than 5.3

## Done

- [x] Extension skeleton, GPL-3.0, public repo (github.com/lojithv/csk360)
- [x] Data model: cast, clips, moves, dialogue lines (saved in the .blend)
- [x] Compiler: NLA tracks per layer, generated move and mouth actions, sound strips; never touches the Manual layer
- [x] Clips: loop / once / pose modes, blends, automatic extra tracks for overlaps, `]` / `[` durations
- [x] Walk to a point or object with stride-matched speed, arrival action
- [x] Starter 3D toon character (`biped_toon`) with mouth shape keys and starter actions
- [x] Voice service outside Blender: Kokoro + Supertonic 3 + Rhubarb, cached, background generation
- [x] Headless test suite and build script
