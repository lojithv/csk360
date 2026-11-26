# SPDX-License-Identifier: GPL-3.0-or-later
"""Default shortcuts. `M` click to walk (character active only), `P` pose pie, `]` / `[` change the active clip by one second,
with Shift by one frame; Alt+Left / Alt+Right jump between clip boundaries.
Bound in Object Mode only (Pose mode uses the
bracket keys for hierarchy selection). Can be switched off in the
extension preferences."""

import bpy
from bpy.props import BoolProperty

_keymaps = []

BINDINGS = (
    # key, shift, delta, by_frames
    ("RIGHT_BRACKET", False, 1.0, False),
    ("LEFT_BRACKET", False, -1.0, False),
    ("RIGHT_BRACKET", True, 1.0, True),
    ("LEFT_BRACKET", True, -1.0, True),
)


def _add_keymaps():
    kc = bpy.context.window_manager.keyconfigs.addon
    if kc is None:  # background mode
        return
    km = kc.keymaps.new(name="Object Mode", space_type="EMPTY")
    for key, shift, delta, by_frames in BINDINGS:
        kmi = km.keymap_items.new("csk360.clip_duration", key, "PRESS", shift=shift)
        kmi.properties.delta = delta
        kmi.properties.by_frames = by_frames
        _keymaps.append((km, kmi))
    # M only takes over when a CSK360 character is active (the operator's poll
    # fails otherwise and Blender's "Move to Collection" runs as usual).
    kmi = km.keymap_items.new("csk360.click_move", "M", "PRESS")
    _keymaps.append((km, kmi))
    kmi = km.keymap_items.new("wm.call_menu_pie", "P", "PRESS")
    kmi.properties.name = "CSK360_MT_pose_pie"
    _keymaps.append((km, kmi))
    for key, direction in (("RIGHT_ARROW", "NEXT"), ("LEFT_ARROW", "PREV")):
        kmi = km.keymap_items.new("csk360.jump_clip", key, "PRESS", alt=True)
        kmi.properties.direction = direction
        _keymaps.append((km, kmi))


def _remove_keymaps():
    for km, kmi in _keymaps:
        try:
            km.keymap_items.remove(kmi)
        except (ReferenceError, RuntimeError):
            pass
    _keymaps.clear()


def _shortcuts_changed(self, context):
    _remove_keymaps()
    if self.use_shortcuts:
        _add_keymaps()


class CSK360_Preferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    use_shortcuts: BoolProperty(
        name="CSK360 Shortcuts",
        description="In Object Mode with a character active: M click to walk, P pose pie, "
                    "] and [ lengthen or shorten the active clip "
                    "(Shift: by one frame), Alt+Left/Right jump between clips",
        default=True,
        update=_shortcuts_changed,
    )

    def draw(self, context):
        self.layout.prop(self, "use_shortcuts")


def _prefs():
    addon = bpy.context.preferences.addons.get(__package__)
    return addon.preferences if addon else None


def register():
    bpy.utils.register_class(CSK360_Preferences)
    prefs = _prefs()
    if prefs is None or prefs.use_shortcuts:
        _add_keymaps()


def unregister():
    _remove_keymaps()
    bpy.utils.unregister_class(CSK360_Preferences)
