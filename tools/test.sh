#!/bin/sh
# Run the headless test suite on macOS or Linux.
#   ./tools/test.sh            all tests
#   ./tools/test.sh move       tests whose name contains "move"
# Set BLENDER if Blender is not at the usual place.
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [ -z "$BLENDER" ]; then
  if [ -x /Applications/Blender.app/Contents/MacOS/Blender ]; then
    BLENDER=/Applications/Blender.app/Contents/MacOS/Blender
  else
    BLENDER=blender
  fi
fi
if [ -n "$1" ]; then set -- -- -k "$1"; fi
exec "$BLENDER" -b --factory-startup --python-exit-code 1 -P "$ROOT/tests/run_tests.py" "$@"
