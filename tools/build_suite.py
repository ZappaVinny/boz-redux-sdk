#!/usr/bin/env python3
"""Assemble the BOZ Redux editor: a Blender user scripts folder holding the boz_suite app
template and the bozkit modules it needs, with a generated startup.blend.

    build/suite/scripts/startup/bl_app_templates_user/boz_suite/   app template (+ _vendor/bozkit)

The launcher runs Blender with BLENDER_USER_SCRIPTS pointing here. In a checkout it rebuilds
this folder when the sources are newer.
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / 'blender' / 'boz_suite'
BOZKIT = ROOT / 'tools' / 'bozkit' / 'bozkit'
OUTPUT = ROOT / 'build' / 'suite'
NOT_VENDORED = {'desktop.py', 'desktop_window.py', 'desktop_style.py', '__main__.py'}
sys.path.insert(0, str(BOZKIT.parent))
from bozkit.schema import gamedef_file  # noqa: E402
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
    files = [*TEMPLATE.glob('*.py'), *BOZKIT.glob('*.py'), Path(__file__),
             *(ROOT / 'gamedef' / 'runtime').glob('*.toml')]
    return files


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
    runtime = gamedef_file('runtime')
    if runtime.is_file():
        shutil.copy2(runtime, target / '_vendor' / 'bozkit' / 'runtime_names.toml')


PILLOW = 'pillow==11.3.0'
PILLOW_FOLDERS = {'linux': 'pillow-linux', 'win32': 'pillow-windows'}
PILLOW_PLATFORMS = {'pillow-linux': 'manylinux_2_28_x86_64', 'pillow-windows': 'win_amd64'}


def _blender_python(blender: Path) -> Path | None:
    """The Python an official Blender build carries (<version>/python/bin/python*), or None when
    Blender uses the system's Python (Linux distribution packages)."""
    found = sorted(blender.resolve().parent.glob('*/python/bin/python*'))
    return next((path for path in found
                 if path.name == 'python.exe' or re.fullmatch(r'python3\.\d+', path.name)), None)


def _vendor_pillow(blender: Path, vendor: Path, all_platforms: bool) -> None:
    """bozkit uses Pillow for images, which Blender's own Python lacks: install it with that
    Python's pip next to the editor's bozkit (bozkit/__init__.py finds it). all_platforms (the
    release build) also adds the other system's copy, for the same Python version."""
    python = _blender_python(blender)
    if python is None:
        return
    here = PILLOW_FOLDERS['win32' if sys.platform == 'win32' else 'linux']
    install = subprocess.run([str(python), '-m', 'pip', 'install', PILLOW, '--quiet',
                              '--disable-pip-version-check', '--target', str(vendor / here)],
                             capture_output=True, text=True, encoding='utf-8', errors='replace')
    if install.returncode != 0:
        raise RuntimeError(f'cannot install Pillow with {python}:\n{install.stderr}')
    if not all_platforms:
        return
    version = python.name.removeprefix('python').replace('.', '')   # python3.13 -> 313
    for folder, platform in PILLOW_PLATFORMS.items():
        if folder == here:
            continue
        with tempfile.TemporaryDirectory() as temp:
            download = subprocess.run(
                [str(python), '-m', 'pip', 'download', PILLOW, '--quiet', '--no-deps',
                 '--disable-pip-version-check', '--only-binary=:all:', '--implementation', 'cp',
                 '--python-version', version, '--platform', platform, '--dest', temp],
                capture_output=True, text=True, encoding='utf-8', errors='replace')
            wheels = list(Path(temp).glob('*.whl'))
            if download.returncode != 0 or not wheels:
                raise RuntimeError(f'cannot download Pillow for {platform}:\n{download.stderr}')
            with zipfile.ZipFile(wheels[0]) as wheel:
                wheel.extractall(vendor / folder)


def build(blender: str | Path, output: Path = OUTPUT, all_platforms: bool = False) -> Path:
    blender = Path(blender)
    launcher_target = blender.with_name('blender.exe')
    if blender.name.lower() == 'blender-launcher.exe' and launcher_target.is_file():
        blender = launcher_target   # the launcher passes no output or exit code back
    scripts = output / 'scripts'
    if output.exists():
        shutil.rmtree(output)
    template = scripts / 'startup' / 'bl_app_templates_user' / 'boz_suite'
    template.mkdir(parents=True)
    for path in sorted(TEMPLATE.glob('*.py')):
        shutil.copy2(path, template / path.name)
    _vendor(template)
    script = output / 'generate.py'
    script.write_text(GENERATE, encoding='utf-8', newline='\n')
    startup = template / 'startup.blend'
    _vendor_pillow(blender, template / '_vendor', all_platforms)
    result = subprocess.run([str(blender), '-b', '--factory-startup', '--python', str(script),
                             '--', str(template / 'tabs.py'), str(startup)],
                            capture_output=True, text=True, encoding='utf-8', errors='replace')
    script.unlink()
    if result.returncode != 0 or not startup.is_file():
        raise RuntimeError(f'startup.blend was not generated:\n{result.stdout}\n{result.stderr}')
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--blender', default=shutil.which('blender') or 'blender')
    parser.add_argument('-o', '--output', type=Path, default=OUTPUT)
    parser.add_argument('--all-platforms', action='store_true',
                        help='also bundle Pillow for the other system (release packages)')
    args = parser.parse_args()
    try:
        print(build(args.blender, args.output, args.all_platforms))
    except (OSError, RuntimeError) as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
