#!/usr/bin/env python3
"""Build a deterministic Blender add-on ZIP with the required bozkit codecs bundled."""
from __future__ import annotations

import argparse
import hashlib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADDON = ROOT / 'blender' / 'boz_redux'
BOZKIT = ROOT / 'tools' / 'bozkit' / 'bozkit'
VENDORED = {
    '__init__.py', 'blender_scene.py', 'bullet.py', 'collision.py', 'group.py', 'hashing.py',
    'map_resources.py', 'native.py', 'navbuild.py', 'navigation.py', 'reflect.py', 'resources.py',
}
ZIP_TIME = (1980, 1, 1, 0, 0, 0)
NAVMESH_HELPERS = [ROOT / 'tools' / 'navmesh' / 'build' / name
                   for name in ('boz-navmesh', 'boz-navmesh.exe')]


def _write(archive: zipfile.ZipFile, name: str, data: bytes, mode: int = 0o644) -> None:
    info = zipfile.ZipInfo(name, ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = (0o100000 | mode) << 16
    archive.writestr(info, data)


def build(output: Path) -> str:
    files = {f'boz_redux/{path.name}': path.read_bytes()
             for path in sorted(ADDON.glob('*.py')) if path.name != '_build.py'}
    files['boz_redux/_vendor/__init__.py'] = b''
    for name in sorted(VENDORED):
        files[f'boz_redux/_vendor/bozkit/{name}'] = (BOZKIT / name).read_bytes()
    # The navmesh helper is native code built from tools/navmesh; bundle the one for this platform.
    for helper in NAVMESH_HELPERS:
        if helper.is_file():
            files[f'boz_redux/_vendor/bozkit/{helper.name}'] = helper.read_bytes()
    # A content hash identifies the build in Blender's sidebar while keeping the ZIP reproducible.
    digest = hashlib.sha256()
    for name in sorted(files):
        digest.update(name.encode() + b'\0' + files[name])
    build_id = digest.hexdigest()[:8]
    files['boz_redux/_build.py'] = f'BUILD = "{build_id}"\n'.encode()
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'w') as archive:
        for name in sorted(files):
            _write(archive, name, files[name], 0o755 if 'boz-navmesh' in name else 0o644)
    return build_id


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('output', nargs='?', type=Path,
                        default=ROOT / 'build' / 'blender' / 'boz-redux-blender.zip')
    args = parser.parse_args()
    build_id = build(args.output)
    helper = next((path for path in NAVMESH_HELPERS if path.is_file()), None)
    print(f'{args.output.resolve()} (build {build_id})')
    if helper is None:
        print('warning: tools/navmesh is not built; the add-on cannot rebuild navmeshes')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
