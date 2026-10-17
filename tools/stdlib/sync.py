#!/usr/bin/env python3
"""Copies the standard library (lib/boz) into the reference mods that carry it (scripts/boz).

    python3 tools/stdlib/sync.py           copy
    python3 tools/stdlib/sync.py --check   exit 1 when a mod's copy differs (CI)

A map project gets the standard library from bozkit at build time; only the reference mods in
this repo keep a copy of their own, so they work as plain folders.
"""
from __future__ import annotations

import argparse
import filecmp
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT / 'lib' / 'boz'
MODS = [ROOT / 'mods' / 'developer']
GENERATED_PER_MOD = {'world_data.lua'}


def differences(mod: Path) -> list[str]:
    copy = mod / 'scripts' / 'boz'
    wanted = {p.name for p in LIB.glob('*.lua')}
    present = {p.name for p in copy.glob('*.lua')} - GENERATED_PER_MOD if copy.is_dir() else set()
    out = [f'missing {name}' for name in sorted(wanted - present)]
    out += [f'extra {name}' for name in sorted(present - wanted)]
    out += [f'differs {name}' for name in sorted(wanted & present)
            if not filecmp.cmp(LIB / name, copy / name, shallow=False)]
    return out


def sync(mod: Path) -> None:
    copy = mod / 'scripts' / 'boz'
    copy.mkdir(parents=True, exist_ok=True)
    for stale in copy.glob('*.lua'):
        if stale.name not in GENERATED_PER_MOD and not (LIB / stale.name).exists():
            stale.unlink()
    for source in LIB.glob('*.lua'):
        shutil.copyfile(source, copy / source.name)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--check', action='store_true', help='only report differences')
    args = parser.parse_args()
    status = 0
    for mod in MODS:
        if args.check:
            found = differences(mod)
            for line in found:
                print(f'{mod.relative_to(ROOT)}: {line}')
            status |= bool(found)
        else:
            sync(mod)
            print(f'{mod.relative_to(ROOT)}: synced')
    return status


if __name__ == '__main__':
    sys.exit(main())
