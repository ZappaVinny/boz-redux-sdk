#!/usr/bin/env python3
"""Build a deterministic Blender add-on ZIP with the required bozkit codecs bundled."""
from __future__ import annotations

import argparse
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADDON = ROOT / 'blender' / 'boz_redux'
BOZKIT = ROOT / 'tools' / 'bozkit' / 'bozkit'
VENDORED = {
    '__init__.py', 'blender_scene.py', 'collision.py', 'group.py', 'hashing.py',
    'map_resources.py', 'native.py', 'navigation.py', 'reflect.py', 'resources.py',
}
ZIP_TIME = (1980, 1, 1, 0, 0, 0)


def _write(archive: zipfile.ZipFile, name: str, data: bytes) -> None:
    info = zipfile.ZipInfo(name, ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    archive.writestr(info, data)


def build(output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'w') as archive:
        for path in sorted(ADDON.glob('*.py')):
            _write(archive, f'boz_redux/{path.name}', path.read_bytes())
        _write(archive, 'boz_redux/_vendor/__init__.py', b'')
        for name in sorted(VENDORED):
            _write(archive, f'boz_redux/_vendor/bozkit/{name}', (BOZKIT / name).read_bytes())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('output', nargs='?', type=Path,
                        default=ROOT / 'build' / 'blender' / 'boz-redux-blender.zip')
    args = parser.parse_args()
    build(args.output)
    print(args.output.resolve())
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
