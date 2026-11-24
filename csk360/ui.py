# SPDX-License-Identifier: GPL-3.0-or-later
"""CSK360 sidebar tab in the 3D viewport (N panel)."""

import bpy

from . import library
from .model import MOUTH_SHAPES
from .operators import active_item, context_cast

LAYER_ICONS = {"BODY": "ARMATURE_DATA", "GESTURE": "VIEW_PAN", "FACE": "USER"}


def _sorted_for_cast(ui_list, items, cast_id, key):
    flags = [ui_list.bitflag_filter_item if it.cast_id == cast_id else 0 for it in items]
    ranked = sorted(range(len(items)), key=lambda i: key(items[i]))
    order = [0] * len(items)
    for rank, i in enumerate(ranked):
        order[i] = rank
    return flags, order


class CSK360_UL_cast(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        row.prop(item, "name", text="", emboss=False,
                 icon="OUTLINER_OB_ARMATURE" if item.rig_type != "prop" else "OBJECT_DATA")
        row.label(text=item.object.name if item.object else "(missing)")


class CSK360_UL_clips(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        row.label(text=item.asset or "?", icon=LAYER_ICONS.get(item.layer, "ACTION"))
        row.prop(item, "start", text="")
        row.prop(item, "duration", text="")

    def filter_items(self, context, data, propname):
        cast = context_cast(context)
        return _sorted_for_cast(self, getattr(data, propname), cast.id if cast else "",
                                lambda c: (c.start, c.layer))


class CSK360_UL_moves(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        if item.target_kind == "OBJECT":
            label = item.target_object.name if item.target_object else "(no target)"
        else:
            label = "({:.1f}, {:.1f})".format(*item.target_point[:2])
        row.label(text=label, icon="TRACKING_FORWARDS")
        row.prop(item, "start", text="")
        row.label(text=f"{item.duration:.1f}s")

    def filter_items(self, context, data, propname):
        cast = context_cast(context)
        return _sorted_for_cast(self, getattr(data, propname), cast.id if cast else "",
                                lambda m: m.start)


class CSK360_UL_lines(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        row.prop(item, "text", text="", emboss=False, icon="SPEAKER")
        row.prop(item, "start", text="")

    def filter_items(self, context, data, propname):
        cast = context_cast(context)
        return _sorted_for_cast(self, getattr(data, propname), cast.id if cast else "",
                                lambda l: l.start)


class _Panel:
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "CSK360"


class CSK360_PT_cast(_Panel, bpy.types.Panel):
    bl_label = "Cast"

    def draw(self, context):
        layout = self.layout
        proj = context.scene.csk360
        layout.operator("csk360.add_starter_character", icon="OUTLINER_OB_ARMATURE")
        row = layout.row()
        row.template_list("CSK360_UL_cast", "", proj, "cast", proj, "active_cast_index", rows=3)
        col = row.column(align=True)
        col.operator("csk360.add_cast", text="", icon="ADD")
        col.operator("csk360.remove_cast", text="", icon="REMOVE")

        cast = context_cast(context)
        if cast is not None:
            box = layout.box()
            box.label(text=f"Editing: {cast.name}", icon="USER")
            box.prop(cast, "rig_type")
            box.prop(cast, "voice")
            box.operator("csk360.set_home", icon="PIVOT_CURSOR")
        layout.operator("csk360.rebuild", icon="FILE_REFRESH")
        if proj.last_report:
            for msg in proj.last_report.split("; ")[:5]:
                layout.label(text=msg, icon="ERROR")


class CSK360_PT_clips(_Panel, bpy.types.Panel):
    bl_label = "Poses and Actions"
    bl_parent_id = "CSK360_PT_cast"

    @classmethod
    def poll(cls, context):
        return context_cast(context) is not None

    def draw(self, context):
        layout = self.layout
        proj = context.scene.csk360
        row = layout.row()
        row.template_list("CSK360_UL_clips", "", proj, "clips", proj, "active_clip_index", rows=4)
        col = row.column(align=True)
        col.operator("csk360.add_clip", text="", icon="ADD").asset = ""
        col.operator("csk360.remove_clip", text="", icon="REMOVE")

        clip = active_item(proj.clips, proj.active_clip_index)
        cast = context_cast(context)
        if clip is None or cast is None or clip.cast_id != cast.id:
            return
        row = layout.row(align=True)
        op = row.operator("csk360.clip_duration", text="-1 s", icon="REMOVE")
        op.delta, op.by_frames = -1.0, False
        op = row.operator("csk360.clip_duration", text="+1 s", icon="ADD")
        op.delta, op.by_frames = 1.0, False
        col = layout.column()
        col.prop_search(clip, "asset", bpy.data, "actions")
        col.prop(clip, "layer")
        col.prop(clip, "loop_mode")
        col.prop(clip, "start")
        col.prop(clip, "duration")
        sub = col.row(align=True)
        sub.prop(clip, "blend_in")
        sub.prop(clip, "blend_out")


class CSK360_PT_moves(_Panel, bpy.types.Panel):
    bl_label = "Movement"
    bl_parent_id = "CSK360_PT_cast"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return context_cast(context) is not None

    def draw(self, context):
        layout = self.layout
        proj = context.scene.csk360
        row = layout.row(align=True)
        row.operator("csk360.add_move", text="Walk to Cursor", icon="PIVOT_CURSOR").to = "CURSOR"
        row.operator("csk360.add_move", text="Walk to Selected", icon="OBJECT_DATA").to = "SELECTED"
        row = layout.row()
        row.template_list("CSK360_UL_moves", "", proj, "moves", proj, "active_move_index", rows=3)
        row.operator("csk360.remove_move", text="", icon="REMOVE")
        m = active_item(proj.moves, proj.active_move_index)
        cast = context_cast(context)
        if m is None or cast is None or m.cast_id != cast.id:
            return
        col = layout.column()
        col.prop(m, "start")
        col.prop(m, "target_kind")
        col.prop(m, "target_object" if m.target_kind == "OBJECT" else "target_point")
        col.prop(m, "speed")
        col.prop_search(m, "walk_asset", bpy.data, "actions")
        col.prop_search(m, "arrival_asset", bpy.data, "actions")
        col.label(text=f"Walk time: {m.duration:.2f} s")


class CSK360_PT_dialogue(_Panel, bpy.types.Panel):
    bl_label = "Dialogue"
    bl_parent_id = "CSK360_PT_cast"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return context_cast(context) is not None

    def draw(self, context):
        layout = self.layout
        proj = context.scene.csk360
        row = layout.row()
        row.template_list("CSK360_UL_lines", "", proj, "lines", proj, "active_line_index", rows=3)
        col = row.column(align=True)
        col.operator("csk360.add_line", text="", icon="ADD")
        col.operator("csk360.remove_line", text="", icon="REMOVE")
        line = active_item(proj.lines, proj.active_line_index)
        cast = context_cast(context)
        if line is None or cast is None or line.cast_id != cast.id:
            return
        col = layout.column()
        col.prop(line, "text")
        col.prop(line, "start")
        col.prop(line, "audio_path")
        col.prop(line, "duration")
        col.prop(line, "emotion")
        shapes = "".join(MOUTH_SHAPES[v.shape] for v in line.visemes[:40])
        col.label(text=f"Mouth: {shapes or 'none yet'}")


class CSK360_PT_library(_Panel, bpy.types.Panel):
    bl_label = "Library"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        layout.operator("csk360.mark_asset", icon="ASSET_MANAGER")
        assets = library.search(marked_only=True)
        if not assets:
            layout.label(text="No library actions yet.")
            return
        can_add = context_cast(context) is not None
        for a in assets:
            row = layout.row(align=True)
            row.label(text=a["id"], icon=LAYER_ICONS.get(a["layer"], "ACTION"))
            row.label(text=f"{a['kind']}, {a['duration']:.1f}s")
            sub = row.row(align=True)
            sub.enabled = can_add
            sub.operator("csk360.add_clip", text="", icon="ADD").asset = a["id"]


classes = (
    CSK360_UL_cast,
    CSK360_UL_clips,
    CSK360_UL_moves,
    CSK360_UL_lines,
    CSK360_PT_cast,
    CSK360_PT_clips,
    CSK360_PT_moves,
    CSK360_PT_dialogue,
    CSK360_PT_library,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
