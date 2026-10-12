"""Project assets: high-quality models and textures turned into game-ready ones.

An asset is a model brought into a project from a high-quality source (.blend, FBX, glTF, OBJ)
and reduced to the game's level: a triangle budget and power-of-two textures no larger than a
preset. The editor's Assets tab runs the reduction (Blender does the geometry); this module keeps
the data, the presets, the texture reduction, the checks, and hands the game version to the
compiler as a ``world.Mesh``.

In a project::

    assets/<name>/<file>              a copy of the source file (provenance)
    source/assets/<name>.json         the settings (AssetDef)
    source/assets/<name>/model.json   the game version: vertices (ASSET_UNIT), uvs, triangles,
                                      materials (texture per triangle), and for weapons bones,
                                      per-vertex weights and parts
    source/assets/<name>/textures/N.png, stats.json

Positions are stored in tenths of a centimetre (ASSET_UNIT) so small details survive the game's
16-bit integer positions; a placed asset is scaled by ASSET_SCALE to come out in centimetres.
"""
from __future__ import annotations

import json
import re
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import world

FORMAT = 1
ASSET_UNIT = 10            # stored units per centimetre
ASSET_SCALE = 1.0 / ASSET_UNIT
KINDS = ('prop', 'weapon')
PRESETS = {                # preset -> kind -> (triangles, texture side)
    'stock': {'weapon': (1500, 512), 'prop': (800, 256)},
    'pc': {'weapon': (4000, 1024), 'prop': (2500, 512)},
}
PRESET_LABELS = {'stock': 'Stock (like the game\'s own)', 'pc': 'PC (sharper)'}
UNITS = {'cm': 1.0, 'm': 100.0, 'inch': 2.54, 'mm': 0.1}   # source unit -> centimetres
SOURCE_TYPES = ('.blend', '.fbx', '.glb', '.gltf', '.obj')
MAX_BONES_PER_VERTEX = 4
MAX_VERTICES = 65535
MIN_PART_TRIANGLES = 24    # the budget never squeezes a mesh below this
# Parts every weapon is expected to have: (tag bone, label). A missing one is a warning.
WEAPON_PARTS = (('tag_clip', 'Magazine'),)
NAME_RE = re.compile(r'^[A-Za-z][A-Za-z0-9_]{0,40}$')


class AssetError(ValueError):
    pass


@dataclass
class AssetDef:
    name: str
    kind: str = 'prop'
    source: str = ''               # the copy, relative to the project root
    original: str = ''             # where it was imported from (Refresh from source)
    objects: list[str] = field(default_factory=list)   # source objects used (empty: all meshes)
    preset: str = 'stock'
    triangles: int = 0             # 0: the preset's
    texture_size: int = 0          # 0: the preset's
    unit: str = ''                 # the source's unit (UNITS); '' guesses it from the size
    bake_normals: bool = True      # shade the colour with the normal map (the game has none)
    edited: bool = False           # the game version was touched up by hand

    def budget(self) -> int:
        return self.triangles or PRESETS[self.preset][self.kind][0]

    def max_texture(self) -> int:
        return self.texture_size or PRESETS[self.preset][self.kind][1]


@dataclass
class Bone:
    name: str
    parent: str            # '' for a root
    head: tuple[float, float, float]     # bind position, ASSET_UNIT, asset space


@dataclass
class GameModel:
    """The game version of an asset."""
    vertices: list[tuple[int, int, int]]          # ASSET_UNIT
    uvs: list[tuple[float, float]]                # GL (v = 0 is the first row)
    triangles: list[tuple[int, int, int]]
    materials: list[int]                          # texture index per triangle
    texture_names: list[str] = field(default_factory=list)   # source material per texture
    bones: list[Bone] = field(default_factory=list)
    weights: list[list[tuple[int, float]]] = field(default_factory=list)   # per vertex
    parts: dict[str, list[int]] = field(default_factory=dict)   # part label -> triangle indices


# --- Files ----------------------------------------------------------------------------------

def assets_dir(source: Path) -> Path:
    return Path(source) / 'assets'


def def_path(source: Path, name: str) -> Path:
    return assets_dir(source) / f'{name}.json'


def game_dir(source: Path, name: str) -> Path:
    return assets_dir(source) / name


def list_defs(source: Path) -> list[AssetDef]:
    folder = assets_dir(source)
    if not folder.is_dir():
        return []
    return [load_def(source, p.stem) for p in sorted(folder.glob('*.json'))]


def load_def(source: Path, name: str) -> AssetDef:
    try:
        data = json.loads(def_path(source, name).read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise AssetError(f'asset {name}: {exc}') from None
    data.pop('format', None)
    known = {f for f in AssetDef.__dataclass_fields__}
    asset = AssetDef(**{k: v for k, v in data.items() if k in known})
    check_def(asset)
    return asset


def check_def(asset: AssetDef) -> None:
    if not NAME_RE.fullmatch(asset.name):
        raise AssetError(f'asset name {asset.name!r}: use letters, digits and _')
    if asset.kind not in KINDS:
        raise AssetError(f'asset {asset.name}: kind must be prop or weapon')
    if asset.preset not in PRESETS:
        raise AssetError(f'asset {asset.name}: preset must be stock or pc')
    if asset.unit and asset.unit not in UNITS:
        raise AssetError(f'asset {asset.name}: unit must be one of {", ".join(UNITS)}')
    side = asset.texture_size
    if side and (side < 4 or side > world.MAX_TEXTURE or side & (side - 1)):
        raise AssetError(f'asset {asset.name}: texture size must be a power of two up to '
                         f'{world.MAX_TEXTURE}')
    if asset.triangles < 0:
        raise AssetError(f'asset {asset.name}: the triangle budget cannot be negative')


def save_def(source: Path, asset: AssetDef) -> Path:
    check_def(asset)
    path = def_path(source, asset.name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'format': FORMAT, **asdict(asset)}, indent=1) + '\n',
                    encoding='utf-8')
    return path


def delete(root: Path, name: str) -> None:
    """Remove an asset: its settings, game version and source copy."""
    source = Path(root) / 'source'
    def_path(source, name).unlink(missing_ok=True)
    for folder in (game_dir(source, name), Path(root) / 'assets' / name):
        if folder.is_dir():
            shutil.rmtree(folder)


def copy_source(root: Path, name: str, original: Path) -> str:
    """Copy *original* into the project's assets/<name>/; the copy's path from the root."""
    original = Path(original)
    if original.suffix.lower() not in SOURCE_TYPES:
        raise AssetError(f'{original.name}: pick a {", ".join(SOURCE_TYPES)} file')
    folder = Path(root) / 'assets' / name
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / original.name
    if original.resolve() != target.resolve():
        shutil.copy2(original, target)
    return target.relative_to(root).as_posix()


def write_game(source: Path, name: str, model: GameModel, textures: list[world.Texture],
               stats: dict | None = None) -> Path:
    folder = game_dir(source, name)
    if folder.is_dir():
        shutil.rmtree(folder)
    (folder / 'textures').mkdir(parents=True)
    data = {'vertices': [list(v) for v in model.vertices],
            'uvs': [[round(u, 6), round(v, 6)] for u, v in model.uvs],
            'triangles': [list(t) for t in model.triangles],
            'materials': list(model.materials), 'texture_names': list(model.texture_names)}
    if model.bones:
        data['bones'] = [{'name': b.name, 'parent': b.parent, 'head': [round(c, 3) for c in b.head]}
                         for b in model.bones]
        data['weights'] = [[[b, round(w, 4)] for b, w in vertex] for vertex in model.weights]
    if model.parts:
        data['parts'] = model.parts
    (folder / 'model.json').write_text(json.dumps(data, separators=(',', ':')) + '\n',
                                       encoding='utf-8')
    for index, texture in enumerate(textures):
        world.write_texture(texture, folder / 'textures' / f'{index}.png')
    (folder / 'stats.json').write_text(json.dumps(stats or describe(model, textures), indent=1)
                                       + '\n', encoding='utf-8')
    return folder


def has_game(source: Path, name: str) -> bool:
    return (game_dir(source, name) / 'model.json').is_file()


def load_game(source: Path, name: str) -> tuple[GameModel, list[world.Texture]]:
    folder = game_dir(source, name)
    try:
        data = json.loads((folder / 'model.json').read_text(encoding='utf-8'))
        count = max(data.get('materials') or [0]) + 1
        textures = [world.read_texture(folder / 'textures' / f'{i}.png') for i in range(count)]
    except (OSError, ValueError) as exc:
        raise AssetError(f'asset {name}: no game version ({exc}); make it in the Assets tab') \
            from None
    model = GameModel([tuple(int(c) for c in v) for v in data['vertices']],
                      [tuple(map(float, uv)) for uv in data['uvs']],
                      [tuple(map(int, t)) for t in data['triangles']],
                      [int(m) for m in data.get('materials', [])],
                      list(data.get('texture_names', [])),
                      [Bone(b['name'], b.get('parent', ''), tuple(b['head']))
                       for b in data.get('bones', [])],
                      [[(int(b), float(w)) for b, w in vertex] for vertex in data.get('weights', [])],
                      {k: [int(i) for i in v] for k, v in data.get('parts', {}).items()})
    return model, textures


def load_stats(source: Path, name: str) -> dict:
    try:
        return json.loads((game_dir(source, name) / 'stats.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


EXPECTED_LENGTH = {'weapon': (30.0, 200.0), 'prop': (10.0, 600.0)}   # centimetres


def guess_unit(length: float, kind: str) -> str:
    """The source unit that makes a model *length* source units long come out at a believable
    size for its kind (centimetres when several would)."""
    low, high = EXPECTED_LENGTH.get(kind, EXPECTED_LENGTH['prop'])
    for unit in ('cm', 'inch', 'm', 'mm'):
        if low <= length * UNITS[unit] <= high:
            return unit
    return 'cm'


# --- Budget and textures --------------------------------------------------------------------

def split_budget(triangle_counts: list[int], budget: int, floor: int = MIN_PART_TRIANGLES) -> list[int]:
    """Each mesh's share of *budget*, by its share of the triangles; no mesh gets less than
    *floor* (or its own count, when that is smaller) and none more than it has."""
    total = sum(triangle_counts)
    if total <= budget:
        return list(triangle_counts)
    shares = [min(count, floor) for count in triangle_counts]
    left = budget - sum(shares)
    if left <= 0:
        return shares
    extra = [count - share for count, share in zip(triangle_counts, shares)]
    pool = sum(extra) or 1
    return [share + min(e, int(left * e / pool)) for share, e in zip(shares, extra)]


def texture_side(size: int, wanted: int) -> int:
    """The largest power of two no larger than *size* and *wanted* (at least 4)."""
    side = 4
    while side * 2 <= min(size, wanted):
        side *= 2
    return side


def texture_sizes(uv_areas: list[float], max_side: int) -> list[int]:
    """A side for each material's texture by its surface area (*uv_areas*): the largest gets
    *max_side*; one with a quarter of its area gets half, and so on (at least 64), so every
    material shows about as many texels per centimetre."""
    import math
    largest = max(uv_areas or [1.0]) or 1.0
    out = []
    for area in uv_areas:
        steps = int(math.log(largest / area, 4)) if area > 0 else 8
        out.append(max(min(64, max_side), max_side >> steps))
    return out


LIGHT = (0.35, 0.45, 0.82)   # normal-map light: from above and in front (tangent space)


def shade(rgba, normal, strength: float = 0.55):
    """*rgba* (numpy, H x W x 4, 0..1) shaded by a tangent-space *normal* map of the same size
    (H x W x 3, 0..1): the game has no normal maps, so their detail goes into the colour. A
    flat normal leaves the colour as it is; faces turned to the light get up to *strength*
    brighter, faces turned away up to *strength* darker."""
    import numpy as np

    light = np.array(LIGHT, dtype=np.float32)
    light /= np.linalg.norm(light)
    n = normal[..., :3].astype(np.float32) * 2.0 - 1.0
    # Rebuild z from x and y: two-channel normal maps (Call of Duty's, BC5) leave blue empty.
    n[..., 2] = np.sqrt(np.clip(1.0 - n[..., 0] ** 2 - n[..., 1] ** 2, 0.0, 1.0))
    lit = np.clip(n @ light, 0.0, None) / light[2]
    factor = 1.0 + strength * (lit - 1.0)
    out = rgba.astype(np.float32).copy()
    out[..., :3] = np.clip(out[..., :3] * factor[..., None], 0.0, 1.0)
    return out


def texture_from_rgba(rgba, bottom_up: bool = False) -> world.Texture:
    """A world.Texture from numpy RGBA (H x W x 4, 0..1); *bottom_up* as Blender keeps pixels."""
    import numpy as np

    pixels = rgba[::-1] if bottom_up else rgba
    data = (np.clip(pixels, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
    bgra = data[..., [2, 1, 0, 3]]
    return world.Texture(int(rgba.shape[1]), int(rgba.shape[0]), bgra.tobytes())


def reduce_texture(colour, side, normal=None, strength: float = 0.55) -> world.Texture:
    """A game texture from Pillow images: *colour* resized to *side* (a power of two, or
    (width, height)) and shaded by the tangent-space *normal* image when given."""
    import numpy as np
    from PIL import Image

    size = (side, side) if isinstance(side, int) else tuple(side)
    rgba = np.asarray(colour.convert('RGBA').resize(size, Image.LANCZOS), dtype=np.float32) / 255.0
    if normal is not None:
        normals = np.asarray(normal.convert('RGB').resize(size, Image.LANCZOS),
                             dtype=np.float32) / 255.0
        rgba = shade(rgba, normals, strength)
    return texture_from_rgba(rgba)


def flat_texture(colour: tuple[float, float, float, float]) -> world.Texture:
    """A 4 x 4 texture of one colour (0..1 RGBA), for a material without an image."""
    r, g, b, a = (max(0, min(255, round(c * 255))) for c in colour)
    return world.Texture(4, 4, bytes((b, g, r, a)) * 16)


# --- Checks and the compiler ----------------------------------------------------------------

def describe(model: GameModel, textures: list[world.Texture]) -> dict:
    return {'triangles': len(model.triangles), 'vertices': len(model.vertices),
            'textures': [[t.width, t.height] for t in textures],
            'texture_bytes': sum(t.width * t.height * 4 for t in textures),
            'bones': len(model.bones), 'parts': sorted(model.parts)}


def check(asset: AssetDef, model: GameModel, textures: list[world.Texture]) -> tuple[list[str], list[str]]:
    """(errors that block the build, warnings) for an asset's game version."""
    errors, warnings = [], []
    if not model.triangles:
        errors.append('it has no triangles')
    if len(model.vertices) > MAX_VERTICES:
        errors.append(f'{len(model.vertices)} vertices: the game takes at most {MAX_VERTICES} '
                      'per model (reduce it)')
    if any(not -32768 <= c <= 32767 for v in model.vertices for c in v):
        errors.append(f'it is more than {32767 / ASSET_UNIT / 100:.1f} m from its centre '
                      '(check the unit)')
    if any(not -8.0 < c < 8.0 for uv in model.uvs for c in uv):
        errors.append('texture coordinates reach past -8..8 (the game cannot repeat further)')
    if len(model.uvs) != len(model.vertices):
        errors.append('every vertex needs texture coordinates')
    if model.materials and max(model.materials) >= len(textures):
        errors.append('a material has no texture')
    for index, texture in enumerate(textures):
        try:
            texture.check(f'texture {index}')
        except world.WorldError as exc:
            errors.append(str(exc))
        if max(texture.width, texture.height) > asset.max_texture():
            warnings.append(f'texture {index} is {texture.width} x {texture.height}, above the '
                            f'preset\'s {asset.max_texture()}')
    if any(len(vertex) > MAX_BONES_PER_VERTEX for vertex in model.weights):
        errors.append(f'a vertex follows more than {MAX_BONES_PER_VERTEX} bones')
    if len(model.triangles) > asset.budget():
        warnings.append(f'{len(model.triangles)} triangles, above the budget of {asset.budget()}')
    if asset.kind == 'weapon':
        bones = {b.name.lower() for b in model.bones}
        for tag, label in WEAPON_PARTS:
            if label not in model.parts:
                if tag in bones:
                    warnings.append(f'no {label.lower()} yet ({tag} has no mesh): the reload '
                                    'shows none')
                else:
                    warnings.append(f'no {label.lower()} ({tag}) yet: the reload shows none')
    return errors, warnings


def mesh_name(name: str) -> str:
    return f'asset_{name}'


def to_mesh(name: str, model: GameModel, textures: list[world.Texture]) -> world.Mesh:
    return world.Mesh(mesh_name(name), list(model.vertices), list(model.uvs),
                      list(model.triangles), list(textures), 'solid',
                      face_textures=list(model.materials) if any(model.materials) else [])


def attach(world_: world.World, source: Path) -> world.World:
    """Point the world's asset models at their game versions (added to world.meshes) and scale
    them from ASSET_UNIT to centimetres. Raises world.WorldError for a missing or broken
    asset."""
    wanted = {}
    for _full, item in world.walk(world_.objects()):
        if isinstance(item, world.Model) and item.asset:
            wanted.setdefault(item.asset, []).append(item)
    have = {mesh.name for mesh in world_.meshes}
    for name, models in wanted.items():
        try:
            asset = load_def(source, name)
            model, textures = load_game(source, name)
        except AssetError as exc:
            raise world.WorldError(str(exc)) from None
        errors, _warnings = check(asset, model, textures)
        if errors:
            raise world.WorldError(f'asset {name}: ' + '; '.join(errors))
        if mesh_name(name) not in have:
            world_.meshes.append(to_mesh(name, model, textures))
            have.add(mesh_name(name))
        for item in models:
            item.mesh = mesh_name(name)
            item.scale = tuple(c * ASSET_SCALE for c in item.scale)
    return world_
