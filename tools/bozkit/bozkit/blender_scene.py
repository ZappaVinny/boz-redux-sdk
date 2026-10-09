"""Blender-neutral import/export boundary for existing native groups.

The Blender add-on converts these plain dataclasses to and from ``bpy`` objects. Native parsing,
identity matching, validation, and lossless group writing stay here so the UI cannot grow a second
set of format codecs.

A map is several groups: Kino places models from ``kino_dynamics`` and the shared ``ingame`` group
in ``kino_statics``, and each room's ``*_shared`` group holds its own geometry while its textures
live elsewhere. :func:`import_groups` therefore resolves models, materials and textures across
every group it is given. Edits are written back to the group that owns each resource.
"""
from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field
from pathlib import Path

from . import collision, group, map_resources, native, navbuild, navigation, reflect, resources
from .hashing import iw_hash

SCHEMA = 2
MODEL = iw_hash('CIwModel')
MATERIAL = iw_hash('CIwMaterial')
TEXTURE = iw_hash('CIwTexture')
PORTAL = iw_hash('CIsPortal')
ENTITY_SPEC = iw_hash('CIsEntitySpec')
NAV_CONNECTION = iw_hash('CIsNavMeshConnection')
TRANSFORM = iw_hash('CIsTransform')
RENDERABLE_MODEL = iw_hash('CIsRenderableModel')
RENDERABLE_ASSET = iw_hash('CIsRenderableAsset')
LOCAL_POSITION = iw_hash('m_localPosition')
LOCAL_ROTATION = iw_hash('m_localRotation')
LOCAL_SCALE = iw_hash('m_localScale')
ASSETS = iw_hash('assets')
MODEL_REFERENCE = iw_hash('model')
_VEC3 = iw_hash('CIwFVec3')
_QUAT = iw_hash('CIwFQuat')
_TRANSFORM_FIELDS = {LOCAL_POSITION: _VEC3, LOCAL_ROTATION: _QUAT, LOCAL_SCALE: _VEC3}
IDENTITY_ROTATION = (0.0, 0.0, 0.0, 1.0)
UNIT_SCALE = (1.0, 1.0, 1.0)

# Entity markers: the first matching component names the marker's category.
_COMPONENT_NAMES = [
    'CSpawnPoint', 'CIsRenderableGFXEmitter', 'CFogEffect', 'CPOI', 'CSnowTrigger',
    'CSoundEmitter', 'CPlayerJumpPoint', 'CLocator', 'CIsNavMeshTarget', 'CTeleportPointGersch',
    'CLighthouseTarget', 'CIsCamera', 'CAIControllerZombie', 'CAIControllerHellhound',
    'CAIControllerMonkey', 'CAIControllerRomero', 'CAITutor', 'CIsCollisionBox',
    'CIsCollisionSphere', 'CIsCollisionCapsule', 'CIsCollisionCompound', 'CIsBoneAttachment',
    'CPerk', 'CMysteryBox', 'CDoor', 'CBarricade', 'CTrap', 'CTrapSwitch', 'CPowerSwitch',
    'CTeleporter', 'CEasterEgg', 'CWeaponChalkOutline', 'CIsTransform', 'CIsNamed',
    'CIsBroadcaster', 'CIsHierarchy', 'CIsRenderableModel', 'CPackAPunch', 'CHealth',
    'CTeleporterCable', 'CTeleportMainframe', 'CZipLine', 'CTurret', 'CLunarLanderStation',
    'CCentrifuge', 'CIceSlide', 'CFlinger', 'CTVScreen', 'CProjectorScreen', 'CTutorialPickup',
]
COMPONENT_NAMES = {iw_hash(name): name for name in _COMPONENT_NAMES}
MARKER_CATEGORIES = [
    # Gameplay functions first: a perk machine is a perk even though it is also interactable.
    ('perk', {'CPerk'}),
    ('pack_a_punch', {'CPackAPunch'}),
    ('mystery_box', {'CMysteryBox'}),
    ('door', {'CDoor'}),
    ('power', {'CPowerSwitch'}),
    ('trap', {'CTrap', 'CTrapSwitch'}),
    ('wall_buy', {'CWeaponChalkOutline'}),
    ('barricade', {'CBarricade'}),
    ('teleporter', {'CTeleporter', 'CTeleportPointGersch', 'CTeleporterCable',
                    'CTeleportMainframe'}),
    ('easter_egg', {'CEasterEgg'}),
    ('ride', {'CZipLine', 'CFlinger', 'CIceSlide', 'CCentrifuge', 'CLunarLanderStation'}),
    ('spawn', {'CSpawnPoint'}),
    ('effect', {'CIsRenderableGFXEmitter', 'CFogEffect'}),
    ('interact', {'CPOI'}),
    ('trigger', {'CSnowTrigger'}),
    ('sound', {'CSoundEmitter'}),
    ('jump', {'CPlayerJumpPoint'}),
    ('locator', {'CLocator', 'CIsNavMeshTarget', 'CLighthouseTarget'}),
    ('camera', {'CIsCamera'}),
    ('ai', {'CAIControllerZombie', 'CAIControllerHellhound', 'CAIControllerMonkey',
            'CAIControllerRomero', 'CAITutor'}),
    ('collision', {'CIsCollisionBox', 'CIsCollisionSphere', 'CIsCollisionCapsule',
                   'CIsCollisionCompound'}),
]
COLLISION_BOX = iw_hash('CIsCollisionBox')
COLLISION_SPHERE = iw_hash('CIsCollisionSphere')
COLLISION_CAPSULE = iw_hash('CIsCollisionCapsule')
POI = iw_hash('CPOI')
_FLOAT = iw_hash('float')
AREA = iw_hash('CArea')
# Reference fields between entities. Field names were recovered by hashing the game's strings
# (the reflection export misses them). Values are IwHashString of a CIsNamed name, except
# m_AreasUnlock, which holds CArea resource names.
POWERED = ('CPerk', 'CDoor', 'CPackAPunch', 'CTrapSwitch', 'CTeleporter', 'CTVScreen',
           'CProjectorScreen', 'CTurret', 'CTeleportMainframe')
LINK_FIELDS = {  # (component, field) -> (link kind, is a list)
    **{(component, 'powerSwitch'): ('power', False) for component in POWERED},
    ('CTrapSwitch', 'traps'): ('trap', True),
    ('CDoor', 'm_Siblings'): ('sibling', True),
    ('CDoor', 'm_AreasUnlock'): ('unlocks', True),
}
AREA_FIELDS = ('m_SpawnPoints', 'm_PerkMachines', 'm_GerschTeleportPoints', 'm_Shortcuts',
               'm_Locators')
FUNCTION_CATEGORIES = {'perk', 'pack_a_punch', 'mystery_box', 'door', 'power', 'trap', 'wall_buy',
                       'barricade', 'teleporter', 'easter_egg', 'ride'}
_PERK_STINGS = {'jugganog': 'Juggernog', 'revive': 'Quick Revive', 'doubletap': 'Double Tap',
                'speed': 'Speed Cola', 'mule': 'Mule Kick', 'stamin': 'Stamin-Up',
                'phd': 'PhD Flopper', 'deadshot': 'Deadshot', 'electric': 'Electric Cherry',
                'widows': "Widow's Wine"}
_NAMES: dict[int, str] | None = None
_LINK_COMPONENTS = {iw_hash(name): name for name in POWERED}
_LINK_FIELD_NAMES = {iw_hash(name): name for name in
                     ('powerSwitch', 'traps', 'm_Siblings', 'm_AreasUnlock', *AREA_FIELDS)}


def _names() -> dict[int, str]:
    """The optional local name dictionary (``bozkit names``), for readable hashes."""
    global _NAMES
    if _NAMES is None:
        _NAMES = {}
        try:
            for line in (Path.home() / '.cache' / 'bozkit' / 'names.txt').read_text(
                    errors='ignore').split():
                _NAMES.setdefault(iw_hash(line), line)
        except OSError:
            pass
    return _NAMES


def to_blender(value):
    """Rotate BOZ's right-handed Y-up coordinates into Blender's Z-up basis."""
    x, y, z = value
    return (x, -z, y)


def from_blender(value):
    """Rotate Blender Z-up coordinates back into BOZ's native Y-up basis."""
    x, y, z = value
    return (x, z, -y)


def scale_to_blender(value):
    """Per-axis scale follows the axis permutation (sign-free)."""
    x, y, z = value
    return (x, z, y)


def scale_from_blender(value):
    x, y, z = value
    return (x, z, y)


def uv_to_blender(value):
    """Native UVs follow GL: v = 0 is the first stored texel row. Blender's v = 0 is the bottom
    row of an upright image, and imported images are uploaded upright, so v is mirrored."""
    u, v = value
    return (u, 1.0 - v)


def uv_from_blender(value):
    u, v = value
    return (u, 1.0 - v)


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
    uvs: list[tuple[float, float]] = field(default_factory=list)  # native convention
    face_materials: list[int] = field(default_factory=list)
    front_sector: str = ''
    back_sector: str = ''
    material_names: list[str] = field(default_factory=list)
    location: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotation: tuple[float, float, float, float] = IDENTITY_ROTATION  # xyzw
    instance_resource_hash: int | None = None
    instance_resource_index: int | None = None
    material_hashes: list[int] = field(default_factory=list)
    vertex_colours: list[tuple[int, int, int, int]] = field(default_factory=list)
    uvs2: list[tuple[float, float]] = field(default_factory=list)  # native convention
    scale: tuple[float, float, float] = UNIT_SCALE
    instance_source_group: str = ''
    instance_path: tuple[int, ...] = ()
    key: str = ''
    parent_key: str = ''
    mesh_key: str = ''
    group_name: str = ''
    collision_triangles: list[int] = field(default_factory=list)  # original triangle indices
    category: str = ''  # entity markers, badges and shape roles
    components: list[str] = field(default_factory=list)
    description: str = ''
    shape: str = ''  # 'box', 'sphere', 'capsule' or 'reach' for shape helpers
    shape_component: int = -1  # index of the shape's component in its entity spec node
    link_id: int = 0  # the hash other entities use to reference this one (0: not referable)
    links: list[dict] = field(default_factory=list)  # {component, field, kind, list, targets}


@dataclass
class SceneImport:
    source_group: str
    meshes: list[SceneMesh] = field(default_factory=list)
    materials: dict[int, SceneMaterial] = field(default_factory=dict)
    textures: dict[int, SceneTexture] = field(default_factory=dict)
    preserved: int = 0
    source_groups: list[str] = field(default_factory=list)
    reference_groups: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


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

    @property
    def blend_mode(self) -> int:
        """Framebuffer blend, flags bits 16-18 (0/5 opaque, 1/4 alpha, 2 additive, 3 inverse)."""
        return (self.flags >> 16) & 7

    @property
    def stage1_mode(self) -> int:
        """Texture stage 1 environment, flags bits 19-21 (0x4a2b74fc): 0 modulate, 1 decal,
        2 add, 3 replace, 4 GL_BLEND, 5 modulate x2, 6 modulate x4."""
        return (self.flags >> 19) & 7

    @property
    def lightmap(self) -> int:
        """The stage-1 texture (a baked lightmap atlas in shipped maps), or 0."""
        return self.texture_hashes[1] if len(self.texture_hashes) > 1 else 0


@dataclass
class SceneEdit:
    kind: str
    class_hash: int
    resource_hash: int
    resource_index: int
    vertices: list[tuple[float, float, float]]
    faces: list[tuple[int, int, int]]
    edges: list[tuple[int, int]] = field(default_factory=list)
    uvs: list[tuple[float, float]] = field(default_factory=list)  # native convention
    face_materials: list[int] = field(default_factory=list)
    front_sector: str = ''
    back_sector: str = ''
    location: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotation: tuple[float, float, float, float] = IDENTITY_ROTATION
    instance_resource_hash: int | None = None
    instance_resource_index: int | None = None
    uvs2: list[tuple[float, float]] = field(default_factory=list)  # native convention
    scale: tuple[float, float, float] = UNIT_SCALE
    source_group: str = ''
    instance_source_group: str = ''
    instance_path: tuple[int, ...] = ()
    collision_triangles: list[int] = field(default_factory=list)
    shape: str = ''
    shape_component: int = -1
    links: list[dict] = field(default_factory=list)
    # A new entity copied in the editor: {'id', 'group', 'index', 'hash', 'root_path', 'path'}.
    # root_path is the copied node in the source entity spec, path the node within the copy.
    copy: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ExportReport:
    edited: int
    preserved: int
    written: tuple[str, ...] = ()
    navmesh: str = ''  # what happened to the navmesh, for the status line
    added: int = 0     # entities created by copies
    removed: int = 0   # entities deleted


def _identity(item: group.Resource) -> int:
    return item.name_hash if item.name_hash is not None else item.in_group_hash


def _triangles(indices: list[int]) -> list[tuple[int, int, int]]:
    return [tuple(indices[index:index + 3]) for index in range(0, len(indices), 3)]


def _group_name(path: str) -> str:
    name = Path(path).name
    return name[:-len('.group.bin')] if name.endswith('.group.bin') else Path(path).stem


def _model_materials(body: bytes, known: set[int]) -> list[int]:
    """Decode the terminal CIwModel material-reference array, validated against known materials."""
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


def _transform_blob(spec: resources.EntitySpec):
    return next((component.blob for component in spec.components
                 if component.blob and component.blob.class_hash == TRANSFORM), None)


def _model_reference(spec: resources.EntitySpec) -> int | None:
    """The single CIwModel a renderable spec draws, or None."""
    for component in spec.components:
        blob = component.blob
        if not blob or blob.class_hash != RENDERABLE_MODEL:
            continue
        assets = _property(blob, ASSETS)
        if assets is None or not assets.elements:
            return None
        hashes = set()
        for asset in assets.elements:
            if asset.class_hash != RENDERABLE_ASSET:
                continue
            prop = _property(asset, MODEL_REFERENCE)
            value = reflect.typed_value(prop) if prop else None
            if isinstance(value, int):
                hashes.add(value)
        return hashes.pop() if len(hashes) == 1 else None
    return None


def _local_transform(spec: resources.EntitySpec):
    """Native (position, xyzw rotation, scale) of a spec; absent fields are the identity."""
    blob = _transform_blob(spec)
    values = {LOCAL_POSITION: (0.0, 0.0, 0.0), LOCAL_ROTATION: IDENTITY_ROTATION,
              LOCAL_SCALE: UNIT_SCALE}
    if blob is not None:
        for name_hash, default in list(values.items()):
            prop = _property(blob, name_hash)
            value = reflect.typed_value(prop) if prop else None
            if isinstance(value, list) and len(value) == len(default):
                values[name_hash] = tuple(value)
    return values[LOCAL_POSITION], values[LOCAL_ROTATION], values[LOCAL_SCALE]


def _placed_model(spec: resources.EntitySpec):
    """Return (model hash, native position, native xyzw quaternion) for a renderable entity."""
    if _transform_blob(spec) is None:
        return None
    model_hash = _model_reference(spec)
    if model_hash is None:
        return None
    position, rotation, _ = _local_transform(spec)
    return model_hash, position, rotation


def _spec_at(spec: resources.EntitySpec, path: tuple[int, ...]) -> resources.EntitySpec:
    for index in path:
        if index >= len(spec.children):
            raise ValueError('entity child path no longer exists')
        spec = spec.children[index][2]
    return spec


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


def _same_rotation(a, b) -> bool:
    # q and -q are the same rotation; Blender may hand back either sign.
    return _close(a, b) or _close(a, tuple(-value for value in b))


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


class _Groups:
    """Parsed groups with per-class resource indices and cross-group lookups by identity."""

    def __init__(self, editable: list[str], reference: list[str]):
        self.paths = editable + [path for path in reference if path not in editable]
        self.parsed = {path: group.parse(Path(path).read_bytes()) for path in self.paths}
        self.by_class: dict[int, dict[int, tuple[str, int, group.Resource]]] = {}
        for path in self.paths:  # editable groups first: they win identity collisions
            for class_hash, index, item in self.resources(path):
                self.by_class.setdefault(class_hash, {}).setdefault(_identity(item),
                                                                    (path, index, item))

    def resources(self, path: str):
        indices: dict[int, int] = {}
        for resource_type in self.parsed[path].types():
            for item in resource_type.resources:
                index = indices.get(resource_type.class_hash, 0)
                indices[resource_type.class_hash] = index + 1
                yield resource_type.class_hash, index, item

    def find(self, class_hash: int, identity: int):
        return self.by_class.get(class_hash, {}).get(identity)


def import_group(path: str | Path, *, include_models: bool = True,
                 include_collision: bool = True, include_portals: bool = True,
                 include_navigation: bool = True) -> SceneImport:
    """Decode every supported editable resource in one self-contained group."""
    return import_groups([path], include_models=include_models,
                         include_collision=include_collision, include_portals=include_portals,
                         include_navigation=include_navigation)


def import_groups(paths, reference_paths=(), *, include_models: bool = False,
                  include_collision: bool = True, include_portals: bool = True,
                  include_navigation: bool = True, attach_collision: bool = True) -> SceneImport:
    """Decode the editable resources of several groups, resolving references across all of them.

    *paths* are imported as editable content. *reference_paths* (for example the shared
    ``ingame`` group) only supply models, materials and textures that the editable groups
    reference; their own entities are not imported. Unsupported and malformed resources are
    counted as preserved and stay byte-identical on export. Anything that cannot be resolved is
    reported in ``warnings`` rather than dropped silently.
    """
    editable = [str(Path(path).resolve()) for path in paths]
    reference = [str(Path(path).resolve()) for path in reference_paths]
    groups = _Groups(editable, reference)
    result = SceneImport(editable[0] if editable else '', source_groups=editable,
                         reference_groups=[path for path in reference if path not in editable])
    material_ids = set(groups.by_class.get(MATERIAL, {}))
    models_cache: dict[int, native.Model] = {}

    def model(identity: int) -> native.Model:
        if identity not in models_cache:
            models_cache[identity] = native.decode_model(groups.find(MODEL, identity)[2].body)
        return models_cache[identity]

    # Every model placed by any editable entity, so it is not duplicated as a local asset.
    unresolved_models: dict[int, int] = {}
    entity_specs = []
    placed_models = set()
    for path in editable:
        for class_hash, index, item in groups.resources(path):
            if class_hash != ENTITY_SPEC:
                continue
            try:
                spec = resources.decode_entity_spec(item.body)
            except (ValueError, struct.error):
                continue
            entity_specs.append((path, index, item, spec))
            stack = [spec]
            while stack:
                node = stack.pop()
                reference_hash = _model_reference(node)
                if reference_hash is not None:
                    placed_models.add(reference_hash)
                    if not groups.find(MODEL, reference_hash):
                        unresolved_models[reference_hash] = (
                            unresolved_models.get(reference_hash, 0) + 1)
                stack.extend(child for _, _, child in node.children)

    def placed_tree(path, index, item, spec):
        """Objects for every renderable node of one entity tree, parents before children."""
        name = _group_name(path)
        entity_hash = _identity(item)

        def visit(node, node_path, parent_key):
            position, rotation, scale = _local_transform(node)
            key = f'{path}|{index}|{"/".join(map(str, node_path))}'
            suffix = ''.join(f'.{value}' for value in node_path)
            reference_hash = _model_reference(node)
            found = groups.find(MODEL, reference_hash) if reference_hash is not None else None
            common = dict(location=to_blender(position), rotation=rotation_to_blender(rotation),
                          scale=scale_to_blender(scale), instance_resource_hash=entity_hash,
                          instance_resource_index=index, instance_source_group=path,
                          instance_path=node_path, key=key, parent_key=parent_key,
                          group_name=name)
            names = _component_names(node)
            category = _category(names)
            label, description = _describe(node, category)
            own_name = _blob_value(_component(node, 'CIsNamed'), 'name', None)
            link_info = dict(link_id=iw_hash(own_name) if isinstance(own_name, str) else 0,
                             links=_node_links(node))
            if found is not None:
                model_path, model_index, model_item = found
                decoded = model(reference_hash)
                functional = category in FUNCTION_CATEGORIES
                result.meshes.append(SceneMesh(
                    'placed_model', MODEL, reference_hash, model_index, model_path,
                    f'{name}:{label if functional else "placed"} {entity_hash:08x}{suffix}',
                    f'{name} Placed Models',
                    [to_blender(tuple(map(float, vertex))) for vertex in decoded.vertices],
                    list(decoded.triangles), uvs=decoded.uvs,
                    face_materials=decoded.face_materials,
                    material_hashes=_model_materials(model_item.body, material_ids),
                    vertex_colours=decoded.vertex_colours, uvs2=decoded.uvs2,
                    mesh_key=f'{model_path}|{reference_hash:08x}',
                    category=category if functional else '', components=names,
                    description=description if functional else '', **link_info, **common))
                if functional:
                    # A locked badge on the model shows what it does; it moves with the model.
                    owner = result.meshes[-1]
                    top = max((vertex[2] for vertex in owner.vertices), default=0.0)
                    inverse = tuple(1.0 / value if value else 1.0 for value in owner.scale)
                    result.meshes.append(SceneMesh(
                        'badge', ENTITY_SPEC, entity_hash, index, path, f'{owner.display_name} badge',
                        f'{name} Markers', category=category, components=names,
                        description=description, key=f'{key}|badge', parent_key=key,
                        group_name=name, mesh_key='boz-badge',
                        location=(0.0, 0.0, top + 30.0 * inverse[2]), scale=inverse))
            else:
                result.meshes.append(SceneMesh(
                    'entity', ENTITY_SPEC, entity_hash, index, path,
                    f'{name}:{label} {entity_hash:08x}{suffix}', f'{name} Markers',
                    category=category, components=names, description=description,
                    mesh_key='boz-badge', **link_info, **common))
            owner = next(item for item in reversed(result.meshes) if item.key == key)
            result.meshes.extend(_shapes(node, owner))
            for child_index, (_, _, child) in enumerate(node.children):
                visit(child, node_path + (child_index,), key)

        visit(spec, (), '')

    collision_ids = set()
    for path in editable:
        name = _group_name(path)
        for class_hash, resource_index, item in groups.resources(path):
            resource_hash = _identity(item)
            label = f'{resource_hash:08x}'
            if class_hash == MODEL:
                if include_models and resource_hash not in placed_models:
                    decoded = native.decode_model(item.body)
                    result.meshes.append(SceneMesh(
                        'model', MODEL, resource_hash, resource_index, path,
                        f'{name}:model_{label}', f'{name} Local Asset Models',
                        [to_blender(tuple(map(float, vertex))) for vertex in decoded.vertices],
                        list(decoded.triangles), uvs=decoded.uvs,
                        face_materials=decoded.face_materials,
                        material_hashes=_model_materials(item.body, material_ids),
                        vertex_colours=decoded.vertex_colours, uvs2=decoded.uvs2,
                        key=f'{path}|model|{resource_index}', group_name=name,
                        mesh_key=f'{path}|{resource_hash:08x}'))
                else:
                    result.preserved += 1
            elif include_portals and class_hash == PORTAL:
                portal = map_resources.decode_portal(item.body)
                faces = [(0, index, index + 1) for index in range(1, len(portal.vertices) - 1)]
                result.meshes.append(SceneMesh(
                    'portal', PORTAL, resource_hash, resource_index, path, f'{name}:portal_{label}',
                    f'{name} Portals', [to_blender(vertex) for vertex in portal.vertices], faces,
                    front_sector=portal.front_sector, back_sector=portal.back_sector,
                    key=f'{path}|portal|{resource_index}', group_name=name))
            elif include_collision and class_hash == ENTITY_SPEC:
                try:
                    spec, component = _collision_spec(item)
                except (ValueError, struct.error):
                    result.preserved += 1
                    continue
                # Collision vertices are in the entity's local space, like placed models.
                position, rotation, scale = _local_transform(spec)
                collision_ids.add((path, resource_index))
                mesh = collision.decode(component.extra)
                result.meshes.append(SceneMesh(
                    'collision', ENTITY_SPEC, resource_hash, resource_index, path,
                    f'{name}:collision_{label}', f'{name} Collision',
                    [to_blender(vertex) for vertex in mesh.vertices], _triangles(mesh.indices),
                    face_materials=list(mesh.materials), material_names=mesh.material_names,
                    location=to_blender(position), rotation=rotation_to_blender(rotation),
                    scale=scale_to_blender(scale), instance_resource_hash=resource_hash,
                    instance_resource_index=resource_index, instance_source_group=path,
                    key=f'{path}|collision|{resource_index}', group_name=name))
            elif include_navigation and class_hash == NAVMESH:
                try:
                    result.meshes.append(navmesh_meshes(path, item, resource_index, name))
                except (ValueError, struct.error):
                    result.preserved += 1
            elif include_navigation and class_hash == NAV_CONNECTION:
                connection = navigation.decode_connection(item.body)
                result.meshes.append(SceneMesh(
                    'navigation_connection', NAV_CONNECTION, resource_hash, resource_index,
                    path, f'{name}:navigation_connection_{label}', f'{name} Navigation',
                    [to_blender(connection.start), to_blender(connection.end)], [], [(0, 1)],
                    key=f'{path}|navigation|{resource_index}', group_name=name))
            elif class_hash != ENTITY_SPEC:
                result.preserved += 1
    for path, index, item, spec in entity_specs:
        if (path, index) not in collision_ids:
            placed_tree(path, index, item, spec)
    if attach_collision:
        _attach_collision(result)
    _import_areas(result, groups, editable)
    if unresolved_models:
        result.warnings.append(
            f'{sum(unresolved_models.values())} placement(s) use a model that is not in the loaded '
            'game files; skipped')

    referenced_materials = {value for mesh in result.meshes for value in mesh.material_hashes}
    referenced_textures = set()
    missing_materials = 0
    for material_hash in sorted(referenced_materials):
        found = groups.find(MATERIAL, material_hash)
        if found is None:
            missing_materials += 1
            continue
        try:
            material = native.decode_material(found[2].body)
        except (ValueError, struct.error):
            continue
        texture_hashes = list(material.textures)
        diffuse = tuple(material.colours[0]) if material.colours else (255, 255, 255, 255)
        scene_material = SceneMaterial(material_hash, texture_hashes, diffuse, material.flags)
        result.materials[material_hash] = scene_material
        referenced_textures.update(value for value in texture_hashes[:2] if value)
    missing_textures = undecodable = 0
    for texture_hash in sorted(referenced_textures):
        found = groups.find(TEXTURE, texture_hash)
        if found is None:
            missing_textures += 1
            continue
        try:
            texture = native.decode_texture_rgba(found[2].body)
        except (ValueError, struct.error):
            undecodable += 1
            continue
        result.textures[texture_hash] = SceneTexture(texture_hash, texture.width, texture.height,
                                                     texture.rgba, texture.format,
                                                     struct.unpack_from('<I', found[2].body)[0])
    if missing_materials:
        result.warnings.append(f'{missing_materials} materials are in groups that were not loaded')
    if missing_textures:
        result.warnings.append(f'{missing_textures} textures are in groups that were not loaded')
    if undecodable:
        result.warnings.append(f'{undecodable} textures use a layout bozkit cannot decode yet')
    return result


def _component_names(node: resources.EntitySpec) -> list[str]:
    return [COMPONENT_NAMES.get(component.type_hash, f'{component.type_hash:08x}')
            for component in node.components]


def _category(names: list[str]) -> str:
    present = set(names)
    return next((category for category, members in MARKER_CATEGORIES if present & members),
                'entity')


def _blob_value(blob, name, default):
    prop = _property(blob, iw_hash(name)) if blob else None
    value = reflect.typed_value(prop) if prop else None
    return default if value is None else value


def _component(node, name):
    return next((component.blob for component in node.components
                 if component.type_hash == iw_hash(name)), None)


def _describe(node: resources.EntitySpec, category: str) -> tuple[str, str]:
    """A short label and a one-line description of what an entity does."""
    names = _names()

    def value(component, field, default=None):
        result = _blob_value(_component(node, component), field, default)
        return names.get(result, result) if isinstance(result, int) and not isinstance(
            result, bool) else result

    def raw_string(component, field_hash):
        blob = _component(node, component)
        prop = next((p for p in blob.properties if p.name_hash == field_hash), None) if blob else None
        return reflect.typed_value(prop) if prop else None

    named = value('CIsNamed', 'name')
    needs_power = ', linked to the power switch' if any(value(c, 'powerSwitch') for c in (
        'CPerk', 'CDoor', 'CPackAPunch', 'CTrapSwitch', 'CTeleporter')) else ''
    if category == 'perk':
        sting = raw_string('CPerk', 0xc836045c) or ''
        perk = next((label for key, label in _PERK_STINGS.items() if key in sting), 'Perk')
        label = f'{perk} perk'
        details = f'{perk} perk machine, {value("CPerk", "m_perkSinglePCost", "?")} points{needs_power}'
    elif category == 'pack_a_punch':
        label = 'Pack-a-Punch'
        details = f'Pack-a-Punch, {value("CPackAPunch", "m_Cost", "?")} points{needs_power}'
    elif category == 'mystery_box':
        label = 'Mystery box'
        details = (f'Mystery box location, {value("CMysteryBox", "m_Cost", "?")} points '
                   '(the game picks the active one)')
    elif category == 'door':
        label = f'Door {value("CDoor", "m_Cost", "")}'.strip()
        details = f'Buyable door or debris, {value("CDoor", "m_Cost", "?")} points{needs_power}'
    elif category == 'power':
        label, details = 'Power switch', 'Power switch: turns on everything that needs power'
    elif category == 'trap':
        if _component(node, 'CTrapSwitch'):
            label = 'Trap switch'
            details = f'Trap switch, {value("CTrapSwitch", "m_Cost", "?")} points{needs_power}'
        else:
            label = 'Trap'
            details = (f'Trap: active {value("CTrap", "m_ActivePeriodMS", 0) // 1000} s, cooldown '
                       f'{value("CTrap", "m_CoolDownPeriodMS", 0) // 1000} s, '
                       f'{value("CTrap", "m_PlayerDamage", "?")} player damage')
    elif category == 'wall_buy':
        kind = value('CWeaponChalkOutline', 'm_weaponType', 'weapon')
        cost = value('CWeaponChalkOutline', 'm_cost', None) or value('CWeaponChalkOutline',
                                                                     'm_Cost', '?')
        label, details = f'Wall buy {cost}', f'Wall buy ({kind}), {cost} points'
    elif category == 'barricade':
        label, details = 'Barricade', 'Window barricade zombies tear down and players rebuild'
    elif category == 'teleporter':
        label, details = 'Teleporter', f'Teleporter part{needs_power}'
    elif category == 'easter_egg':
        sound = raw_string('CEasterEgg', 0xc0c5b1df)
        label = 'Easter egg'
        details = f'Easter egg (shoot or knife it){", plays " + sound if sound else ""}'
    elif category == 'ride':
        label = details = 'Ride or launcher'
    elif category == 'spawn':
        if isinstance(named, str) and named.lower().startswith('spawn_player'):
            label = details = f'Player spawn {named.rsplit("_", 1)[-1]}'
        else:
            kind = value('CSpawnPoint', 'spawnType', 'zombie')
            label, details = f'Zombie spawn ({kind})', f'Zombie spawn point, type {kind}'
    elif category == 'effect':
        emitter = value('CIsRenderableGFXEmitter', 'emitterSpec', None)
        fog = ' with fog' if _component(node, 'CFogEffect') else ''
        label = 'Effect'
        details = f'Particle effect{fog}{f" ({emitter})" if isinstance(emitter, str) else ""}'
    elif category == 'interact':
        label, details = 'Interact point', 'Interaction point (press to use)'
    elif category == 'trigger':
        label, details = 'Trigger', 'Trigger volume'
    elif category == 'sound':
        sound = value('CSoundEmitter', 'soundName', None)
        label = 'Sound'
        details = f'Sound emitter{f" ({sound})" if isinstance(sound, str) else ""}'
    elif category == 'jump':
        label, details = 'Jump point', 'Window or barricade jump point for zombies'
    elif category == 'locator':
        label, details = 'Locator', 'Target or locator point used by scripts'
    elif category == 'camera':
        label, details = 'Camera', 'Camera'
    elif category == 'ai':
        label, details = 'AI character', 'Placed AI character'
    elif category == 'collision':
        label, details = 'Collision', 'Collision-only entity'
    else:
        label, details = 'Entity', 'Entity (groups or positions other entities)'
    if isinstance(named, str) and named not in label and named != 'model':
        label = f'{label} "{named}"'
    return label, details


def _u32_values(raw: bytes, is_list: bool = True) -> list[int] | None:
    """A counted u32 list (std::list<unsigned int>), or a single u32 when not *is_list*."""
    if not is_list:
        return [struct.unpack('<I', raw)[0]] if len(raw) == 4 else None
    if len(raw) >= 4:
        count = struct.unpack_from('<I', raw)[0]
        if 4 + count * 4 == len(raw):
            return list(struct.unpack_from(f'<{count}I', raw, 4))
    return None


def _node_links(node: resources.EntitySpec) -> list[dict]:
    links = []
    for number, component in enumerate(node.components):
        name = COMPONENT_NAMES.get(component.type_hash) or _LINK_COMPONENTS.get(component.type_hash)
        if not component.blob or not name:
            continue
        for prop in component.blob.properties:
            spec = LINK_FIELDS.get((name, _LINK_FIELD_NAMES.get(prop.name_hash, '')))
            values = _u32_values(prop.raw, spec[1]) if spec else None
            if values is None:
                continue
            links.append({'component': number, 'field': _LINK_FIELD_NAMES[prop.name_hash],
                          'kind': spec[0], 'list': spec[1],
                          'targets': values if spec[1] else [v for v in values if v]})
    return links


def _write_links(blobs, links) -> bool:
    """Write link targets into reflected blobs ({component index or -1: blob}); returns changed."""
    changed = False
    for link in links:
        blob = blobs.get(link['component'])
        if blob is None:
            raise ValueError('linked component no longer exists; re-import')
        prop = _property(blob, iw_hash(link['field']))
        targets = [int(value) for value in link['targets']]
        if link['list']:
            raw = struct.pack(f'<I{len(targets)}I', len(targets), *targets)
        else:
            if len(targets) > 1:
                raise ValueError(f'{link["field"]} links to one entity only')
            raw = struct.pack('<I', targets[0] if targets else 0)
        if prop is None:
            if not targets:
                continue
            type_name = 'std::list<unsigned int>' if link['list'] else 'unsigned int'
            prop = reflect.Property(blob.class_hash, iw_hash(type_name), iw_hash(link['field']), b'')
            blob.properties.append(prop)
        if prop.raw != raw:
            prop.raw, prop.nested, prop.elements = raw, None, None
            changed = True
    return changed


def _shape_geometry(shape: str):
    """Unit helper meshes (Blender basis), all triangles: a cube and sphere of radius 1, a capsule
    of radius 1 whose straight part spans z -1..1, and a disc of radius 1 in the ground plane."""
    if shape == 'box':
        vertices = [(x, y, z) for x in (-1.0, 1.0) for y in (-1.0, 1.0) for z in (-1.0, 1.0)]
        quads = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
        return vertices, [(a, b, c) for a, b, c, d in quads] + [(a, c, d) for a, b, c, d in quads], []
    segments = 16
    ring = [(math.cos(2 * math.pi * i / segments), math.sin(2 * math.pi * i / segments))
            for i in range(segments)]
    if shape == 'reach':
        vertices = [(0.0, 0.0, 0.0)] + [(x, y, 0.0) for x, y in ring]
        return vertices, [(0, 1 + i, 1 + (i + 1) % segments) for i in range(segments)], []
    rings = 8
    vertices, faces = [(0.0, 0.0, -1.0)], []
    for level in range(1, rings):
        phi = math.pi * level / rings - math.pi / 2
        z = math.sin(phi)
        if shape == 'capsule':
            z += 1.0 if z > 0 else -1.0
        if shape == 'capsule' and level == rings // 2:
            # the straight part: a lower and an upper equator
            vertices += [(x, y, -1.0) for x, y in ring]
            z = 1.0
        vertices += [(math.cos(phi) * x, math.cos(phi) * y, z) for x, y in ring]
    vertices.append((0.0, 0.0, 1.0))
    top = len(vertices) - 1
    count = (len(vertices) - 2) // segments
    faces += [(0, 1 + (i + 1) % segments, 1 + i) for i in range(segments)]
    for band in range(count - 1):
        a, b = 1 + band * segments, 1 + (band + 1) * segments
        for i in range(segments):
            j = (i + 1) % segments
            faces += [(a + i, a + j, b + j), (a + i, b + j, b + i)]
    last = 1 + (count - 1) * segments
    faces += [(last + i, last + (i + 1) % segments, top) for i in range(segments)]
    return vertices, faces, []


def _shapes(node: resources.EntitySpec, parent: SceneMesh) -> list[SceneMesh]:
    """Editable helpers for a node's collision shapes and its interaction reach."""
    result = []
    for number, component in enumerate(node.components):
        blob = component.blob
        ghost = bool(_blob_value(blob, 'm_Ghost', False))
        if component.type_hash == COLLISION_BOX:
            half = _blob_value(blob, 'm_halfAxis', [0.0, 0.0, 0.0])
            centre = _blob_value(blob, 'm_Offset', None) or _blob_value(blob, 'm_boxCentre',
                                                                         [0.0, 0.0, 0.0])
            shape, location, scale = 'box', to_blender(centre), scale_to_blender(half)
        elif component.type_hash == COLLISION_SPHERE:
            radius = _blob_value(blob, 'm_Radius', 0.0)
            shape, location, scale = 'sphere', (0.0, 0.0, 0.0), (radius,) * 3
        elif component.type_hash == COLLISION_CAPSULE:
            radius = _blob_value(blob, 'm_Radius', 0.0)
            half_height = _blob_value(blob, 'm_height', 0.0) / 2
            shape, location, scale = 'capsule', (0.0, 0.0, 0.0), (radius, radius, half_height)
        elif component.type_hash == POI:
            reach = _blob_value(blob, 'm_MaxDistance', 0.0)
            height = _blob_value(blob, 'm_HeightOffset', 0.0)
            shape, location, scale = 'reach', (0.0, 0.0, height), (reach, reach, 1.0)
        else:
            continue
        vertices, faces, edges = _shape_geometry(shape)
        result.append(SceneMesh(
            'shape', ENTITY_SPEC, parent.instance_resource_hash, parent.instance_resource_index,
            parent.instance_source_group, f'{parent.display_name} {shape}',
            f'{parent.group_name} Shapes', vertices, faces, edges, location=location,
            scale=tuple(scale), instance_resource_hash=parent.instance_resource_hash,
            instance_resource_index=parent.instance_resource_index,
            instance_source_group=parent.instance_source_group,
            instance_path=parent.instance_path, key=f'{parent.key}|shape|{number}',
            parent_key=parent.key, group_name=parent.group_name, shape=shape,
            shape_component=number, mesh_key=f'boz-shape|{shape}',
            category='reach' if shape == 'reach' else ('ghost' if ghost else 'solid')))
    return result


def _set_float(blob, name, value):
    prop = _property(blob, iw_hash(name))
    if prop is None:
        prop = reflect.Property(blob.class_hash, _FLOAT, iw_hash(name), b'')
        blob.properties.append(prop)
    reflect.set_typed_value(prop, float(value))


def _set_vec3(blob, name, value):
    prop = _property(blob, iw_hash(name))
    if prop is None:
        prop = reflect.Property(blob.class_hash, _VEC3, iw_hash(name), b'')
        blob.properties.append(prop)
    reflect.set_typed_value(prop, tuple(float(v) for v in value))


def _apply_shape(node: resources.EntitySpec, edit: SceneEdit) -> bool:
    """Write a shape helper's transform back into its component; returns whether it changed."""
    if not 0 <= edit.shape_component < len(node.components):
        raise ValueError('shape component no longer exists; re-import')
    blob = node.components[edit.shape_component].blob
    if blob is None:
        raise ValueError('shape component has no properties')
    if not _same_rotation(edit.rotation, IDENTITY_ROTATION):
        raise ValueError(f'{edit.shape} shapes cannot be rotated relative to their entity')
    scale = [abs(value) for value in edit.scale]
    before = reflect.encode(blob)
    if edit.shape == 'box':
        old_centre = _blob_value(blob, 'm_Offset', None) or _blob_value(blob, 'm_boxCentre',
                                                                         [0.0, 0.0, 0.0])
        old_half = _blob_value(blob, 'm_halfAxis', [0.0, 0.0, 0.0])
        centre, half = from_blender(edit.location), scale_from_blender(scale)
        if not _close(half, old_half):
            _set_vec3(blob, 'm_halfAxis', half)
        if not _close(centre, old_centre):
            name = 'm_boxCentre' if _property(blob, iw_hash('m_boxCentre')) else 'm_Offset'
            _set_vec3(blob, name, centre)
    else:
        if not _close(edit.location[:2], (0.0, 0.0)) or (
                edit.shape != 'reach' and not _close(edit.location[2:], (0.0,))):
            raise ValueError(f'{edit.shape} shapes stay centred on their entity; move the entity')
        if edit.shape == 'sphere':
            if not _close((scale[0], scale[1]), (scale[2], scale[2])):
                raise ValueError('collision spheres must be scaled uniformly')
            if not _close((scale[0],), (_blob_value(blob, 'm_Radius', 0.0),)):
                _set_float(blob, 'm_Radius', scale[0])
        elif edit.shape == 'capsule':
            if not _close((scale[0],), (scale[1],)):
                raise ValueError('capsule radius must be the same on both horizontal axes')
            if not _close((scale[0],), (_blob_value(blob, 'm_Radius', 0.0),)):
                _set_float(blob, 'm_Radius', scale[0])
            if not _close((scale[2] * 2,), (_blob_value(blob, 'm_height', 0.0),)):
                _set_float(blob, 'm_height', scale[2] * 2)
        elif edit.shape == 'reach':
            if not _close((scale[0],), (scale[1],)):
                raise ValueError('interaction reach must be a circle (equal X and Y scale)')
            if not _close((scale[0],), (_blob_value(blob, 'm_MaxDistance', 0.0),)):
                _set_float(blob, 'm_MaxDistance', scale[0])
            if not _close(edit.location[2:], (_blob_value(blob, 'm_HeightOffset', 0.0),)):
                _set_float(blob, 'm_HeightOffset', edit.location[2])
        else:
            raise ValueError(f'unknown shape {edit.shape!r}')
    return reflect.encode(blob) != before


def _rotate(q, v):
    x, y, z, w = q
    return ((1 - 2 * (y * y + z * z)) * v[0] + 2 * (x * y - z * w) * v[1] + 2 * (x * z + y * w) * v[2],
            2 * (x * y + z * w) * v[0] + (1 - 2 * (x * x + z * z)) * v[1] + 2 * (y * z - x * w) * v[2],
            2 * (x * z - y * w) * v[0] + 2 * (y * z + x * w) * v[1] + (1 - 2 * (x * x + y * y)) * v[2])


def _to_world(chain, vertex):
    """Apply object transforms (Blender basis, innermost first) to a local vertex."""
    for location, rotation, scale in chain:
        vertex = _rotate(rotation, tuple(vertex[i] * scale[i] for i in range(3)))
        vertex = tuple(vertex[i] + location[i] for i in range(3))
    return vertex


def _to_local(chain, vertex):
    for location, rotation, scale in reversed(chain):
        inverse = (-rotation[0], -rotation[1], -rotation[2], rotation[3])
        vertex = _rotate(inverse, tuple(vertex[i] - location[i] for i in range(3)))
        vertex = tuple(vertex[i] / scale[i] if scale[i] else 0.0 for i in range(3))
    return vertex


def _chains(meshes):
    by_key = {mesh.key: mesh for mesh in meshes if mesh.key}

    def chain(mesh):
        result, current = [], mesh
        while current is not None:
            result.append((current.location, current.rotation, current.scale))
            current = by_key.get(current.parent_key) if current.parent_key else None
        return result
    return chain


ATTACH_TOLERANCE = 1.0  # world units; collision was cooked from the render vertices


def _import_areas(result: SceneImport, groups, editable) -> None:
    """Areas (zones) as objects at the centre of their members, carrying their member lists.

    An area's name is the name of the visibility sector with the same hash."""
    sector_names = {}
    for mesh in result.meshes:
        if mesh.kind == 'portal':
            for name in (mesh.front_sector, mesh.back_sector):
                sector_names[iw_hash(name)] = name
    chain = _chains(result.meshes)
    by_link = {}
    for mesh in result.meshes:
        if mesh.link_id and mesh.kind in ('entity', 'placed_model'):
            by_link.setdefault(mesh.link_id, mesh)
    for path in editable:
        group_name = _group_name(path)
        for class_hash, index, item in groups.resources(path):
            if class_hash != AREA:
                continue
            blob = resources.decode_reflected(item.body)
            if blob is None:
                continue
            identity = _identity(item)
            links = []
            for prop in blob.properties:
                field_name = _LINK_FIELD_NAMES.get(prop.name_hash)
                values = _u32_values(prop.raw)
                if field_name in AREA_FIELDS and values is not None:
                    links.append({'component': -1, 'field': field_name, 'kind': 'member',
                                  'list': True, 'targets': values})
            members = [by_link[target] for link in links for target in link['targets']
                       if target in by_link]
            points = [_to_world(chain(member), (0.0, 0.0, 0.0)) for member in members]
            centre = tuple(sum(point[i] for point in points) / len(points) for i in range(3)) \
                if points else (0.0, 0.0, 0.0)
            name = sector_names.get(identity) or _names().get(identity) or f'{identity:08x}'
            result.meshes.append(SceneMesh(
                'area', AREA, identity, index, path, f'{group_name}:Area {name}',
                f'{group_name} Markers', location=centre, key=f'{path}|area|{index}',
                group_name=group_name, category='area', link_id=identity, links=links,
                description=f'Area (zone) {name}: {len(members)} linked spawns, perks and points',
                mesh_key='boz-badge'))


def _attach_collision(result: SceneImport) -> None:
    """Split world collision into pieces owned by the placed models it was built from.

    A collision triangle belongs to a placed model when all three of its vertices coincide with
    vertices of that model (and of no other). In Kino this holds for 82% of the triangles. Each
    piece becomes a child of its model, so transforming the model carries its collision; the rest
    stays in the collision object. Export stitches everything back by original triangle index.
    """
    chain = _chains(result.meshes)
    placed = [mesh for mesh in result.meshes if mesh.kind == 'placed_model']
    index: dict[tuple[int, int, int], list[tuple[int, tuple]]] = {}
    for number, mesh in enumerate(placed):
        transforms = chain(mesh)
        for vertex in mesh.vertices:
            world = _to_world(transforms, vertex)
            index.setdefault(tuple(round(value) for value in world), []).append((number, world))

    def owners(point):
        found = set()
        base = tuple(round(value) for value in point)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    for number, world in index.get((base[0] + dx, base[1] + dy, base[2] + dz), ()):
                        if sum((world[i] - point[i]) ** 2 for i in range(3)) < ATTACH_TOLERANCE ** 2:
                            found.add(number)
        return found

    pieces = []
    for mesh in [mesh for mesh in result.meshes if mesh.kind == 'collision']:
        transforms = chain(mesh)
        world = [_to_world(transforms, vertex) for vertex in mesh.vertices]
        vertex_owners = [owners(point) for point in world] if index else [set()] * len(world)
        groups: dict[int | None, list[int]] = {}
        for triangle, face in enumerate(mesh.faces):
            common = vertex_owners[face[0]] & vertex_owners[face[1]] & vertex_owners[face[2]]
            groups.setdefault(next(iter(common)) if len(common) == 1 else None, []).append(triangle)

        def subset(triangles, convert):
            remap, vertices, faces = {}, [], []
            for triangle in triangles:
                corners = []
                for vertex in mesh.faces[triangle]:
                    if vertex not in remap:
                        remap[vertex] = len(vertices)
                        vertices.append(convert(vertex))
                    corners.append(remap[vertex])
                faces.append(tuple(corners))
            materials = [mesh.face_materials[triangle] for triangle in triangles]
            return vertices, faces, materials

        for number, triangles in groups.items():
            if number is None:
                continue
            owner = placed[number]
            owner_chain = chain(owner)
            vertices, faces, materials = subset(
                triangles, lambda vertex: _to_local(owner_chain, world[vertex]))
            pieces.append(SceneMesh(
                'collision_piece', mesh.class_hash, mesh.resource_hash, mesh.resource_index,
                mesh.source_group, f'{owner.display_name} collision', mesh.collection, vertices,
                faces, face_materials=materials, material_names=mesh.material_names,
                key=f'{mesh.key}|piece|{owner.key}', parent_key=owner.key,
                group_name=mesh.group_name, collision_triangles=triangles))
        leftover = groups.get(None, [])
        mesh.vertices, mesh.faces, mesh.face_materials = subset(
            leftover, lambda vertex: mesh.vertices[vertex])
        mesh.collision_triangles = leftover
    result.meshes.extend(pieces)


def _assemble_collision(mesh: collision.CollisionMesh, edits, entity_transform,
                        dropped=frozenset()) -> bool:
    """Rebuild a collision mesh from the objects holding its triangles; returns whether it changed.

    Positions are native and local to the collision entity. Triangle order, count and indices are
    kept; a vertex whose corners now disagree (a moved piece next to a still one) is split.
    """
    count = len(mesh.indices) // 3
    corners: list[tuple | None] = [None] * count
    materials = bytearray(mesh.materials)
    added = []  # (corners, material) of triangles from copied pieces
    for edit in edits:
        if edit.copy:
            location, rotation, scale = entity_transform
            local = [from_blender(_to_local([(location, rotation, scale)], vertex))
                     for vertex in edit.vertices]
            for number, face in enumerate(edit.faces):
                material = edit.face_materials[number] if edit.face_materials else 0
                added.append((tuple(local[vertex] for vertex in face), material))
            continue
        if edit.kind == 'collision_piece':
            location, rotation, scale = entity_transform
            local = [from_blender(_to_local([(location, rotation, scale)], vertex))
                     for vertex in edit.vertices]
        else:
            local = [from_blender(tuple(map(float, vertex))) for vertex in edit.vertices]
        triangles = edit.collision_triangles or list(range(len(edit.faces)))
        if len(triangles) != len(edit.faces):
            raise ValueError('collision faces no longer match their native triangles; re-import')
        if edit.face_materials and len(edit.face_materials) != len(edit.faces):
            raise ValueError('collision requires one material assignment per face')
        for number, (triangle, face) in enumerate(zip(triangles, edit.faces)):
            if not 0 <= triangle < count or corners[triangle] is not None:
                raise ValueError('collision triangles are duplicated or unknown; re-import')
            corners[triangle] = tuple(local[vertex] for vertex in face)
            if edit.face_materials:
                value = edit.face_materials[number]
                if not 0 <= value <= 255:
                    raise ValueError('collision material indices must fit in one byte')
                materials[triangle] = value
    missing = [index for index, corner in enumerate(corners) if corner is None]
    if any(index not in dropped for index in missing):
        raise ValueError('collision triangles are missing (a collision object was deleted); '
                         're-import the level')
    vertices = list(mesh.vertices)
    indices = list(mesh.indices)
    placed: dict[int, tuple] = {}
    splits: dict[tuple[int, tuple], int] = {}
    for triangle in range(count):
        if corners[triangle] is None:
            continue
        for corner in range(3):
            slot = triangle * 3 + corner
            original = mesh.indices[slot]
            position = corners[triangle][corner]
            if _close(position, mesh.vertices[original], 1e-2):
                position = mesh.vertices[original]
            if original not in placed:
                placed[original] = position
                vertices[original] = position
            elif placed[original] != position:
                key = (original, position)
                if key not in splits:
                    splits[key] = len(vertices)
                    vertices.append(position)
                indices[slot] = splits[key]
    if dropped:
        kept = [triangle for triangle in range(count) if corners[triangle] is not None]
        indices = [indices[triangle * 3 + corner] for triangle in kept for corner in range(3)]
        materials = bytearray(materials[triangle] for triangle in kept)
    for triangle, material in added:
        for position in triangle:
            indices.append(len(vertices))
            vertices.append(position)
        materials.append(material)
    if vertices == mesh.vertices and indices == mesh.indices and bytes(materials) == mesh.materials:
        return False
    mesh.vertices, mesh.indices, mesh.materials = vertices, indices, bytes(materials)
    return True


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
    if edit.kind in ('entity', 'shape', 'badge', 'area', 'navmesh'):
        return
    if edit.kind == 'collision' and edit.collision_triangles == [] and not edit.faces:
        return  # every triangle of this collision lives in attached pieces
    if not edit.vertices or (not edit.faces and edit.kind != 'navigation_connection'):
        raise ValueError(f'{edit.kind} {edit.resource_hash:#010x} has no geometry')
    if any(len(face) != 3 for face in edit.faces):
        raise ValueError(f'{edit.kind} {edit.resource_hash:#010x} contains a non-triangle face')
    if any(index < 0 or index >= len(edit.vertices) for face in edit.faces for index in face):
        raise ValueError(f'{edit.kind} {edit.resource_hash:#010x} has an invalid vertex index')
    for uvs in (edit.uvs, edit.uvs2):
        if uvs and len(uvs) != len(edit.vertices):
            raise ValueError(f'{edit.kind} {edit.resource_hash:#010x} UV count does not match '
                             'vertices')


def _set_transform(spec: resources.EntitySpec, position, rotation, scale) -> bool:
    """Write a native local transform into a spec; returns whether any value changed."""
    blob = _transform_blob(spec)
    current = _local_transform(spec)
    wanted = {LOCAL_POSITION: (position, current[0]), LOCAL_ROTATION: (rotation, current[1]),
              LOCAL_SCALE: (scale, current[2])}
    changed = False
    for name_hash, (value, old) in wanted.items():
        same = _same_rotation(value, old) if name_hash == LOCAL_ROTATION else _close(value, old)
        if same:
            continue
        if blob is None:
            raise ValueError('entity has no CIsTransform component to move')
        prop = _property(blob, name_hash)
        if prop is None:
            # Reflection reads properties by name, so an absent default can be added.
            prop = reflect.Property(TRANSFORM, _TRANSFORM_FIELDS[name_hash], name_hash, b'')
            blob.properties.append(prop)
        reflect.set_typed_value(prop, tuple(value))
        changed = True
    return changed


def _model_edit_key(edit: SceneEdit):
    return (tuple(edit.vertices), tuple(edit.faces), tuple(edit.uvs), tuple(edit.uvs2),
            tuple(edit.face_materials))


NAVMESH = iw_hash('CIsNavMesh')
DOOR = iw_hash('CDoor')


def _native_apply(chain, point):
    """Apply native (position, xyzw rotation, scale) transforms, innermost first."""
    for position, rotation, scale in chain:
        point = _rotate(rotation, tuple(point[i] * scale[i] for i in range(3)))
        point = tuple(point[i] + position[i] for i in range(3))
    return point


_BOX_FACES = [(0, 2, 1), (1, 2, 3), (4, 5, 6), (5, 7, 6), (0, 1, 4), (1, 5, 4),
              (2, 6, 3), (3, 6, 7), (0, 4, 2), (2, 4, 6), (1, 3, 5), (3, 7, 5)]


def navmesh_input(parsed: dict[str, group.Group]):
    """The navmesh build input of a level: collision meshes plus solid entity collision boxes,
    leaving out doors (the navmesh runs under doors; their tags gate it). Metres, the game's
    Y-up axes and triangle winding."""
    vertices, triangles = [], []
    # Order by file name so a mod's copy of a group lines up with the game's original.
    for path in sorted(parsed, key=lambda value: (Path(value).name.lower(), value)):
        for resource_type in parsed[path].types():
            if resource_type.class_hash != ENTITY_SPEC:
                continue
            for item in resource_type.resources:
                try:
                    spec = resources.decode_entity_spec(item.body)
                except (ValueError, struct.error):
                    continue
                meshes = [c for c in spec.components if c.class_hash == resources.COLLISION_MESH_SPEC]
                if len(meshes) == 1:
                    chain = [_local_transform(spec)]
                    mesh = collision.decode(meshes[0].extra)
                    base = len(vertices)
                    vertices += [tuple(v / 100 for v in _native_apply(chain, vertex))
                                 for vertex in mesh.vertices]
                    triangles += [(base + mesh.indices[i], base + mesh.indices[i + 1],
                                   base + mesh.indices[i + 2]) for i in range(0, len(mesh.indices), 3)]
                    continue
                stack = [(spec, [], False)]
                while stack:
                    node, parents, in_door = stack.pop()
                    chain = [_local_transform(node)] + parents
                    door = in_door or any(c.type_hash == DOOR for c in node.components)
                    for component in node.components:
                        blob = component.blob
                        if component.type_hash != COLLISION_BOX or door or \
                                _blob_value(blob, 'm_Ghost', False):
                            continue
                        half = _blob_value(blob, 'm_halfAxis', [0.0, 0.0, 0.0])
                        centre = _blob_value(blob, 'm_Offset', None) or _blob_value(
                            blob, 'm_boxCentre', [0.0, 0.0, 0.0])
                        base = len(vertices)
                        for corner in range(8):
                            local = tuple(centre[i] + (half[i] if corner >> i & 1 else -half[i])
                                          for i in range(3))
                            vertices.append(tuple(v / 100 for v in _native_apply(chain, local)))
                        # outward-facing counter-clockwise, then swapped into the game's winding
                        triangles += [(base + a, base + c, base + b) for a, b, c in _BOX_FACES]
                    stack.extend((child, chain, door) for _, _, child in node.children)
    return vertices, triangles


NAV_SLOTS = ('walkable', 'door', 'jump', 'tagged')


def navmesh_meshes(path: str, item: group.Resource, index: int, group_name: str) -> SceneMesh:
    """A display mesh of a navmesh: enabled polygons by tag (slots NAV_SLOTS) and its off-mesh
    links as loose edges. Disabled polygons (flags 0) are left out."""
    mesh = navigation.decode(item.body)
    vertices, faces, materials, edges = [], [], [], []
    keys: dict[tuple, int] = {}

    def vertex(point):
        key = tuple(round(value, 4) for value in point)
        if key not in keys:
            keys[key] = len(vertices)
            vertices.append(to_blender(tuple(value * 100 for value in point)))
        return keys[key]

    for tile in mesh.tiles:
        decoded = navigation.decode_tile(tile.data)
        for poly, triangle in decoded.triangles():
            if not poly.flags:
                continue
            corners = tuple(vertex(point) for point in triangle)
            if len(set(corners)) < 3:
                continue
            faces.append(corners)
            materials.append(1 if poly.flags & 0x2 else 2 if poly.flags & 0x4000 else
                             3 if poly.extra or poly.flags & ~0x1 else 0)
        for start, end, *_ in decoded.off_mesh:
            edges.append((vertex(start), vertex(end)))
    return SceneMesh('navmesh', NAVMESH, _identity(item), index, path, f'{group_name}:Navmesh',
                     f'{group_name} Navigation', vertices, faces, edges, face_materials=materials,
                     material_names=list(NAV_SLOTS), key=f'{path}|navmesh|{index}',
                     group_name=group_name,
                     description='Walkable areas (blue), door-gated floor (orange), jump areas '
                                 '(white), other tagged floor (violet), window crossings and '
                                 'climbs (lines)')


def _dirty_boxes(before, after):
    """XZ boxes (metres) around navmesh input triangles that were added, removed or moved.

    Triangles are compared as geometry (a multiset of rounded corner sets), so inserting or
    deleting triangles anywhere marks only those triangles, not everything after them."""
    def keyed(data):
        vertices, triangles = data
        result = {}
        for triangle in triangles:
            corners = tuple(sorted(tuple(round(value, 3) for value in vertices[i]) for i in triangle))
            result[corners] = result.get(corners, 0) + 1
        return result
    old, new = keyed(before), keyed(after)
    boxes = []
    for corners in set(old) | set(new):
        if old.get(corners, 0) == new.get(corners, 0):
            continue
        boxes.append((min(p[0] for p in corners), min(p[2] for p in corners),
                      max(p[0] for p in corners), max(p[2] for p in corners)))
    merged = []
    for box in sorted(boxes):
        for index, other in enumerate(merged):
            if (box[0] <= other[2] + 0.5 and box[2] >= other[0] - 0.5 and
                    box[1] <= other[3] + 0.5 and box[3] >= other[1] - 0.5):
                merged[index] = (min(other[0], box[0]), min(other[1], box[1]),
                                 max(other[2], box[2]), max(other[3], box[3]))
                break
        else:
            merged.append(box)
    return merged


def _update_navmesh(parsed: dict[str, group.Group], base_folder: Path, changed: set) -> str:
    """Rebuild the level's navmesh from the game's original: every tile whose input differs from
    the game's files is rebuilt, so repeated saves and stale mod copies converge."""
    names = {path.name.lower(): path for path in base_folder.glob('*.group.bin')}
    level = {path: value for path, value in parsed.items() if Path(path).name.lower() in names}
    navmesh = None
    for path, value in level.items():
        for resource_type in value.types():
            if resource_type.class_hash == NAVMESH:
                for index, item in enumerate(resource_type.resources):
                    navmesh = (path, index, item)
    if navmesh is None:
        return ''
    originals = {str(path): group.parse(path.read_bytes()) for path in names.values()}
    base_body = None
    for value in originals.values():
        for resource_type in value.types():
            if resource_type.class_hash == NAVMESH:
                base_body = resource_type.resources[navmesh[1]].body
    if base_body is None:
        return ''
    vertices, triangles = navmesh_input(level)
    dirty = _dirty_boxes(navmesh_input(originals), (vertices, triangles))
    try:
        body, report = navbuild.rebuild(base_body, vertices, triangles, dirty=dirty)
    except FileNotFoundError:
        return 'navmesh NOT rebuilt: the boz-navmesh helper is missing'
    if body != navmesh[2].body:
        navmesh[2].body = body
        changed.add((navmesh[0], NAVMESH, navmesh[1]))
    if not dirty:
        return 'navmesh matches the game' if body == base_body else ''
    kept = f', {report.reachable} kept for window links' if report.reachable else ''
    return f'navmesh: {report.tiles} tiles rebuilt{kept}'


def _entity_nodes(parsed):
    """(path, resource type, item, root spec, node path, node) for every entity spec node."""
    for path, value in parsed.items():
        for resource_type in value.types():
            if resource_type.class_hash != ENTITY_SPEC:
                continue
            for item in resource_type.resources:
                try:
                    root = resources.decode_entity_spec(item.body)
                except (ValueError, struct.error):
                    continue
                stack = [((), root)]
                while stack:
                    node_path, node = stack.pop()
                    yield path, resource_type, item, root, node_path, node
                    stack.extend((node_path + (index,), child)
                                 for index, (_, _, child) in enumerate(node.children))


def _name_prop(node):
    blob = _component(node, 'CIsNamed')
    return _property(blob, iw_hash('name')) if blob else None


def _areas(parsed):
    for path, value in parsed.items():
        for resource_type in value.types():
            if resource_type.class_hash == AREA:
                for item in resource_type.resources:
                    blob = resources.decode_reflected(item.body)
                    if blob is not None:
                        yield path, item, blob


def _apply_copies(parsed, copies, resource, changed) -> int:
    """Create the copied entities: a new spec resource for a copied top-level entity, a new
    child for a copied child entity. Names unique in the level get a free _2, _3... suffix and
    the copy joins every area the original belongs to."""
    if not copies:
        return 0
    counts: dict[str, int] = {}
    for _, _, _, _, _, node in _entity_nodes(parsed):
        prop = _name_prop(node)
        value = reflect.typed_value(prop) if prop else None
        if isinstance(value, str):
            counts[value.lower()] = counts.get(value.lower(), 0) + 1
    taken = set(counts)
    renames = []
    created = 0
    for copy_id, edits in copies.items():
        info = edits[0].copy
        source = str(Path(info['group']).resolve())
        item = resource(source, ENTITY_SPEC, info['index'], info['hash'], 'copied entity')
        root = resources.decode_entity_spec(item.body)
        root_path = tuple(info['root_path'])
        node = _spec_at(root, root_path)
        clone = resources.decode_entity_spec(resources.encode_entity_spec(node))
        for edit in edits:
            target = _spec_at(clone, tuple(edit.copy.get('path', ())))
            if edit.kind == 'shape':
                _apply_shape(target, edit)
                continue
            _set_transform(target, from_blender(edit.location), rotation_from_blender(edit.rotation),
                           scale_from_blender(edit.scale))
            if edit.links:
                _write_links({n: c.blob for n, c in enumerate(target.components)}, edit.links)
        stack = [clone]
        while stack:
            current = stack.pop()
            stack.extend(child for _, _, child in current.children)
            prop = _name_prop(current)
            name = reflect.typed_value(prop) if prop else None
            if not isinstance(name, str) or counts.get(name.lower(), 0) != 1:
                continue  # generic names (shared by several entities) stay as they are
            number = 2
            while f'{name}_{number}'.lower() in taken:
                number += 1
            new_name = f'{name}_{number}'
            taken.add(new_name.lower())
            reflect.set_typed_value(prop, new_name)
            renames.append((iw_hash(name), iw_hash(new_name)))
        resource_type = next(t for t in parsed[source].types()
                             if t.class_hash == ENTITY_SPEC and any(r is item for r in t.resources))
        if root_path:
            parent = _spec_at(root, root_path[:-1])
            class_hash, reserved, _ = parent.children[root_path[-1]]
            parent.children.append((class_hash, reserved, clone))
            item.body = resources.encode_entity_spec(root)
            changed.add((source, ENTITY_SPEC, info['index']))
        else:
            existing = {_identity(other) for other in resource_type.resources}
            number = 1
            while iw_hash(f'boz_copy_{info["hash"]:08x}_{number}') in existing:
                number += 1
            identity = iw_hash(f'boz_copy_{info["hash"]:08x}_{number}')
            resource_type.resources.append(group.Resource(
                None if resource_type.names_omitted else identity, identity,
                resources.encode_entity_spec(clone)))
            changed.add((source, ENTITY_SPEC, -1))
        created += 1
    lookup = dict(renames)
    for path, item, blob in _areas(parsed):
        dirty = False
        for prop in blob.properties:
            if _LINK_FIELD_NAMES.get(prop.name_hash) not in AREA_FIELDS:
                continue
            values = _u32_values(prop.raw) or []
            extra = [lookup[value] for value in values if value in lookup]
            if extra:
                values = values + extra
                prop.raw = struct.pack(f'<I{len(values)}I', len(values), *values)
                dirty = True
        if dirty:
            item.body = resources.encode_reflected(blob)
            changed.add((path, AREA, -1))
    return created


def _apply_deletions(parsed, deletions, resource, changed) -> int:
    if not deletions:
        return 0
    targets = []
    for deletion in deletions:
        source = str(Path(deletion['group']).resolve())
        item = resource(source, ENTITY_SPEC, deletion['index'], deletion['hash'], 'deleted entity')
        targets.append((source, item, tuple(deletion.get('path', ()))))
    # Names going away, and the nodes that go with them.
    doomed_names, doomed_nodes = set(), set()
    for source, item, path in targets:
        root = resources.decode_entity_spec(item.body)
        stack = [(path, _spec_at(root, path))]
        while stack:
            node_path, node = stack.pop()
            doomed_nodes.add((id(item), node_path))
            prop = _name_prop(node)
            name = reflect.typed_value(prop) if prop else None
            if isinstance(name, str):
                doomed_names.add(iw_hash(name))
            stack.extend((node_path + (index,), child) for index, (_, _, child) in
                         enumerate(node.children))
    for _, _, item, _, node_path, node in _entity_nodes(parsed):
        if (id(item), node_path) in doomed_nodes:
            continue
        for link in _node_links(node):
            if link['kind'] != 'member' and doomed_names & set(link['targets']):
                prop = _name_prop(node)
                who = reflect.typed_value(prop) if prop else f'{_identity(item):08x}'
                raise ValueError(f'cannot delete: {who} still has a {link["field"]} link to it; '
                                 'remove that link first')
    for path, item, blob in _areas(parsed):
        dirty = False
        for prop in blob.properties:
            if _LINK_FIELD_NAMES.get(prop.name_hash) not in AREA_FIELDS:
                continue
            values = _u32_values(prop.raw) or []
            kept = [value for value in values if value not in doomed_names]
            if len(kept) != len(values):
                prop.raw = struct.pack(f'<I{len(kept)}I', len(kept), *kept)
                dirty = True
        if dirty:
            item.body = resources.encode_reflected(blob)
            changed.add((path, AREA, -1))
    # Children first, deepest and last-index first, so remaining paths stay valid.
    by_item: dict[int, list] = {}
    for source, item, path in targets:
        by_item.setdefault(id(item), [source, item, []])[2].append(path)
    for source, item, paths in by_item.values():
        if () in paths:
            for resource_type in parsed[source].types():
                if any(other is item for other in resource_type.resources):
                    resource_type.resources[:] = [r for r in resource_type.resources if r is not item]
            changed.add((source, ENTITY_SPEC, -1))
            continue
        root = resources.decode_entity_spec(item.body)
        for path in sorted(paths, key=lambda value: (-len(value), [-v for v in value])):
            _spec_at(root, path[:-1]).children.pop(path[-1])
        item.body = resources.encode_entity_spec(root)
        changed.add((source, ENTITY_SPEC, -1))
    return len(targets)


def export_groups(edits: list[SceneEdit], outputs: dict[str | Path, str | Path], *,
                  write_unchanged: bool = False,
                  replaceable: str | Path | None = None,
                  level_folder: str | Path | None = None,
                  force_navmesh: bool = False,
                  deletions=()) -> ExportReport:
    """Patch edits into copies of their source groups.

    Edits with ``copy`` create new entities; *deletions* ({'group', 'index', 'hash', 'path',
    'collision': [{'group', 'index', 'hash', 'triangles'}]}) remove entities and their collision
    triangles. Deleting an entity that power, trap, door or area-unlock links still reference is
    refused; area memberships are removed.

    *outputs* maps each source group to the file it is written to. Sources are never overwritten,
    except files inside *replaceable* (a mod's own asset folder, whose groups were written by an
    earlier export). Only groups with changes are written unless *write_unchanged* is set.
    Instances sharing one model must carry identical geometry.
    """
    targets = {str(Path(source).resolve()): Path(output).resolve()
               for source, output in outputs.items()}
    own = Path(replaceable).resolve() if replaceable else None
    for source, output in targets.items():
        if own is not None and output.is_relative_to(own):
            continue
        if Path(source) == output or output in {Path(path) for path in targets}:
            raise ValueError('a source group is never overwritten; choose a new output path')
    if len(set(targets.values())) != len(targets):
        raise ValueError('two source groups would be written to the same output file')
    parsed: dict[str, group.Group] = {}
    resources_by_id = {}
    totals = {}

    def load(path: str):
        if path not in targets:
            raise ValueError(f'edit refers to a group that is not being exported: {path}')
        if path not in parsed:
            parsed[path] = group.parse(Path(path).read_bytes())
            indices: dict[int, int] = {}
            total = 0
            for resource_type in parsed[path].types():
                for item in resource_type.resources:
                    total += 1
                    index = indices.get(resource_type.class_hash, 0)
                    indices[resource_type.class_hash] = index + 1
                    resources_by_id[(path, resource_type.class_hash, index)] = item
            totals[path] = total

    def resource(path: str, class_hash: int, index: int, identity: int | None, label: str):
        load(path)
        item = resources_by_id.get((path, class_hash, index))
        if item is None:
            raise ValueError(f'source {label} {identity or 0:#010x} no longer exists')
        if identity is not None and _identity(item) != identity:
            raise ValueError(f'source {label} identity changed at index {index}')
        return item

    default_source = next(iter(targets)) if len(targets) == 1 else ''
    changed = set()
    seen = set()
    model_edits = {}
    collision_edits: dict[tuple, list[SceneEdit]] = {}
    shape_edits: list[SceneEdit] = []
    area_edits: list[SceneEdit] = []
    link_edits: list[SceneEdit] = []
    entity_specs = {}
    transforms = {}
    copies: dict[str, list[SceneEdit]] = {}
    dropped: dict[tuple, set[int]] = {}
    for deletion in deletions:
        for piece in deletion.get('collision', ()):
            key = (str(Path(piece['group']).resolve()), ENTITY_SPEC, piece['index'])
            dropped.setdefault(key, set()).update(piece['triangles'])
    for edit in edits:
        _validate_edit(edit)
        if edit.copy and edit.kind in ('placed_model', 'entity', 'shape'):
            copies.setdefault(edit.copy['id'], []).append(edit)
            if edit.kind == 'placed_model':
                key = (str(Path(edit.source_group).resolve()), MODEL, edit.resource_index)
                if key in model_edits and _model_edit_key(model_edits[key]) != _model_edit_key(edit):
                    raise ValueError(f'instances of shared model {edit.resource_hash:#010x} have '
                                     'different geometry; edit the shared mesh once')
                model_edits.setdefault(key, edit)
            continue
        if edit.copy and edit.kind == 'badge':
            continue
        source = str(Path(edit.source_group).resolve()) if edit.source_group else default_source
        if not source:
            raise ValueError('edit has no source group')
        key = (source, edit.class_hash, edit.resource_index)
        # Collision edits made before transforms were imported carry no instance; they are
        # vertex-only edits of an identity-transform entity.
        if edit.kind in ('placed_model', 'entity') or (
                edit.kind == 'collision' and edit.instance_resource_index is not None):
            instance_source = (str(Path(edit.instance_source_group).resolve())
                               if edit.instance_source_group else source)
            if edit.instance_resource_index is None or edit.instance_resource_hash is None:
                raise ValueError('placed model entity resource no longer exists')
            instance = (instance_source, ENTITY_SPEC, edit.instance_resource_index,
                        tuple(edit.instance_path))
            if instance in transforms:
                raise ValueError(f'duplicate edit for entity {edit.instance_resource_hash:#010x}')
            transforms[instance] = edit
        if edit.kind in ('entity', 'placed_model') and edit.links:
            link_edits.append(edit)
        if edit.kind == 'entity':
            continue
        if edit.kind == 'placed_model' or (edit.kind == 'model' and edit.class_hash == MODEL):
            if key in model_edits:
                if _model_edit_key(model_edits[key]) != _model_edit_key(edit):
                    raise ValueError(f'instances of shared model {edit.resource_hash:#010x} have '
                                     'different geometry; edit the shared mesh once')
                continue
            model_edits[key] = edit
            continue
        if edit.kind in ('collision', 'collision_piece') and edit.class_hash == ENTITY_SPEC:
            collision_edits.setdefault(key, []).append(edit)
            continue
        if edit.kind == 'shape':
            shape_edits.append(edit)
            continue
        if edit.kind in ('badge', 'navmesh'):
            continue  # display only (a navmesh is rebuilt from collision when saving)
        if edit.kind == 'area':
            area_edits.append(edit)
            continue
        if key in seen:
            raise ValueError(f'duplicate edit for resource {edit.resource_hash:#010x}')
        seen.add(key)
        item = resource(source, edit.class_hash, edit.resource_index, edit.resource_hash,
                        'resource')
        if edit.kind == 'portal' and edit.class_hash == PORTAL:
            portal = map_resources.decode_portal(item.body)
            if ((portal.front_sector and not edit.front_sector) or
                    (portal.back_sector and not edit.back_sector)):
                raise ValueError(f'portal {edit.resource_hash:#010x} lost a sector name')
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
        changed.add(key)

    for key, group_edits in collision_edits.items():
        source, class_hash, index = key
        main = [edit for edit in group_edits if edit.kind == 'collision']
        if len(main) > 1:
            raise ValueError(f'duplicate edit for collision {group_edits[0].resource_hash:#010x}')
        item = resource(source, ENTITY_SPEC, index, group_edits[0].resource_hash, 'collision')
        spec, component = _collision_spec(item)
        mesh = collision.decode(component.extra)
        if main:
            entity_transform = (main[0].location, main[0].rotation, main[0].scale)
        else:
            position, rotation, scale = _local_transform(spec)
            entity_transform = (to_blender(position), rotation_to_blender(rotation),
                                scale_to_blender(scale))
        if _assemble_collision(mesh, group_edits, entity_transform, dropped.get(key, frozenset())):
            component.extra = collision.encode(mesh)
            item.body = resources.encode_entity_spec(spec)
            changed.add(key)

    for key, edit in model_edits.items():
        source, class_hash, index = key
        item = resource(source, MODEL, index, edit.resource_hash, 'model')
        old = native.decode_model(item.body)
        vertices = [tuple(round(value) for value in from_blender(vertex))
                    for vertex in edit.vertices]
        vertices = _reconcile_model_positions(old, vertices)
        model = native.Model(vertices, list(edit.faces), edit.uvs or old.uvs,
                             face_materials=edit.face_materials, uvs2=edit.uvs2)
        if (model.vertices != old.vertices or model.triangles != old.triangles or
                model.uvs != old.uvs or (model.uvs2 and model.uvs2 != old.uvs2)):
            item.body = native.encode_model(model, item.body)
            changed.add(key)

    for (source, class_hash, index, path), edit in transforms.items():
        entity_key = (source, ENTITY_SPEC, index)
        if entity_key not in entity_specs:
            item = resource(source, ENTITY_SPEC, index, edit.instance_resource_hash, 'entity')
            entity_specs[entity_key] = (item, resources.decode_entity_spec(item.body), [False])
        item, root, dirty = entity_specs[entity_key]
        node = _spec_at(root, path)
        if edit.kind == 'placed_model' and _model_reference(node) != edit.resource_hash:
            raise ValueError('placed model reference changed')
        if _set_transform(node, from_blender(edit.location), rotation_from_blender(edit.rotation),
                          scale_from_blender(edit.scale)):
            dirty[0] = True
    for edit in shape_edits:
        source = (str(Path(edit.instance_source_group).resolve())
                  if edit.instance_source_group else default_source)
        entity_key = (source, ENTITY_SPEC, edit.instance_resource_index)
        if entity_key not in entity_specs:
            item = resource(source, ENTITY_SPEC, edit.instance_resource_index,
                            edit.instance_resource_hash, 'entity')
            entity_specs[entity_key] = (item, resources.decode_entity_spec(item.body), [False])
        item, root, dirty = entity_specs[entity_key]
        if _apply_shape(_spec_at(root, tuple(edit.instance_path)), edit):
            dirty[0] = True
    for edit in link_edits:
        source = (str(Path(edit.instance_source_group).resolve())
                  if edit.instance_source_group else default_source)
        entity_key = (source, ENTITY_SPEC, edit.instance_resource_index)
        if entity_key not in entity_specs:
            item = resource(source, ENTITY_SPEC, edit.instance_resource_index,
                            edit.instance_resource_hash, 'entity')
            entity_specs[entity_key] = (item, resources.decode_entity_spec(item.body), [False])
        item, root, dirty = entity_specs[entity_key]
        node = _spec_at(root, tuple(edit.instance_path))
        blobs = {number: component.blob for number, component in enumerate(node.components)}
        if _write_links(blobs, edit.links):
            dirty[0] = True
    for edit in area_edits:
        source = str(Path(edit.source_group).resolve()) if edit.source_group else default_source
        item = resource(source, AREA, edit.resource_index, edit.resource_hash, 'area')
        blob = resources.decode_reflected(item.body)
        if blob is None:
            raise ValueError('area resource is not a reflected resource')
        if _write_links({-1: blob}, edit.links):
            item.body = resources.encode_reflected(blob)
            changed.add((source, AREA, edit.resource_index))
    for entity_key, (item, root, dirty) in entity_specs.items():
        if dirty[0]:
            item.body = resources.encode_entity_spec(root)
            changed.add(entity_key)

    added = removed = 0
    if copies or deletions:
        for source in targets:
            load(source)
        added = _apply_copies(parsed, copies, resource, changed)
        removed = _apply_deletions(parsed, deletions, resource, changed)

    navmesh_note = ''
    if level_folder is None and targets:
        # Without a level folder, the folder of the group that holds the navmesh is the level.
        level_folder = next((Path(path).parent for path in targets
                             if path.endswith('_statics.group.bin')), None)
    if level_folder is not None and (changed or force_navmesh):
        for source in targets:
            load(source)
        navmesh_note = _update_navmesh(parsed, Path(level_folder).resolve(), changed)
    written = []
    for source, output in targets.items():
        group_changed = any(key[0] == source for key in changed)
        if not group_changed and not write_unchanged:
            continue
        if source not in parsed:
            load(source)
        output.parent.mkdir(parents=True, exist_ok=True)
        # Write then rename, so replacing a mod's earlier export never leaves a partial file.
        temporary = output.with_name(output.name + '.tmp')
        temporary.write_bytes(group.encode(parsed[source]))
        temporary.replace(output)
        written.append(str(output))
    total = sum(totals.values())
    return ExportReport(len(changed), total - len(changed), tuple(written), navmesh_note,
                        added, removed)


def export_group(source: str | Path, output: str | Path,
                 edits: list[SceneEdit]) -> ExportReport:
    """Patch edited Blender meshes into a copy of one source group (always written)."""
    source_path = str(Path(source).resolve())
    for edit in edits:
        for path in (edit.source_group, edit.instance_source_group):
            if path and str(Path(path).resolve()) != source_path:
                raise ValueError('the scene contains resources from several groups; export them '
                                 'as a level instead')
    return export_groups(edits, {source_path: output}, write_unchanged=True)


def _overlay_index(folder: Path) -> dict[str, Path]:
    """Groups a mod overrides, by lower-case file name (the client also matches by name)."""
    if not folder.is_dir():
        return {}
    return {path.name.lower(): path for path in sorted(folder.rglob('*.group.bin'))}


def level_groups(directory: str | Path,
                 mod_assets: str | Path | None = None) -> tuple[list[Path], list[Path]]:
    """The groups of one level folder and the shared reference groups the level uses.

    A level folder (``levels/kino``) holds the level's own groups. Placed objects also use the
    shared ``ingame`` group and the level's weapon groups (wall-buy displays use
    ``weapons_<level>``, their materials ``weapon_projectiles_<level>`` textures), found as
    ``ingame/ingame.group.bin`` and ``ingame/weapons/*_<level>.group.bin`` in an extracted pack
    root above the folder.
    """
    root = Path(directory).resolve()
    editable = sorted(root.glob('*.group.bin'))
    if not editable:
        raise ValueError(f'no .group.bin files in {root}')
    references = []
    for parent in [root, *root.parents]:
        candidate = parent / 'ingame' / 'ingame.group.bin'
        if candidate.is_file():
            references.append(candidate)
            references.extend(sorted((parent / 'ingame' / 'weapons').glob(
                f'*_{root.name}.group.bin')))
            break
    if mod_assets is not None:
        # The mod's copy replaces the game's, as it does in the client.
        overlay = _overlay_index(Path(mod_assets).resolve())
        editable = [overlay.get(path.name.lower(), path) for path in editable]
        references = [overlay.get(path.name.lower(), path) for path in references]
    return editable, references


MOD_MANIFEST = """id = "{id}"
name = "{name}"
version = "0.1.0"
author = "BOZ Redux Blender add-on"
game = "1.0.11"
description = "Map edits saved from Blender."
"""


def mod_assets_folder(client_root: str | Path, mod_id: str, create: bool = False) -> Path:
    """The ``assets`` folder of a client mod, optionally creating the mod and its manifest."""
    if not mod_id or not all(c.isalnum() or c in '-_' for c in mod_id):
        raise ValueError('mod name may use only letters, digits, - and _')
    root = Path(client_root).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f'BOZ Redux client folder not found: {root}')
    mod = root / 'mods' / mod_id
    if create:
        (mod / 'assets').mkdir(parents=True, exist_ok=True)
        manifest = mod / 'mod.toml'
        if not manifest.exists():
            manifest.write_text(MOD_MANIFEST.format(id=mod_id, name=mod_id.replace('_', ' ')))
    return mod / 'assets'


def export_to_mod(edits: list[SceneEdit], client_root: str | Path, mod_id: str, *,
                  level_folder: str | Path | None = None, sources=(),
                  force_navmesh: bool = False, deletions=()) -> ExportReport:
    """Write every changed group into a client mod, under its game file name.

    *level_folder* is the game's level folder (for the navmesh, which is always rebuilt from the
    game's original); *sources* adds groups to consider beyond those the edits mention."""
    assets = mod_assets_folder(client_root, mod_id, create=True)
    paths = sorted({path for edit in edits
                    for path in (edit.source_group, edit.instance_source_group) if path}
                   | {str(path) for path in sources})
    return export_groups(edits, {path: assets / Path(path).name for path in paths},
                         replaceable=assets, level_folder=level_folder,
                         force_navmesh=force_navmesh, deletions=deletions)
