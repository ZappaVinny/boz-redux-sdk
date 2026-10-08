"""Blender-neutral import/export boundary for existing native groups.

The Blender add-on converts these plain dataclasses to and from ``bpy`` objects. Native parsing,
identity matching, validation, and lossless group writing stay here so the UI cannot grow a second
set of format codecs.
"""
from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field
from pathlib import Path

from . import collision, group, map_resources, native, navigation, reflect, resources
from .hashing import iw_hash

SCHEMA = 1
MODEL = iw_hash('CIwModel')
MATERIAL = iw_hash('CIwMaterial')
PORTAL = iw_hash('CIsPortal')
ENTITY_SPEC = iw_hash('CIsEntitySpec')
NAV_CONNECTION = iw_hash('CIsNavMeshConnection')
TRANSFORM = iw_hash('CIsTransform')
RENDERABLE_MODEL = iw_hash('CIsRenderableModel')
RENDERABLE_ASSET = iw_hash('CIsRenderableAsset')
LOCAL_POSITION = iw_hash('m_localPosition')
LOCAL_ROTATION = iw_hash('m_localRotation')
ASSETS = iw_hash('assets')
MODEL_REFERENCE = iw_hash('model')


def to_blender(value):
    """Rotate BOZ's right-handed Y-up coordinates into Blender's Z-up basis."""
    x, y, z = value
    return (x, -z, y)


def from_blender(value):
    """Rotate Blender Z-up coordinates back into BOZ's native Y-up basis."""
    x, y, z = value
    return (x, z, -y)


@dataclass
class SceneMesh:
    kind: str
    class_hash: int
    resource_hash: int
    resource_index: int
    source_group: str
    display_name: str
    collection: str
    vertices: list[tuple[float, float, float]] = field(default_factory=list)
    faces: list[tuple[int, int, int]] = field(default_factory=list)
    edges: list[tuple[int, int]] = field(default_factory=list)
    uvs: list[tuple[float, float]] = field(default_factory=list)
    face_materials: list[int] = field(default_factory=list)
    front_sector: str = ''
    back_sector: str = ''
    material_names: list[str] = field(default_factory=list)
    location: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotation: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 1.0)  # xyzw
    instance_resource_hash: int | None = None
    instance_resource_index: int | None = None
    material_hashes: list[int] = field(default_factory=list)
    vertex_colours: list[tuple[int, int, int, int]] = field(default_factory=list)


@dataclass
class SceneImport:
    source_group: str
    meshes: list[SceneMesh] = field(default_factory=list)
    materials: dict[int, SceneMaterial] = field(default_factory=dict)
    textures: dict[int, SceneTexture] = field(default_factory=dict)
    preserved: int = 0


@dataclass
class SceneTexture:
    resource_hash: int
    width: int
    height: int
    rgba: bytes
    format: str
    flags: int = 0


@dataclass
class SceneMaterial:
    resource_hash: int
    texture_hashes: list[int] = field(default_factory=list)
    diffuse: tuple[int, int, int, int] = (255, 255, 255, 255)
    flags: int = 0


@dataclass
class SceneEdit:
    kind: str
    class_hash: int
    resource_hash: int
    resource_index: int
    vertices: list[tuple[float, float, float]]
    faces: list[tuple[int, int, int]]
    edges: list[tuple[int, int]] = field(default_factory=list)
    uvs: list[tuple[float, float]] = field(default_factory=list)
    face_materials: list[int] = field(default_factory=list)
    front_sector: str = ''
    back_sector: str = ''
    location: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotation: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 1.0)
    instance_resource_hash: int | None = None
    instance_resource_index: int | None = None


@dataclass(frozen=True)
class ExportReport:
    edited: int
    preserved: int


def _identity(item: group.Resource) -> int:
    return item.name_hash if item.name_hash is not None else item.in_group_hash


def _triangles(indices: list[int]) -> list[tuple[int, int, int]]:
    return [tuple(indices[index:index + 3]) for index in range(0, len(indices), 3)]


def _model_materials(body: bytes, known: set[int]) -> list[int]:
    """Decode the terminal CIwModel material-reference array, validated against the group."""
    matches = []
    for offset in range(max(0, len(body) - 4096), len(body) - 3):
        count = struct.unpack_from('<I', body, offset)[0]
        if count > 1024 or offset + 4 + count * 4 != len(body):
            continue
        values = list(struct.unpack_from(f'<{count}I', body, offset + 4)) if count else []
        if values and all(value in known for value in values):
            matches.append(values)
    return matches[0] if len(matches) == 1 else []


def _collision_spec(item: group.Resource):
    spec = resources.decode_entity_spec(item.body)
    matches = [component for component in spec.components
               if component.class_hash == resources.COLLISION_MESH_SPEC]
    if len(matches) != 1:
        raise ValueError('entity spec does not contain exactly one collision mesh')
    return spec, matches[0]


def _property(blob: reflect.Blob, name_hash: int):
    return next((prop for prop in blob.properties if prop.name_hash == name_hash), None)


def _placed_model(spec: resources.EntitySpec):
    """Return (model hash, native position, native xyzw quaternion) for a renderable entity."""
    transform = renderable = None
    for component in spec.components:
        blob = component.blob
        if blob and blob.class_hash == TRANSFORM:
            transform = blob
        elif blob and blob.class_hash == RENDERABLE_MODEL:
            renderable = blob
    if transform is None or renderable is None:
        return None
    assets = _property(renderable, ASSETS)
    if assets is None or not assets.elements:
        return None
    model_hashes = []
    for asset in assets.elements:
        if asset.class_hash != RENDERABLE_ASSET:
            continue
        prop = _property(asset, MODEL_REFERENCE)
        value = reflect.typed_value(prop) if prop else None
        if isinstance(value, int):
            model_hashes.append(value)
    if len(set(model_hashes)) != 1:
        return None
    position_prop = _property(transform, LOCAL_POSITION)
    rotation_prop = _property(transform, LOCAL_ROTATION)
    position = reflect.typed_value(position_prop) if position_prop else None
    rotation = reflect.typed_value(rotation_prop) if rotation_prop else None
    if not isinstance(position, list) or len(position) != 3:
        position = [0.0, 0.0, 0.0]
    if not isinstance(rotation, list) or len(rotation) != 4:
        rotation = [0.0, 0.0, 0.0, 1.0]
    return model_hashes[0], tuple(position), tuple(rotation)


def _quat_mul(a, b):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw,
            aw * bw - ax * bx - ay * by - az * bz)


def rotation_to_blender(value):
    basis = (math.sqrt(0.5), 0.0, 0.0, math.sqrt(0.5))
    inverse = (-basis[0], -basis[1], -basis[2], basis[3])
    return _quat_mul(_quat_mul(basis, value), inverse)


def rotation_from_blender(value):
    basis = (math.sqrt(0.5), 0.0, 0.0, math.sqrt(0.5))
    inverse = (-basis[0], -basis[1], -basis[2], basis[3])
    return _quat_mul(_quat_mul(inverse, value), basis)


def _close(a, b, tolerance=1e-5):
    return len(a) == len(b) and all(math.isclose(x, y, abs_tol=tolerance, rel_tol=tolerance)
                                    for x, y in zip(a, b))


def _reconcile_model_positions(old: native.Model, edited):
    """Apply one seam-copy edit to every render vertex sharing its native position."""
    if len(edited) != len(old.vertices):
        return edited
    remap = old.position_remap or list(range(len(old.vertices)))
    groups = {}
    for render_index, position_index in enumerate(remap):
        groups.setdefault(position_index, []).append(render_index)
    result = list(edited)
    for indices in groups.values():
        original = old.vertices[indices[0]]
        changed = {edited[index] for index in indices if edited[index] != original}
        if len(changed) > 1:
            raise ValueError('render vertices sharing one native position were moved to '
                             'different destinations')
        if changed:
            destination = changed.pop()
            for index in indices:
                result[index] = destination
    return result


def import_group(path: str | Path, *, include_models: bool = True,
                 include_collision: bool = True, include_portals: bool = True,
                 include_navigation: bool = True) -> SceneImport:
    """Decode every supported editable mesh in one group.

    Unsupported and malformed resource classes are counted as preserved and remain byte-identical
    during export. A recognized editable resource is never silently skipped after decoding starts.
    """
    source = str(Path(path).resolve())
    parsed = group.parse(Path(source).read_bytes())
    result = SceneImport(source)
    class_indices: dict[int, int] = {}
    model_resources = {}
    material_hashes = set()
    material_resources = {}
    texture_resources = {}
    entity_instances = []
    for resource_type in parsed.types():
        for index, item in enumerate(resource_type.resources):
            if resource_type.class_hash == MODEL:
                model_resources[_identity(item)] = (index, item)
            elif resource_type.class_hash == MATERIAL:
                material_hashes.add(_identity(item))
                material_resources[_identity(item)] = item
            elif resource_type.class_hash == iw_hash('CIwTexture'):
                texture_resources[_identity(item)] = item
            elif resource_type.class_hash == ENTITY_SPEC:
                try:
                    placed = _placed_model(resources.decode_entity_spec(item.body))
                except (ValueError, struct.error):
                    placed = None
                if placed:
                    entity_instances.append((index, item, placed))
    entity_instances = [entry for entry in entity_instances if entry[2][0] in model_resources]
    placed_model_hashes = {placed[0] for _, _, placed in entity_instances}
    for resource_type in parsed.types():
        for item in resource_type.resources:
            resource_index = class_indices.get(resource_type.class_hash, 0)
            class_indices[resource_type.class_hash] = resource_index + 1
            resource_hash = _identity(item)
            label = f'{resource_hash:08x}'
            if include_models and resource_type.class_hash == MODEL and resource_hash not in placed_model_hashes:
                model = native.decode_model(item.body)
                result.meshes.append(SceneMesh('model', MODEL, resource_hash, resource_index, source,
                                               f'model_{label}', 'BOZ Local Asset Models',
                                               [to_blender(tuple(map(float, vertex)))
                                                for vertex in model.vertices],
                                               list(model.triangles), uvs=model.uvs,
                                               face_materials=model.face_materials,
                                               material_hashes=_model_materials(item.body,
                                                                               material_hashes),
                                               vertex_colours=model.vertex_colours))
            elif resource_type.class_hash == MODEL and resource_hash in placed_model_hashes:
                result.preserved += 1
            elif include_portals and resource_type.class_hash == PORTAL:
                portal = map_resources.decode_portal(item.body)
                faces = [(0, index, index + 1) for index in range(1, len(portal.vertices) - 1)]
                result.meshes.append(SceneMesh('portal', PORTAL, resource_hash, resource_index, source,
                                               f'portal_{label}', 'BOZ Portals',
                                               [to_blender(vertex) for vertex in portal.vertices],
                                               faces, front_sector=portal.front_sector,
                                               back_sector=portal.back_sector))
            elif include_collision and resource_type.class_hash == ENTITY_SPEC:
                try:
                    _, component = _collision_spec(item)
                except (ValueError, struct.error):
                    result.preserved += 1
                    continue
                mesh = collision.decode(component.extra)
                result.meshes.append(SceneMesh('collision', ENTITY_SPEC, resource_hash, resource_index, source,
                                               f'collision_{label}', 'BOZ Collision',
                                               [to_blender(vertex) for vertex in mesh.vertices],
                                               _triangles(mesh.indices), face_materials=list(mesh.materials),
                                               material_names=mesh.material_names))
            elif include_navigation and resource_type.class_hash == NAV_CONNECTION:
                connection = navigation.decode_connection(item.body)
                result.meshes.append(SceneMesh(
                    'navigation_connection', NAV_CONNECTION, resource_hash, resource_index,
                    source, f'navigation_connection_{label}', 'BOZ Navigation',
                    [to_blender(connection.start), to_blender(connection.end)], [], [(0, 1)]))
            else:
                result.preserved += 1
    for entity_index, entity, placed in entity_instances:
        model_hash, position, rotation = placed
        model_index, model_item = model_resources[model_hash]
        model = native.decode_model(model_item.body)
        result.meshes.append(SceneMesh(
            'placed_model', MODEL, model_hash, model_index, source,
            f'placed_model_{_identity(entity):08x}', 'BOZ Placed Models',
            [to_blender(tuple(map(float, vertex))) for vertex in model.vertices],
            list(model.triangles), uvs=model.uvs, face_materials=model.face_materials,
            location=to_blender(position),
            rotation=rotation_to_blender(rotation),
            instance_resource_hash=_identity(entity), instance_resource_index=entity_index,
            material_hashes=_model_materials(model_item.body, material_hashes),
            vertex_colours=model.vertex_colours))
    referenced_materials = {value for mesh in result.meshes for value in mesh.material_hashes}
    referenced_textures = set()
    for material_hash in referenced_materials:
        item = material_resources.get(material_hash)
        if item is None:
            continue
        try:
            material = native.decode_material(item.body)
        except (ValueError, struct.error):
            continue
        texture_hashes = list(material.textures)
        diffuse = tuple(material.colours[0]) if material.colours else (255, 255, 255, 255)
        result.materials[material_hash] = SceneMaterial(material_hash, texture_hashes, diffuse,
                                                       material.flags)
        referenced_textures.update(texture_hashes)
    for texture_hash in referenced_textures:
        item = texture_resources.get(texture_hash)
        if item is None:
            continue
        try:
            texture = native.decode_texture_rgba(item.body)
        except (ValueError, struct.error):
            continue
        result.textures[texture_hash] = SceneTexture(texture_hash, texture.width, texture.height,
                                                     texture.rgba, texture.format,
                                                     struct.unpack_from('<I', item.body)[0])
    return result


def _normal(vertices: list[tuple[float, float, float]], original):
    if len(vertices) < 3:
        raise ValueError('portal requires at least three vertices')
    a, b, c = vertices[:3]
    ab = tuple(b[index] - a[index] for index in range(3))
    ac = tuple(c[index] - a[index] for index in range(3))
    value = (ab[1] * ac[2] - ab[2] * ac[1],
             ab[2] * ac[0] - ab[0] * ac[2],
             ab[0] * ac[1] - ab[1] * ac[0])
    length = math.sqrt(sum(component * component for component in value))
    if length <= 1e-8:
        raise ValueError('portal vertices are collinear')
    value = tuple(component / length for component in value)
    if sum(value[index] * original[index] for index in range(3)) < 0:
        value = tuple(-component for component in value)
    return value


def _validate_edit(edit: SceneEdit) -> None:
    if not edit.vertices or (not edit.faces and edit.kind != 'navigation_connection'):
        raise ValueError(f'{edit.kind} {edit.resource_hash:#010x} has no geometry')
    if any(len(face) != 3 for face in edit.faces):
        raise ValueError(f'{edit.kind} {edit.resource_hash:#010x} contains a non-triangle face')
    if any(index < 0 or index >= len(edit.vertices) for face in edit.faces for index in face):
        raise ValueError(f'{edit.kind} {edit.resource_hash:#010x} has an invalid vertex index')
    if edit.uvs and len(edit.uvs) != len(edit.vertices):
        raise ValueError(f'{edit.kind} {edit.resource_hash:#010x} UV count does not match vertices')


def export_group(source: str | Path, output: str | Path,
                 edits: list[SceneEdit]) -> ExportReport:
    """Patch edited Blender meshes into a copy of their source group."""
    source_path = Path(source).resolve()
    output_path = Path(output).resolve()
    if source_path == output_path:
        raise ValueError('the source group is never overwritten; choose a new output path')
    parsed = group.parse(source_path.read_bytes())
    resources_by_id = {}
    class_indices: dict[int, int] = {}
    total = 0
    for resource_type in parsed.types():
        for item in resource_type.resources:
            total += 1
            resource_index = class_indices.get(resource_type.class_hash, 0)
            class_indices[resource_type.class_hash] = resource_index + 1
            key = (resource_type.class_hash, resource_index)
            resources_by_id[key] = item
    seen = set()
    changed_resources = set()
    for edit in edits:
        _validate_edit(edit)
        key = (edit.class_hash, edit.resource_index)
        if key in seen:
            raise ValueError(f'duplicate edit for resource {edit.resource_hash:#010x}')
        seen.add(key)
        item = resources_by_id.get(key)
        if item is None:
            raise ValueError(f'source resource {edit.resource_hash:#010x} no longer exists')
        if _identity(item) != edit.resource_hash:
            raise ValueError(f'source resource identity changed at index {edit.resource_index}')
        if edit.kind in ('model', 'placed_model') and edit.class_hash == MODEL:
            old = native.decode_model(item.body)
            vertices = [tuple(round(value) for value in from_blender(vertex))
                        for vertex in edit.vertices]
            vertices = _reconcile_model_positions(old, vertices)
            model = native.Model(vertices, list(edit.faces), edit.uvs or old.uvs,
                                 face_materials=edit.face_materials)
            if (model.vertices != old.vertices or model.triangles != old.triangles or
                    model.uvs != old.uvs):
                item.body = native.encode_model(model, item.body)
                changed_resources.add(key)
        elif edit.kind == 'collision' and edit.class_hash == ENTITY_SPEC:
            spec, component = _collision_spec(item)
            mesh = collision.decode(component.extra)
            indices = [index for face in edit.faces for index in face]
            if len(edit.vertices) != len(mesh.vertices) or len(indices) != len(mesh.indices):
                raise ValueError('collision export currently requires unchanged topology')
            vertices = [from_blender(tuple(map(float, vertex))) for vertex in edit.vertices]
            materials = bytes(edit.face_materials) if edit.face_materials else mesh.materials
            if vertices == mesh.vertices and indices == mesh.indices and materials == mesh.materials:
                continue
            mesh.vertices = vertices
            mesh.indices = indices
            if edit.face_materials:
                if len(edit.face_materials) != len(edit.faces):
                    raise ValueError('collision requires one material assignment per face')
                if any(index < 0 or index > 255 for index in edit.face_materials):
                    raise ValueError('collision material indices must fit in one byte')
                mesh.materials = materials
            component.extra = collision.encode(mesh)
            item.body = resources.encode_entity_spec(spec)
        elif edit.kind == 'portal' and edit.class_hash == PORTAL:
            portal = map_resources.decode_portal(item.body)
            vertices = [from_blender(tuple(map(float, vertex))) for vertex in edit.vertices]
            if (vertices == portal.vertices and edit.front_sector == portal.front_sector and
                    edit.back_sector == portal.back_sector):
                continue
            portal.vertices = vertices
            portal.normal = _normal(portal.vertices, portal.normal)
            portal.distance = sum(portal.normal[index] * portal.vertices[0][index]
                                  for index in range(3))
            portal.front_sector = edit.front_sector
            portal.back_sector = edit.back_sector
            item.body = map_resources.encode_portal(portal)
        elif edit.kind == 'navigation_connection' and edit.class_hash == NAV_CONNECTION:
            if len(edit.vertices) != 2 or edit.edges != [(0, 1)]:
                raise ValueError('navigation connection must remain one two-point edge')
            connection = navigation.decode_connection(item.body)
            start, end = (from_blender(tuple(map(float, vertex))) for vertex in edit.vertices)
            if start == connection.start and end == connection.end:
                continue
            connection.start = start
            connection.end = end
            item.body = navigation.encode_connection(connection)
        else:
            raise ValueError(f'unsupported Blender edit kind {edit.kind!r}')
        if edit.kind not in ('model', 'placed_model'):
            changed_resources.add(key)
        if edit.kind == 'placed_model':
            instance_key = (ENTITY_SPEC, edit.instance_resource_index)
            entity = resources_by_id.get(instance_key)
            if entity is None or edit.instance_resource_hash is None:
                raise ValueError('placed model entity resource no longer exists')
            if _identity(entity) != edit.instance_resource_hash:
                raise ValueError('placed model entity identity changed')
            spec = resources.decode_entity_spec(entity.body)
            placed = _placed_model(spec)
            if placed is None or placed[0] != edit.resource_hash:
                raise ValueError('placed model reference changed')
            transform = next(component.blob for component in spec.components
                             if component.blob and component.blob.class_hash == TRANSFORM)
            position_prop = _property(transform, LOCAL_POSITION)
            rotation_prop = _property(transform, LOCAL_ROTATION)
            native_position = from_blender(edit.location)
            native_rotation = rotation_from_blender(edit.rotation)
            transform_changed = False
            if position_prop and not _close(tuple(reflect.typed_value(position_prop)), native_position):
                reflect.set_typed_value(position_prop, native_position)
                transform_changed = True
            if rotation_prop and not _close(tuple(reflect.typed_value(rotation_prop)), native_rotation):
                reflect.set_typed_value(rotation_prop, native_rotation)
                transform_changed = True
            if transform_changed:
                entity.body = resources.encode_entity_spec(spec)
                changed_resources.add(instance_key)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(group.encode(parsed))
    return ExportReport(len(changed_resources), total - len(changed_resources))
