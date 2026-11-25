# SPDX-License-Identifier: GPL-3.0-or-later
"""Run CSK360 straight from this repository in a normal Blender window,
without installing it or touching your preferences:

    blender [file.blend] --python tools/dev_load.py
"""

import os
import sys

import bpy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

if any(k == "csk360" or k.endswith(".csk360") for k in bpy.context.preferences.addons.keys()):
    print("CSK360 is already enabled as an extension; disable it to run the repository copy.")
else:
    import csk360
    csk360.register()
    print("CSK360 loaded from", os.path.join(ROOT, "csk360"))
