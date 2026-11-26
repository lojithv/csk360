# SPDX-License-Identifier: GPL-3.0-or-later
"""CSK360 Creator Shortcuts Kit: clip-based character animation for Blender.

Scripts and agents should use `commands` (see AGENTS.md in the repository).
"""

from . import (commands, compiler, handlers, keymaps, library, model, operators, paths, render, script,
               starter, ui, voice, world)

_modules = (model, operators, ui, keymaps, handlers, paths)


def register():
    for module in _modules:
        module.register()


def unregister():
    for module in reversed(_modules):
        module.unregister()
