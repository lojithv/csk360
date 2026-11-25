# SPDX-License-Identifier: GPL-3.0-or-later
"""Build a CSK360 scene from a script, headless.

    blender -b [scene.blend] -P csk360_build.py -- script.yaml [options]

Options:
    --save out.blend     save the result (default: overwrite the opened .blend, if any)
    --no-voices          skip voice generation (lines keep their text, no audio)
    --validate           only check the script and print problems
    --render out.mp4     render an MP4 (H.264 + AAC) after building
    --engine NAME        workbench (fast, default for --render) or eevee
    --subtitles MODE     srt (default), burn, both or none
    --frames A-B         render only frames A to B
    --json               print the report as JSON (for agents)

Exit code 0 on success, 1 when the script has errors.
"""

import importlib
import json
import os
import sys

import bpy


def _csk360():
    """The enabled extension if there is one, else this folder as a package."""
    for key in bpy.context.preferences.addons.keys():
        if key == "csk360" or key.endswith(".csk360"):
            return importlib.import_module(key)
    here = os.path.dirname(os.path.abspath(__file__))
    parent, name = os.path.split(here)
    if parent not in sys.path:
        sys.path.insert(0, parent)
    pkg = importlib.import_module(name)
    pkg.register()
    return pkg


def main(argv):
    if not argv or argv[0].startswith("--"):
        print(__doc__)
        return 1
    path, opts = argv[0], argv[1:]

    def opt(name):
        return opts[opts.index(name) + 1] if name in opts and opts.index(name) + 1 < len(opts) else None

    if not bpy.data.filepath:
        # No .blend given: start from an empty scene, not the default cube.
        bpy.ops.wm.read_factory_settings(use_empty=True)
    pkg = _csk360()
    script_mod = importlib.import_module(pkg.__name__ + ".script")
    scene = bpy.context.scene
    try:
        data = script_mod.load(path)
        if "--validate" in opts:
            errors, warnings = script_mod.validate(data, scene)
            report = {"ok": not errors, "errors": errors, "warnings": warnings}
        else:
            report = script_mod.build(scene, data, voices="--no-voices" not in opts)
            report["ok"] = not report["voice_errors"]
            if opt("--render"):
                render = importlib.import_module(pkg.__name__ + ".render")
                frames = None
                if opt("--frames"):
                    a, _, b = opt("--frames").partition("-")
                    frames = (int(a), int(b))
                report["video"] = render.render_video(
                    scene, opt("--render"), engine=opt("--engine") or "workbench",
                    subtitles=opt("--subtitles") or "srt", frames=frames)
            save = opt("--save") or (bpy.data.filepath or None)
            if save:  # after rendering, so the camera, stage and subtitles are saved too
                bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(save))
                report["saved"] = os.path.abspath(save)
    except script_mod.ScriptError as e:
        report = {"ok": False, "errors": e.problems, "warnings": []}
    if "--json" in opts:
        print(json.dumps(report, indent=2))
    else:
        for e in report.get("errors", []) + report.get("voice_errors", []):
            print("ERROR:", e)
        for w in report.get("warnings", []):
            print("warning:", w)
        if report.get("ok"):
            print(f"CSK360: built {len(report.get('cast', {}))} character(s), "
                  f"{len(report.get('clips', []))} clip(s), {len(report.get('moves', []))} move(s), "
                  f"{len(report.get('lines', []))} line(s)"
                  + (f"; saved {report['saved']}" if report.get("saved") else "")
                  + (f"; rendered {report['video']}" if report.get("video") else ""))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    code = main(argv)
    if bpy.app.background:
        sys.exit(code)
