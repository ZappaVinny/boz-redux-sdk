"""A map's own effects and projectiles (the Effects tab's "Your effects" and "Your projectiles"),
and the build that makes them game resources.

An own effect is one or more particle emitters (bozkit.gfx), each with its texture (a PNG, an
optional flipbook of frames, a tint) and blend. It is built as:

- per emitter: a CIwTexture, a CIwMaterial (alpha mode: add or blend; the flipbook in the
  material's animation block) and a CIwGFXEmitterSpec;
- "lasting" (it keeps going until removed: a glow, a trail): an entity spec like the game's
  (0x2ed264de in ingame): a CIsTransform and CIsHierarchy parent with one child per emitter
  (CIsHierarchy, CIsTransform, CIsRenderableGFXEmitter naming its emitter spec);
- "burst" (it plays once, like an impact): a CImpactEffect listing its emitter specs
  (m_EmitterNames), like the game's impactZombiePistol.

An own projectile is the Ray Gun's bolt (weapon_projectiles_kino 0xcc1dcaeb, behaviourType 2:
it flies straight, ray-casts every frame and explodes on what it hits) with its values: the
blast (CExplosion: impact effect, inner and outer radius, damage at the centre and at the edge),
the ribbon behind it (CRenderableTrail: texture, width, colour, fade time) and particles left
along the path (CSmokeTrail: emitter specs, from one of your effects). A weapon fires it when its
fire mode is a launcher (behaviour 9) and its projectile is this one (bozkit.weapons).

Everything goes into the map's weapon_projectiles group (always loaded with the map).

Project file: source/fx.json {"effects": [...], "projectiles": [...]}; textures are copied to
source/fx/.
"""
from __future__ import annotations

import copy
import json
import re
import shutil
import struct
from pathlib import Path

from . import gfx, native, reflect, resources
from .hashing import iw_hash

FILE = 'fx.json'
TEXTURE_DIR = 'fx'
NAME_RE = re.compile(r'[a-z][a-z0-9_]{0,31}')
KINDS = ('lasting', 'burst')
BLENDS = {'add': 2, 'blend': 4}            # CIwMaterial alpha modes (flags bits 16-18)
LASTING_TEMPLATE = ('ingame/ingame.group.bin', 0x2ed264de)
BURST_TEMPLATE = ('ingame/effects/visualeffects.group.bin', iw_hash('impactZombiePistol'))
PROJECTILE_TEMPLATE = ('ingame/weapons/weapon_projectiles_kino.group.bin', 0xcc1dcaeb)
MATERIAL_TEMPLATE = ('ingame/ingame.group.bin', iw_hash('iceShatter'))
MAX_EMITTERS = 8
MAX_TEXTURE = 512
MAX_DAMAGE = 1_000_000
MAX_RADIUS = 10_000.0

ENTITY_SPEC = resources.ENTITY_SPEC
MATERIAL = iw_hash('CIwMaterial')
TEXTURE = iw_hash('CIwTexture')
EMITTER = iw_hash('CIsRenderableGFXEmitter')


class FxError(ValueError):
    pass


# A new emitter: a soft glow puff, in the fields' own units (gfx.FIELDS).
DEFAULT_EMITTER = {
    'texture': '', 'frames': 1, 'columns': 1, 'blend': 'add', 'tint': [255, 255, 255],
    'space': 0, 'order': 0, 'shape': 0, 'flags': ['additive', 'flag_1', 'fade_out'], 'duration': -1,
    'size_scale': 1.0, 'position': [0, 0, 0], 'position_spread': [5, 5, 5],
    'velocity': [0, 40, 0], 'velocity_spread': [20, 20, 20], 'gravity': [0, 0, 0],   # y is up
    'life': [600, 900], 'size': [12.0, 18.0], 'spin': [-45, 45], 'angle': [0, 360],
    'spawn_every': [40, 60], 'growth': 10, 'frame_mode': 1, 'frame_time': 33,
}
# A projectile: how it flies, an optional script (scripts/projectiles/<name>.lua: a boz.Projectile
# class with on_launch, on_update, on_hit, on_enter, on_leave, on_end) and optional
# pieces, the defaults that run unless its script says otherwise. A new one is blank.
DEFAULT_RIBBON = {'texture': '', 'width': 100.0, 'colour': [1.0, 1.0, 1.0, 1.0], 'fade': 1200.0}
PIECES = {
    'blast': {'damage': [1000, 1500], 'radius': [32.0, 64.0]},       # on a hit: damage around it
    'lure': {'seconds': 6.0},                                       # on a hit: zombies go there
    'black_hole': {'seconds': 6.0},                                 # on a hit: the Gersch black hole
    'trail': '',                                                    # one of your effects, along its path
    'impact': '',                                                   # an effect where it hits
    'ribbon': DEFAULT_RIBBON,                                       # a streak behind it
}
# An effect's pieces run where it appears, when it spawns (unless its script's on_spawn returns false).
EFFECT_PIECES = ('blast', 'lure', 'black_hole')
DEFAULT_PROJECTILE = {'speed': 3000.0, 'gravity': False, 'lifetime': 5.0, 'radius': 0.0, 'script': '', 'pieces': {}}
PRESETS = {
    'blank': ('Blank', 'Flies and does nothing until you add pieces or a script', {}),
    'bolt': ('Ray Gun bolt', 'Explodes where it hits, with a ribbon behind it',
             {'blast': PIECES['blast'], 'ribbon': DEFAULT_RIBBON}),
    'lure': ('Lure', 'Where it lands, zombies go for a while', {'lure': PIECES['lure']}),
    'black_hole': ('Black hole', 'Where it lands, a Gersch black hole opens', {'black_hole': PIECES['black_hole']}),
}
GERSCH = ('boz_black_hole', 'ascension', 0x8eae245e)   # bh_bomb: the Gersch device's black hole


def path(source: Path) -> Path:
    return Path(source) / FILE


def load(source: Path) -> dict:
    """source/fx.json ({"effects": [], "projectiles": []} when there is none)."""
    file = path(source)
    if not file.is_file():
        return {'effects': [], 'projectiles': []}
    try:
        data = json.loads(file.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise FxError(f'fx.json: {exc}') from None
    data.setdefault('effects', [])
    data['projectiles'] = [upgrade_projectile(p) for p in data.setdefault('projectiles', [])]
    return data


def upgrade_projectile(projectile: dict) -> dict:
    """A projectile of an earlier SDK (always the Ray Gun bolt: damage, radius, impact, trail,
    ribbon) as pieces."""
    if 'pieces' in projectile:
        return projectile
    out = {k: v for k, v in projectile.items() if k not in ('damage', 'radius', 'impact', 'trail', 'ribbon')}
    out.update({k: v for k, v in DEFAULT_PROJECTILE.items() if k not in out and k != 'pieces'})
    pieces = {'blast': {'damage': projectile.get('damage', PIECES['blast']['damage']),
                        'radius': projectile.get('radius', PIECES['blast']['radius'])},
              'ribbon': {**DEFAULT_RIBBON, **(projectile.get('ribbon') or {})}}
    for key in ('impact', 'trail'):
        if projectile.get(key):
            pieces[key] = projectile[key]
    out['pieces'] = pieces
    return out


def save(source: Path, data: dict) -> None:
    file = path(source)
    if not data.get('effects') and not data.get('projectiles'):
        file.unlink(missing_ok=True)
        return
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(json.dumps(data, indent=2, sort_keys=True) + '\n', encoding='utf-8', newline='\n')


def new_emitter(**changes) -> dict:
    out = copy.deepcopy(DEFAULT_EMITTER)
    out.update(changes)
    return out


def new_effect(name: str, kind: str = 'lasting') -> dict:
    return {'name': name, 'kind': kind, 'scale': 1.0, 'emitters': [new_emitter()]}


def new_projectile(name: str, preset: str = 'blank') -> dict:
    out = copy.deepcopy(DEFAULT_PROJECTILE)
    out['name'] = name
    out['pieces'] = copy.deepcopy(PRESETS[preset][2])
    return out


def script_path(kind: str, name: str) -> str:
    """Where an effect's or projectile's script goes (relative to the project)."""
    return f'scripts/{"projectiles" if kind == "projectile" else "effects"}/{name}.lua'


def script_stub(kind: str, name: str) -> str:
    cls = ''.join(part.capitalize() for part in name.split('_')) or 'Mine'
    if kind == 'projectile':
        return f'''-- {name}: what this projectile does. Its pieces (Effects tab) run unless a function
-- here returns false. self.effect is the projectile (position, velocity, effects on it).
local {cls} = boz.Projectile:extend("{cls}")

function {cls}:on_launch(shooter)
end

function {cls}:on_hit(hit)
    -- hit.kind: "zombie", "player" or "world"; hit.zombie, hit.position
end

function {cls}:on_enter(what)      -- what.kind: "zombie" or "player", within its radius (Effects tab)
end

return {cls}
'''
    return f'''-- {name}: what this effect does while it is in the world. self.effect changes it live
-- (self.effect:set{{scale = 2}}).
local {cls} = boz.Effect:extend("{cls}")

function {cls}:on_spawn()
end

function {cls}:on_update(dt)
end

function {cls}:on_end()
end

return {cls}
'''


def import_texture(source: Path, png: Path, name: str) -> str:
    """Copy an image into source/fx/ and return its path relative to the project."""
    folder = Path(source) / TEXTURE_DIR
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f'{name}{png.suffix.lower()}'
    if png.resolve() != target.resolve():
        shutil.copyfile(png, target)
    return f'source/{TEXTURE_DIR}/{target.name}'


def emitter_raw(emitter: dict, material: int) -> dict:
    """An emitter's values (in their units) as gfx raw values."""
    out = {}
    for f in gfx.FIELDS:
        if f.name == 'material':
            out['material'] = material
            continue
        value = emitter.get(f.name, DEFAULT_EMITTER.get(f.name))
        if f.name == 'flags':
            bits = {name: bit for bit, (name, _help) in gfx.FLAGS.items()}
            out['flags'] = sum(bits[n] for n in value if n in bits) if isinstance(value, list) else int(value)
        elif f.kind in ('fixed', 'float'):
            out[f.name] = gfx.raw(f.name, value)
        else:
            out[f.name] = int(value)
    return out


def emitter_from_raw(spec: dict) -> dict:
    """A game emitter's values in their units (to start an own one from it)."""
    out = new_emitter()
    for f in gfx.FIELDS:
        if f.name == 'material':
            continue
        value = spec[f.name]
        if f.name == 'flags':
            out['flags'] = gfx.flag_names(value)
        elif f.kind == 'fixed':
            out[f.name] = gfx.shown(f.name, value)
        else:
            out[f.name] = value
    return out


def _number(value, low, high) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and low <= value <= high


def check(data: dict, project_root: Path | None = None, taken: set | None = None) -> list[str]:
    """Problems with the project's own effects and projectiles (the build stops on them)."""
    problems = []
    names = [e.get('name', '') for e in data.get('effects', [])] + \
        [p.get('name', '') for p in data.get('projectiles', [])]
    for name in names:
        if not NAME_RE.fullmatch(str(name)):
            problems.append(f'Effects: "{name}": names use a-z, 0-9 and _ (at most 32, starting with a letter)')
        elif names.count(name) > 1 or name in (taken or set()):
            problems.append(f'Effects: two effects or projectiles are called "{name}"')
    effects = {e.get('name') for e in data.get('effects', [])}
    for effect in data.get('effects', []):
        label = f'Effects: "{effect.get("name")}"'
        if effect.get('kind', 'lasting') not in KINDS:
            problems.append(f'{label}: kind must be lasting or burst')
        emitters = effect.get('emitters') or []
        if not 1 <= len(emitters) <= MAX_EMITTERS:
            problems.append(f'{label}: give it 1 to {MAX_EMITTERS} emitters')
        if not _number(effect.get('scale', 1.0), 0.01, 100):
            problems.append(f'{label}: scale must be from 0.01 to 100')
        for i, emitter in enumerate(emitters):
            where = f'{label} emitter {i + 1}'
            texture = emitter.get('texture', '')
            if not texture:
                problems.append(f'{where}: pick a texture (PNG)')
            elif project_root is not None and not (Path(project_root) / texture).is_file():
                problems.append(f'{where}: its texture {texture} is missing')
            if emitter.get('blend', 'add') not in BLENDS:
                problems.append(f'{where}: blend must be add or blend')
            frames, columns = emitter.get('frames', 1), emitter.get('columns', 1)
            if not (isinstance(frames, int) and isinstance(columns, int) and 1 <= columns <= frames <= 64):
                problems.append(f'{where}: frames (1-64) must be at least the columns')
            for f in gfx.FIELDS:
                if f.name in ('material', 'order'):
                    continue
                value = emitter.get(f.name, DEFAULT_EMITTER.get(f.name))
                values = value if isinstance(value, list) else [value]
                if f.kind == 'enum' and value not in gfx.ENUMS[f.name]:
                    problems.append(f'{where}: {f.label} must be one of {sorted(gfx.ENUMS[f.name])}')
                elif f.kind in ('fixed', 'float', 'uint') and not all(_number(v, -1e6, 1e6) for v in values):
                    problems.append(f'{where}: {f.label} must be numbers from -1,000,000 to 1,000,000')
            if min(emitter.get('life', [1, 1])) <= 0:
                problems.append(f'{where}: particles must live longer than 0 ms')
            if min(emitter.get('spawn_every', [1, 1])) <= 0:
                problems.append(f'{where}: spawn every must be more than 0')
    for projectile in data.get('projectiles', []):
        projectile = upgrade_projectile(projectile)
        label = f'Projectiles: "{projectile.get("name")}"'
        pieces = projectile.get('pieces') or {}
        if not _number(projectile.get('speed', 3000.0), 1, 100_000):
            problems.append(f'{label}: speed must be from 1 to 100,000 units a second')
        if not _number(projectile.get('lifetime', 5.0), 0.1, 600):
            problems.append(f'{label}: lifetime must be from 0.1 to 600 seconds')
        if not _number(projectile.get('radius', 0.0), 0, MAX_RADIUS):
            problems.append(f'{label}: the enter/leave radius must be from 0 to {MAX_RADIUS:,}')
        unknown = [k for k in pieces if k not in PIECES]
        if unknown:
            problems.append(f'{label}: unknown pieces {", ".join(unknown)}')
        problems += _check_values(label, pieces)
        for key in ('trail', 'impact'):
            if pieces.get(key) and pieces[key] not in effects and key == 'trail':
                problems.append(f'{label}: its trail "{pieces[key]}" is not one of your effects')
        ribbon = pieces.get('ribbon') or {}
        if ribbon.get('texture') and project_root is not None and \
                not (Path(project_root) / ribbon['texture']).is_file():
            problems.append(f'{label}: its ribbon texture {ribbon["texture"]} is missing')
        script = projectile.get('script', '')
        if script and project_root is not None and not (Path(project_root) / script).is_file():
            problems.append(f'{label}: its script {script} is missing')
    for effect in data.get('effects', []):
        label = f'Effects: "{effect.get("name")}"'
        pieces = effect.get('pieces') or {}
        unknown = [k for k in pieces if k not in EFFECT_PIECES]
        if unknown:
            problems.append(f'{label}: unknown pieces {", ".join(unknown)}')
        problems += _check_values(label, pieces)
        script = effect.get('script', '')
        if script and project_root is not None and not (Path(project_root) / script).is_file():
            problems.append(f'Effects: "{effect.get("name")}": its script {script} is missing')
    return problems


def _check_values(label: str, pieces: dict) -> list[str]:
    """Problems with the blast, lure and black hole pieces (projectiles' and effects')."""
    problems = []
    blast = pieces.get('blast')
    if blast is not None:
        damage, radius = blast.get('damage', [0, 0]), blast.get('radius', [0, 0])
        if not (len(damage) == 2 and all(_number(d, 0, MAX_DAMAGE) for d in damage)):
            problems.append(f'{label}: blast damage must be two numbers from 0 to {MAX_DAMAGE:,}')
        if not (len(radius) == 2 and all(_number(r, 0, MAX_RADIUS) for r in radius) and radius[0] <= radius[1]):
            problems.append(f'{label}: the blast radius is an inner and an outer number (inner <= outer)')
    for key in ('lure', 'black_hole'):
        if key in pieces and not _number((pieces[key] or {}).get('seconds', 0), 0.1, 600):
            problems.append(f'{label}: {key.replace("_", " ")} seconds must be from 0.1 to 600')
    return problems


# Building -------------------------------------------------------------------------------------

def emitter_name(effect: str, index: int) -> int:
    return iw_hash(f'boz_fx_{effect}_{index}')


def effect_hash(name: str) -> int:
    return iw_hash(f'boz_fx_{name}')


def projectile_hash(name: str) -> int:
    return iw_hash(f'boz_proj_{name}')


def texture_body(png: Path, template: bytes, tint=(255, 255, 255), max_side: int = MAX_TEXTURE) -> bytes:
    """A raw texture from an image: tinted, at most *max_side* on a side, power-of-two sides;
    *template* is a raw game texture whose header is copied."""
    from PIL import Image
    with Image.open(png) as image:
        image = image.convert('RGBA')
    width, height = (_pow2(min(side, max_side)) for side in image.size)
    if image.size != (width, height):
        image = image.resize((width, height), Image.LANCZOS)
    if tuple(tint[:3]) != (255, 255, 255):
        r, g, b, a = image.split()
        r = r.point(lambda v: v * tint[0] // 255)
        g = g.point(lambda v: v * tint[1] // 255)
        b = b.point(lambda v: v * tint[2] // 255)
        image = Image.merge('RGBA', (r, g, b, a))
    return native.encode_texture(image, template, 4)


def _pow2(side: int) -> int:
    value = 1
    while value * 2 <= side:
        value *= 2
    return max(1, value)


def material_body(template: bytes, texture: int, blend: str, frames: int = 1, columns: int = 1,
                  cell: tuple[int, int] = (0, 0)) -> bytes:
    """A particle material: the template's, with the texture, alpha mode and flipbook."""
    material = native.decode_material(template)
    material.flags = (material.flags & ~0x70000) | (BLENDS[blend] << 16)
    material.textures = [texture] + [0] * (max(len(material.textures), 1) - 1)
    trailer = material.trailer
    rest = trailer[7:] if trailer[:1] == b'\x01' else trailer[1:]
    if frames > 1:
        material.trailer = bytes([1, 0, frames, columns, cell[0] & 0xff, cell[1] & 0xff, 1]) + rest
    else:
        material.trailer = b'\x00' + rest
    return native.encode_material(material)


def _template(read, where: tuple[str, int], class_hash: int = ENTITY_SPEC):
    """(group, resource type, resource) of a game resource used as a template."""
    from . import group as group_module
    path, value = where
    parsed = group_module.read_parsed(read, path)
    for t in parsed.types():
        if t.class_hash != class_hash:
            continue
        for r in t.resources:
            if r.in_group_hash == value:
                return parsed, t, r
    raise FxError(f'no template 0x{value:08x} in {path} (rebuild the asset library)')


def _set(component, name: str, raw: bytes, type_name: str) -> None:
    """Set (or add) a reflected property's raw value on a component."""
    blob = component.blob
    for prop in blob.properties:
        if prop.name_hash == iw_hash(name):
            prop.raw, prop.nested, prop.elements = raw, None, None
            return
    blob.properties.append(reflect.Property(blob.class_hash, iw_hash(type_name), iw_hash(name), raw))


def _component(spec, class_name: str):
    found = [c for c in spec.components if c.type_hash == iw_hash(class_name)]
    if not found:
        raise FxError(f'template has no {class_name}')
    return found[0]


def _hash_list(values: list[int]) -> bytes:
    return struct.pack(f'<I{len(values)}I', len(values), *values)


def effect_spec(read, effect: dict) -> bytes:
    """The entity spec of an own effect (lasting: one child per emitter; burst: an impact
    effect listing its emitters)."""
    emitters = [emitter_name(effect['name'], i) for i in range(len(effect['emitters']))]
    scale = float(effect.get('scale', 1.0))
    if effect.get('kind', 'lasting') == 'burst':
        _g, _t, resource = _template(read, BURST_TEMPLATE)
        spec = resources.decode_entity_spec(resource.body)
        impact = _component(spec, 'CImpactEffect')
        _set(impact, 'name', struct.pack('<I', effect_hash(effect['name'])), 'unsigned int')
        _set(impact, 'm_EmitterNames', _hash_list(emitters), 'std::list<unsigned int>')
        return resources.encode_entity_spec(spec)
    _g, _t, resource = _template(read, LASTING_TEMPLATE)
    spec = resources.decode_entity_spec(resource.body)
    if not spec.children:
        raise FxError('the lasting effect template has no child')
    cls, reserved, child = spec.children[0]
    children = []
    for value in emitters:
        one = copy.deepcopy(child)
        emitter = _component(one, 'CIsRenderableGFXEmitter')
        _set(emitter, 'emitterSpec', struct.pack('<I', value), 'unsigned int')
        _set(emitter, 'effectScale', struct.pack('<f', scale), 'float')
        children.append((cls, reserved, one))
    spec.children = children
    return resources.encode_entity_spec(spec)


GRAVITY_TEMPLATE = ('ingame/weapons/weapon_projectiles_kino.group.bin', 0x3340684c)   # a bolt with a body


def projectile_spec(read, projectile: dict, data: dict, effect_hashes: dict) -> bytes:
    """The entity spec of an own projectile: the Ray Gun's bolt (it flies, ray-casts its path and
    calls Projectile_Impact on a hit, which boz.Projectile takes over) without its blast (the
    pieces run in Lua) and without its smoke (the trail piece follows it), with a rigid body when
    it falls, its lifetime, and the ribbon when it has one."""
    projectile = upgrade_projectile(projectile)
    _g, _t, resource = _template(read, PROJECTILE_TEMPLATE)
    spec = resources.decode_entity_spec(resource.body)
    pieces = projectile.get('pieces') or {}
    drop = {iw_hash('CExplosion'), iw_hash('CSmokeTrail')}
    if not pieces.get('ribbon'):
        drop.add(iw_hash('CRenderableTrail'))
    spec.components = [c for c in spec.components if c.type_hash not in drop]
    if projectile.get('gravity'):
        _gg, _gt, falling = _template(read, GRAVITY_TEMPLATE)
        body = next(c for c in resources.decode_entity_spec(falling.body).components
                    if c.type_hash == iw_hash('CIsRigidBody'))
        spec.components.append(copy.deepcopy(body))
    entity = _component(spec, 'CProjectileEntity')
    _set(entity, 'm_maxLifeTime', struct.pack('<I', int(float(projectile.get('lifetime', 5.0)) * 1000)), 'unsigned int')
    _set(entity, 'm_bHasLifeTime', b'\x01', 'bool')
    ribbon = pieces.get('ribbon')
    if ribbon:
        ribbon = {**DEFAULT_RIBBON, **ribbon}
        trail = _component(spec, 'CRenderableTrail')
        if ribbon.get('texture'):
            _set(trail, 'material', struct.pack('<I', iw_hash(f'boz_proj_{projectile["name"]}_ribbon')), 'unsigned int')
        _set(trail, 'trailWidth', struct.pack('<f', float(ribbon['width'])), 'float')
        _set(trail, 'colour', struct.pack('<4f', *[float(c) for c in ribbon['colour']]), 'CIwFVec4')
        _set(trail, 'colourFadeTime', struct.pack('<f', float(ribbon['fade'])), 'float')
    return resources.encode_entity_spec(spec)


def resources_of(read, data: dict, project_root: Path, effect_hashes: dict | None = None):
    """Every resource the project's own effects and projectiles need:
    [(class name, hash, body, template (group, type))]."""
    from PIL import Image
    out = []
    from . import levels
    _mg, material_type, material = _template(read, MATERIAL_TEMPLATE, MATERIAL)
    texture_type = next(t for t in _mg.types() if t.class_hash == TEXTURE)
    raw_texture = next(r.body for t in _mg.types() if t.class_hash == TEXTURE for r in t.resources
                       if levels.is_raw_texture(r.body))
    emitter_type = next(t for t in _mg.types() if t.class_hash == gfx.EMITTER_SPEC)
    hashes = dict(effect_hashes or {})
    for effect in data.get('effects', []):
        hashes[effect['name']] = effect_hash(effect['name'])
    for effect in data.get('effects', []):
        for i, emitter in enumerate(effect['emitters']):
            png = Path(project_root) / emitter['texture']
            frames, columns = int(emitter.get('frames', 1)), int(emitter.get('columns', 1))
            body = texture_body(png, raw_texture, emitter.get('tint', [255, 255, 255]))
            with Image.open(png) as image:
                width, height = (_pow2(min(side, MAX_TEXTURE)) for side in image.size)
            rows = -(-frames // columns)
            cell = (width // columns, height // rows)
            texture = iw_hash(f'boz_fxt_{effect["name"]}_{i}')
            material_hash = iw_hash(f'boz_fxm_{effect["name"]}_{i}')
            out.append(('CIwTexture', texture, body, texture_type))
            out.append(('CIwMaterial', material_hash, material_body(
                material.body, texture, emitter.get('blend', 'add'), frames, columns, cell), material_type))
            out.append(('CIwGFXEmitterSpec', emitter_name(effect['name'], i),
                        gfx.encode(emitter_raw(emitter, material_hash)), emitter_type))
        _sg, spec_type, _r = _template(read, BURST_TEMPLATE if effect.get('kind') == 'burst' else LASTING_TEMPLATE)
        out.append(('CIsEntitySpec', effect_hash(effect['name']), effect_spec(read, effect), spec_type))
    for projectile in data.get('projectiles', []):
        projectile = upgrade_projectile(projectile)
        _pg, spec_type, _r = _template(read, PROJECTILE_TEMPLATE)
        out.append(('CIsEntitySpec', projectile_hash(projectile['name']),
                    projectile_spec(read, projectile, data, hashes), spec_type))
        ribbon = (projectile.get('pieces') or {}).get('ribbon') or {}
        if ribbon.get('texture'):
            texture = iw_hash(f'boz_proj_{projectile["name"]}_ribbon_t')
            out.append(('CIwTexture', texture, texture_body(Path(project_root) / ribbon['texture'], raw_texture),
                        texture_type))
            out.append(('CIwMaterial', iw_hash(f'boz_proj_{projectile["name"]}_ribbon'),
                        material_body(material.body, texture, 'add'), material_type))
    return out


def apply(read, source: Path, groups: dict, map_name: str, effect_hashes: dict | None = None) -> list[dict]:
    """Put the project's own effects and projectiles in the map's projectiles group; returns
    their runtime entries for boz.effects ({name, hash, kind, behaviour, triggers})."""
    from . import group as group_module
    data = load(source)
    if not data.get('effects') and not data.get('projectiles'):
        return []
    project_root = Path(source).parent
    problems = check(data, project_root, set(effect_hashes or {}))
    if problems:
        raise FxError('; '.join(problems))
    target = groups.get(f'weapon_projectiles_{map_name}.group.bin')
    if target is None:
        raise FxError('the map has no weapon projectiles group for its effects')
    for _cls, value, body, template_type in resources_of(read, data, project_root, effect_hashes):
        existing = next((t for t in target.types() if t.class_hash == template_type.class_hash), None)
        resource = group_module.Resource(None if template_type.names_omitted else value, value, body)
        if existing is None:
            for section in target.sections:
                if section.types is not None:
                    section.types.append(group_module.ResourceType(
                        template_type.class_hash, template_type.names_omitted, template_type.has_size, []))
                    existing = section.types[-1]
                    break
        if existing is None:
            raise FxError('the projectiles group has no resource section')
        existing.resources = [r for r in existing.resources if r.in_group_hash != value]
        if existing.names_omitted != template_type.names_omitted:
            resource.name_hash = None if existing.names_omitted else value
        existing.resources.append(resource)
    out = []
    for effect in data['effects']:
        out.append({'name': effect['name'], 'hash': effect_hash(effect['name']), 'kind': 'effect',
                    'behaviour': 0, 'triggers': [], 'own': True, 'script': script_module(effect.get('script', '')),
                    'pieces': dict(effect.get('pieces') or {})})
    for projectile in data['projectiles']:
        pieces = {k: v for k, v in (projectile.get('pieces') or {}).items() if k != 'ribbon'}
        out.append({'name': projectile['name'], 'hash': projectile_hash(projectile['name']),
                    'kind': 'projectile', 'behaviour': 2, 'triggers': [], 'own': True,
                    'script': script_module(projectile.get('script', '')), 'radius': float(projectile.get('radius', 0)),
                    'speed': float(projectile.get('speed', 3000.0)),
                    'pieces': pieces})
    return out


def script_module(path: str) -> str:
    """A project script path (scripts/projectiles/x.lua) as the name loadscript takes
    (projectiles/x: relative to the mod's scripts folder, without .lua)."""
    if not path:
        return ''
    path = path.replace('\\', '/')
    if path.startswith('scripts/'):
        path = path[len('scripts/'):]
    return path[:-4] if path.endswith('.lua') else path


def needs_game(data: dict) -> list:
    """bozkit.effects.Used entries for the game projectiles the pieces use (the black hole)."""
    from . import effects
    holders = [upgrade_projectile(p) for p in data.get('projectiles', [])] + list(data.get('effects', []))
    if not any('black_hole' in (h.get('pieces') or {}) for h in holders):
        return []
    name, level, value = GERSCH
    return [effects.Used(name, 'projectile', level, value, 6, hidden=True, anchored=True)]


# Copying a game effect -------------------------------------------------------------------------

def _emitter_specs_of(spec) -> list[int]:
    """The emitter specs an entity spec draws (its emitters, its children's, an impact's list)."""
    out = []
    for component in spec.components:
        if component.blob is None:
            continue
        for prop in component.blob.properties:
            if component.type_hash == EMITTER and prop.name_hash == iw_hash('emitterSpec'):
                value = struct.unpack_from('<I', prop.raw)[0]
                if value:
                    out.append(value)
            elif prop.name_hash == iw_hash('m_EmitterNames') and len(prop.raw) >= 4:
                (count,) = struct.unpack_from('<I', prop.raw)
                out += list(struct.unpack_from(f'<{count}I', prop.raw, 4))
    for _cls, _reserved, child in spec.children:
        out += _emitter_specs_of(child)
    return out


def copy_game_effect(pack, effect_hash: int, name: str, source: Path) -> dict:
    """An own effect made from a game effect: its emitters' values, and their textures saved as
    PNGs in source/fx/ (flipbooks kept). Lasting unless the game's is an impact (burst)."""
    from . import bundle
    registry = bundle.Registry.of(pack)

    def find(value, cls):
        return next((e.resource.body for e in registry.entries(value) if e.cls == cls), None)

    body = find(effect_hash, ENTITY_SPEC)
    if body is None:
        raise FxError(f'no game effect 0x{effect_hash:08x}')
    spec = resources.decode_entity_spec(body)
    burst = any(c.type_hash == iw_hash('CImpactEffect') for c in spec.components)
    emitters = []
    for i, value in enumerate(_emitter_specs_of(spec)[:MAX_EMITTERS]):
        emitter_body = find(value, gfx.EMITTER_SPEC)
        if emitter_body is None:
            continue
        raw = gfx.decode(emitter_body)
        emitter = emitter_from_raw(raw)
        material_body = find(raw['material'], MATERIAL)
        if material_body is not None:
            material = native.decode_material(material_body)
            emitter['blend'] = 'blend' if (material.flags >> 16) & 7 == 4 else 'add'
            if material.trailer[:1] == b'\x01' and len(material.trailer) >= 7:
                emitter['frames'], emitter['columns'] = material.trailer[2], max(1, material.trailer[3])
            texture_body_ = find(material.textures[0], TEXTURE) if material.textures else None
            if texture_body_ is not None:
                folder = Path(source) / TEXTURE_DIR
                folder.mkdir(parents=True, exist_ok=True)
                target = folder / f'{name}_{i}.png'
                from PIL import Image
                decoded = native.decode_texture_rgba(texture_body_)
                Image.frombytes('RGBA', (decoded.width, decoded.height), decoded.rgba).save(target)
                emitter['texture'] = f'source/{TEXTURE_DIR}/{target.name}'
        emitters.append(emitter)
    if not emitters:
        raise FxError('that game effect has no particle emitters to copy')
    return {'name': name, 'kind': 'burst' if burst else 'lasting', 'scale': 1.0, 'emitters': emitters}
