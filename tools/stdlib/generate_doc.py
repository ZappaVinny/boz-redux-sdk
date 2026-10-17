#!/usr/bin/env python3
"""Writes docs/standard-library.md from the standard lib's own comments (lib/boz/*.lua).

  python3 tools/stdlib/generate_doc.py [lib/boz] [docs/standard-library.md]

Each module's leading comment becomes its description; every public function (`function m.f(...)`
or `function Class:f(...)`) and constant (`m.NAME = ...`) is listed with the `---` comment lines
right above it. Keep those comments current: this page is the standard lib's reference.
"""

import re
import sys
from pathlib import Path

SDK = Path(__file__).resolve().parents[2]

# Reference order and grouping. Modules not listed go to "Other".
GROUPS = [
    ("Gameplay", ["player", "camera", "rounds", "zombies", "weapons", "effects", "score", "pickups",
                  "pieces", "map", "fly", "deadops"]),
    ("Map scripting", ["world", "prefabs", "objects", "match_events", "timers", "saved", "hooks",
                       "game", "levels"]),
    ("Engine access", ["entities", "components", "reflect", "resources", "physics", "game_events",
                       "spawns", "audio", "screen", "hud", "stats", "saves", "network"]),
    ("Controls", ["input"]),
    ("Console", ["console", "cvars"]),
    ("Menus and text", ["pause_settings", "text"]),
    ("Game UI building blocks", ["iwui", "frontend", "flash", "swf", "avm1"]),
    ("Low-level helpers", ["hash", "enums"]),
]
# Internals and generated data: not part of the reference.
HIDDEN = {"core", "symbol_data", "reflection_data", "event_names", "cvar_data", "world_data"}

FUNCTION = re.compile(r"^function ([\w\.]+[\.:]\w+)\((.*)\)")
CONSTANT = re.compile(r"^(\w+\.\w+)\s*=")
ONE_LINER = re.compile(r"^function .*\bend$")


def parse(path):
    lines = path.read_text().splitlines()
    header = []
    for line in lines:
        if line.startswith("--") and not line.startswith("---"):
            header.append(line[3:] if line.startswith("-- ") else line[2:].lstrip())
        else:
            break
    summary, description = "", []
    if header:
        first = header[0]
        summary = first.split(":", 1)[1].strip() if ":" in first else first
        description = header[1:]
    entries = []
    shared = None   # a run of one-line functions under one comment shares it
    for i, line in enumerate(lines):
        match = FUNCTION.match(line) or CONSTANT.match(line)
        if not match:
            shared = None
            continue
        doc = []
        j = i - 1
        while j >= 0 and lines[j].startswith("---"):
            doc.insert(0, lines[j][3:].strip())
            j -= 1
        if not doc and shared and ONE_LINER.match(line) and ONE_LINER.match(lines[i - 1]):
            doc = shared
        shared = doc if ONE_LINER.match(line) else None
        if not doc:
            continue  # internal helpers are left out
        if FUNCTION.match(line):
            name, params = match.group(1), match.group(2)
            entries.append(("%s(%s)" % (name, params), " ".join(doc)))
        else:
            entries.append((match.group(1), " ".join(doc)))
    return summary, description, entries


def paragraphs(lines):
    """Joins comment lines into paragraphs, keeping indented lines (examples) as code."""
    out, text, code = [], [], []

    def flush_text():
        if text:
            joined = " ".join(text)
            if joined.startswith("How it works"):
                body = joined.split(":", 1)[1].strip() if ":" in joined else joined
                joined = "<details><summary>How it works</summary>\n\n%s\n\n</details>" % body
            out.append(joined)
            text.clear()

    def flush_code():
        if code:
            out.append("```lua\n" + "\n".join(code) + "\n```")
            code.clear()

    for line in lines:
        if line.startswith("  "):
            flush_text()
            code.append(line[2:])
        elif not line.strip():
            flush_text()
            flush_code()
        else:
            flush_code()
            text.append(line.strip())
    flush_text()
    flush_code()
    return out


def render(lib):
    modules = {p.stem: parse(p) for p in sorted(lib.glob("*.lua")) if p.stem not in HIDDEN}
    out = [
        "# Standard library",
        "",
        "The standard lib (`boz.*`) is the friendly layer for writing mods: plain functions for the",
        "player, menus, the console and more, with the game's addresses, offsets and events hidden",
        "inside. Mods should use it instead of the client's low-level `game`/`hook` functions",
        "([lua-api.md](lua-api.md)) wherever it covers what they need.",
        "",
        "This page is generated from the comments in `lib/boz/*.lua` (`tools/stdlib/generate_doc.py`); see",
        "[making-mods.md](making-mods.md) for how to use it in a mod.",
        "",
        "Using it in a mod: an SDK project's build adds it to the mod as `scripts/boz`; then",
        "`local player = require(\"boz.player\")`. Each mod carries its own copy; copies in different",
        "mods work together.",
        "",
        "Functions that need a Zombies match return `nil` (or `false`) outside one instead of failing.",
        "",
        "## Contents",
        "",
    ]
    listed = set()
    for title, names in GROUPS:
        present = [n for n in names if n in modules]
        listed.update(present)
        out.append("- **%s**: %s" % (title, ", ".join("[boz.%s](#boz%s)" % (n, n.replace("_", "")) for n in present)))
    others = [n for n in modules if n not in listed]
    if others:
        out.append("- **Other**: " + ", ".join("[boz.%s](#boz%s)" % (n, n.replace("_", "")) for n in others))
    out.append("")
    for title, names in GROUPS + [("Other", others)]:
        present = [n for n in names if n in modules]
        if not present:
            continue
        out.append("## %s" % title)
        out.append("")
        for name in present:
            summary, description, entries = modules[name]
            out.append("### boz.%s" % name)
            out.append("")
            if summary:
                out.append(summary[0].upper() + summary[1:])
                out.append("")
            for para in paragraphs(description):
                out.append(para)
                out.append("")
            if entries:
                out.append("| Function | Description |")
                out.append("| --- | --- |")
                for signature, doc in entries:
                    out.append("| `%s` | %s |" % (signature, doc.replace("|", "\\|")))
                out.append("")
    return "\n".join(out)


def main(argv):
    lib = Path(argv[1]) if len(argv) > 1 else SDK / "lib" / "boz"
    target = Path(argv[2]) if len(argv) > 2 else SDK / "docs" / "standard-library.md"
    target.write_text(render(lib))
    print("%s: %d modules" % (target, len([p for p in lib.glob("*.lua") if p.stem not in HIDDEN])))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
