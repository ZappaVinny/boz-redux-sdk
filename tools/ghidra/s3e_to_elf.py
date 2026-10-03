#!/usr/bin/env python3
"""Convert a Marmalade S3E image (boz.s3e.unpacked) into an ARM ELF for Ghidra and other tools.

The ELF has the game's code and data at the address the BOZ Redux client loads them
(0x4a000000), so addresses in the client's logs and traces match the disassembly. Each of the
image's imports (s3eFileOpen, glDrawArrays, ...) becomes a named stub function in a separate
".imports" segment, and the image's import slots point at those stubs, so decompiled calls read
s3eFileOpen(...) instead of an indirect call through a table.

The output contains game code: keep it next to your own game files and never commit it.

It also writes <output>.code-pointers.txt: every Thumb function the image stores a pointer to
(callbacks and C++ virtual methods), which Ghidra's analysis cannot find on its own. Run
tools/ghidra/BozSeedFunctions.java on the imported program to create them.

Usage: s3e_to_elf.py assets/boz.s3e.unpacked re/boz.elf
"""

import struct
import sys

S3E_MAGIC = 0x55334558
FIXUP_SYMBOLS = 0
FIXUP_INTERNAL = 1
FIXUP_EXTERNAL = (2, 3, 4)
STUB_ARM_BX_LR = 0xE12FFF1E
PAGE = 0x1000


def align(value, alignment):
    return (value + alignment - 1) // alignment * alignment


class S3EImage:
    def __init__(self, data):
        if len(data) < 76:
            raise ValueError("file is too small for an S3E header")
        fields = struct.unpack_from("<IIHHIIIIIIIIIIIIII", data, 0)
        (self.ident, self.version, self.flags, self.arch, self.fixup_offset, self.fixup_size,
         self.code_offset, self.code_file_size, self.code_mem_size, _sig_offset, _sig_size,
         self.entry_offset, _config_offset, _config_size, self.base, _extra_offset, _extra_size,
         ext_header_size) = fields
        if self.ident != S3E_MAGIC:
            raise ValueError("not an uncompressed S3E image (run the APK extractor first)")
        self.data_offset = struct.unpack_from("<I", data, 68)[0] if ext_header_size == 0x0C else 0
        self.code = bytearray(data[self.code_offset:self.code_offset + self.code_file_size])
        self.code += bytes(self.code_mem_size - self.code_file_size)
        self.symbols = []
        self.import_slots = []  # (image offset, symbol index)
        self.internal_offsets = []  # image offsets holding absolute pointers into the image
        self._parse_fixups(data)

    def _parse_fixups(self, data):
        pos = self.fixup_offset
        end = self.fixup_offset + self.fixup_size
        while pos < end:
            kind, size = struct.unpack_from("<II", data, pos)
            body = pos + 8
            if kind == FIXUP_SYMBOLS:
                count = struct.unpack_from("<H", data, body)[0]
                cursor = body + 2
                for _ in range(count):
                    terminator = data.index(b"\0", cursor)
                    self.symbols.append(data[cursor:terminator].decode("ascii"))
                    cursor = terminator + 1
            elif kind == FIXUP_INTERNAL:
                count = struct.unpack_from("<I", data, body)[0]
                self.internal_offsets = list(struct.unpack_from("<%dI" % count, data, body + 4))
            elif kind in FIXUP_EXTERNAL:
                count = struct.unpack_from("<I", data, body)[0]
                cursor = body + 4
                for _ in range(count):
                    hi, lo, index = struct.unpack_from("<HHH", data, cursor)
                    self.import_slots.append(((hi << 16) | lo, index))
                    cursor += 6
            pos += size


class StringTable:
    def __init__(self):
        self.data = bytearray(b"\0")
        self.offsets = {}

    def add(self, text):
        if text not in self.offsets:
            self.offsets[text] = len(self.data)
            self.data += text.encode("ascii") + b"\0"
        return self.offsets[text]


def build_elf(image):
    base = image.base
    text_size = image.data_offset or image.code_mem_size
    stub_base = align(base + image.code_mem_size, 0x100000)
    stubs = bytearray()
    stub_address = {}
    for index, name in enumerate(image.symbols):
        stub_address[index] = stub_base + len(stubs)
        stubs += struct.pack("<I", STUB_ARM_BX_LR)

    code = bytearray(image.code)
    for offset, index in image.import_slots:
        struct.pack_into("<I", code, offset, stub_address[index])

    # Sections: null, .text, .data (incl. bss contents as zeros), .imports, .symtab, .strtab,
    # .shstrtab. Everything the game loads is PROGBITS so Ghidra keeps one contiguous image.
    shstr = StringTable()
    strtab = StringTable()
    symbols = [struct.pack("<IIIBBH", 0, 0, 0, 0, 0, 0)]

    def symbol(name, value, size, kind, section):
        info = (1 << 4) | kind  # STB_GLOBAL
        symbols.append(struct.pack("<IIIBBH", strtab.add(name), value, size, info, 0, section))

    STT_OBJECT, STT_FUNC = 1, 2
    for index, name in enumerate(image.symbols):
        symbol(name, stub_address[index], 4, STT_FUNC, 3)
    for offset, index in sorted(set(image.import_slots)):
        symbol("PTR_" + image.symbols[index] + "_%06x" % offset, base + offset, 4, STT_OBJECT,
               1 if offset < text_size else 2)
    symbol("s3e_entry", base + image.entry_offset, 0, STT_FUNC, 1)

    header_size = 52
    ph_count = 3
    ph_size = 32
    text_file = align(header_size + ph_count * ph_size, PAGE)
    data_file = text_file + text_size
    stub_file = align(data_file + (image.code_mem_size - text_size), PAGE)
    symtab_file = stub_file + len(stubs)
    symtab_data = b"".join(symbols)
    strtab_file = symtab_file + len(symtab_data)
    shstr_names = [shstr.add(n) for n in
                   (".text", ".data", ".imports", ".symtab", ".strtab", ".shstrtab")]
    shstr_file = strtab_file + len(strtab.data)
    sh_file = align(shstr_file + len(shstr.data), 4)

    out = bytearray(sh_file + 7 * 40)
    ident = b"\x7fELF" + bytes([1, 1, 1, 0]) + bytes(8)
    struct.pack_into("<16sHHIIIIIHHHHHH", out, 0, ident, 2, 40, 1, base + image.entry_offset,
                     header_size, sh_file, 0x05000200, header_size, ph_size, ph_count, 40, 7, 6)

    PF_X, PF_W, PF_R = 1, 2, 4
    segments = [
        (text_file, base, text_size, text_size, PF_R | PF_X),
        (data_file, base + text_size, image.code_mem_size - text_size,
         image.code_mem_size - text_size, PF_R | PF_W),
        (stub_file, stub_base, len(stubs), len(stubs), PF_R | PF_X),
    ]
    for i, (offset, vaddr, filesz, memsz, flags) in enumerate(segments):
        struct.pack_into("<IIIIIIII", out, header_size + i * ph_size, 1, offset, vaddr, vaddr,
                         filesz, memsz, flags, PAGE)

    out[text_file:text_file + text_size] = code[:text_size]
    out[data_file:data_file + image.code_mem_size - text_size] = code[text_size:]
    out[stub_file:stub_file + len(stubs)] = stubs
    out[symtab_file:symtab_file + len(symtab_data)] = symtab_data
    out[strtab_file:strtab_file + len(strtab.data)] = strtab.data
    out[shstr_file:shstr_file + len(shstr.data)] = shstr.data

    SHT_PROGBITS, SHT_SYMTAB, SHT_STRTAB = 1, 2, 3
    SHF_WRITE, SHF_ALLOC, SHF_EXEC = 1, 2, 4
    sections = [
        (0, 0, 0, 0, 0, 0, 0, 0, 0, 0),
        (shstr_names[0], SHT_PROGBITS, SHF_ALLOC | SHF_EXEC, base, text_file, text_size, 0, 0, 4, 0),
        (shstr_names[1], SHT_PROGBITS, SHF_ALLOC | SHF_WRITE, base + text_size, data_file,
         image.code_mem_size - text_size, 0, 0, 4, 0),
        (shstr_names[2], SHT_PROGBITS, SHF_ALLOC | SHF_EXEC, stub_base, stub_file, len(stubs),
         0, 0, 4, 0),
        (shstr_names[3], SHT_SYMTAB, 0, 0, symtab_file, len(symtab_data), 5, 1, 4, 16),
        (shstr_names[4], SHT_STRTAB, 0, 0, strtab_file, len(strtab.data), 0, 0, 1, 0),
        (shstr_names[5], SHT_STRTAB, 0, 0, shstr_file, len(shstr.data), 0, 0, 1, 0),
    ]
    for i, section in enumerate(sections):
        struct.pack_into("<IIIIIIIIII", out, sh_file + i * 40, *section)
    return bytes(out), stub_base


def thumb_code_pointers(image):
    """Targets of stored pointers that point into code with the Thumb bit set."""
    text_end = image.data_offset or image.code_mem_size
    targets = set()
    for offset in image.internal_offsets:
        value = struct.unpack_from("<I", image.code, offset)[0] - image.base
        if 0 <= value < text_end and value & 1:
            targets.add(image.base + value - 1)
    return sorted(targets)


def main():
    if len(sys.argv) != 3:
        print(__doc__.strip().splitlines()[-1], file=sys.stderr)
        return 2
    with open(sys.argv[1], "rb") as f:
        image = S3EImage(f.read())
    elf, stub_base = build_elf(image)
    with open(sys.argv[2], "wb") as f:
        f.write(elf)
    pointers = thumb_code_pointers(image)
    with open(sys.argv[2] + ".code-pointers.txt", "w") as f:
        f.write("".join("%08x\n" % address for address in pointers))
    print("%s: code 0x%08x-0x%08x, data to 0x%08x, %d imports at 0x%08x, %d import slots, "
          "%d internal pointers, %d Thumb functions behind pointers" % (
              sys.argv[2], image.base, image.base + (image.data_offset or 0),
              image.base + image.code_mem_size, len(image.symbols), stub_base,
              len(image.import_slots), len(image.internal_offsets), len(pointers)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
