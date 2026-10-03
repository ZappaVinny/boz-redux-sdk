"""
Reflected property blobs (``LFER`` blocks).

The studio engine stores reflected objects (``CIsReflectedResource`` data such as waves and
rounds, and the components of entity specs) as a property blob that its reflection system reads
back by name::

    char  tag[4] = "LFER"        ("REFL" byte-reversed)
    u32   class_hash             IwHashString of the object's class
    u32   size                   bytes from the tag to the end of the blob; 0 in an empty
                                 placeholder blob (class 0, no records, 16 bytes)
    u32   count                  number of property records (authoritative: a few shipped
                                 blobs carry a stale, smaller size)
    count x record:
        u32 owner_hash           class that declares the property (the class or a base)
        u32 type_hash            IwHashString of the property's type ("float", "CIwFVec3", ...)
        u32 unknown1             always 1 in 1.0.11
        u32 name_hash            IwHashString of the property name ("m_ZombieCount")
        u32 unknown2             always 1 in 1.0.11
        u32 value_size
        value[value_size]        raw value; a struct-typed property holds a nested blob, a
                                 container of objects (std::list/vector) holds u32 count + that
                                 many blobs, a string holds its characters and a trailing zero

Decoding keeps every value as raw bytes plus a best-effort typed view, so encoding a decoded
blob gives back the original bytes.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field

TAG = b'LFER'


@dataclass
class Property:
    owner_hash: int
    type_hash: int
    name_hash: int
    raw: bytes
    unknown1: int = 1
    unknown2: int = 1
    nested: Blob | None = None  # set when raw is itself a blob
    elements: list[Blob] | None = None  # set when raw is a list/vector of objects (u32 n + n blobs)


@dataclass
class Blob:
    class_hash: int
    properties: list[Property] = field(default_factory=list)
    empty: bool = False  # written with size 0
    size_delta: int = 0  # declared size minus actual size (stale size fields in a few files)


def is_blob(data: bytes, offset: int = 0) -> bool:
    return data[offset:offset + 4] == TAG


def decode(data: bytes, offset: int = 0) -> tuple[Blob, int]:
    """Decode the blob at *offset*; return it and the offset just past it."""
    if not is_blob(data, offset):
        raise ValueError(f'no LFER tag at {offset:#x}')
    class_hash, size, count = struct.unpack_from('<III', data, offset + 4)
    if size == 0:
        if count != 0:
            raise ValueError(f'empty blob at {offset:#x} with {count} records')
        return Blob(class_hash, empty=True), offset + 16
    end = offset + size
    p = offset + 16
    blob = Blob(class_hash)
    for _ in range(count):
        owner, type_hash, u1, name_hash, u2, vsize = struct.unpack_from('<IIIIII', data, p)
        p += 24
        raw = bytes(data[p:p + vsize])
        p += vsize
        nested = decode(raw)[0] if vsize >= 16 and is_blob(raw) else None
        elements = _decode_elements(raw) if nested is None else None
        blob.properties.append(Property(owner, type_hash, name_hash, raw, u1, u2, nested, elements))
    # A few shipped blobs declare a size that covers only their first records; the records
    # (count) are authoritative. Keep the difference so the blob re-encodes byte for byte.
    blob.size_delta = end - p
    return blob, p


def _decode_elements(raw: bytes) -> list[Blob] | None:
    """A container of objects: u32 count, then count blobs filling the rest exactly."""
    if len(raw) < 20 or not is_blob(raw, 4):
        return None
    (n,) = struct.unpack_from('<I', raw, 0)
    try:
        blobs = decode_sequence(raw, 4, len(raw) - 4)
    except (ValueError, struct.error):
        return None
    return blobs if len(blobs) == n else None


def decode_sequence(data: bytes, offset: int, size: int) -> list[Blob]:
    """Blobs back to back filling *size* bytes from *offset* (component payloads)."""
    blobs = []
    p, end = offset, offset + size
    while p < end:
        blob, p = decode(data, p)
        blobs.append(blob)
    if p != end:
        raise ValueError(f'blob sequence at {offset:#x} overruns by {p - end}')
    return blobs


def encode(blob: Blob) -> bytes:
    """Encode a blob; nested blobs are re-encoded from their decoded form."""
    if blob.empty and not blob.properties:
        return TAG + struct.pack('<III', blob.class_hash, 0, 0)
    body = bytearray()
    for prop in blob.properties:
        if prop.nested is not None:
            raw = encode(prop.nested)
        elif prop.elements is not None:
            raw = struct.pack('<I', len(prop.elements)) + b''.join(encode(e) for e in prop.elements)
        else:
            raw = prop.raw
        body += struct.pack('<IIIIII', prop.owner_hash, prop.type_hash, prop.unknown1,
                            prop.name_hash, prop.unknown2, len(raw))
        body += raw
    size = 16 + len(body) + blob.size_delta
    return TAG + struct.pack('<III', blob.class_hash, size, len(blob.properties)) + bytes(body)


# Typed views of common value types (by IwHashString of the type name).
def _type_codecs():
    from .hashing import iw_hash
    codecs = {
        'float': ('<f', 4), 'int': ('<i', 4), 'unsigned int': ('<I', 4), 'short': ('<h', 2),
        'unsigned short': ('<H', 2), 'char': ('<b', 1), 'unsigned char': ('<B', 1), 'bool': ('<?', 1),
        'CIwFVec2': ('<2f', 8), 'CIwFVec3': ('<3f', 12), 'CIwFVec4': ('<4f', 16), 'CIwFQuat': ('<4f', 16),
        'CIwColour': ('<4B', 4),
    }
    return {iw_hash(name): (name, fmt, size) for name, (fmt, size) in codecs.items()}


_CODECS = None


def typed_value(prop: Property):
    """A Python value for common types, a string for string-like raw data, else None."""
    global _CODECS
    if _CODECS is None:
        _CODECS = _type_codecs()
    codec = _CODECS.get(prop.type_hash)
    if codec and len(prop.raw) == codec[2]:
        value = struct.unpack(codec[1], prop.raw)
        return value[0] if len(value) == 1 else list(value)
    if prop.raw.endswith(b'\0') and all(32 <= c < 127 for c in prop.raw[:-1]):
        return prop.raw[:-1].decode('ascii')
    return None


def set_typed_value(prop: Property, value) -> None:
    """Replace a property's value from a Python value of its type (see typed_value)."""
    global _CODECS
    if _CODECS is None:
        _CODECS = _type_codecs()
    codec = _CODECS.get(prop.type_hash)
    if codec:
        values = value if isinstance(value, (list, tuple)) else [value]
        prop.raw = struct.pack(codec[1], *values)
    elif isinstance(value, str):
        prop.raw = value.encode('ascii') + b'\0'
    else:
        raise TypeError(f'no codec for type hash {prop.type_hash:#010x}')
    prop.nested = None
    prop.elements = None
