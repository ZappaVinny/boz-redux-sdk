"""The weapon pictures on the HUD (top right, beside the ammo count).

Every weapon's HUD picture is a rectangle of one shared texture, ``hud_icons`` (1024 x 1024,
16-bit) in ``ingame/ingame.group.bin``: a weapon's ``m_uv0`` and ``m_uv1`` (``CIwSVec2``: x, y in
pixels) are its corners, and the HUD's ``weapon_icon`` element (a ``CUIWeaponIcon``) shows that
rectangle (CHUDManager::UpdateWeapon). Stock pictures are 177 x 58: a grey, lit, grainy side view
of the gun with a dark shadow down and to the right.

A project weapon's icon (``WeaponDef.icon``) is one of:

- ``{}``: its base weapon's picture;
- ``{"like": "<weapon>"}``: another weapon's picture (any map's);
- ``{"image": "<file>"}``: a picture of its own (``source/weapons/icons/<file>``, PNG with
  transparency). The build fits it into a free spot of the atlas, ships the patched
  ``ingame.group.bin`` in the map mod (the client serves it by name) and points the weapon at it.
"""
from __future__ import annotations

import struct
from pathlib import Path

from .hashing import iw_hash
from . import spec_fields

INGAME = 'ingame/ingame.group.bin'
ATLAS = iw_hash('hud_icons')
TEXTURE = iw_hash('CIwTexture')
SVEC2 = iw_hash('CIwSVec2')
SIZE = (177, 58)          # a stock picture's rectangle
SLOT = (SIZE[0] + 3, SIZE[1] + 2)   # the free space one needs (with a margin)
# Own pictures go in rows added below the stock sheet: its transparent parts are not free (the hit
# overlay and other HUD art draw from them). The sheet's rectangles are in pixels, so the stock
# ones stay where they are.
EXTRA_HEIGHT = 1024


class IconError(ValueError):
    pass


def icons_dir(source: Path) -> Path:
    return Path(source) / 'weapons' / 'icons'


# --- Weapons' rectangles ------------------------------------------------------------------

def uv_of(blob) -> tuple[int, int, int, int] | None:
    """(x0, y0, x1, y1) of a CPlayerWeapon blob's HUD picture, or None."""
    first, second = spec_fields.prop(blob, 'm_uv0'), spec_fields.prop(blob, 'm_uv1')
    if first is None or second is None or len(first.raw) < 4 or len(second.raw) < 4:
        return None
    return struct.unpack('<hh', first.raw[:4]) + struct.unpack('<hh', second.raw[:4])


def set_uv(blob, rect: tuple[int, int, int, int]) -> None:
    """Point a CPlayerWeapon blob at a rectangle of the atlas."""
    from . import reflect
    from .weapons import PLAYER_WEAPON
    for name, values in (('m_uv0', rect[:2]), ('m_uv1', rect[2:])):
        prop = spec_fields.prop(blob, name)
        raw = struct.pack('<hh', *values)
        if prop is None:
            blob.properties.append(reflect.Property(PLAYER_WEAPON, SVEC2, iw_hash(name), raw))
        else:
            prop.raw = raw
            prop.nested = prop.elements = None


def game_uv(pack, weapon: str) -> tuple[int, int, int, int] | None:
    """The HUD rectangle of a shipped weapon (any map's), or None."""
    from . import bundle, resources, weapons
    target = weapons.hash_of(weapon)
    for entry in bundle.Registry.of(pack).entries(target):
        if entry.cls != bundle.ENTITY_SPEC:
            continue
        try:
            blob = weapons.weapon_blob(resources.decode_entity_spec(entry.resource.body))
        except Exception:   # noqa: BLE001
            continue
        rect = uv_of(blob) if blob is not None else None
        if rect is not None:
            return rect
    return None


# --- The atlas ----------------------------------------------------------------------------

def atlas_resource(parsed):
    """The hud_icons texture resource of a parsed ingame group, or None."""
    for resource_type in parsed.types():
        if resource_type.class_hash == TEXTURE:
            for resource in resource_type.resources:
                if resource.in_group_hash == ATLAS:
                    return resource
    return None


def atlas_image(parsed):
    from . import native
    resource = atlas_resource(parsed)
    if resource is None:
        raise IconError('the game has no hud_icons texture')
    return native.decode_texture(resource.body).convert('RGBA')


def fit(picture):
    """A picture fitted into a stock rectangle: cropped to what it shows, scaled to fit (kept
    in proportion), centred."""
    from PIL import Image
    picture = picture.convert('RGBA')
    box = picture.getchannel('A').getbbox()
    if box is None:
        raise IconError('the picture is empty (fully transparent)')
    picture = picture.crop(box)
    scale = min((SIZE[0] - 2) / picture.width, (SIZE[1] - 2) / picture.height)
    size = (max(1, round(picture.width * scale)), max(1, round(picture.height * scale)))
    picture = picture.resize(size, Image.LANCZOS)
    out = Image.new('RGBA', SIZE, (0, 0, 0, 0))
    out.alpha_composite(picture, ((SIZE[0] - size[0]) // 2, (SIZE[1] - size[1]) // 2))
    return out


# --- The touch sticks ---------------------------------------------------------------------

STICKS = iw_hash('HUD_ALL')
STICK_RECTS = ((0, 0, 257, 236), (257, 0, 92, 72), (625, 431, 80, 80))


def hide_sticks(parsed) -> bool:
    """Make the on-screen joystick art of HUD_ALL transparent, as the client does to the shipped
    ingame group (codboz_hide_virtual_stick_artwork: it only knows the shipped file's size, so a
    patched copy needs it done here). Returns True when the art was found."""
    import numpy as np
    from PIL import Image
    from . import native
    for resource_type in parsed.types():
        if resource_type.class_hash != TEXTURE:
            continue
        for resource in resource_type.resources:
            if resource.in_group_hash != STICKS:
                continue
            pixels = np.array(native.decode_texture(resource.body).convert('RGBA'))
            for x, y, w, h in STICK_RECTS:
                pixels[y:y + h, x:x + w, 3] = 0
            resource.body = native.encode_texture(Image.fromarray(pixels, 'RGBA'), resource.body)
            return True
    return False


# --- The build ----------------------------------------------------------------------------

def apply(source: Path, defs, read, groups: dict, map_name: str, pack=None) -> list[str]:
    """Give the project's weapons their icons: copies of other weapons' rectangles, or their own
    pictures painted into free spots of a patched hud_icons (added to *groups* as
    ingame.group.bin, or the copy already there). Returns what it did, for the build log."""
    from PIL import Image
    from . import group as group_module, native, resources, weapons
    wanted = [d for d in defs if getattr(d, 'icon', None)]
    if not wanted:
        return []
    weapons_group = groups.get(f'weapons_{map_name}.group.bin')
    if weapons_group is None:
        raise IconError('the map has no weapons group')
    specs = {r.in_group_hash: r for r in weapons.entity_specs(weapons_group).resources}
    done, atlas, parsed, slots = [], None, None, None
    for weapon in wanted:
        resource = specs.get(weapons.hash_of(weapon.name))
        if resource is None:
            raise IconError(f'weapon {weapon.name} is not in the map')
        spec = resources.decode_entity_spec(resource.body)
        blob = weapons.weapon_blob(spec)
        like, image = weapon.icon.get('like'), weapon.icon.get('image')
        if like:
            other = specs.get(weapons.hash_of(like))
            rect = uv_of(weapons.weapon_blob(resources.decode_entity_spec(other.body))) \
                if other is not None else None
            if rect is None and pack is not None:
                rect = game_uv(pack, like)
            if rect is None:
                raise IconError(f'weapon {weapon.name}: no weapon {like} to take the icon of')
            done.append(f'{weapon.name}: the icon of {like}')
        elif image:
            path = icons_dir(source) / image
            if not path.is_file():
                raise IconError(f'weapon {weapon.name}: no icon picture {path.name} (Weapons tab → HUD icon)')
            if atlas is None:
                parsed = groups.get('ingame.group.bin')
                if parsed is None:
                    parsed = group_module.read_parsed(read, INGAME)
                atlas = atlas_image(parsed)
                stock_height = atlas.height
                slots = [(x, stock_height + y) for y in range(0, EXTRA_HEIGHT - SIZE[1] + 1, SIZE[1] + 2)
                         for x in range(0, atlas.width - SIZE[0] + 1, SIZE[0] + 3)]
                grown = Image.new('RGBA', (atlas.width, stock_height + EXTRA_HEIGHT), (0, 0, 0, 0))
                grown.paste(atlas, (0, 0))
                atlas = grown
            if not slots:
                raise IconError(f'weapon {weapon.name}: no room left for pictures of your own')
            x, y = slots.pop(0)
            with Image.open(path) as picture:
                fitted = fit(picture)
            atlas.paste(fitted, (x, y))
            rect = (x, y, x + SIZE[0], y + SIZE[1])
            done.append(f'{weapon.name}: its own icon at {x},{y}')
        else:
            continue
        set_uv(blob, rect)
        resource.body = resources.encode_entity_spec(spec)
    if atlas is not None:
        resource = atlas_resource(parsed)
        resource.body = native.encode_texture(atlas, resource.body)
        groups['ingame.group.bin'] = parsed
    return done


def preview(pack, source: Path, weapon, base_level: str = ''):
    """The picture a weapon will show on the HUD (PIL RGBA, 177 x 58), or None: its own fitted
    picture, or the rectangle it points at in the shipped atlas."""
    from PIL import Image
    from . import group as group_module
    icon = getattr(weapon, 'icon', None) or {}
    if icon.get('image'):
        path = icons_dir(source) / icon['image']
        if not path.is_file():
            return None
        with Image.open(path) as picture:
            return fit(picture)
    if pack is None:
        return None
    rect = game_uv(pack, icon.get('like') or weapon.source)
    if rect is None:
        return None
    parsed = group_module.read_parsed(pack.read, INGAME)
    return atlas_image(parsed).crop(rect)
