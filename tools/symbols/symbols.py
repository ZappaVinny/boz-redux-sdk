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
      Writes the console catalog: every console variable (name, type, default) and developer
      command (name, owning class) from ExportBozCvars.java and ExportBozCommands.java output.

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
    if command == "console" and len(argv) == 5:
        with open(argv[2]) as f:
            cv = json.load(f)
        with open(argv[3]) as f:
            cm = json.load(f)
        import os
        os.makedirs(os.path.dirname(argv[4]) or ".", exist_ok=True)
        with open(argv[4], "w") as f:
            f.write(dump_console(cv["cvars"] if isinstance(cv, dict) else cv, cm["commands"]))
        with open(argv[4], "rb") as f:
            db = tomllib.load(f)
        print("%s: %d cvars, %d commands" % (argv[4], len(db["cvar"]), len(db["command"])))
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
