"""
Save files (``<home>/data-etc/*.i3d``), written by CSaveManager through IwSerialise.

Every file::

    u32 version          0x493e1 (game saves) / 0x493e0 (the others) in 1.0.11
    u32 checksum         Adler-32 of the whole file with this field zeroed
    body

Game save (``N_save_game.i3d``) body::

    cstring level        e.g. "kino"
    u32 dynamic_count    (version >= 300000) entities spawned at run time, stored in the
                         DynamicEntityData section
    u32 section_count
    section_count x: u32 id, u32 class_hash, u32 size, data[size]

``id`` is the saving object's name hash (a placed door, perk machine, trap...) or the system's
class hash; each system writes its own word stream (CIsDataBuffer) into its section.

Settings (``save_settings.i3d``) body: see SETTINGS_FIELDS (CSaveManager +0xf8, written by
the options menu). Strings in IwSerialise files are zero-terminated.
"""
from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass, field

DYNAMIC_ENTITY_VERSION = 300000


def checksum(data: bytes) -> int:
    return zlib.adler32(data[:4] + b'\0\0\0\0' + data[8:])


def sign(data: bytes) -> bytes:
    """Return *data* with a correct checksum."""
    return data[:4] + struct.pack('<I', checksum(data)) + data[8:]


def _cstring(data: bytes, p: int) -> tuple[str, int]:
    end = data.index(b'\0', p)
    return data[p:end].decode('latin-1'), end + 1


@dataclass
class Section:
    id: int
    class_hash: int
    data: bytes


@dataclass
class GameSave:
    version: int
    level: str
    dynamic_count: int | None
    sections: list[Section] = field(default_factory=list)


def parse_game_save(data: bytes) -> GameSave:
    version, stored = struct.unpack_from('<II', data, 0)
    if stored != checksum(data):
        raise ValueError('bad checksum')
    level, p = _cstring(data, 8)
    dynamic = None
    if version > DYNAMIC_ENTITY_VERSION - 1:
        (dynamic,) = struct.unpack_from('<I', data, p)
        p += 4
    (count,) = struct.unpack_from('<I', data, p)
    p += 4
    save = GameSave(version, level, dynamic)
    for _ in range(count):
        sid, cls, size = struct.unpack_from('<III', data, p)
        p += 12
        save.sections.append(Section(sid, cls, bytes(data[p:p + size])))
        p += size
    if p != len(data):
        raise ValueError(f'{len(data) - p} trailing bytes')
    return save


def encode_game_save(save: GameSave) -> bytes:
    out = bytearray(struct.pack('<II', save.version, 0))
    out += save.level.encode('latin-1') + b'\0'
    if save.dynamic_count is not None:
        out += struct.pack('<I', save.dynamic_count)
    out += struct.pack('<I', len(save.sections))
    for s in save.sections:
        out += struct.pack('<III', s.id, s.class_hash, len(s.data)) + s.data
    return sign(bytes(out))


# (name, struct format or 'cstring', offset in the settings object at CSaveManager +0xf8),
# in file order (FUN_4a1f449e).
SETTINGS_FIELDS = (
    ('sensitivity_x', '<f', 0x00),
    ('sensitivity_y', '<f', 0x04),
    ('detail_level', '<f', 0x18),
    ('brightness', '<f', 0x1c),
    ('invert_y', '<?', 0x08),
    ('lefty_controls', '<?', 0x0f),
    ('auto_aim', '<?', 0x0e),
    ('flag_0x20', '<?', 0x20),
    ('flag_0x2c', '<?', 0x2c),
    ('music_volume', '<I', 0x10),
    ('control_method', '<h', 0x0a),
    ('sfx_volume', '<h', 0x14),
    ('flags_0x21', '<4?', 0x21),
    ('accelerometer_calibration', '<i', 0x28),
    ('value_0xd4', '<I', 0xd4),
    ('value_0x30', '<f', 0x30),
    ('last_level', 'cstring', 0x34),
    ('value_0xd8', '<I', 0xd8),
    ('value_0x0c', '<h', 0x0c),
)


def parse_settings(data: bytes) -> tuple[int, dict]:
    version, stored = struct.unpack_from('<II', data, 0)
    if stored != checksum(data):
        raise ValueError('bad checksum')
    p = 8
    values = {}
    for name, fmt, _ in SETTINGS_FIELDS:
        if fmt == 'cstring':
            values[name], p = _cstring(data, p)
            continue
        v = struct.unpack_from(fmt, data, p)
        values[name] = list(v) if len(v) > 1 else v[0]
        p += struct.calcsize(fmt)
    if p != len(data):
        raise ValueError(f'settings: {len(data) - p} trailing bytes')
    return version, values


def encode_settings(version: int, values: dict) -> bytes:
    out = bytearray(struct.pack('<II', version, 0))
    for name, fmt, _ in SETTINGS_FIELDS:
        v = values[name]
        if fmt == 'cstring':
            out += v.encode('latin-1') + b'\0'
        else:
            out += struct.pack(fmt, *(v if isinstance(v, list) else [v]))
    return sign(bytes(out))
