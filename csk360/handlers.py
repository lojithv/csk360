# SPDX-License-Identifier: GPL-3.0-or-later
"""App handlers: copy generated voices next to the .blend when it is saved."""

import bpy
from bpy.app.handlers import persistent


@persistent
def _save_pre(filepath, *_args):
    from . import commands
    for scene in bpy.data.scenes:
        if hasattr(scene, "csk360") and len(scene.csk360.lines):
            try:
                commands.localize_audio(scene, blend_path=filepath or bpy.data.filepath)
            except OSError as e:  # never block saving
                print(f"CSK360: could not copy voice files: {e}")


def register():
    bpy.app.handlers.save_pre.append(_save_pre)


def unregister():
    if _save_pre in bpy.app.handlers.save_pre:
        bpy.app.handlers.save_pre.remove(_save_pre)
