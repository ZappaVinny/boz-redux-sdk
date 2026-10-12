#!/usr/bin/env python3
"""Regenerate the field reference in docs/weapons.md from bozkit.weapons.FIELDS (the same list the
editor's Weapons tab shows)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools' / 'bozkit'))

from bozkit import weapons  # noqa: E402

DOC = ROOT / 'docs' / 'weapons.md'
START, END = '<!-- fields:start -->', '<!-- fields:end -->'


def table() -> str:
    out = []
    for group in weapons.GROUPS:
        out.append(f'### {group}\n')
        out.append('| Field | Key | Unit | Default | What it does |')
        out.append('| --- | --- | --- | --- | --- |')
        for spec in weapons.FIELDS:
            if spec.group != group:
                continue
            text = spec.description
            if spec.options:
                text += ' Values: ' + ', '.join(f'{v} {label}' for v, label in spec.options) + '.'
            if not spec.confirmed:
                text += ' *Likely (from the shipped weapons).*'
            default = spec.default if spec.kind != 'enum' else dict(spec.options).get(spec.default, spec.default)
            out.append(f'| {spec.label} | `{spec.key}` | {spec.unit} | {default} | {text} |')
        out.append('')
    return '\n'.join(out)


def main() -> int:
    text = DOC.read_text(encoding='utf-8')
    before, rest = text.split(START, 1)
    _, after = rest.split(END, 1)
    DOC.write_text(f'{before}{START}\n{table()}\n{END}{after}', encoding='utf-8', newline='\n')
    print(DOC)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
