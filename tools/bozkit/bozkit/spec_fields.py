"""Reading and changing an entity spec (CIsEntitySpec): its components, their reflected fields and
its transform."""
from __future__ import annotations

import math

from . import reflect
from .hashing import iw_hash

TRANSFORM = iw_hash('CIsTransform')
RENDERABLE_MODEL = iw_hash('CIsRenderableModel')
RENDERABLE_ASSET = iw_hash('CIsRenderableAsset')
LOCAL_POSITION = iw_hash('m_localPosition')
LOCAL_ROTATION = iw_hash('m_localRotation')
LOCAL_SCALE = iw_hash('m_localScale')
ASSETS = iw_hash('assets')
MODEL_REFERENCE = iw_hash('model')
_VEC3, _QUAT = iw_hash('CIwFVec3'), iw_hash('CIwFQuat')
_TRANSFORM_FIELDS = {LOCAL_POSITION: _VEC3, LOCAL_ROTATION: _QUAT, LOCAL_SCALE: _VEC3}
IDENTITY_ROTATION = (0.0, 0.0, 0.0, 1.0)
UNIT_SCALE = (1.0, 1.0, 1.0)


def component(spec, class_name: str):
    """The spec's component of a class, or None."""
    return next((c for c in spec.components if c.type_hash == iw_hash(class_name)), None)


def component_blob(spec, class_name: str):
    """The reflected fields (a Blob) of the spec's component of a class, or None."""
    return next((c.blob for c in spec.components if c.type_hash == iw_hash(class_name)), None)


def prop(blob, name: str):
    """The property called *name* of a blob (None for no blob or no such property)."""
    return field(blob, iw_hash(name)) if blob is not None else None


def field(blob, name_hash: int):
    return next((p for p in blob.properties if p.name_hash == name_hash), None)


def value(blob, name: str, default):
    """The typed value of a blob's property, or *default*."""
    found = prop(blob, name) if blob else None
    result = reflect.typed_value(found) if found else None
    return default if result is None else result


def transform_blob(spec):
    return next((c.blob for c in spec.components if c.blob and c.blob.class_hash == TRANSFORM), None)


def local_transform(spec):
    """(position, rotation x y z w, scale) of a spec; absent fields are the identity."""
    blob = transform_blob(spec)
    values = {LOCAL_POSITION: (0.0, 0.0, 0.0), LOCAL_ROTATION: IDENTITY_ROTATION, LOCAL_SCALE: UNIT_SCALE}
    if blob is not None:
        for name_hash, default in list(values.items()):
            found = field(blob, name_hash)
            result = reflect.typed_value(found) if found else None
            if isinstance(result, list) and len(result) == len(default):
                values[name_hash] = tuple(result)
    return values[LOCAL_POSITION], values[LOCAL_ROTATION], values[LOCAL_SCALE]


def close(a, b, tolerance=1e-5) -> bool:
    return len(a) == len(b) and all(math.isclose(x, y, abs_tol=tolerance, rel_tol=tolerance)
                                    for x, y in zip(a, b))


def same_rotation(a, b) -> bool:
    # q and -q are the same rotation; Blender may hand back either sign.
    return close(a, b) or close(a, tuple(-v for v in b))


def set_transform(spec, position=None, rotation=None, scale=None) -> bool:
    """Write a spec's local transform (None keeps a part as it is). Returns whether anything
    changed."""
    blob = transform_blob(spec)
    current = local_transform(spec)
    wanted = {LOCAL_POSITION: (position, current[0]), LOCAL_ROTATION: (rotation, current[1]),
              LOCAL_SCALE: (scale, current[2])}
    changed = False
    for name_hash, (new, old) in wanted.items():
        if new is None:
            continue
        new = tuple(map(float, new))
        if same_rotation(new, old) if name_hash == LOCAL_ROTATION else close(new, old):
            continue
        if blob is None:
            raise ValueError('entity has no CIsTransform component to move')
        found = field(blob, name_hash)
        if found is None:
            # Reflection reads properties by name, so an absent default can be added.
            found = reflect.Property(TRANSFORM, _TRANSFORM_FIELDS[name_hash], name_hash, b'')
            blob.properties.append(found)
        reflect.set_typed_value(found, new)
        changed = True
    return changed


def scale_by(spec, scale) -> None:
    """Multiply a spec's own scale by *scale* (placements are relative to it)."""
    own = local_transform(spec)[2]
    set_transform(spec, scale=tuple(own[i] * float(scale[i]) for i in range(3)))


def model_reference(spec) -> int | None:
    """The single CIwModel a renderable spec draws, or None."""
    for c in spec.components:
        blob = c.blob
        if not blob or blob.class_hash != RENDERABLE_MODEL:
            continue
        assets = field(blob, ASSETS)
        if assets is None or not assets.elements:
            return None
        hashes = set()
        for asset in assets.elements:
            if asset.class_hash != RENDERABLE_ASSET:
                continue
            found = field(asset, MODEL_REFERENCE)
            result = reflect.typed_value(found) if found else None
            if isinstance(result, int):
                hashes.add(result)
        return hashes.pop() if len(hashes) == 1 else None
    return None


def quat_mul(a, b):
    """The product of two quaternions (x, y, z, w)."""
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw,
            aw * bw - ax * bx - ay * by - az * bz)


def rotate(q, v):
    """A point turned by the quaternion *q* (x, y, z, w)."""
    x, y, z, w = q
    return ((1 - 2 * (y * y + z * z)) * v[0] + 2 * (x * y - z * w) * v[1] + 2 * (x * z + y * w) * v[2],
            2 * (x * y + z * w) * v[0] + (1 - 2 * (x * x + z * z)) * v[1] + 2 * (y * z - x * w) * v[2],
            2 * (x * z - y * w) * v[0] + 2 * (y * z + x * w) * v[1] + (1 - 2 * (x * x + y * y)) * v[2])


def apply_chain(chain, point):
    """A point through (position, rotation, scale) transforms, innermost first."""
    for position, rotation, scale in chain:
        point = rotate(rotation, tuple(point[i] * scale[i] for i in range(3)))
        point = tuple(point[i] + position[i] for i in range(3))
    return point
