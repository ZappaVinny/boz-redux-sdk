#!/usr/bin/env python3
"""Recover the game's C++ class hierarchy from its run-time type information.

BOZ is built with GCC (Itanium C++ ABI) and keeps RTTI, so every polymorphic class has:
  - a type name string (mangled, e.g. "9CDOPlayer");
  - a typeinfo object: [vptr, name*] plus, for single inheritance, [base typeinfo*], or for
    multiple/virtual inheritance, [flags, base count, (base typeinfo*, offset flags)...];
  - one or more vtables: [offset to top, typeinfo*, virtual function pointers...].

All pointers in the image are listed in its internal relocations, which makes these structures
easy to find without guessing. Output: JSON with each class's mangled name, typeinfo address,
bases, and vtables (address, offset to top, function addresses with Thumb bit).

The output describes the game's code: keep it in re/ (gitignored).

Virtual slots named in the symbol database ([[vslot]]) name every override after them.

Usage: rtti_classes.py assets/boz.s3e.unpacked re/classes.json [--symbols gamedef/symbols/boz-1.0.11.toml]
"""

import json
import os
import re
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from s3e_to_elf import S3EImage  # noqa: E402

NAME = re.compile(rb"N?[1-9][0-9]*[A-Za-z_][A-Za-z0-9_]*")


BUILTIN_TYPES = {
    "v": "void", "b": "bool", "c": "char", "a": "signed char", "h": "unsigned char", "s": "short",
    "t": "unsigned short", "i": "int", "j": "unsigned int", "l": "long", "m": "unsigned long",
    "x": "long long", "y": "unsigned long long", "f": "float", "d": "double", "w": "wchar_t",
}


class Demangler:
    """Just enough of the Itanium ABI for RTTI type names: nested names, templates, builtins,
    pointers/references/const and literal template arguments."""

    def __init__(self, text):
        self.text = text
        self.pos = 0
        self.subs = []

    def peek(self):
        return self.text[self.pos] if self.pos < len(self.text) else ""

    def source_name(self):
        start = self.pos
        while self.peek().isdigit():
            self.pos += 1
        length = int(self.text[start:self.pos])
        name = self.text[self.pos:self.pos + length]
        self.pos += length
        return name

    def template_args(self):
        self.pos += 1  # I
        args = []
        while self.peek() != "E":
            if self.peek() == "L":  # literal: L<type><value>E
                self.pos += 1
                kind = self.type_name()
                end = self.text.index("E", self.pos)
                value = self.text[self.pos:end].replace("n", "-")
                self.pos = end + 1
                args.append(value if kind not in ("bool",) else ("true" if value == "1" else "false"))
            else:
                args.append(self.type_name())
        self.pos += 1
        return "<" + ", ".join(args) + ">"

    def substitution(self):
        self.pos += 1  # S
        if self.peek() == "t":
            self.pos += 1
            return "std::" + self.unqualified()
        if self.peek() in "absiod":
            name = {"a": "std::allocator", "b": "std::basic_string", "s": "std::string",
                    "i": "std::istream", "o": "std::ostream", "d": "std::iostream"}.get(self.peek(), "std")
            self.pos += 1
            return name
        start = self.pos
        while self.peek() != "_":
            self.pos += 1
        seq = self.text[start:self.pos]
        self.pos += 1
        index = 0 if seq == "" else int(seq, 36) + 1
        return self.subs[index]

    def unqualified(self):
        name = self.source_name()
        if self.peek() == "I":
            self.subs.append(name)  # the template name is a candidate before its arguments
            name += self.template_args()
        return name

    def nested(self):
        self.pos += 1  # N
        parts = []
        while self.peek() in "KVr":
            self.pos += 1
        while self.peek() != "E":
            if self.peek() == "S":
                parts.append(self.substitution())  # not a new candidate itself
                continue
            if self.peek() == "I":
                parts[-1] += self.template_args()
            else:
                parts.append(self.source_name())
            if self.peek() != "E":
                self.subs.append("::".join(parts))  # every proper prefix is a candidate
        self.pos += 1
        return "::".join(parts)

    def type_name(self):
        c = self.peek()
        if c in BUILTIN_TYPES:
            self.pos += 1
            return BUILTIN_TYPES[c]
        if c == "P":
            self.pos += 1
            return self.type_name() + " *"
        if c == "R":
            self.pos += 1
            return self.type_name() + " &"
        if c == "K":
            self.pos += 1
            return "const " + self.type_name()
        if c == "N":
            name = self.nested()
        elif c == "S":
            name = self.substitution()
            if self.peek() == "I":
                name += self.template_args()
        elif c.isdigit():
            name = self.unqualified()
        else:
            raise ValueError("unsupported mangling at %r" % self.text[self.pos:])
        self.subs.append(name)
        return name


def demangle(mangled):
    try:
        demangler = Demangler(mangled)
        name = demangler.type_name()
        return name if demangler.pos == len(mangled) else mangled
    except (ValueError, IndexError):
        return mangled


def slot_chain(name, offset, by_name, by_typeinfo):
    """Classes sharing the vtable at `offset` inside `name`, most derived first: the class itself
    and its primary bases (offset 0), or for a secondary vtable the base found at that offset."""
    c = by_name.get(name)
    if c is None:
        return []
    bases = sorted(((b["offset"], by_typeinfo[b["typeinfo"]]["name"]) for b in c["bases"]
                    if b["typeinfo"] in by_typeinfo and not b.get("virtual")), key=lambda b: b[0])
    if offset == 0:
        primary = [b for b in bases if b[0] == 0]
        return [name] + (slot_chain(primary[0][1], 0, by_name, by_typeinfo) if primary else [])
    below = [b for b in bases if 0 < b[0] <= offset]
    if not below:
        return []
    base_offset, base_name = below[-1]
    return slot_chain(base_name, offset - base_offset, by_name, by_typeinfo)


def assign_owners(classes, slot_names=None):
    """Each virtual function belongs to the most basic class whose vtable has it: inherited,
    non-overridden functions appear in every derived class's vtable too."""
    by_typeinfo = {c["typeinfo"]: c for c in classes}
    depth_cache = {}

    def depth(c):
        if c["typeinfo"] not in depth_cache:
            depth_cache[c["typeinfo"]] = 0
            depth_cache[c["typeinfo"]] = 1 + max(
                [depth(by_typeinfo[b["typeinfo"]]) for b in c["bases"]] or [-1])
        return depth_cache[c["typeinfo"]]

    slot_names = slot_names or {}
    by_name = {c["name"]: c for c in classes}
    users = {}
    for c in classes:
        for v in c["vtables"]:
            for slot, target in enumerate(v["functions"]):
                users.setdefault(target, []).append((depth(c), c["name"], v["offset_to_top"], slot))
    functions = []
    for target, uses in sorted(users.items()):
        uses.sort()
        _, owner, offset_to_top, slot = uses[0]
        # Primary vtable slots are "vf<slot>"; slots of a secondary vtable (a base at a non-zero
        # offset) are "vf<slot>_off<offset>", since each secondary vtable restarts at slot 0.
        named = None
        for cls in slot_chain(owner, -offset_to_top, by_name, by_typeinfo):
            named = slot_names.get((cls, slot)) or named
        base_name = named or "vf%d" % slot
        name = base_name if offset_to_top == 0 else "%s_off%x" % (base_name, -offset_to_top)
        functions.append({"address": target & ~1, "thumb": bool(target & 1), "owner": owner,
                          "name": name, "offset": -offset_to_top, "slot": slot,
                          "classes": len({u[1] for u in uses})})
    return functions


def library_of(name):
    """Which code a class comes from, by naming convention."""
    if name.startswith(("bt", "bParse::", "bDNA")):
        return "bullet"
    if name.startswith("gameswf::") or name.startswith("tu_"):
        return "gameswf"
    if name.startswith("bd") and name[2:3].isupper():
        return "demonware"
    if name.startswith(("CIw", "IIw", "CIwGame")):
        return "marmalade"
    if name.startswith(("CIs", "IIs")):
        return "studio"
    if name.startswith("std::") or name.startswith("__cxxabi") or name.startswith("__gnu"):
        return "libstdc++"
    return "game"


def main():
    if len(sys.argv) not in (3, 5):
        print(__doc__.strip().splitlines()[-1], file=sys.stderr)
        return 2
    with open(sys.argv[1], "rb") as f:
        image = S3EImage(f.read())
    code = bytes(image.code)
    base = image.base
    text_end = image.data_offset
    size = image.code_mem_size

    pointers = {}  # image offset of slot -> image offset of target (with Thumb bit kept)
    for offset in image.internal_offsets:
        value = struct.unpack_from("<I", code, offset)[0] - base
        if 0 <= value < size + 1:
            pointers[offset] = value
    slots_to = {}
    for slot, target in pointers.items():
        slots_to.setdefault(target, []).append(slot)

    def word(offset):
        return struct.unpack_from("<I", code, offset)[0]

    def c_string(offset):
        end = code.index(b"\0", offset)
        return code[offset:end]

    # typeinfo objects: T with a pointer at T+4 to a plausible mangled type name, and a pointer
    # at T (the vptr into one of the libsupc++ type_info vtables).
    typeinfos = {}
    for slot, target in pointers.items():
        if slot < 4 or (slot - 4) not in pointers:
            continue
        if not 0 <= target < size:  # names can start at odd addresses
            continue
        try:
            name = c_string(target)
        except ValueError:
            continue
        if not NAME.fullmatch(name) or len(name) > 400:
            continue
        typeinfos[slot - 4] = {"name": name.decode(), "vptr": pointers[slot - 4]}

    # The libsupc++ type_info vtables: count how often each vptr is used and classify by shape.
    vptr_kinds = {}
    for t, info in typeinfos.items():
        vptr_kinds.setdefault(info["vptr"], []).append(t)

    def bases_of(t):
        nxt = t + 8
        if nxt in pointers and pointers[nxt] in typeinfos:
            return "si", [{"typeinfo": pointers[nxt], "offset": 0, "public": True}]
        # __vmi_class_type_info: flags, base count, then (typeinfo*, offset_flags) pairs.
        count = word(t + 12) if t + 16 <= size else 0
        if 0 < count < 32 and all((t + 16 + 8 * i) in pointers and
                                  pointers[t + 16 + 8 * i] in typeinfos for i in range(count)):
            out = []
            for i in range(count):
                flags = word(t + 20 + 8 * i)
                out.append({"typeinfo": pointers[t + 16 + 8 * i], "offset": flags >> 8,
                            "public": bool(flags & 2), "virtual": bool(flags & 1)})
            return "vmi", out
        return "class", []

    for t, info in typeinfos.items():
        kind, bases = bases_of(t)
        info["kind"] = kind
        info["bases"] = bases

    # vtables: a slot V+4 pointing at a typeinfo, with offset-to-top at V (not a pointer, small),
    # followed by code pointers.
    vtables = []
    for t in typeinfos:
        for slot in slots_to.get(t, []):
            v = slot - 4
            if v in pointers or v < 0:
                continue
            offset_to_top = struct.unpack_from("<i", code, v)[0]
            if not -0x10000 < offset_to_top <= 0:
                continue
            functions = []
            cursor = v + 8
            while cursor in pointers and pointers[cursor] < text_end:
                functions.append(pointers[cursor])
                cursor += 4
            # A vtable with no functions is only possible for odd classes; skip typeinfo
            # references from elsewhere (e.g. exception tables) that look similar.
            if functions:
                vtables.append({"typeinfo": t, "address": v, "offset_to_top": offset_to_top,
                                "functions": functions})

    classes = []
    by_typeinfo = {}
    for t, info in sorted(typeinfos.items()):
        entry = {
            "name": demangle(info["name"]),
            "mangled": info["name"],
            "library": library_of(demangle(info["name"])),
            "typeinfo": t,
            "kind": info["kind"],
            "bases": info["bases"],
            "vtables": [],
        }
        by_typeinfo[t] = entry
        classes.append(entry)
    for vtable in vtables:
        by_typeinfo[vtable["typeinfo"]]["vtables"].append(
            {k: vtable[k] for k in ("address", "offset_to_top", "functions")})
    for entry in classes:
        entry["vtables"].sort(key=lambda v: -v["offset_to_top"])

    slot_names = {}
    if len(sys.argv) == 5 and sys.argv[3] == "--symbols":
        import tomllib
        with open(sys.argv[4], "rb") as f:
            for vslot in tomllib.load(f).get("vslot", []):
                slot_names[(vslot["class"], vslot["slot"])] = vslot["name"]
    virtual_functions = assign_owners(classes, slot_names)
    out = {
        "image_base": base,
        "virtual_functions": virtual_functions,
        "type_info_vtables": {str(k): len(v) for k, v in sorted(vptr_kinds.items(),
                                                                 key=lambda kv: -len(kv[1]))},
        "classes": classes,
    }
    with open(sys.argv[2], "w") as f:
        json.dump(out, f, indent=1)
    with_vtables = sum(1 for c in classes if c["vtables"])
    functions = {f for c in classes for v in c["vtables"] for f in v["functions"]}
    print("%s: %d classes (%d with vtables, %d single and %d multiple inheritance), %d vtables, "
          "%d distinct virtual functions" % (
              sys.argv[2], len(classes), with_vtables,
              sum(1 for c in classes if c["kind"] == "si"),
              sum(1 for c in classes if c["kind"] == "vmi"), len(vtables), len(functions)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
