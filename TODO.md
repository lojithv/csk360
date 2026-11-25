# CSK360 TODO

Work list for the roadmap in the design doc. Done items move to the bottom.
Status: `[ ]` to do, `[~]` in progress, `[x]` done, `[!]` blocked (reason given).

## Phase 1: MVP (current)

### Agent and scripting interface
- [x] Scene script (doc format) in JSON and YAML (built-in YAML-subset parser, no PyYAML in Blender) and Frameling's screenplay text format
- [x] `validate(script)`: check cast, assets, props, voices; precise errors with suggestions
- [x] `build(script)`: cast (starter character when the rig doesn't exist), clips, moves, lines, voices
- [x] CLI `csk360_build.py`: `blender -b [scene.blend] -P csk360/csk360_build.py -- script.yaml [--save out.blend] [--no-voices] [--validate] [--json]` (`--render` comes with render presets)
- [x] Gestures given with a line follow that line when it moves or gets voiced
- [ ] Contact-sheet preview (`--preview sheet.png`): 12 frames with timestamps
- [ ] MCP server `csk360` (about 8 tools: list_library, validate, build, patch, preview, render, voices, describe_scene)

### Timeline and clip editing
- [x] Next / previous clip (`Alt+→` / `Alt+←`) jumps the playhead to clip boundaries
- [x] Split clip at the playhead (button and `csk360.split_clip`; the `K` key waits for the CSK360 workspace, since `K` is a Blender default)
- [ ] Coloured clip bars drawn over the Timeline / Dope Sheet (gpu module), one row per character and layer
- [ ] Clip name overlay above each character in the viewport

### Pose picker
- [ ] Pie menu (`P`) of favourite poses and actions for the selected character
- [ ] Full picker grid with category chips (Standing, Gestures, Sitting and kneeling, Lying, Motion keys) and search
- [ ] Thumbnails for library items (auto-rendered from the starter character)
- [ ] Save current pose to the library (`Ctrl+Shift+P`)

### Movement
- [ ] Click-to-move modal tool (`M`): ray cast to the floor or a prop, Escape cancels
- [ ] Dashed path and destination handle drawn in the viewport; drag to re-plan
- [ ] Turn-in-place clip for turns over 90°

### Character life and dialogue
- [ ] Blinks every 2–5 s (starter character eyelids + `blink` control)
- [ ] Idle when no Body clip is active
- [ ] Listeners turn their heads toward whoever is speaking
- [ ] Face layer expressions on the starter character (happy, sad, angry, surprised, worried, thinking)
- [ ] Optional "talking" gesture loop on the Gesture layer while speaking
- [x] Copy generated audio next to the .blend (`//csk360_audio/`) so projects are portable
- [!] Test Supertonic 3 voices end to end: blocked until Lojith accepts its OpenRAIL-M terms (Voices panel)

### Preview and render
- [ ] Render presets: 1080p, 9:16, square; EEVEE or Workbench; MP4 with audio
- [ ] Subtitles from dialogue lines (text strips in the sequencer, optional SRT)

### Quality
- [ ] Click through every panel and operator in a live Blender 5.3 window
- [ ] GitHub Actions: download Blender 5.3 and run the headless tests on each push
- [ ] Golden-frame render tests for key features

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
