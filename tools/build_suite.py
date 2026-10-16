#!/usr/bin/env python3
"""Assemble the BOZ Redux editor: a Blender user scripts folder holding the boz_suite app
template, the boz_redux add-on and the bozkit modules both need, with a generated startup.blend.

    build/suite/scripts/startup/bl_app_templates_user/boz_suite/   app template (+ _vendor/bozkit)
    build/suite/scripts/addons/boz_redux/                          add-on (+ _vendor/bozkit)

The launcher runs Blender with BLENDER_USER_SCRIPTS pointing here. In a checkout it rebuilds
this folder when the sources are newer.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / 'blender' / 'boz_suite'
ADDON = ROOT / 'blender' / 'boz_redux'
BOZKIT = ROOT / 'tools' / 'bozkit' / 'bozkit'
OUTPUT = ROOT / 'build' / 'suite'
NOT_VENDORED = {'desktop.py', '__main__.py'}
NAVMESH_HELPERS = [ROOT / 'tools' / 'navmesh' / 'build' / name
                   for name in ('boz-navmesh', 'boz-navmesh.exe')]
GENERATE = '''
import importlib.util, sys
import bpy
spec = importlib.util.spec_from_file_location("boz_suite_tabs", sys.argv[-2])
tabs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tabs)
tabs.generate()
bpy.ops.wm.save_as_mainfile(filepath=sys.argv[-1], compress=True)
'''


def sources() -> list[Path]:
    files = [*TEMPLATE.glob('*.py'), *ADDON.glob('*.py'), *BOZKIT.glob('*.py'), Path(__file__),
             *(ROOT / 'gamedef' / 'runtime').glob('*.toml')]
    return [path for path in files if path.name != '_build.py']


def stale(output: Path = OUTPUT) -> bool:
    marker = output / 'scripts' / 'startup' / 'bl_app_templates_user' / 'boz_suite' / 'startup.blend'
    if not marker.is_file():
        return True
    built = marker.stat().st_mtime
    return any(path.stat().st_mtime > built for path in sources())


def _vendor(target: Path) -> None:
    (target / '_vendor' / 'bozkit').mkdir(parents=True)
    (target / '_vendor' / '__init__.py').write_bytes(b'')
    for path in sorted(BOZKIT.glob('*.py')):
        if path.name not in NOT_VENDORED:
            shutil.copy2(path, target / '_vendor' / 'bozkit' / path.name)
    for helper in NAVMESH_HELPERS:
        if helper.is_file():
            shutil.copy2(helper, target / '_vendor' / 'bozkit' / helper.name)
    # The game definition's runtime names (bozkit.bundle: what classes play or spawn by name).
    runtime = ROOT / 'gamedef' / 'runtime' / 'boz-1.0.11.toml'
    if runtime.is_file():
        shutil.copy2(runtime, target / '_vendor' / 'bozkit' / 'runtime_names.toml')


def build(blender: str | Path, output: Path = OUTPUT) -> Path:
    scripts = output / 'scripts'
    if output.exists():
        shutil.rmtree(output)
    template = scripts / 'startup' / 'bl_app_templates_user' / 'boz_suite'
    addon = scripts / 'addons' / 'boz_redux'
    template.mkdir(parents=True)
    addon.mkdir(parents=True)
    for path in sorted(TEMPLATE.glob('*.py')):
        shutil.copy2(path, template / path.name)
    for path in sorted(ADDON.glob('*.py')):
        if path.name != '_build.py':
            shutil.copy2(path, addon / path.name)
    (addon / '_build.py').write_text('BUILD = "suite"\n')
    _vendor(template)
    _vendor(addon)
    script = output / 'generate.py'
    script.write_text(GENERATE)
    startup = template / 'startup.blend'
    result = subprocess.run([str(blender), '-b', '--factory-startup', '--python', str(script),
                             '--', str(template / 'tabs.py'), str(startup)],
                            capture_output=True, text=True)
    script.unlink()
    if result.returncode != 0 or not startup.is_file():
        raise RuntimeError(f'startup.blend was not generated:\n{result.stdout}\n{result.stderr}')
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--blender', default=shutil.which('blender') or 'blender')
    parser.add_argument('-o', '--output', type=Path, default=OUTPUT)
    args = parser.parse_args()
    try:
        print(build(args.blender, args.output))
    except (OSError, RuntimeError) as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
