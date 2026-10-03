"""
Resource bodies bozkit understands, decoded losslessly.

* Reflected resources (``CIsReflectedResource`` subclasses: CWave, CDORound, CLevel, ...)::

      u32 blob_size, blob (see reflect.py)

* Entity specs (``CIsEntitySpec``: weapons, pickups, map objects), recursive::

      u32 component_count
      component_count x: u32 class_hash (CIsComponentSpec or a subclass), u32 reserved,
                         u32 component_type_hash, u32 size,
                         blobs filling size bytes (usually one; empty placeholders are 16 bytes)
      u32 child_count
      child_count x: u32 class_hash (CIsEntitySpec), u32 reserved, entity spec body (this layout)

  A component whose class is CIsCollisionMeshSpec appends its collision data after the blobs
  (u32 size + serialised Bullet shape, the triangle mesh, one material byte per triangle).
  bozkit keeps it as raw ``extra`` bytes. The game puts that component last in a spec with no
  children, so its end is the end of the spec less the 4-byte (zero) child count.

Other classes keep their raw body.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field

from . import reflect
from .hashing import iw_hash

ENTITY_SPEC = iw_hash('CIsEntitySpec')
COLLISION_MESH_SPEC = iw_hash('CIsCollisionMeshSpec')


@dataclass
class Component:
    class_hash: int
    reserved: int
    type_hash: int
    blobs: list[reflect.Blob]
    extra: bytes = b''  # class-specific data after the blobs (collision meshes)

    @property
    def blob(self) -> reflect.Blob | None:
        """The first non-empty blob (the component's properties)."""
        return next((b for b in self.blobs if not b.empty), None)


@dataclass
class EntitySpec:
    components: list[Component] = field(default_factory=list)
    children: list[tuple[int, int, EntitySpec]] = field(default_factory=list)  # (class, reserved, spec)


def decode_reflected(body: bytes) -> reflect.Blob | None:
    """The blob of a reflected resource body, or None if the body is not one."""
    if len(body) < 20 or not reflect.is_blob(body, 4):
        return None
    (size,) = struct.unpack_from('<I', body, 0)
    blob, end = reflect.decode(body, 4)
    if end != len(body) or size != end - 4:
        return None
    return blob


def encode_reflected(blob: reflect.Blob) -> bytes:
    data = reflect.encode(blob)
    return struct.pack('<I', len(data)) + data


def decode_entity_spec(body: bytes) -> EntitySpec:
    spec, end = _decode_spec(body, 0, len(body))
    if end != len(body):
        raise ValueError(f'entity spec: {len(body) - end} trailing bytes')
    return spec


def _decode_spec(body: bytes, p: int, limit: int) -> tuple[EntitySpec, int]:
    (count,) = struct.unpack_from('<I', body, p)
    p += 4
    spec = EntitySpec()
    for i in range(count):
        class_hash, reserved, type_hash, size = struct.unpack_from('<IIII', body, p)
        p += 16
        blobs = reflect.decode_sequence(body, p, size)
        p += size
        extra = b''
        if class_hash == COLLISION_MESH_SPEC:
            if i != count - 1 or struct.unpack_from('<I', body, limit - 4)[0] != 0:
                raise ValueError('collision mesh component is not the last part of its spec')
            extra = bytes(body[p:limit - 4])
            p = limit - 4
        spec.components.append(Component(class_hash, reserved, type_hash, blobs, extra))
    (children,) = struct.unpack_from('<I', body, p)
    p += 4
    for _ in range(children):
        class_hash, reserved = struct.unpack_from('<II', body, p)
        p += 8
        child, p = _decode_spec(body, p, limit)
        spec.children.append((class_hash, reserved, child))
    return spec, p


def encode_entity_spec(spec: EntitySpec) -> bytes:
    out = bytearray(struct.pack('<I', len(spec.components)))
    for c in spec.components:
        data = b''.join(reflect.encode(b) for b in c.blobs)
        out += struct.pack('<IIII', c.class_hash, c.reserved, c.type_hash, len(data)) + data + c.extra
    out += struct.pack('<I', len(spec.children))
    for class_hash, reserved, child in spec.children:
        out += struct.pack('<II', class_hash, reserved) + encode_entity_spec(child)
    return bytes(out)
