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


class CSK360_OT_pose_picker(bpy.types.Operator):
    """Pick a pose or action for the character from the whole library"""
    bl_idname = "csk360.pose_picker"
    bl_label = "Poses and Actions"
    bl_options = {"REGISTER"}

    category: EnumProperty(name="Category", items=[("ALL", "All", "")]
                           + [(c, c, "") for c in library.CATEGORIES], default="ALL")
    search: StringProperty(name="Search", options={"TEXTEDIT_UPDATE"})

    @classmethod
    def poll(cls, context):
        return context_cast(context) is not None

    def invoke(self, context, event):
        return context.window_manager.invoke_popup(self, width=420)

    def draw(self, context):
        layout = self.layout
        cast = context_cast(context)
        layout.label(text=f"Add to {cast.name} at the playhead" if cast else "Select a character")
        chips = layout.grid_flow(row_major=True, columns=3, even_columns=True, align=True)
        for ident, label, _ in [("ALL", "All", "")] + [(c, c, "") for c in library.CATEGORIES]:
            chips.prop_enum(self, "category", ident, text=label)
        layout.prop(self, "search", text="", icon="VIEWZOOM")
        items = library.search(self.search, category=None if self.category == "ALL" else self.category)
        if not items:
            layout.label(text="Nothing matches.")
            return
        grid = layout.grid_flow(row_major=True, columns=3, even_columns=True)
        for i in items:
            op = grid.operator("csk360.add_clip", text=i["id"].replace("_", " ").title(),
                               icon={"GESTURE": "VIEW_PAN", "FACE": "USER"}.get(i["layer"], "ARMATURE_DATA"))
            op.asset = i["id"]

    def execute(self, context):
        return {"FINISHED"}


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


class CSK360_OT_split_clip(_CSKOperator, bpy.types.Operator):
    """Split the active clip in two at the playhead"""
    bl_idname = "csk360.split_clip"
    bl_label = "Split Clip"

    @classmethod
    def poll(cls, context):
        return len(context.scene.csk360.clips) > 0

    def run(self, context):
        proj = context.scene.csk360
        clip = active_item(proj.clips, proj.active_clip_index)
        if clip is None:
            raise CSKError("Select a clip first.")
        commands.split_clip(context.scene, clip.id)


class CSK360_OT_jump_clip(_CSKOperator, bpy.types.Operator):
    """Jump the playhead to the next or previous clip start or end of the character"""
    bl_idname = "csk360.jump_clip"
    bl_label = "Jump to Clip"
    bl_options = {"REGISTER"}

    direction: EnumProperty(items=[("NEXT", "Next", ""), ("PREV", "Previous", "")], default="NEXT")

    def run(self, context):
        cast = context_cast(context)
        t = commands.jump_to_clip(context.scene, 1 if self.direction == "NEXT" else -1,
                                  cast.id if cast else None)
        if t is None:
            self.report({"INFO"}, "No more clips that way")


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


def _window_region(area):
    for region in area.regions:
        if region.type == "WINDOW":
            return region
    return None


class CSK360_OT_click_move(bpy.types.Operator):
    """Click the floor or a prop to walk the character there. Shift+click keeps adding walks"""
    bl_idname = "csk360.click_move"
    bl_label = "Click to Walk"
    bl_options = {"UNDO"}

    STATUS = ("Click the floor or a prop to walk there  ·  Shift+click: add another walk  ·  "
              "Alt+click a surface: jump onto it  ·  Right-click or Esc: done")

    @classmethod
    def poll(cls, context):
        # Strict: only when a character is active, so M falls through to
        # Blender's own "Move to Collection" for every other object.
        area = context.area
        return (area is not None and area.type == "VIEW_3D" and context.mode == "OBJECT"
                and commands.cast_for_object(context.scene, context.active_object) is not None)

    def invoke(self, context, event):
        from . import paths
        self.area = context.area
        self.region = _window_region(context.area)
        if self.region is None:
            return {"CANCELLED"}
        cast = commands.cast_for_object(context.scene, context.active_object)
        self.cast_id = cast.id
        self.added = 0
        paths.preview.clear()
        start = cast.object.matrix_world.translation.copy()
        start.z = paths.floor_height(cast)
        paths.preview.update({"cast_id": cast.id, "to": None, "from": start})
        context.workspace.status_text_set(self.STATUS)
        context.window.cursor_modal_set("CROSSHAIR")
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def _pick(self, context, event):
        from bpy_extras import view3d_utils
        from . import paths
        region = self.region
        x, y = event.mouse_x - region.x, event.mouse_y - region.y
        if not (0 <= x < region.width and 0 <= y < region.height):
            return False, None
        rv3d = self.area.spaces.active.region_3d
        origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, (x, y))
        direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, (x, y))
        cast = commands.get_cast(context.scene, self.cast_id)
        return True, paths.pick(context.scene, context.evaluated_depsgraph_get(), cast, origin,
                                direction, stand=event.alt)

    def _finish(self, context):
        from . import paths
        paths.preview.clear()
        context.workspace.status_text_set(None)
        context.window.cursor_modal_restore()
        self.area.tag_redraw()
        return {"FINISHED"} if self.added else {"CANCELLED"}

    def modal(self, context, event):
        from . import paths
        if event.type in {"ESC", "RIGHTMOUSE"} and event.value == "PRESS":
            return self._finish(context)
        if event.type == "MOUSEMOVE":
            inside, result = self._pick(context, event)
            if not inside:
                return {"PASS_THROUGH"}
            cast = commands.get_cast(context.scene, self.cast_id)
            paths.preview["to"] = paths.target_location(result, paths.preview["from"],
                                                        paths.floor_height(cast))
            self.area.tag_redraw()
            return {"RUNNING_MODAL"}
        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            inside, result = self._pick(context, event)
            if not inside:
                return {"PASS_THROUGH"}
            if result is None:
                self.report({"WARNING"}, "Click on the floor or on a prop.")
                return {"RUNNING_MODAL"}
            scene = context.scene
            try:
                if "point" in result:
                    commands.add_move(scene, self.cast_id, point=tuple(result["point"]),
                                      after_previous=self.added > 0)
                else:
                    commands.add_move(scene, self.cast_id, target=result["target"],
                                      arrival=result["arrival"], after_previous=self.added > 0,
                                      jump=event.alt)
            except CSKError as e:
                self.report({"ERROR"}, str(e))
                return self._finish(context)
            self.added += 1
            cast = commands.get_cast(scene, self.cast_id)
            paths.preview["from"] = paths.target_location(result, paths.preview["from"],
                                                          paths.floor_height(cast))
            if scene.csk360.last_report:
                self.report({"WARNING"}, scene.csk360.last_report)
            if not event.shift:
                return self._finish(context)
            return {"RUNNING_MODAL"}
        if event.type in {"MIDDLEMOUSE", "WHEELUPMOUSE", "WHEELDOWNMOUSE", "TRACKPADPAN",
                          "TRACKPADZOOM", "NDOF_MOTION"} or event.type.startswith("NUMPAD"):
            return {"PASS_THROUGH"}  # let the user orbit and zoom while picking
        return {"RUNNING_MODAL"}


class CSK360_OT_pick_up(_CSKOperator, bpy.types.Operator):
    """Pick up the other selected object at the playhead (walks over first if needed)"""
    bl_idname = "csk360.pick_up"
    bl_label = "Pick Up Selected"

    @classmethod
    def poll(cls, context):
        return context_cast(context) is not None

    def run(self, context):
        cast = context_cast(context)
        others = [o for o in context.selected_objects
                  if commands.cast_for_object(context.scene, o) is None]
        if not others:
            raise CSKError("Click the object to pick up, then Shift+click the character, "
                           "so both are selected and the character is active.")
        commands.pick_up(context.scene, cast.id, others[0])


class CSK360_OT_put_down(_CSKOperator, bpy.types.Operator):
    """Put down what the character is carrying, at the playhead"""
    bl_idname = "csk360.put_down"
    bl_label = "Put Down"

    where: EnumProperty(name="Where", items=[
        ("FRONT", "In Front", "On the floor in front of the character"),
        ("SELECTED", "On Selected", "On top of the other selected object"),
        ("CURSOR", "At 3D Cursor", "")], default="FRONT")

    @classmethod
    def poll(cls, context):
        cast = context_cast(context)
        return cast is not None and any(c.cast_id == cast.id and c.end < 0
                                        for c in context.scene.csk360.carries)

    def run(self, context):
        scene = context.scene
        cast = context_cast(context)
        at = None
        if self.where == "SELECTED":
            others = [o for o in context.selected_objects
                      if commands.cast_for_object(scene, o) is None
                      and not any(c.object is o for c in scene.csk360.carries)]
            if not others:
                raise CSKError("Select where to put it as well as the character.")
            at = others[0]
        elif self.where == "CURSOR":
            at = tuple(scene.cursor.location)
        commands.put_down(scene, cast.id, at=at)


class CSK360_OT_remove_carry(_CSKOperator, bpy.types.Operator):
    """Stop carrying: the object goes back to where it was"""
    bl_idname = "csk360.remove_carry"
    bl_label = "Remove Carry"

    carry_id: StringProperty()

    def run(self, context):
        commands.remove_carry(context.scene, self.carry_id)


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


class CSK360_OT_save_pose(_CSKOperator, bpy.types.Operator):
    """Save the character's current pose to the library, to reuse on any character (Ctrl+Shift+P)"""
    bl_idname = "csk360.save_pose"
    bl_label = "Save Pose to Library"

    name: StringProperty(name="Name", default="My Pose")
    category: EnumProperty(name="Category", items=[(c, c, "") for c in library.CATEGORIES],
                           default="My poses")
    layer: EnumProperty(name="Layer", items=[
        ("AUTO", "Automatic", "Gesture if only the upper body moved, else Body"),
        ("BODY", "Body", "Whole body; replaces walks and sits while it plays"),
        ("GESTURE", "Gesture", "Upper body; layers over the body clip"),
    ], default="AUTO")
    favorite: BoolProperty(name="Show in Pie Menu (P)", default=True)
    add_clip: BoolProperty(name="Add as Clip at Playhead", default=True)
    overwrite: BoolProperty(name="Overwrite if the Name Exists", default=False)

    @classmethod
    def poll(cls, context):
        ob = context.active_object
        return (ob is not None and ob.type == "ARMATURE"
                and commands.cast_for_object(context.scene, ob) is not None)

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def run(self, context):
        scene = context.scene
        cast = commands.cast_for_object(scene, context.active_object)
        asset = commands.save_pose(scene, cast.id, self.name, category=self.category,
                                   layer=self.layer, favorite=self.favorite,
                                   overwrite=self.overwrite)
        if self.add_clip:
            commands.add_clip(scene, cast.id, asset)
        self.report({"INFO"}, f"Saved pose '{asset}' to the CSK360 library")


class CSK360_OT_detect_labels(_CSKOperator, bpy.types.Operator):
    """Guess what characters can do with each object (walk on, stand on, lift, weight) from its size"""
    bl_idname = "csk360.detect_labels"
    bl_label = "Detect Labels"

    overwrite: BoolProperty(name="Redo Detected and Your Own Labels", default=False)

    def run(self, context):
        from . import world
        done = world.detect(context.scene, overwrite=self.overwrite)
        self.report({"INFO"}, f"Labelled {len(done)} object(s). Check them in CSK360 > Objects.")


class CSK360_OT_confirm_label(_CSKOperator, bpy.types.Operator):
    """Keep the active object's labels as they are (marks them as set by you)"""
    bl_idname = "csk360.confirm_label"
    bl_label = "Looks Right"

    @classmethod
    def poll(cls, context):
        ob = context.active_object
        return ob is not None and ob.csk360_label.source == "AUTO"

    def run(self, context):
        context.active_object.csk360_label.source = "USER"


class CSK360_OT_check_ability(bpy.types.Operator):
    """Check whether the chosen character can lift, or jump onto, the active object"""
    bl_idname = "csk360.check_ability"
    bl_label = "Check"

    what: EnumProperty(items=[("LIFT", "Lift", ""), ("JUMP", "Jump Onto", "")])
    cast_id: StringProperty()

    def execute(self, context):
        from . import world
        fn = world.can_lift if self.what == "LIFT" else world.can_jump_onto
        ok, why = fn(context.scene, self.cast_id, context.active_object)
        self.report({"INFO"} if ok else {"WARNING"}, why)
        return {"FINISHED"}


def _maker_items(self, context):
    items = [("NONE", "Nobody", "It just appears")]
    items += [(c.id, c.name, f"{c.name} makes it, in front of them")
              for c in context.scene.csk360.cast]
    return items


class CSK360_OT_spawn(_CSKOperator, bpy.types.Operator):
    """Make the active object (or a copy of it) appear at the playhead, with a pop"""
    bl_idname = "csk360.spawn"
    bl_label = "Make It Appear"

    copy: BoolProperty(name="Make a Copy", default=True,
                       description="Place a new copy; off makes this object itself appear")
    where: EnumProperty(name="Where", items=[
        ("CURSOR", "At 3D Cursor", ""), ("IN_PLACE", "Where It Is", ""),
        ("MAKER", "In Front of the Maker", "")], default="CURSOR")
    by: EnumProperty(name="Made By", items=_maker_items)

    @classmethod
    def poll(cls, context):
        ob = context.active_object
        return ob is not None and commands.cast_for_object(context.scene, ob) is None

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def run(self, context):
        scene = context.scene
        by = None if self.by == "NONE" else self.by
        loc = None
        if self.where == "CURSOR":
            loc = tuple(scene.cursor.location)
        elif self.where == "MAKER" and by is None:
            raise CSKError("Choose who makes it, or another place.")
        commands.spawn(scene, context.active_object, location=loc, by=by, copy=self.copy)


class CSK360_OT_remove_spawn(_CSKOperator, bpy.types.Operator):
    """Remove this appearance (a copy CSK360 made is deleted)"""
    bl_idname = "csk360.remove_spawn"
    bl_label = "Remove"

    spawn_id: StringProperty()

    def run(self, context):
        commands.remove_spawn(context.scene, self.spawn_id)


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


class CSK360_OT_render_video(bpy.types.Operator):
    """Render the scene to an MP4 with sound, using a preset size"""
    bl_idname = "csk360.render_video"
    bl_label = "Render Video"

    filepath: StringProperty(subtype="FILE_PATH", default="//render.mp4")
    filter_glob: StringProperty(default="*.mp4", options={"HIDDEN"})
    preset: EnumProperty(name="Size", items=[
        ("1080p", "1080p (16:9)", ""), ("720p", "720p (16:9)", ""), ("9:16", "Vertical 9:16", ""),
        ("square", "Square", ""), ("4k", "4K", "")], default="1080p")
    engine: EnumProperty(name="Engine", items=[
        ("workbench", "Workbench (fast)", ""), ("eevee", "EEVEE (nicer)", "")], default="eevee")
    subtitles: EnumProperty(name="Subtitles", items=[
        ("srt", "SRT File", "Write subtitles next to the video"),
        ("burn", "Burned In", "Draw subtitles in the picture"),
        ("both", "Both", ""), ("none", "None", "")], default="srt")

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        from . import render
        try:
            path = render.render_video(context.scene, self.filepath, preset=self.preset,
                                       engine=self.engine, subtitles=self.subtitles)
        except (ValueError, RuntimeError) as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        self.report({"INFO"}, f"Rendered {path}")
        return {"FINISHED"}


classes = (
    CSK360_OT_render_video,
    CSK360_OT_add_cast,
    CSK360_OT_add_starter_character,
    CSK360_OT_remove_cast,
    CSK360_OT_set_home,
    CSK360_OT_add_clip,
    CSK360_OT_pose_picker,
    CSK360_OT_remove_clip,
    CSK360_OT_clip_duration,
    CSK360_OT_split_clip,
    CSK360_OT_jump_clip,
    CSK360_OT_add_move,
    CSK360_OT_click_move,
    CSK360_OT_pick_up,
    CSK360_OT_put_down,
    CSK360_OT_remove_carry,
    CSK360_OT_remove_move,
    CSK360_OT_add_line,
    CSK360_OT_remove_line,
    CSK360_OT_rebuild,
    CSK360_OT_save_pose,
    CSK360_OT_detect_labels,
    CSK360_OT_spawn,
    CSK360_OT_remove_spawn,
    CSK360_OT_confirm_label,
    CSK360_OT_check_ability,
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
