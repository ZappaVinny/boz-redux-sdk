"""The asset library: the game's Zombies assets, indexed with previews, built from the user's own
game files once per game version (never shipped).

Layout of ``<SDK data>/library/1.0.11/``::

    groups/<pack path>    pristine copies of the Zombies groups (templates read these)
    index.sqlite          every asset: kind, name, label, groups, maps, sizes, thumbnail
    thumbs/<kind>/<hash>.png
    names.txt             names recovered from the game's strings (hash lookups)
    stamp.json            what the library was built from; a mismatch means rebuild
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
import sqlite3
import struct
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from . import blender_scene as scene
from . import derbh, group, native, reflect, resources
from .hashing import iw_hash
from .schema import Names

LIBRARY_VERSION = 3  # 3: raw textures read as R, G, B, A
GAME_VERSION = '1.0.11'
PACK = 'blackops_etc.dz'
THUMB = 128
MAPS = {'kino': 'Kino der Toten', 'callofthedead': 'Call of the Dead', 'ascension': 'Ascension',
        'tutorial': 'Tutorial'}
KINDS = ('prop', 'weapon', 'model', 'texture', 'material', 'effect', 'sound', 'animation')
KIND_LABELS = {'prop': 'Props', 'weapon': 'Weapons', 'model': 'Models', 'texture': 'Textures',
               'material': 'Materials', 'effect': 'Effects', 'sound': 'Sounds',
               'animation': 'Animations'}

MODEL = iw_hash('CIwModel')
TEXTURE = iw_hash('CIwTexture')
MATERIAL = iw_hash('CIwMaterial')
ENTITY = iw_hash('CIsEntitySpec')
SOUND = iw_hash('CIwSoundSpec')
EMITTER = iw_hash('CIwGFXEmitterSpec')
ANIM = iw_hash('CIwAnim')
_STRING = re.compile(rb'[A-Za-z_][A-Za-z0-9_./-]{2,80}')

Progress = Callable[[float, str], None]


class LibraryError(RuntimeError):
    pass


class Cancelled(LibraryError):
    pass


def library_root() -> Path:
    from .sdkhome import data_dir
    return data_dir() / 'library'


def library_dir() -> Path:
    return library_root() / GAME_VERSION


def _pack_path(client_root: str | Path) -> Path:
    return Path(client_root).expanduser() / 'assets' / PACK


def _source_stamp(client_root: str | Path) -> dict:
    pack = _pack_path(client_root)
    info = pack.stat()
    return {'library': LIBRARY_VERSION, 'game': GAME_VERSION, 'pack': PACK, 'size': info.st_size,
            'mtime_ns': info.st_mtime_ns}


def needs_build(client_root: str | Path, folder: Path | None = None) -> bool:
    """True when there is no library yet, or it was built from other game files or by an older
    SDK. False when the game data is missing (nothing to build from)."""
    folder = folder or library_dir()
    if not _pack_path(client_root).is_file():
        return False
    try:
        stamp = json.loads((folder / 'stamp.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return True
    return stamp != _source_stamp(client_root)


def map_of(path: str) -> str:
    """The map a pack path belongs to, or 'shared'."""
    parts = path.split('/')
    if parts[0] in ('levels', 'loading') and len(parts) > 2:
        return parts[1]
    stem = parts[-1].split('.', 1)[0]
    for prefix in ('weapons_', 'weapon_projectiles_', 'arms_'):
        if stem.startswith(prefix):
            return stem[len(prefix):]
    return 'shared'


def map_groups(paths: Iterable[str], level: str) -> list[str]:
    """The pack paths a level template needs: its own level, loading, weapon and arms groups
    (the tutorial uses Kino's weapons and arms)."""
    gear = 'kino' if level == 'tutorial' else level
    wanted = []
    for path in paths:
        stem = path.rsplit('/', 1)[-1].split('.', 1)[0]
        if path.startswith((f'levels/{level}/', f'loading/{level}/')) or stem in (
                f'weapons_{gear}', f'weapon_projectiles_{gear}', f'arms_{gear}'):
            wanted.append(path)
    return sorted(wanted)


# Previews


def _cooked_preview(body: bytes, target: int):
    """A small RGBA image of an ETC1 or DXT1 texture: the smallest mip at least *target* wide,
    decoding only every n-th block when there is no small mip."""
    from PIL import Image

    mip_count, width, height = struct.unpack_from('<III', body, 35)
    if not 1 <= mip_count <= 12 or not width or not height or width > 4096 or height > 4096:
        raise ValueError('invalid cooked texture')
    sizes = struct.unpack_from(f'<{mip_count}I', body, 47)
    offset, level = 23 + 0x48, 0
    while level + 1 < mip_count and max(width >> (level + 1), height >> (level + 1)) >= target:
        offset += sizes[level]
        level += 1
    w, h = max(1, width >> level), max(1, height >> level)
    blocks_x, blocks_y = (w + 3) // 4, (h + 3) // 4
    data = body[offset:offset + blocks_x * blocks_y * 8]
    if len(data) < blocks_x * blocks_y * 8:
        raise ValueError('truncated cooked texture')
    step = max(1, max(w, h) // (target * 2))
    if step > 1:
        rows = range(0, blocks_y, step)
        cols = range(0, blocks_x, step)
        data = b''.join(data[(by * blocks_x + bx) * 8:(by * blocks_x + bx) * 8 + 8]
                        for by in rows for bx in cols)
        w, h = len(cols) * 4, len(rows) * 4
    if body[23] == 0x27:
        rgba = native._decode_etc1(data, w, h)
    elif body[23] == 0x34:
        rgba = native._decode_dxt1(data, w, h)
    else:
        raise ValueError('unsupported cooked texture platform')
    return Image.frombytes('RGBA', (w, h), rgba), (width, height)


def texture_preview(body: bytes, target: int = THUMB):
    """(RGBA image no larger than about 2 x *target*, (width, height)) of any shipped texture."""
    from PIL import Image

    try:
        layout = native.texture_layout(body)
    except ValueError:
        return _cooked_preview(body, target)
    if layout.pixel_format == 0x0E:
        image = native.decode_texture(body)
    else:
        decoded = native.decode_texture_rgba(body)
        image = Image.frombytes('RGBA', (decoded.width, decoded.height), decoded.rgba)
    return image, (layout.width, layout.height)


def _thumbnail(image, size: int = THUMB):
    from PIL import Image

    image = image.copy()
    image.thumbnail((size, size), Image.Resampling.LANCZOS)
    return image


def render_model(model: native.Model, face_colours, size: int = THUMB):
    """A three-quarter view of a model with flat-shaded, colour-filled triangles (painter's
    algorithm). *face_colours* gives each triangle's base RGB."""
    from PIL import Image, ImageDraw

    if not model.triangles:
        return None
    yaw, pitch = math.radians(145), math.radians(25)  # front three-quarter view (models face +Z)
    cy, sy, cp, sp = math.cos(yaw), math.sin(yaw), math.cos(pitch), math.sin(pitch)

    def view(v):
        x, y, z = v
        x, z = x * cy - z * sy, x * sy + z * cy       # yaw around Y (up)
        y, z = y * cp - z * sp, y * sp + z * cp       # pitch around X
        return x, y, z

    points = [view(v) for v in model.vertices]
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    span = max(max(xs) - min(xs), max(ys) - min(ys), 1e-6)
    scale = size * 2 * 0.9 / span
    mid_x, mid_y = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
    light = (0.4, 0.8, -0.45)
    faces = []
    for index, (a, b, c) in enumerate(model.triangles):
        pa, pb, pc = points[a], points[b], points[c]
        ux, uy, uz = pb[0] - pa[0], pb[1] - pa[1], pb[2] - pa[2]
        vx, vy, vz = pc[0] - pa[0], pc[1] - pa[1], pc[2] - pa[2]
        nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
        length = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
        shade = 0.35 + 0.65 * abs((nx * light[0] + ny * light[1] + nz * light[2]) / length)
        r, g, bl = face_colours(index)
        colour = (int(r * shade), int(g * shade), int(bl * shade), 255)
        depth = (pa[2] + pb[2] + pc[2]) / 3
        polygon = [((p[0] - mid_x) * scale + size, (mid_y - p[1]) * scale + size)
                   for p in (pa, pb, pc)]
        faces.append((depth, polygon, colour))
    faces.sort(key=lambda face: -face[0])
    image = Image.new('RGBA', (size * 2, size * 2), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    for _depth, polygon, colour in faces:
        draw.polygon(polygon, fill=colour)
    return image.resize((size, size), Image.Resampling.LANCZOS)


# Building


@dataclass
class _Item:
    kind: str
    hash: int
    name: str = ''
    label: str = ''
    details: str = ''
    category: str = ''
    width: int = 0
    height: int = 0
    triangles: int = 0
    model: int = 0
    size: int = 0
    thumb: str = ''

    def __post_init__(self) -> None:
        self.groups: set[str] = set()
        self.maps: set[str] = set()
        self.variant = ''
        self.candidates: list[int] = []
        self.path = ''  # the first group it was found in


_MODEL_FIELDS = (iw_hash('model'), iw_hash('skel'), iw_hash('m_name'))


def _referenced_models(spec: resources.EntitySpec) -> list[int]:
    """Hashes a spec may name its model by, best first: any nested ``model`` field (weapons keep
    theirs in renderableAsset), then ``skel`` and ``m_name``."""
    found: dict[int, list[int]] = {field: [] for field in _MODEL_FIELDS}

    def walk(blob) -> None:
        for prop in blob.properties:
            if prop.name_hash in found:
                value = reflect.typed_value(prop)
                if isinstance(value, int) and not isinstance(value, bool):
                    found[prop.name_hash].append(value)
            if prop.nested is not None:
                walk(prop.nested)
            for element in prop.elements or ():
                walk(element)

    for component in spec.components:
        if component.blob is not None:
            walk(component.blob)
    return [value for field in _MODEL_FIELDS for value in found[field]]


def _strings(blobs: Iterable[bytes]) -> set[str]:
    found: set[str] = set()
    for data in blobs:
        for match in _STRING.finditer(data):
            text = match.group().decode('ascii')
            found.add(text)
            leaf = text.rsplit('/', 1)[-1]
            found.add(leaf)
            found.add(leaf.split('.', 1)[0])
    return found


def build(client_root: str | Path, folder: Path | None = None,
          progress: Progress | None = None, cancelled: Callable[[], bool] | None = None) -> Path:
    """Build the library from the client's game files into *folder* (default library_dir()).
    The old library is replaced only when the new one is complete."""
    folder = Path(folder or library_dir())
    report = progress or (lambda fraction, message: None)
    stop = cancelled or (lambda: False)
    pack_path = _pack_path(client_root)
    if not pack_path.is_file():
        raise LibraryError(f'{pack_path} not found: install the game files in the client first')

    def check() -> None:
        if stop():
            raise Cancelled('library build cancelled')

    work = folder.with_name(folder.name + '.building')
    if work.exists():
        shutil.rmtree(work)
    (work / 'groups').mkdir(parents=True)
    started = time.time()
    pack = derbh.Pack(pack_path)
    try:
        paths = [path for path in pack.names()
                 if not path.startswith('deadops') and not path.startswith('loading/deadops')]
        data: dict[str, bytes] = {}
        for number, path in enumerate(paths):
            check()
            report(0.15 * number / len(paths), f'Copying {path}')
            body = pack.read(path)
            data[path] = body
            target = work / 'groups' / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(body)
    finally:
        pack.close()

    report(0.16, 'Recovering names from the game')
    sources = list(data.values())
    image = Path(client_root).expanduser() / 'assets' / 'boz.s3e'
    if image.is_file():
        sources.append(image.read_bytes())
    found = _strings(sources)
    (work / 'names.txt').write_text('\n'.join(sorted(found)) + '\n', encoding='latin-1')
    names = Names()
    for text in found:
        names.add(text)
    scene.add_names(found)

    def known(value: int) -> str:
        text = names.names.get(value)
        return text if text and not text.startswith('0x') else ''

    report(0.2, 'Reading groups')
    groups = {path: group.parse(body) for path, body in data.items() if path.endswith('.group.bin')}
    # The same name can hold different contents in different groups (a map's own loading screen,
    # sounds, waves), so every distinct body is its own variant, and references are resolved in
    # the referring group first, then in the same map, then anywhere.
    bodies: dict[tuple[int, int, str], bytes] = {}
    where: dict[str, dict[tuple[int, int], str]] = {}
    by_map: dict[str, dict[tuple[int, int], str]] = {}
    anywhere: dict[tuple[int, int], str] = {}
    for path, parsed in groups.items():
        local = where[path] = {}
        for resource_type in parsed.types():
            for resource in resource_type.resources:
                key = (resource_type.class_hash, resource.in_group_hash)
                digest = hashlib.sha1(resource.body).hexdigest()[:8]
                bodies.setdefault((*key, digest), resource.body)
                local[key] = digest
                by_map.setdefault(map_of(path), {}).setdefault(key, digest)
                anywhere.setdefault(key, digest)

    def resolve(cls: int, value: int, path: str) -> str | None:
        key = (cls, value)
        return (where.get(path, {}).get(key) or by_map.get(map_of(path), {}).get(key)
                or anywhere.get(key))

    items: dict[tuple[str, int, str], _Item] = {}

    def item(kind: str, cls: int, resource: group.Resource, path: str) -> _Item:
        value = resource.in_group_hash
        digest = where[path][(cls, value)]
        entry = items.get((kind, value, digest))
        if entry is None:
            name = known(value) or (known(resource.name_hash) if resource.name_hash else '')
            entry = items[(kind, value, digest)] = _Item(kind, value, name)
            entry.variant = digest
            entry.path = path
            entry.size = len(resource.body)
        entry.groups.add(path)
        entry.maps.add(map_of(path))
        return entry

    simple = {MODEL: 'model', TEXTURE: 'texture', MATERIAL: 'material', SOUND: 'sound',
              EMITTER: 'effect', ANIM: 'animation'}
    for path, parsed in groups.items():
        weapons = path.rsplit('/', 1)[-1].startswith('weapons_')
        for resource_type in parsed.types():
            cls = resource_type.class_hash
            for resource in resource_type.resources:
                if cls in simple:
                    entry = item(simple[cls], cls, resource, path)
                    if cls == EMITTER:
                        entry.category = 'emitter'
                    continue
                if cls != ENTITY:
                    continue
                try:
                    spec = resources.decode_entity_spec(resource.body)
                except (ValueError, struct.error):
                    continue
                category = scene._category(scene._component_names(spec))
                model = scene._model_reference(spec) or 0
                if weapons:
                    kind = 'weapon'
                elif category == 'effect':
                    kind = 'effect'
                elif path.startswith(('levels/', 'ingame/')) and (
                        category in scene.FUNCTION_CATEGORIES or model or category in (
                            'spawn', 'sound', 'interact', 'trigger', 'jump', 'locator')):
                    kind = 'prop'
                else:
                    continue
                entry = item(kind, cls, resource, path)
                entry.category = category
                entry.model = model
                if not model:
                    entry.candidates = _referenced_models(spec)
                try:
                    label, details = scene._describe(spec, category)
                except (ValueError, KeyError, TypeError, struct.error):
                    label, details = '', ''
                if label and label != 'Entity':
                    entry.label = label
                entry.details = details
    check()

    def find(kind: str, cls: int, value: int, path: str) -> _Item | None:
        digest = resolve(cls, value, path)
        return items.get((kind, value, digest)) if digest else None

    material_cache: dict[tuple[int, str], native.Material | None] = {}

    def material(value: int, path: str) -> native.Material | None:
        digest = resolve(MATERIAL, value, path)
        if digest is None:
            return None
        if (value, digest) not in material_cache:
            try:
                material_cache[(value, digest)] = native.decode_material(
                    bodies[(MATERIAL, value, digest)])
            except (ValueError, struct.error):
                material_cache[(value, digest)] = None
        return material_cache[(value, digest)]

    report(0.25, 'Texture previews')
    thumbs = work / 'thumbs'
    for kind in KINDS:
        (thumbs / kind).mkdir(parents=True, exist_ok=True)
    swatches: dict[tuple[int, str], object] = {}
    textures = [entry for entry in items.values() if entry.kind == 'texture']
    for number, entry in enumerate(textures):
        check()
        if number % 20 == 0:
            report(0.25 + 0.3 * number / max(1, len(textures)),
                   f'Texture previews ({number}/{len(textures)})')
        try:
            image, (entry.width, entry.height) = texture_preview(
                bodies[(TEXTURE, entry.hash, entry.variant)])
        except (ValueError, struct.error, OSError):
            continue
        entry.thumb = f'texture/{entry.hash:08x}-{entry.variant}.png'
        _thumbnail(image).save(thumbs / entry.thumb)
        swatches[(entry.hash, entry.variant)] = _thumbnail(image.convert('RGB'), 16)

    def texture_of(material_hash: int, path: str) -> _Item | None:
        found = material(material_hash, path)
        if found and found.textures:
            return find('texture', TEXTURE, found.textures[0], path)
        return None

    for entry in items.values():
        if entry.kind == 'material':
            found = material(entry.hash, entry.path)
            source = texture_of(entry.hash, entry.path)
            if source is not None:
                entry.thumb = source.thumb
                entry.width, entry.height = source.width, source.height
                entry.label = entry.label or (f'Material: {source.name}' if source.name else '')
            entry.details = f'flags {found.flags:#x}' if found else ''

    def material_colour(material_hash: int, path: str):
        source = texture_of(material_hash, path)
        if source is not None and (source.hash, source.variant) in swatches:
            return swatches[(source.hash, source.variant)]
        found = material(material_hash, path)
        if found and found.colours:
            r, g, b, _a = found.colours[0]
            return (r, g, b)
        return (170, 170, 170)

    model_users: dict[int, str] = {}
    for entry in items.values():
        if entry.kind in ('prop', 'weapon'):
            for value in [entry.model] if entry.model else entry.candidates:
                model_users.setdefault(value, entry.name or entry.label)
    material_ids = {value for (cls, value, _digest) in bodies if cls == MATERIAL}

    report(0.55, 'Model previews')
    models = [entry for entry in items.values() if entry.kind == 'model']
    for number, entry in enumerate(models):
        check()
        if number % 20 == 0:
            report(0.55 + 0.4 * number / max(1, len(models)),
                   f'Model previews ({number}/{len(models)})')
        body = bodies[(MODEL, entry.hash, entry.variant)]
        try:
            model = native.decode_model(body)
        except (ValueError, struct.error, IndexError):
            continue
        entry.triangles = len(model.triangles)
        refs = scene._model_materials(body, material_ids)
        user = model_users.get(entry.hash)
        if not entry.name and user:
            entry.label = f'Model of {user}'
        colours = [material_colour(ref, entry.path) for ref in refs]

        def colour(index, model=model, colours=colours):
            slot = model.face_materials[index] if index < len(model.face_materials) else 0
            base = colours[slot] if slot < len(colours) else (170, 170, 170)
            if isinstance(base, tuple):
                return base
            a, b, c = model.triangles[index]
            uvs = model.uvs
            if uvs and max(a, b, c) < len(uvs):
                u = (uvs[a][0] + uvs[b][0] + uvs[c][0]) / 3 % 1.0
                v = (uvs[a][1] + uvs[b][1] + uvs[c][1]) / 3 % 1.0
                return base.getpixel((min(base.width - 1, int(u * base.width)),
                                      min(base.height - 1, int(v * base.height))))
            return base.resize((1, 1)).getpixel((0, 0))

        try:
            image = render_model(model, colour)
        except (ValueError, ZeroDivisionError, IndexError):
            image = None
        if image is not None:
            entry.thumb = f'model/{entry.hash:08x}-{entry.variant}.png'
            image.save(thumbs / entry.thumb)
    for entry in items.values():
        if entry.kind in ('prop', 'weapon', 'effect'):
            source = None
            for value in ([entry.model] if entry.model else entry.candidates):
                source = find('model', MODEL, value, entry.path)
                if source is not None:
                    break
            if source is not None:
                entry.model = source.hash
                entry.thumb = source.thumb
                entry.triangles = source.triangles

    report(0.96, 'Writing the index')
    maps = []
    for level, label in MAPS.items():
        level_groups = map_groups(data, level)
        if not any(path.startswith(f'levels/{level}/') for path in level_groups):
            continue
        thumb = ''
        loading = f'loading/{level}/loading.group.bin'
        if loading in groups:
            best = max((find('texture', TEXTURE, r.in_group_hash, loading)
                        for t in groups[loading].types() if t.class_hash == TEXTURE
                        for r in t.resources),
                       key=lambda entry: entry.width * entry.height if entry else -1, default=None)
            if best is not None and best.thumb:
                image, _ = texture_preview(bodies[(TEXTURE, best.hash, best.variant)], 256)
                _thumbnail(image, 256).save(thumbs / f'map_{level}.png')
                thumb = f'map_{level}.png'
        maps.append((level, label, json.dumps(level_groups), thumb))
    database = sqlite3.connect(work / 'index.sqlite')
    database.executescript('''
        CREATE TABLE assets (kind TEXT, hash INTEGER, variant TEXT, name TEXT, label TEXT,
            details TEXT, category TEXT, groups TEXT, maps TEXT, width INTEGER, height INTEGER,
            triangles INTEGER, model INTEGER, size INTEGER, thumb TEXT,
            PRIMARY KEY (kind, hash, variant));
        CREATE TABLE maps (name TEXT PRIMARY KEY, label TEXT, groups TEXT, thumb TEXT);
        CREATE TABLE info (key TEXT PRIMARY KEY, value TEXT);
    ''')
    database.executemany(
        'INSERT INTO assets VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
        [(entry.kind, entry.hash, entry.variant, entry.name, entry.label, entry.details, entry.category,
          json.dumps(sorted(entry.groups)), json.dumps(sorted(entry.maps)), entry.width,
          entry.height, entry.triangles, entry.model, entry.size, entry.thumb)
         for entry in items.values()])
    database.executemany('INSERT INTO maps VALUES (?, ?, ?, ?)', maps)
    database.executemany('INSERT INTO info VALUES (?, ?)', [
        ('built', time.strftime('%Y-%m-%d %H:%M:%S')), ('seconds', f'{time.time() - started:.0f}'),
        ('library', str(LIBRARY_VERSION))])
    database.commit()
    database.close()
    (work / 'stamp.json').write_text(json.dumps(_source_stamp(client_root), indent=2) + '\n',
                                     encoding='utf-8')
    if folder.exists():
        shutil.rmtree(folder)
    work.rename(folder)
    report(1.0, f'Library built in {time.time() - started:.0f} s')
    return folder


# Reading


class LibraryPack:
    """The library's group copies, read like the game's pack (``read('levels/kino/...')``)."""

    def __init__(self, folder: Path | None = None) -> None:
        self.folder = Path(folder or library_dir()) / 'groups'
        if not self.folder.is_dir():
            raise LibraryError('the asset library has not been built yet')

    def read(self, path: str) -> bytes:
        try:
            return (self.folder / path).read_bytes()
        except FileNotFoundError:
            raise KeyError(path) from None

    def __contains__(self, path: str) -> bool:
        return (self.folder / path).is_file()

    def names(self) -> list[str]:
        return sorted(path.relative_to(self.folder).as_posix()
                      for path in self.folder.rglob('*') if path.is_file())

    def close(self) -> None:
        pass


def open_game(client_root: str | Path | None = None):
    """Something that reads the game's groups: the asset library if it is built, else the
    client's pack in place; None when neither exists."""
    try:
        return LibraryPack()
    except LibraryError:
        pass
    if client_root and _pack_path(client_root).is_file():
        return derbh.Pack(_pack_path(client_root))
    return None



@dataclass
class Asset:
    kind: str
    hash: int
    variant: str
    name: str
    label: str
    details: str
    category: str
    groups: list[str]
    maps: list[str]
    width: int
    height: int
    triangles: int
    model: int
    size: int
    thumb: str

    @property
    def title(self) -> str:
        return self.name or self.label or f'{self.kind} {self.hash:08x}'

    @property
    def hash_text(self) -> str:
        return f'0x{self.hash:08x}'


@dataclass
class MapTemplate:
    name: str
    label: str
    groups: list[str]
    thumb: str


class Library:
    """A built library, read-only."""

    def __init__(self, folder: Path | None = None) -> None:
        self.folder = Path(folder or library_dir())
        index = self.folder / 'index.sqlite'
        if not index.is_file():
            raise LibraryError('the asset library has not been built yet')
        self.database = sqlite3.connect(f'file:{index}?mode=ro', uri=True,
                                        check_same_thread=False)

    def close(self) -> None:
        self.database.close()

    def info(self) -> dict[str, str]:
        return dict(self.database.execute('SELECT key, value FROM info'))

    def counts(self) -> dict[str, int]:
        return dict(self.database.execute('SELECT kind, COUNT(*) FROM assets GROUP BY kind'))

    def maps(self) -> list[MapTemplate]:
        return [MapTemplate(name, label, json.loads(groups), thumb) for name, label, groups, thumb
                in self.database.execute('SELECT name, label, groups, thumb FROM maps')]

    def search(self, text: str = '', kind: str = '', level: str = '', named_only: bool = False,
               limit: int = 500) -> list[Asset]:
        """Assets matching *text* (in the name, label, details or hash), optionally of one kind
        and used by one map ('shared' for the common groups). Named and previewed assets first."""
        where, args = [], []
        if kind:
            where.append('kind = ?')
            args.append(kind)
        if level:
            where.append('maps LIKE ?')
            args.append(f'%"{level}"%')
        if named_only:
            where.append("(name != '' OR label != '')")
        for word in text.lower().split():
            where.append("(lower(name) LIKE ? OR lower(label) LIKE ? OR lower(details) LIKE ? "
                         "OR printf('0x%08x', hash) LIKE ?)")
            args += [f'%{word}%'] * 4
        sql = ('SELECT kind, hash, variant, name, label, details, category, groups, maps, width, height, '
               'triangles, model, size, thumb FROM assets')
        if where:
            sql += ' WHERE ' + ' AND '.join(where)
        sql += (" ORDER BY (name = '' AND label = ''), thumb = '', kind, lower(name || label), hash "
                'LIMIT ?')
        args.append(limit)
        return [Asset(*row[:7], json.loads(row[7]), json.loads(row[8]), *row[9:])
                for row in self.database.execute(sql, args)]

    def thumb_for(self, kind: str, value: int) -> Path | None:
        """The preview of an asset by kind and hash (its first variant with one)."""
        row = self.database.execute(
            "SELECT thumb FROM assets WHERE kind = ? AND hash = ? AND thumb != '' LIMIT 1",
            (kind, value)).fetchone()
        return self.folder / 'thumbs' / row[0] if row else None

    def thumb_path(self, asset: Asset | MapTemplate) -> Path | None:
        return self.folder / 'thumbs' / asset.thumb if asset.thumb else None

    def group_path(self, pack_path: str) -> Path:
        return self.folder / 'groups' / pack_path
