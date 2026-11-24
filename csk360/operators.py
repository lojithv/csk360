# SPDX-License-Identifier: GPL-3.0-or-later
"""Operators: thin UI wrappers over `commands`."""

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, StringProperty

from . import commands, library, voice
from .commands import CSKError
from .model import CLIP_LAYERS, LOOP_MODES


def context_cast(context):
    """The cast member of the active object, else the one selected in the list."""
    scene = context.scene
    proj = scene.csk360
    c = commands.cast_for_object(scene, context.active_object)
    if c is not None:
        return c
    if 0 <= proj.active_cast_index < len(proj.cast):
        return proj.cast[proj.active_cast_index]
    return None


def active_item(collection, index):
    return collection[index] if 0 <= index < len(collection) else None


def _asset_search(self, context, edit_text):
    text = edit_text.lower()
    return [n for n in library.asset_ids() if text in n.lower()]


class _CSKOperator:
    bl_options = {"REGISTER", "UNDO"}

    def run(self, context):
        raise NotImplementedError

    def execute(self, context):
        try:
            result = self.run(context)
        except CSKError as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        report = context.scene.csk360.last_report
        if report:
            self.report({"WARNING"}, report)
        return result or {"FINISHED"}


class CSK360_OT_add_cast(_CSKOperator, bpy.types.Operator):
    """Add the active object to the cast"""
    bl_idname = "csk360.add_cast"
    bl_label = "Add to Cast"

    name: StringProperty(name="Name", description="Display name; empty = object name")

    @classmethod
    def poll(cls, context):
        return context.active_object is not None

    def run(self, context):
        commands.add_cast(context.scene, context.active_object, name=self.name or None)


class CSK360_OT_add_starter_character(_CSKOperator, bpy.types.Operator):
    """Add a ready-rigged 3D toon character at the 3D cursor, with starter poses and actions"""
    bl_idname = "csk360.add_starter_character"
    bl_label = "Add Starter Character"

    name: StringProperty(name="Name", default="Leo")

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT"

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def run(self, context):
        scene = context.scene
        commands.add_starter_character(scene, name=self.name or "Character",
                                       location=tuple(scene.cursor.location))


class CSK360_OT_remove_cast(_CSKOperator, bpy.types.Operator):
    """Remove the selected cast member with all its clips, moves and lines"""
    bl_idname = "csk360.remove_cast"
    bl_label = "Remove from Cast"

    @classmethod
    def poll(cls, context):
        return len(context.scene.csk360.cast) > 0

    def run(self, context):
        proj = context.scene.csk360
        c = active_item(proj.cast, proj.active_cast_index)
        if c is None:
            raise CSKError("Select a cast member in the list.")
        commands.remove_cast(context.scene, c.id)


class CSK360_OT_set_home(_CSKOperator, bpy.types.Operator):
    """Use the character's current position and facing as where it starts"""
    bl_idname = "csk360.set_home"
    bl_label = "Set Start Position"

    @classmethod
    def poll(cls, context):
        return context_cast(context) is not None

    def run(self, context):
        commands.set_home(context.scene, context_cast(context).id)


class CSK360_OT_add_clip(_CSKOperator, bpy.types.Operator):
    """Add a pose or action clip for the character at the playhead"""
    bl_idname = "csk360.add_clip"
    bl_label = "Add Clip"

    asset: StringProperty(name="Pose / Action", search=_asset_search)
    duration: FloatProperty(name="Duration", description="Seconds; 0 = the asset's default",
                            default=0.0, min=0.0)
    layer: EnumProperty(name="Layer", items=[("AUTO", "Auto", "Use the asset's layer")]
                        + [i[:3] for i in CLIP_LAYERS], default="AUTO")

    @classmethod
    def poll(cls, context):
        return context_cast(context) is not None

    def invoke(self, context, event):
        if not self.asset:
            return context.window_manager.invoke_props_dialog(self)
        return self.execute(context)

    def run(self, context):
        cast = context_cast(context)
        commands.add_clip(context.scene, cast.id, self.asset,
                          duration=self.duration or None,
                          layer=None if self.layer == "AUTO" else self.layer)


class CSK360_OT_remove_clip(_CSKOperator, bpy.types.Operator):
    """Remove the active clip"""
    bl_idname = "csk360.remove_clip"
    bl_label = "Remove Clip"

    @classmethod
    def poll(cls, context):
        return len(context.scene.csk360.clips) > 0

    def run(self, context):
        proj = context.scene.csk360
        clip = active_item(proj.clips, proj.active_clip_index)
        if clip is None:
            raise CSKError("Select a clip first.")
        commands.remove_clip(context.scene, clip.id)


class CSK360_OT_clip_duration(_CSKOperator, bpy.types.Operator):
    """Make the active clip longer or shorter"""
    bl_idname = "csk360.clip_duration"
    bl_label = "Change Clip Duration"

    delta: FloatProperty(name="Change", default=1.0,
                         description="Seconds to add (negative shortens); frames when By Frames is on")
    by_frames: BoolProperty(name="By Frames", default=False)

    @classmethod
    def poll(cls, context):
        return len(context.scene.csk360.clips) > 0

    def run(self, context):
        scene = context.scene
        proj = scene.csk360
        clip = active_item(proj.clips, proj.active_clip_index)
        if clip is None:
            raise CSKError("Select a clip first.")
        delta = self.delta
        if self.by_frames:
            delta /= scene.render.fps / scene.render.fps_base
        commands.change_clip_duration(scene, clip.id, delta)


class CSK360_OT_add_move(_CSKOperator, bpy.types.Operator):
    """Walk the character to the 3D cursor, or to another selected object"""
    bl_idname = "csk360.add_move"
    bl_label = "Add Movement"

    to: EnumProperty(name="Walk To", items=[
        ("CURSOR", "3D Cursor", "Walk to the 3D cursor on the floor"),
        ("SELECTED", "Selected Object", "Walk to the other selected object"),
    ], default="CURSOR")
    arrival: StringProperty(name="On Arrival", search=_asset_search)

    @classmethod
    def poll(cls, context):
        return context_cast(context) is not None

    def run(self, context):
        scene = context.scene
        cast = context_cast(context)
        if self.to == "SELECTED":
            others = [o for o in context.selected_objects if o is not cast.object]
            if not others:
                raise CSKError("Select a target object as well as the character.")
            commands.add_move(scene, cast.id, target=others[0], arrival=self.arrival)
        else:
            commands.add_move(scene, cast.id, point=tuple(scene.cursor.location), arrival=self.arrival)


class CSK360_OT_remove_move(_CSKOperator, bpy.types.Operator):
    """Remove the active movement"""
    bl_idname = "csk360.remove_move"
    bl_label = "Remove Movement"

    @classmethod
    def poll(cls, context):
        return len(context.scene.csk360.moves) > 0

    def run(self, context):
        proj = context.scene.csk360
        m = active_item(proj.moves, proj.active_move_index)
        if m is None:
            raise CSKError("Select a movement first.")
        commands.remove_move(context.scene, m.id)


class CSK360_OT_add_line(_CSKOperator, bpy.types.Operator):
    """Add a dialogue line for the character"""
    bl_idname = "csk360.add_line"
    bl_label = "Add Dialogue Line"

    text: StringProperty(name="Text")
    audio_path: StringProperty(name="Audio", subtype="FILE_PATH",
                               description="Voice recording (voice generation comes later)")
    place: EnumProperty(name="Place", items=[
        ("PLAYHEAD", "At Playhead", ""),
        ("AFTER", "After Previous Line", ""),
    ], default="PLAYHEAD")

    @classmethod
    def poll(cls, context):
        return context_cast(context) is not None

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=400)

    def run(self, context):
        commands.add_line(context.scene, context_cast(context).id, self.text,
                          after_previous=self.place == "AFTER", audio_path=self.audio_path)


class CSK360_OT_remove_line(_CSKOperator, bpy.types.Operator):
    """Remove the active dialogue line"""
    bl_idname = "csk360.remove_line"
    bl_label = "Remove Dialogue Line"

    @classmethod
    def poll(cls, context):
        return len(context.scene.csk360.lines) > 0

    def run(self, context):
        proj = context.scene.csk360
        line = active_item(proj.lines, proj.active_line_index)
        if line is None:
            raise CSKError("Select a line first.")
        commands.remove_line(context.scene, line.id)


class CSK360_OT_rebuild(_CSKOperator, bpy.types.Operator):
    """Regenerate all CSK360 animation and sound from the clip data"""
    bl_idname = "csk360.rebuild"
    bl_label = "Rebuild Animation"

    def run(self, context):
        commands.rebuild(context.scene)


class CSK360_OT_mark_asset(_CSKOperator, bpy.types.Operator):
    """Add the active object's current action to the CSK360 library"""
    bl_idname = "csk360.mark_asset"
    bl_label = "Add Action to Library"

    kind: EnumProperty(name="Kind", items=[
        ("pose", "Pose", "Holds still"),
        ("action", "Action", "Plays over time"),
        ("transition", "Transition", "Links two states, e.g. stand to sit"),
    ], default="action")
    layer: EnumProperty(name="Layer", items=[i[:3] for i in CLIP_LAYERS], default="BODY")
    loop: BoolProperty(name="Loop", description="Repeat to fill the clip (walk, talk gestures)")
    duration: FloatProperty(name="Default Duration", description="Seconds; 0 = natural length",
                            min=0.0)
    stride: FloatProperty(name="Stride", description="Metres per step, for walk cycles", min=0.0)
    tags: StringProperty(name="Tags", description="Comma separated, e.g. walk, move")
    unassign: BoolProperty(name="Unassign from Object", default=True,
                           description="Clear it from the object so it does not play as manual keys")

    @classmethod
    def poll(cls, context):
        ob = context.active_object
        return ob is not None and ob.animation_data is not None and ob.animation_data.action is not None

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def run(self, context):
        ob = context.active_object
        action = ob.animation_data.action
        library.mark(action, kind=self.kind, layer=self.layer, loop=self.loop,
                     duration=self.duration, stride=self.stride, tags=self.tags)
        if self.unassign:
            ob.animation_data.action = None
        self.report({"INFO"}, f"'{action.name}' added to the CSK360 library")


class _BackgroundOperator:
    """Runs a voice.BackgroundJob and keeps the UI responsive while it works."""
    _timer = None
    _job = None

    def start(self, context, job):
        self._job = job
        wm = context.window_manager
        self._timer = wm.event_timer_add(0.3, window=context.window)
        wm.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type != "TIMER":
            return {"PASS_THROUGH"}
        job = self._job
        context.workspace.status_text_set(f"CSK360: {self.bl_label}… {job.last_progress()}")
        if not job.done:
            return {"PASS_THROUGH"}
        context.window_manager.event_timer_remove(self._timer)
        context.workspace.status_text_set(None)
        for area in context.screen.areas:
            area.tag_redraw()
        if job.error is not None:
            self.report({"ERROR"}, str(job.error))
            return {"CANCELLED"}
        return self.finish(context, job.result)

    def finish(self, context, result):
        return {"FINISHED"}


class CSK360_OT_install_voices(_BackgroundOperator, bpy.types.Operator):
    """Download and set up offline voices (Kokoro, Supertonic 3) and Rhubarb lip sync, about 900 MB"""
    bl_idname = "csk360.install_voices"
    bl_label = "Install Voices"

    supertonic_from: StringProperty(
        name="Supertonic Folder", subtype="DIR_PATH",
        description="Optional: copy Supertonic 3 from an existing folder (e.g. Frameling's) instead of downloading")

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=420)

    def draw(self, context):
        col = self.layout.column()
        col.label(text="Downloads about 900 MB into:")
        col.label(text=voice.home())
        col.prop(self, "supertonic_from")

    def execute(self, context):
        if not bpy.app.online_access:
            self.report({"ERROR"}, "Turn on Preferences > System > Network > Allow Online Access first.")
            return {"CANCELLED"}
        job = voice.BackgroundJob(voice.setup, supertonic_from=bpy.path.abspath(self.supertonic_from) or None)
        return self.start(context, job)

    def finish(self, context, result):
        voice.voices(refresh=True)
        voice.status(refresh=True)
        missing = [k for k in ("kokoro", "supertonic", "rhubarb") if not result.get(k)]
        if missing:
            self.report({"WARNING"}, f"Installed, but not ready: {', '.join(missing)}")
        else:
            self.report({"INFO"}, "Voices installed")
        return {"FINISHED"}


class CSK360_OT_accept_supertonic_terms(_CSKOperator, bpy.types.Operator):
    bl_idname = "csk360.accept_supertonic_terms"
    bl_label = "Accept Supertonic Terms"
    bl_description = voice.SUPERTONIC_TERMS

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(
            self, event, title="Supertonic 3 licence (OpenRAIL-M)", message=voice.SUPERTONIC_TERMS,
            confirm_text="I Accept")

    def run(self, context):
        try:
            voice.accept_supertonic_terms()
        except voice.VoiceError as e:
            raise CSKError(str(e))
        voice.status(refresh=True)


def _voice_items(self, context):
    global _VOICE_ITEMS
    _VOICE_ITEMS = [(v, v, "") for v in voice.voices()] or [("", "No voices installed", "")]
    return _VOICE_ITEMS


_VOICE_ITEMS = []


class CSK360_OT_set_voice(_CSKOperator, bpy.types.Operator):
    """Choose the character's voice"""
    bl_idname = "csk360.set_voice"
    bl_label = "Set Voice"
    bl_property = "voice"

    voice: EnumProperty(name="Voice", items=_voice_items)

    @classmethod
    def poll(cls, context):
        return context_cast(context) is not None

    def invoke(self, context, event):
        context.window_manager.invoke_search_popup(self)
        return {"RUNNING_MODAL"}

    def run(self, context):
        if not self.voice:
            raise CSKError("No voices installed yet. Press Install Voices first.")
        cast = context_cast(context)
        cast.voice = self.voice


class CSK360_OT_generate_lines(_BackgroundOperator, bpy.types.Operator):
    """Voice and lip-sync dialogue lines that are new or whose text or voice changed"""
    bl_idname = "csk360.generate_lines"
    bl_label = "Generate Voices"

    scope: EnumProperty(name="Lines", items=[
        ("ACTIVE", "Active Line", ""),
        ("CAST", "This Character", ""),
        ("ALL", "All Lines", ""),
    ], default="ALL")
    force: BoolProperty(name="Regenerate", description="Regenerate even if up to date")

    def execute(self, context):
        scene = context.scene
        proj = scene.csk360
        ids = None
        if self.scope == "ACTIVE":
            line = active_item(proj.lines, proj.active_line_index)
            ids = [line.id] if line else []
        elif self.scope == "CAST":
            cast = context_cast(context)
            ids = [l.id for l in proj.lines if cast and l.cast_id == cast.id]
        try:
            jobs = commands.voice_jobs(scene, ids, self.force)
        except CSKError as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        if not jobs:
            self.report({"INFO"}, "All lines are up to date")
            return {"FINISHED"}
        self._scene_name = scene.name
        return self.start(context, voice.BackgroundJob(voice.speak, jobs))

    def finish(self, context, result):
        scene = bpy.data.scenes.get(self._scene_name) or context.scene
        errors = commands.apply_voice_results(scene, result)
        if errors:
            self.report({"WARNING"}, "; ".join(errors))
        else:
            self.report({"INFO"}, f"Voiced {len(result)} line(s)")
        return {"FINISHED"}


classes = (
    CSK360_OT_add_cast,
    CSK360_OT_add_starter_character,
    CSK360_OT_remove_cast,
    CSK360_OT_set_home,
    CSK360_OT_add_clip,
    CSK360_OT_remove_clip,
    CSK360_OT_clip_duration,
    CSK360_OT_add_move,
    CSK360_OT_remove_move,
    CSK360_OT_add_line,
    CSK360_OT_remove_line,
    CSK360_OT_rebuild,
    CSK360_OT_mark_asset,
    CSK360_OT_install_voices,
    CSK360_OT_accept_supertonic_terms,
    CSK360_OT_set_voice,
    CSK360_OT_generate_lines,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
