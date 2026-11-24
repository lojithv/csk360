# SPDX-License-Identifier: GPL-3.0-or-later
"""CSK360 Creator Shortcuts Kit: clip-based character animation for Blender.

Scripts and agents should use `commands` (see AGENTS.md in the repository).
"""

from . import commands, compiler, keymaps, library, model, operators, ui

_modules = (model, operators, ui, keymaps)


def register():
    for module in _modules:
        module.register()


def unregister():
    for module in reversed(_modules):
        module.unregister()
