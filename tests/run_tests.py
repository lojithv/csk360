# SPDX-License-Identifier: GPL-3.0-or-later
"""Headless test runner.

    blender -b --factory-startup --python-exit-code 1 -P tests/run_tests.py

Optional: append `-- -k pattern` to run matching tests only.
"""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import bpy  # noqa: E402
import csk360  # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
pattern = argv[argv.index("-k") + 1] if "-k" in argv else None

print(f"CSK360 tests on Blender {bpy.app.version_string}")
csk360.register()
try:
    loader = unittest.TestLoader()
    if pattern:
        loader.testNamePatterns = [f"*{pattern}*"]
    suite = loader.discover(HERE, pattern="test_*.py")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
finally:
    csk360.unregister()

# Register/unregister must be repeatable (extension reloads).
csk360.register()
csk360.unregister()

if not result.wasSuccessful():
    raise SystemExit(1)
