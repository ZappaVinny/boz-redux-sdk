#!/usr/bin/env python3
"""Writes docs/game-events.md: every game event (gamedef/events and the runtime names' engine
events) with who sends and handles it and, where known, what its arguments mean
(tools/symbols/event_notes.toml). Run: python3 tools/docgen/events_doc.py
"""
from __future__ import annotations

import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools' / 'bozkit'))
from bozkit.schema import gamedef_file  # noqa: E402


def main() -> int:
    events = tomllib.loads(gamedef_file('events').read_text(encoding='utf-8'))['event']
    runtime = tomllib.loads(gamedef_file('runtime').read_text(encoding='utf-8'))
    notes = tomllib.loads((ROOT / 'tools/symbols/event_notes.toml').read_text(encoding='utf-8'))
    known = {e['name'] for e in events}
    rows = list(events) + [{'name': n} for n in runtime.get('events', {}).get('names', []) if n not in known]
    lines = ['# Game events', '',
             'The game\'s systems talk to each other with events named `SUBJECT_*` (see',
             '[How the game works](how-the-game-works.md#events)). This page lists every one, with the',
             'classes that send and handle it and, where known, what its two arguments mean.', '',
             '## Following an event', '',
             '```lua',
             'local game_events = require("boz.game_events")',
             '',
             'game_events.on("SUBJECT_ADD_SCORE", function(event)',
             '    log("points earned: " .. event.a)',
             'end)',
             '```', '',
             'The handler gets `{name, id, subject, sender, a, b}`; `a` and `b` mean what the notes say',
             "(pointers to the game's structs where noted). Returning true from a handler stops the event.",
             'Most mods never need this: the [standard library](standard-library.md) already turns the common',
             'events into functions such as `boz.rounds.on_start`.', '',
             '## All events', '',
             f'{len(rows)} events; {sum(1 for r in rows if r["name"] in notes)} with notes on their arguments.',
             'This list is generated from the game definition by `tools/docgen/events_doc.py`.', '',
             '| Event | Sent by | Handled by | Notes |', '| --- | --- | --- | --- |']
    for row in sorted(rows, key=lambda r: r['name']):
        sent = ', '.join(row.get('sent_by', [])[:5])
        handled = ', '.join(row.get('handled_by', [])[:5])
        note = notes.get(row['name'], {}).get('note', '').replace('|', '\\|')
        lines.append(f'| `{row["name"]}` | {sent} | {handled} | {note} |')
    out = ROOT / 'docs' / 'game-events.md'
    out.write_text('\n'.join(lines) + '\n', encoding='utf-8', newline='\n')
    print(f'{out}: {len(rows)} events')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
