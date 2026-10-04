#!/usr/bin/env python3
"""BOZ Redux symbol database tool.

The database (gamedef/symbols/boz-1.0.11.toml) is the committed record of what the game's code is:
names, addresses, signatures, structs and notes. Ghidra is where that knowledge is built.

  symbols.py to-json  gamedef/symbols/boz-1.0.11.toml  re/symbols.json
      Writes the JSON that tools/ghidra/ApplyBozSymbols.java loads into a Ghidra project.

  symbols.py from-json re/symbols-export.json gamedef/symbols/boz-1.0.11.toml
      Rewrites the database from tools/ghidra/ExportBozSymbols.java output, sorted by address so
      diffs stay small. The [game] section and per-subsystem coverage notes are kept.

  symbols.py console re/cvars.json re/commands.json gamedef/console/boz-1.0.11.toml
          [--direct re/cvars-direct.json]
      Writes the console catalog: every console variable (name, type, default) and developer
      command (name, owning class) from ExportBozCvars.java and ExportBozCommands.java output.
      --direct adds ExportBozDirectCvars.java output: cvars registered without a wrapper (type
      inferred from the default) and names the code reads but never registers (lookup_only).

  symbols.py console-doc gamedef/console/boz-1.0.11.toml tools/symbols/console_notes.toml
          docs/console-reference.md
      Writes the readable reference of every console variable and command, with the notes kept
      by hand in console_notes.toml.

  symbols.py stats gamedef/symbols/boz-1.0.11.toml
      Counts per subsystem and confidence.

  symbols.py reflection re/reflection.json gamedef/reflection/boz-1.0.11.toml
      Writes the reflection schema (every class the game registers with CIsClassInfo, its bases
      and its named fields with offsets and types) from tools/ghidra/ExportBozReflection.java
      output. These are the fields the game's data files set and the ones Lua mods read by name.

Python 3.11+ (tomllib); no other dependencies.
"""

import json
import sys
import tomllib
from collections import Counter

SUBSYSTEMS = [
    "engine", "runtime", "state", "entities", "weapons", "rendering", "ui", "audio", "saves",
    "network", "libc", "unknown",
]


def load_toml(path):
    with open(path, "rb") as f:
        db = tomllib.load(f)
    return {
        "game": db.get("game", {}),
        "coverage": db.get("coverage", {}),
        "functions": db.get("function", []),
        "globals": db.get("global", []),
        "structs": db.get("struct", []),
        # Meaning of a virtual function slot in the class that introduces it. The class map tool
        # (tools/ghidra/rtti_classes.py) names every override after it (CMysteryBox::Serialise).
        "vslots": db.get("vslot", []),
    }


def toml_string(text):
    return json.dumps(text, ensure_ascii=False)


def toml_value(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    return toml_string(str(value))


def hex_offset(value):
    return "0x%06x" % value


def write_entry(out, table, entry, key_order):
    out.append("[[%s]]" % table)
    for key in key_order:
        if key not in entry or entry[key] in ("", None):
            continue
        value = entry[key]
        if key in ("offset", "size"):
            out.append("%s = %s" % (key, hex_offset(value)))
        else:
            out.append("%s = %s" % (key, toml_value(value)))


def dump_toml(db):
    out = [
        "# BOZ Redux symbol database. Edit in Ghidra and export (see docs/modding-design.md),",
        "# or by hand. Offsets are from the image base. Confidence: confirmed | likely.",
        "",
        "[game]",
    ]
    for key, value in db["game"].items():
        if key == "image_base":
            out.append("%s = 0x%08x" % (key, value))
        else:
            out.append("%s = %s" % (key, toml_value(value)))
    out.append("")
    if db["coverage"]:
        out.append("# Mapping progress per subsystem (free text, kept by hand).")
        out.append("[coverage]")
        for key, value in db["coverage"].items():
            out.append("%s = %s" % (key, toml_value(value)))
        out.append("")
    for struct in sorted(db["structs"], key=lambda s: s["name"]):
        write_entry(out, "struct", struct, ["name", "size", "subsystem", "confidence", "notes"])
        for field in sorted(struct.get("fields", []), key=lambda f: f["offset"]):
            out.append("[[struct.field]]")
            out.append("name = %s" % toml_string(field["name"]))
            out.append("offset = %s" % hex_offset(field["offset"]))
            out.append("type = %s" % toml_string(field["type"]))
            if field.get("notes"):
                out.append("notes = %s" % toml_string(field["notes"]))
        out.append("")
    if db.get("vslots"):
        out.append("# Virtual function slots: name the slot once in the class that introduces it; every")
        out.append("# override in every derived class is named after it by tools/ghidra/rtti_classes.py.")
        out.append("# Slots 0 and 1 are always the complete and deleting destructors.")
        out.append("")
    for item in sorted(db.get("vslots", []), key=lambda v: (v["class"], v["slot"])):
        out.append("[[vslot]]")
        out.append("class = %s" % toml_string(item["class"]))
        out.append("slot = %d" % item["slot"])
        out.append("name = %s" % toml_string(item["name"]))
        for key in ("confidence", "notes"):
            if item.get(key):
                out.append("%s = %s" % (key, toml_string(item[key])))
        out.append("")
    for item in sorted(db["globals"], key=lambda g: g["offset"]):
        write_entry(out, "global", item,
                    ["name", "offset", "type", "subsystem", "confidence", "notes"])
        out.append("")
    for item in sorted(db["functions"], key=lambda f: f["offset"]):
        write_entry(out, "function", item,
                    ["name", "offset", "thumb", "signature", "subsystem", "confidence", "notes"])
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def to_json(db):
    structs = []
    for struct in db["structs"]:
        structs.append(dict(struct, fields=struct.get("field", struct.get("fields", []))))
    return {
        "game": db["game"],
        "functions": db["functions"],
        "globals": db["globals"],
        "structs": [{k: v for k, v in s.items() if k != "field"} for s in structs],
    }


def check(db):
    problems = []
    seen = {}
    for kind in ("functions", "globals"):
        for item in db[kind]:
            name = item.get("name", "")
            if name in seen:
                problems.append("duplicate name %s" % name)
            seen[name] = item
            if item.get("subsystem", "unknown") not in SUBSYSTEMS:
                problems.append("%s: unknown subsystem %r" % (name, item.get("subsystem")))
            if item.get("confidence", "likely") not in ("confirmed", "likely"):
                problems.append("%s: bad confidence %r" % (name, item.get("confidence")))
    return problems


def reflection_type(name):
    """Readable C++ type for a property-spec type as Ghidra spelled it (spaces became '_')."""
    import re
    t = name.replace("_STL::", "").replace("unsigned_int", "unsigned int").replace("unsigned_char", "unsigned char")
    t = re.sub(r"basic_string<char,char_traits<char>,allocator<char>>", "string", t)
    t = re.sub(r",allocator<[^<>]*(?:<[^<>]*>)?>", "", t)
    return t


def dump_reflection(report):
    out = [
        "# BOZ Redux reflection schema, generated by tools/symbols/symbols.py reflection",
        "# from tools/ghidra/ExportBozReflection.java. Do not edit by hand.",
        "#",
        "# Every class the game registers with its reflection system (CIsClassInfo): bases with their",
        "# offsets, and named fields. offset is from the start of the object (own fields; add the",
        "# base offset for inherited ones). network = true marks NetworkProperty fields (flags 2).",
        "",
        "[game]",
        'version = "1.0.11"',
        "",
    ]
    for c in sorted(report["classes"], key=lambda c: c["name"]):
        out.append("[[class]]")
        out.append("name = %s" % toml_string(c["name"]))
        if c["bases"]:
            out.append("bases = [%s]" % ", ".join(
                "{ name = %s, offset = %s }" % (toml_string(b["name"]), hex(b["offset"])) for b in c["bases"]))
        if c["fields"]:
            out.append("fields = [")
            for f in c["fields"]:
                item = "{ name = %s, offset = %s, size = %d, type = %s" % (
                    toml_string(f["name"]), hex(f["offset"]), f["size"], toml_string(reflection_type(f["type"])))
                if f.get("flags") == 2:
                    item += ", network = true"
                out.append("  " + item + " },")
            out.append("]")
        out.append("")
    return "\n".join(out)


def iw_hash(text):
    """IwHashString: h = 5381; h = h * 33 + c for each byte, A-Z lowercased (32-bit)."""
    h = 5381
    for c in text.encode("latin-1"):
        if 0x41 <= c <= 0x5a:
            c += 0x20
        h = (h * 33 + c) & 0xffffffff
    return h


def owner_classes(functions):
    """Class names of the named methods in a list of qualified function names."""
    out = set()
    for fn in functions:
        if "::" in fn:
            cls = fn.rsplit("::", 1)[0]
            if not cls.startswith("FUN_"):
                out.add(cls)
    return sorted(out)


def dump_events(report, users):
    names = sorted({g["string"] for g in report["hash_globals"] if g["string"].startswith("SUBJECT_")})
    by_event = {e["event"]: e for e in users["events"]}
    out = [
        "# BOZ Redux event catalog, generated by tools/symbols/symbols.py events",
        "# from tools/ghidra/BozNameHashGlobals.java. Do not edit by hand.",
        "#",
        "# The game's observer events (CIsSubject::Notify / CIsObserver::OnEvent). Each is identified",
        "# by id = IwHashString(name): h = 5381, then h = h * 33 + c per byte, A-Z lowercased.",
        "# sent_by and handled_by list the classes whose code sends the event or reacts to it",
        "# (handled_by includes subscribers); functions without a class are left out.",
        "",
        "[game]",
        'version = "1.0.11"',
        "",
    ]
    for n in names:
        out.append("[[event]]")
        out.append("name = %s" % toml_string(n))
        out.append("id = 0x%08x" % iw_hash(n))
        u = by_event.get(n, {})
        sent = owner_classes(u.get("sends", []))
        handled = owner_classes(u.get("handles", []) + u.get("subscribes", []))
        if sent:
            out.append("sent_by = [%s]" % ", ".join(toml_string(c) for c in sent))
        if handled:
            out.append("handled_by = [%s]" % ", ".join(toml_string(c) for c in handled))
        out.append("")
    return "\n".join(out)


def infer_cvar_type(default):
    text = (default or "").strip()
    if text in ("true", "false"):
        return "bool"
    if text.startswith("{"):
        return "floatarray" if "." in text else "intarray"
    if ";" in text:
        return "graph"
    try:
        int(text)
        return "int"
    except ValueError:
        pass
    try:
        float(text.rstrip("f"))
        return "float"
    except ValueError:
        return "string"


def merge_direct_cvars(cvars, direct):
    """Adds ExportBozDirectCvars entries that the wrapper-based export does not have."""
    known = {c.get("name") for c in cvars}
    merged = list(cvars)
    for d in direct:
        if d["name"] in known:
            continue
        known.add(d["name"])
        if d["kind"] == "lookup":
            merged.append({"name": d["name"], "type": "int", "registered_in": d["registered_in"],
                           "lookup_only": True})
        else:
            merged.append({"name": d["name"], "type": infer_cvar_type(d.get("default")),
                           "default": d.get("default"), "registered_in": d["registered_in"],
                           "direct": True})
    return merged


def dump_console(cvars, commands):
    out = [
        "# BOZ Redux console catalog, generated by tools/symbols/symbols.py console",
        "# from tools/ghidra/ExportBozCvars.java and ExportBozCommands.java. Do not edit by hand.",
        "#",
        "# Console variables (cvars) can be set from console files; commands are run by name with",
        "# arguments. Commands named +X / -X are key-binding pairs (pressed / released).",
        "",
        "[game]",
        'version = "1.0.11"',
        "",
    ]
    seen = set()
    for c in sorted((c for c in cvars if c.get("name")), key=lambda c: c["name"].lower()):
        if c["name"] in seen:
            continue
        seen.add(c["name"])
        out.append("[[cvar]]")
        out.append("name = %s" % toml_string(c["name"]))
        out.append("type = %s" % toml_string(c["type"].replace("cvar", "")))
        if c.get("default") is not None:
            out.append("default = %s" % toml_string(str(c["default"])))
        where = c.get("registered_in", "")
        if where and not where.startswith("FUN_"):
            out.append("used_by = %s" % toml_string(where))
        if c.get("direct"):
            out.append('registration = "direct"')
        if c.get("lookup_only"):
            out.append("lookup_only = true")
        out.append("")
    seen = set()
    for c in sorted(commands, key=lambda c: (c.get("class", ""), c["name"].lower())):
        key = (c.get("class", ""), c["name"])
        if key in seen:
            continue
        seen.add(key)
        out.append("[[command]]")
        out.append("name = %s" % toml_string(c["name"]))
        if c.get("class"):
            out.append("class = %s" % toml_string(c["class"]))
        out.append("id = %d" % c["id"])
        out.append("")
    return "\n".join(out)


CVAR_CATEGORIES = [
    ("Dead Ops Arcade", lambda n, o: o.startswith("CDO") or n[:2] in ("do", "DO")),
    ("Online services and network", lambda n, o: any(k in n for k in ("Network", "Multiplayer", "Lobby", "Room", "Demonware", "Coop", "Endpoint", "Central")) or o.startswith(("CIwNetwork", "CFrontendStateConnect", "CGameNetwork"))),
    ("Zombies and AI", lambda n, o: o.startswith(("CAI", "CDOAI")) or n.startswith(("AI", "Zombie", "zombie", "Romero", "Hellhound", "Monkey", "Ambient")) or "Zombie" in n),
    ("Weapons and the mystery box", lambda n, o: o.startswith(("CMysteryBox", "CPlayerWeapon", "CDeathMachine", "CProjectile", "CImpact")) or any(k in n for k in ("Weapon", "Gun", "Ammo", "Grenade", "Reload", "Recoil", "Spread", "Clip", "Box", "Pap", "PackAPunch", "Gersch"))),
    ("Camera, aiming and controls", lambda n, o: o.startswith(("CTouch", "CInput", "CAccelerometer", "CPlayerFreeFly")) or any(k in n for k in ("Turn", "Pitch", "Aim", "Sensitivity", "Fov", "Touch", "Accel", "accel", "Stick", "Camera", "Cam", "Input", "Look", "Sway", "FreeFly"))),
    ("Player", lambda n, o: o.startswith(("CPlayer", "CHealth", "CIngameStateQuickRevive")) or any(k in n for k in ("Walk", "Sprint", "Crouch", "Prone", "Stamina", "Health", "LastStand", "Unlimited", "Revive", "Player", "Perk"))),
    ("Rounds, spawning, score and pickups", lambda n, o: o.startswith(("CScore", "CPickup", "CPerk", "CTeleport", "CSpawn", "CWave", "CLighthouse")) or any(k in n for k in ("Wave", "Round", "Spawn", "Score", "Pickup", "Power", "Teleport", "Carpenter", "Centrifuge"))),
    ("Audio", lambda n, o: o.startswith(("CIwSound", "CMusic", "CAmbience")) or any(k in n for k in ("Sound", "sound", "Music", "music", "Audio", "Volume", "Polyphony"))),
    ("Graphics and effects", lambda n, o: o.startswith(("CIwFog", "CIsLOD", "CFullscreenFX", "CBodyGib", "CIsFrameBone", "CVFX")) or any(k in n for k in ("Fog", "LOD", "Render", "Shadow", "Light", "Shader", "Decal", "Gore", "Gib", "FX", "Weather", "Draw", "Texture", "Frustrum", "Bone", "Renderable", "Snow", "Rain", "Water"))),
    ("Menus, HUD and store", lambda n, o: o.startswith(("CFrontend", "CIngameState", "CGameStore", "CLoading", "CUI", "CHUD", "CTutorial", "CDOInitial")) or any(k in n for k in ("HUD", "Hud", "UI", "Menu", "Font", "Store", "Achievement", "RateMe", "Message", "Loading", "Video", "Tutorial", "Tcolor", "Colour", "Color"))),
    ("Saves", lambda n, o: "Save" in n),
]

COMMAND_CONTEXT = {
    "CGame": "always", "CIwGame": "always", "CIsBulletWorld": "always",
    "CGameNetwork": "always (network and DemonWare tests)", "IwDemonware": "online services (DemonWare; to be removed)",
    "CGameStore": "always (in-app store)", "CGameStateFrontEnd": "main menu",
    "CGameStateIngame": "Zombies match", "CIngameStatePlaying": "Zombies match, playing",
    "CIngameStatePaused": "Zombies pause menu", "CIngameStateOptions": "Zombies options menu",
    "CIngameStateSensitivity": "Zombies sensitivity menu", "CLevelManager": "Zombies match",
    "CWaveManager": "Zombies match (rounds)", "CPlayerController": "Zombies match (player)",
    "CPlayerWeapon": "Zombies match (player weapon)", "CPerkManager": "Zombies match (perks)",
    "CSpawnManager": "Zombies match (spawning)", "CTeleportManager": "Kino der Toten match (teleporters)",
    "CLighthouse": "Shi No Numa / map with a lighthouse", "CRocketLauncher": "Ascension match (rocket)",
    "CTutorialManager": "tutorial", "CVFXManager": "Zombies match (effects)", "CWorld": "match (world)",
    "CIwFreeCameraController": "free camera active", "CIwCircleCameraController": "circle camera active",
}


COMMAND_ORDER = [
    "CGameStateIngame", "CIngameStatePlaying", "CLevelManager", "CWaveManager", "CSpawnManager",
    "CPlayerController", "CPlayerWeapon", "CPerkManager", "CVFXManager", "CWorld", "CTeleportManager",
    "CLighthouse", "CRocketLauncher", "CTutorialManager", "CIngameStatePaused", "CIngameStateOptions",
    "CIngameStateSensitivity", "CGameStateFrontEnd", "CGame", "CIwGame", "CIsBulletWorld",
    "CIwFreeCameraController", "CIwCircleCameraController", "CGameStore", "CGameNetwork", "IwDemonware",
]

# Registered by CIwConsole itself (CIwConsole::CIwConsole, handled in CIwConsole::OnCommand).
BUILTIN_COMMANDS = [
    ("cvar", "<name> <value>", "No handler in the release build: does nothing. The Developer mod's own `cvar <name> <value> [type]` registers the variable through Cvar_Register*, which makes lookup-only variables (StartingScore) work."),
    ("bind", "<key> <command>", "No handler in the release build: does nothing. The Developer mod's own `bind <key> <line>` works (this session only)."),
    ("unbindAll", "", "Removes all key bindings."),
    ("alias", "<name> <command>", "Makes a name run a command line."),
    ("help", "", "No handler in the release build. The Developer mod answers `help` itself."),
    ("listCommands", "[filter]", "Prints registered commands whose names start with filter."),
    ("listVars", "[filter]", "Prints registered variables whose names start with filter."),
    ("listAliases", "[filter]", "Prints aliases."),
    ("listBindingSets", "[filter]", "Prints binding sets (GameStateIngame, BOPlayerControlsWin, XperiaPlayBO, ...)."),
    ("bindingSetActivate", "<set>", "Activates a binding set."),
    ("bindingSetDeactivate", "<set>", "Deactivates a binding set."),
    ("saveConsole", "", "Saves console variables (CIwConsole::SaveVars)."),
]


def command_sort_key(cls):
    if cls in COMMAND_ORDER:
        return (0, COMMAND_ORDER.index(cls), cls)
    if cls.startswith("CDO"):
        return (1, 0, cls)
    return (2, 0, cls)


def command_context(cls):
    if cls in COMMAND_CONTEXT:
        return COMMAND_CONTEXT[cls]
    if cls.startswith("CDO"):
        return "Dead Ops Arcade"
    return "while %s exists" % cls if cls else "unknown owner"


def md_cell(text):
    return str(text).replace("|", "\\|").replace("\n", " ")


def dump_console_doc(db, notes):
    cvars, commands = db.get("cvar", []), db.get("command", [])
    cvar_notes, command_notes = notes.get("cvar", {}), notes.get("command", {})
    out = [
        "# Console reference",
        "",
        "Every console variable (cvar) and developer command in *Call of Duty: Black Ops Zombies*",
        "1.0.11, generated from the game definition (`gamedef/console/boz-1.0.11.toml`) and the",
        "notes in `tools/symbols/console_notes.toml`. Regenerate with",
        "`python3 tools/symbols/symbols.py console-doc gamedef/console/boz-1.0.11.toml "
        "tools/symbols/console_notes.toml docs/console-reference.md`; do not edit by hand.",
        "",
        "## How to use them",
        "",
        "Open the Developer mod's console (`` ` `` or F1) and type:",
        "",
        "- `Name` prints a variable's value; `Name value` sets it (booleans: `true` / `false`;",
        "  arrays: `{1,2,3}`; graphs are `x,y;x,y;` points).",
        "- `Command arguments` runs a command. `+Name` / `-Name` commands are key press and",
        "  release pairs, meant for key bindings.",
        "- `find text` searches this list; `listVars` and `listCommands` ask the game what is",
        "  registered right now.",
        "",
        "Not everything exists all the time. Variables are registered when the code that uses them",
        "first runs, so many appear only once a match has started. Commands belong to a game",
        "system and only answer while it exists (the **Available** column).",
        "",
        "Columns: **Type** is the console type; **Default** is the value the game registers;",
        "**Used by** is the function that registers or reads it, where known. **Status** records",
        "in-game testing (works, partial, no effect, crashes); blank means untested.",
        "",
        "Known gaps: 19 registrations could not be named by static analysis, so they are missing",
        "here. Variables marked *lookup only* are read by the game but never registered: setting",
        "them fails until something registers them.",
        "",
        "Counts: %d variables, %d commands." % (len(cvars), len(commands)),
        "",
        "## Commands",
        "",
    ]
    out.append("### Built into the console")
    out.append("")
    out.append("Available: always.")
    out.append("")
    out.append("| Command | Arguments | Notes | Status |")
    out.append("| --- | --- | --- | --- |")
    for name, args, note in BUILTIN_COMMANDS:
        status = command_notes.get(name, {}).get("status", "")
        out.append("| `%s` | %s | %s | %s |" % (name, "`%s`" % args if args else "", md_cell(note), md_cell(status)))
    out.append("")
    by_class = {}
    for c in commands:
        by_class.setdefault(c.get("class", ""), []).append(c)
    for cls in sorted(by_class, key=command_sort_key):
        out.append("### %s" % (cls or "Unknown owner"))
        out.append("")
        out.append("Available: %s." % command_context(cls))
        out.append("")
        out.append("| Command | Arguments | Notes | Status |")
        out.append("| --- | --- | --- | --- |")
        for c in sorted(by_class[cls], key=lambda c: c["name"].lower()):
            n = command_notes.get(c["name"], {})
            args = n.get("args", "")
            out.append("| `%s` | %s | %s | %s |" % (c["name"], "`%s`" % args if args else "",
                                                   md_cell(n.get("note", "")), md_cell(n.get("status", ""))))
        out.append("")
    out.append("## Variables")
    out.append("")
    groups = {}
    for c in cvars:
        owner = c.get("used_by", "").split("::")[0]
        category = next((title for title, test in CVAR_CATEGORIES if test(c["name"], owner)), "Other")
        groups.setdefault(category, []).append(c)
    order = [title for title, _ in CVAR_CATEGORIES] + ["Other"]
    for title in order:
        if title not in groups:
            continue
        out.append("### %s" % title)
        out.append("")
        out.append("| Variable | Type | Default | Used by | Notes | Status |")
        out.append("| --- | --- | --- | --- | --- | --- |")
        for c in sorted(groups[title], key=lambda c: c["name"].lower()):
            n = cvar_notes.get(c["name"], {})
            default = "*lookup only*" if c.get("lookup_only") else "`%s`" % md_cell(c.get("default", "")) if c.get("default") not in (None, "") else ""
            out.append("| `%s` | %s | %s | %s | %s | %s |" % (
                c["name"], c.get("type", ""), default, md_cell(c.get("used_by", "")),
                md_cell(n.get("note", "")), md_cell(n.get("status", ""))))
        out.append("")
    return "\n".join(out)


def main(argv):
    if len(argv) < 3:
        print(__doc__, file=sys.stderr)
        return 2
    command = argv[1]
    if command == "to-json" and len(argv) == 4:
        db = load_toml(argv[2])
        problems = check(db)
        for problem in problems:
            print("warning:", problem, file=sys.stderr)
        with open(argv[3], "w") as f:
            json.dump(to_json(db), f, indent=1)
        print("%s: %d functions, %d globals, %d structs" %
              (argv[3], len(db["functions"]), len(db["globals"]), len(db["structs"])))
        return 0
    if command == "from-json" and len(argv) == 4:
        with open(argv[2]) as f:
            exported = json.load(f)
        try:
            existing = load_toml(argv[3])
        except FileNotFoundError:
            existing = {"game": {}, "coverage": {}, "vslots": []}
        db = {
            "game": existing["game"] or exported.get("game", {}),
            "coverage": existing["coverage"],
            "vslots": existing.get("vslots", []),  # kept by hand, not in Ghidra
            "functions": exported.get("functions", []),
            "globals": exported.get("globals", []),
            "structs": exported.get("structs", []),
        }
        for problem in check(db):
            print("warning:", problem, file=sys.stderr)
        with open(argv[3], "w") as f:
            f.write(dump_toml(db))
        print("%s: %d functions, %d globals, %d structs" %
              (argv[3], len(db["functions"]), len(db["globals"]), len(db["structs"])))
        return 0
    if command == "reflection" and len(argv) == 4:
        with open(argv[2]) as f:
            report = json.load(f)
        import os
        os.makedirs(os.path.dirname(argv[3]) or ".", exist_ok=True)
        with open(argv[3], "w") as f:
            f.write(dump_reflection(report))
        with open(argv[3], "rb") as f:
            check_db = tomllib.load(f)
        print("%s: %d classes, %d fields" % (argv[3], len(check_db["class"]),
                                             sum(len(c.get("fields", [])) for c in check_db["class"])))
        return 0
    if command == "events" and len(argv) == 5:
        with open(argv[2]) as f:
            report = json.load(f)
        with open(argv[3]) as f:
            users = json.load(f)
        import os
        os.makedirs(os.path.dirname(argv[4]) or ".", exist_ok=True)
        with open(argv[4], "w") as f:
            f.write(dump_events(report, users))
        with open(argv[4], "rb") as f:
            n = len(tomllib.load(f)["event"])
        print("%s: %d events" % (argv[4], n))
        return 0
    if command == "console" and len(argv) in (5, 7):
        with open(argv[2]) as f:
            cv = json.load(f)
        with open(argv[3]) as f:
            cm = json.load(f)
        cvars = cv["cvars"] if isinstance(cv, dict) else cv
        if len(argv) == 7 and argv[5] == "--direct":
            with open(argv[6]) as f:
                cvars = merge_direct_cvars(cvars, json.load(f))
        import os
        os.makedirs(os.path.dirname(argv[4]) or ".", exist_ok=True)
        with open(argv[4], "w") as f:
            f.write(dump_console(cvars, cm["commands"]))
        with open(argv[4], "rb") as f:
            db = tomllib.load(f)
        print("%s: %d cvars, %d commands" % (argv[4], len(db["cvar"]), len(db["command"])))
        return 0
    if command == "console-doc" and len(argv) == 5:
        with open(argv[2], "rb") as f:
            db = tomllib.load(f)
        with open(argv[3], "rb") as f:
            notes = tomllib.load(f)
        with open(argv[4], "w") as f:
            f.write(dump_console_doc(db, notes))
        print("%s: %d variables, %d commands" % (argv[4], len(db.get("cvar", [])), len(db.get("command", []))))
        return 0
    if command == "stats" and len(argv) == 3:
        db = load_toml(argv[2])
        counts = Counter()
        for kind in ("functions", "globals"):
            for item in db[kind]:
                counts[(item.get("subsystem", "unknown"), item.get("confidence", "likely"))] += 1
        print("%-10s %9s %7s" % ("subsystem", "confirmed", "likely"))
        for subsystem in SUBSYSTEMS:
            confirmed = counts[(subsystem, "confirmed")]
            likely = counts[(subsystem, "likely")]
            if confirmed or likely:
                print("%-10s %9d %7d" % (subsystem, confirmed, likely))
        print("structs: %d" % len(db["structs"]))
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
