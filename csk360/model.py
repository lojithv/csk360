# SPDX-License-Identifier: GPL-3.0-or-later
"""CSK360 data model: the single source of truth, stored on the scene.

Blender animation data (NLA tracks, generated actions, sound strips) is
derived from this model by `compiler.py` and must never be edited by hand.
"""

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    FloatProperty,
    FloatVectorProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)

RIG_TYPES = [
    ("biped3d", "3D biped", "Standard 3D toon biped"),
    ("cutout2d", "2D cutout", "Flat cutout character"),
    ("quadruped", "Quadruped", "Four-legged character"),
    ("blob", "Blob", "Mascot or creature with no limbs"),
    ("prop", "Prop", "Object with optional bones"),
]

CLIP_LAYERS = [
    ("BODY", "Body", "Whole body: idle, sit, walk cycle", "ARMATURE_DATA", 0),
    ("GESTURE", "Gesture", "Upper body only, plays over the Body layer", "VIEW_PAN", 1),
    ("FACE", "Face", "Brows, eyes and expression", "USER", 2),
]

LOOP_MODES = [
    ("LOOP", "Loop", "Repeat the action to fill the clip"),
    ("ONCE", "Once", "Play once, then hold the last pose"),
    ("HOLD", "Pose", "Hold the first frame as a still pose"),
]

TARGET_KINDS = [
    ("POINT", "Point", "Walk to a point on the floor"),
    ("OBJECT", "Object", "Walk to an object (its 'approach' empty if it has one)"),
]

# Rhubarb Lip Sync mouth shapes. The index is the value keyed on the rig's
# "mouth" custom property (0 = X, rest).
MOUTH_SHAPES = ("X", "A", "B", "C", "D", "E", "F", "G", "H")


def _changed(self, context):
    from . import commands
    commands.on_item_changed(self)


class CSK360_Viseme(bpy.types.PropertyGroup):
    time: FloatProperty(name="Time", description="Seconds from the start of the line", min=0.0)
    shape: IntProperty(name="Shape", description="Mouth shape index (0=X, 1=A ... 8=H)",
                       min=0, max=len(MOUTH_SHAPES) - 1)


class CSK360_CastMember(bpy.types.PropertyGroup):
    # `name` (display name) is inherited from PropertyGroup.
    id: StringProperty(name="ID", description="Stable id used by scripts and agents")
    object: PointerProperty(name="Character", type=bpy.types.Object, update=_changed)
    rig_type: EnumProperty(name="Rig Type", items=RIG_TYPES, default="biped3d")
    voice: StringProperty(name="Voice", description="Default voice id, e.g. kokoro/af_heart")
    speed: FloatProperty(name="Voice Speed", default=1.0, min=0.25, max=4.0)
    home: FloatVectorProperty(name="Start Position", size=3, subtype="TRANSLATION", update=_changed)
    home_yaw: FloatProperty(name="Start Facing", subtype="ANGLE", update=_changed)
    auto_life: BoolProperty(name="Bring to Life", default=True, update=_changed,
                            description="Blink, idle when no body clip plays, and look at whoever is speaking")
    idle_asset: StringProperty(name="Idle", description="Looping idle action; empty = the library's 'idle'",
                               update=_changed)


class CSK360_Clip(bpy.types.PropertyGroup):
    id: StringProperty(name="ID")
    cast_id: StringProperty(name="Cast ID")
    layer: EnumProperty(name="Layer", items=CLIP_LAYERS, default="BODY", update=_changed)
    asset: StringProperty(name="Asset", description="Library action name", update=_changed)
    start: FloatProperty(name="Start", description="Start time in seconds", min=0.0,
                         unit="TIME_ABSOLUTE", update=_changed)
    duration: FloatProperty(name="Duration", description="Length in seconds", default=2.0,
                            min=0.001, unit="TIME_ABSOLUTE", update=_changed)
    loop_mode: EnumProperty(name="Mode", items=LOOP_MODES, default="LOOP", update=_changed)
    blend_in: FloatProperty(name="Blend In", default=0.2, min=0.0, unit="TIME_ABSOLUTE", update=_changed)
    blend_out: FloatProperty(name="Blend Out", default=0.0, min=0.0, unit="TIME_ABSOLUTE", update=_changed)
    offset: FloatProperty(name="Offset", description="Seconds into the action where the clip starts "
                                                     "(set when a clip is split)",
                          min=0.0, unit="TIME_ABSOLUTE", update=_changed)
    with_line: StringProperty(name="With Line",
                              description="Dialogue line this clip plays with; it moves with that line",
                              update=_changed)
    match_line: BoolProperty(name="Match Line Length", default=True,
                             description="Last as long as the line it plays with", update=_changed)


class CSK360_Move(bpy.types.PropertyGroup):
    id: StringProperty(name="ID")
    cast_id: StringProperty(name="Cast ID")
    start: FloatProperty(name="Start", min=0.0, unit="TIME_ABSOLUTE", update=_changed)
    target_kind: EnumProperty(name="Target", items=TARGET_KINDS, default="POINT", update=_changed)
    target_point: FloatVectorProperty(name="Point", size=3, subtype="TRANSLATION", update=_changed)
    target_object: PointerProperty(name="Object", type=bpy.types.Object, update=_changed)
    speed: FloatProperty(name="Speed", description="Metres per second; 0 = from the walk cycle's stride",
                         default=0.0, min=0.0, unit="VELOCITY", update=_changed)
    walk_asset: StringProperty(name="Walk", description="Looping locomotion action played while moving",
                               update=_changed)
    arrival_asset: StringProperty(name="On Arrival", description="Action played on arrival, e.g. sit",
                                  update=_changed)
    duration: FloatProperty(name="Duration", description="Computed from distance and speed",
                            unit="TIME_ABSOLUTE")


class CSK360_DialogueLine(bpy.types.PropertyGroup):
    id: StringProperty(name="ID")
    cast_id: StringProperty(name="Speaker")
    text: StringProperty(name="Text")
    voice: StringProperty(name="Voice", description="Empty = the speaker's default voice")
    emotion: StringProperty(name="Emotion", default="neutral")
    start: FloatProperty(name="Start", min=0.0, unit="TIME_ABSOLUTE", update=_changed)
    audio_path: StringProperty(name="Audio", subtype="FILE_PATH", update=_changed,
                               options={"PATH_SUPPORTS_BLEND_RELATIVE"})
    duration: FloatProperty(name="Duration", description="From the audio file when there is one",
                            min=0.0, unit="TIME_ABSOLUTE", update=_changed)
    visemes: CollectionProperty(type=CSK360_Viseme)
    follows: StringProperty(name="Follows",
                            description="Id of the line this one plays after; its start then follows "
                                        "that line's end automatically. Clear to place it freely",
                            update=_changed)
    audio_key: StringProperty(name="Voice Key",
                              description="Text+voice+speed the audio was generated from; differs = needs regenerating")


class CSK360_Project(bpy.types.PropertyGroup):
    cast: CollectionProperty(type=CSK360_CastMember)
    clips: CollectionProperty(type=CSK360_Clip)
    moves: CollectionProperty(type=CSK360_Move)
    lines: CollectionProperty(type=CSK360_DialogueLine)

    active_cast_index: IntProperty()
    active_clip_index: IntProperty()
    active_move_index: IntProperty()
    active_line_index: IntProperty()

    next_id: IntProperty(description="Counter for new item ids")
    suspend: BoolProperty(description="Internal: skip recompiles during batched edits")
    last_report: StringProperty(description="Warnings from the last rebuild")
    show_paths: BoolProperty(name="Show Paths", default=True,
                             description="Draw planned walks in the viewport as dashed lines")


classes = (
    CSK360_Viseme,
    CSK360_CastMember,
    CSK360_Clip,
    CSK360_Move,
    CSK360_DialogueLine,
    CSK360_Project,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.csk360 = PointerProperty(type=CSK360_Project)


def unregister():
    del bpy.types.Scene.csk360
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
