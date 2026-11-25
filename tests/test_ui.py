# SPDX-License-Identifier: GPL-3.0-or-later
"""Draw every CSK360 panel, list and menu into a recording layout.

Headless Blender cannot draw UI, so this checks the draw code instead: every
property it shows must exist, every button must name a real operator, and
every operator property it sets must exist. Catches typos before a user does.
"""

import unittest

import bpy

from csk360 import commands, ui

import helpers as h


class _OpProps:
    def __init__(self, test, idname):
        mod, name = idname.split(".")
        op = getattr(getattr(bpy.ops, mod), name)
        object.__setattr__(self, "_names", set(op.get_rna_type().properties.keys()))
        object.__setattr__(self, "_test", test)
        object.__setattr__(self, "_idname", idname)

    def __setattr__(self, key, value):
        self._test.assertIn(key, self._names, f"{self._idname} has no property '{key}'")


class _Layout:
    """Accepts the UILayout calls CSK360 uses and checks their arguments."""

    def __init__(self, test):
        self.test = test
        self.enabled = True
        self.active = True

    def _child(self, *args, **kwargs):
        return _Layout(self.test)

    row = column = box = split = grid_flow = column_flow = menu_pie = _child

    def _check_prop(self, data, name):
        rna = getattr(data, "bl_rna", None)
        ok = (rna is not None and name in rna.properties) or hasattr(data, name)
        self.test.assertTrue(ok, f"{type(data).__name__} has no property '{name}'")

    def prop(self, data, name, **kwargs):
        self._check_prop(data, name)

    def prop_enum(self, data, name, value, **kwargs):
        self._check_prop(data, name)
        rna = getattr(data, "bl_rna", None)
        if rna is not None and name in rna.properties:
            self.test.assertIn(value, rna.properties[name].enum_items.keys())

    def prop_search(self, data, name, search_data, search_name, **kwargs):
        self._check_prop(data, name)
        self.test.assertTrue(hasattr(search_data, search_name))

    def operator(self, idname, **kwargs):
        return _OpProps(self.test, idname)

    def label(self, **kwargs):
        pass

    separator = label

    def template_list(self, list_type, list_id, data, propname, active_data, active_propname, **kwargs):
        self.test.assertTrue(hasattr(bpy.types, list_type), list_type)
        self._check_prop(data, propname)
        self._check_prop(active_data, active_propname)


class _Ctx:
    """The parts of bpy.context the draw code reads."""

    def __init__(self, scene, obj):
        self.scene = scene
        self.active_object = obj
        self.object = obj
        self.mode = "OBJECT"
        self.selected_objects = [obj] if obj else []


class UiDrawTests(unittest.TestCase):
    def setUp(self):
        self.scene = h.reset_scene()
        self.leo = commands.add_starter_character(self.scene, "Leo")
        commands.add_clip(self.scene, self.leo, "wave", start=0)
        commands.add_move(self.scene, self.leo, start=0, point=(1, 0, 0))
        commands.add_line(self.scene, self.leo, "Hi there", start=1, duration=1,
                          visemes=[(0, "B"), (0.5, "X")])
        self.rig = commands.get_cast(self.scene, self.leo).object

    def draw(self, cls, obj):
        layout = _Layout(self)
        ctx = _Ctx(self.scene, obj)
        # Panels and menus read self.layout; bind a stand-in instance.
        inst = type("Stub", (), {"layout": layout})()
        if hasattr(cls, "poll") and not cls.poll(ctx):
            return False
        cls.draw(inst, ctx)
        return True

    def test_every_panel_and_menu_draws(self):
        drawn = []
        for cls in ui.classes:
            if issubclass(cls, (bpy.types.Panel, bpy.types.Menu)):
                for obj in (self.rig, None):
                    if self.draw(cls, obj):
                        drawn.append(cls.__name__)
        for name in ("CSK360_PT_cast", "CSK360_PT_clips", "CSK360_PT_moves", "CSK360_PT_dialogue",
                     "CSK360_PT_voices", "CSK360_PT_output", "CSK360_PT_library", "CSK360_MT_pose_pie"):
            self.assertIn(name, drawn)

    def test_lists_draw_and_filter(self):
        layout = _Layout(self)
        ctx = _Ctx(self.scene, self.rig)
        proj = self.scene.csk360
        for cls, coll in ((ui.CSK360_UL_cast, proj.cast), (ui.CSK360_UL_clips, proj.clips),
                          (ui.CSK360_UL_moves, proj.moves), (ui.CSK360_UL_lines, proj.lines)):
            inst = type("Stub", (), {"bitflag_filter_item": 1 << 30})()
            for i, item in enumerate(coll):
                cls.draw_item(inst, ctx, layout, proj, item, 0, proj, "", i)
            if "filter_items" in cls.__dict__:
                flags, order = cls.filter_items(inst, ctx, proj, coll.path_from_id().split(".")[-1])
                self.assertEqual(len(flags), len(coll))

    def test_pose_picker_popup_draws(self):
        from csk360.operators import CSK360_OT_pose_picker
        layout = _Layout(self)
        inst = type("Stub", (), {"layout": layout, "search": "wave", "category": "ALL"})()
        CSK360_OT_pose_picker.draw(inst, _Ctx(self.scene, self.rig))


if __name__ == "__main__":
    unittest.main()
