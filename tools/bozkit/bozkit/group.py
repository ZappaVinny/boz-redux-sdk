"""
IwResGroup container (``.group.bin``), read and written losslessly.

Layout (see also tools/destin, dade.marmalade.resgroup)::

    header[6]                      0x3d tag, padding, reserved u16
    repeat:
        u32 section_hash           IwHashString of the section name; 0 ends the list
        u32 size                   payload length + 4
        payload[size - 4]
    ("ResGroupResources" payload)
        u32 type_count
        type_count x:
            u32 class_hash, u32 count, u8 names_omitted, u8 has_size
            count x: u32 size (from the size field to the end of the body),
                     [u32 name_hash unless names_omitted], u32 in_group_hash, body

Bodies are kept as bytes; see resources.py for the classes bozkit understands. Anything after
the terminating zero section hash is kept as-is.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field

from .hashing import iw_hash

RESOURCES = iw_hash('ResGroupResources')
MEMBERS = iw_hash('ResGroupMembers')


@dataclass
class Resource:
    name_hash: int | None
    in_group_hash: int
    body: bytes


@dataclass
class ResourceType:
    class_hash: int
    names_omitted: int
    has_size: int
    resources: list[Resource] = field(default_factory=list)


@dataclass
class Section:
    hash: int
    payload: bytes
    types: list[ResourceType] | None = None  # parsed ResGroupResources


@dataclass
class Group:
    header: bytes
    sections: list[Section]
    trailer: bytes = b''

    @property
    def name(self) -> str | None:
        for s in self.sections:
            if s.hash == MEMBERS:
                return s.payload.split(b'\0', 1)[0].decode('latin-1')
        return None

    def types(self) -> list[ResourceType]:
        out: list[ResourceType] = []
        for s in self.sections:
            if s.types is not None:
                out.extend(s.types)
        return out


def _parse_resources(payload: bytes) -> list[ResourceType]:
    q = 0
    (count_types,) = struct.unpack_from('<I', payload, q)
    q += 4
    types = []
    for _ in range(count_types):
        class_hash, count = struct.unpack_from('<II', payload, q)
        names_omitted, has_size = payload[q + 8], payload[q + 9]
        q += 10
        if not has_size:
            raise ValueError(f'resource class {class_hash:#010x} has no size prefix (unsupported)')
        t = ResourceType(class_hash, names_omitted, has_size)
        for _ in range(count):
            start = q
            (size,) = struct.unpack_from('<I', payload, q)
            q += 4
            name_hash = None
            if not names_omitted:
                (name_hash,) = struct.unpack_from('<I', payload, q)
                q += 4
            (in_group,) = struct.unpack_from('<I', payload, q)
            q += 4
            t.resources.append(Resource(name_hash, in_group, bytes(payload[q:start + size])))
            q = start + size
        types.append(t)
    if q != len(payload):
        raise ValueError(f'ResGroupResources: {len(payload) - q} trailing bytes')
    return types


def _encode_resources(types: list[ResourceType]) -> bytes:
    out = bytearray(struct.pack('<I', len(types)))
    for t in types:
        out += struct.pack('<II', t.class_hash, len(t.resources)) + bytes([t.names_omitted, t.has_size])
        for r in t.resources:
            head = b'' if t.names_omitted else struct.pack('<I', r.name_hash or 0)
            head += struct.pack('<I', r.in_group_hash)
            out += struct.pack('<I', 4 + len(head) + len(r.body)) + head + r.body
    return bytes(out)


def parse(data: bytes) -> Group:
    if not data or data[0] != 0x3D:
        raise ValueError('not an IwResGroup (.group.bin)')
    p = 6
    sections = []
    while True:
        (h,) = struct.unpack_from('<I', data, p)
        p += 4
        if h == 0:
            break
        (size,) = struct.unpack_from('<I', data, p)
        p += 4
        payload = bytes(data[p:p + size - 4])
        p += size - 4
        sections.append(Section(h, payload, _parse_resources(payload) if h == RESOURCES else None))
    return Group(bytes(data[:6]), sections, bytes(data[p:]))


def encode(group: Group) -> bytes:
    out = bytearray(group.header)
    for s in group.sections:
        payload = _encode_resources(s.types) if s.types is not None else s.payload
        out += struct.pack('<II', s.hash, len(payload) + 4) + payload
    out += struct.pack('<I', 0) + group.trailer
    return bytes(out)
