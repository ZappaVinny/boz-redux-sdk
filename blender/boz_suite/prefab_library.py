"""The project's prefab library and assets in the asset browser: the "My prefabs" and "My
assets" catalogs of the BOZ Game palette.

Prefabs are saved in the project (source/prefabs, bozkit.world.save_prefab). For the asset
browser, the editor writes ``my_prefabs.blend`` into the palette's folder: one stand-in per
library prefab (an empty carrying the prefab's name, with a preview), marked as an asset in the
"My prefabs" catalog. It is rewritten when the project opens and whenever a prefab is saved or
deleted, so it always holds the open project's prefabs. Dropping one pastes the prefab where it
was dropped (palette.realize).
"""
from __future__ import annotations

import math
import struct
import uuid
from pathlib import Path

import bpy

from ._bozkit import assets, library, png, world

CATALOG = "My prefabs"
ASSET_CATALOG = "My assets"
FILE_NAME = "my_prefabs.blend"
# The palette's catalog ids are uuid5(NAMESPACE, path) (palette_build.py); the same here.
NAMESPACE = uuid.UUID("6d1f1c52-7a0e-4d43-9a58-1f2a6b9c0b11")
COLOUR = (230, 190, 60)


def catalog_id(name: str = CATALOG) -> str:
    return str(uuid.uuid5(NAMESPACE, name))


def palette_dir() -> Path:
    return library.library_dir() / "blender"


def _ensure_catalog() -> None:
    """The palette's catalog file lists My prefabs (palettes built before it existed)."""
    path = palette_dir() / "blender_assets.cats.txt"
    try:
        text = path.read_text(encoding='utf-8')
    except OSError:
        text = "# Blender asset catalogs, written by the BOZ Redux editor\nVERSION 1\n\n"
    for name in (CATALOG, ASSET_CATALOG):
        if catalog_id(name) not in text:
            text = text.rstrip("\n") + f"\n{catalog_id(name)}:{name}:{name}\n"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding='utf-8', newline='\n')


def _set_preview(datablock, width: int, height: int, rgba: bytes) -> None:
    rows = [rgba[y * width * 4:(y + 1) * width * 4] for y in range(height)][::-1]
    preview = datablock.preview_ensure()
    preview.image_size = (width, height)
    preview.image_pixels.foreach_set(struct.unpack(f"<{width * height}i", b"".join(rows)))


def _badge(datablock, size: int = 96) -> None:
    out = bytearray()
    centre, half = (size - 1) / 2, size * 0.38
    for y in range(size):
        for x in range(size):
            # A rounded square: what a prefab (a group) looks like next to the round game badges.
            dx, dy = max(abs(x - centre) - half * 0.6, 0), max(abs(y - centre) - half * 0.6, 0)
            if math.hypot(dx, dy) <= half * 0.4:
                shade = 1.0 - 0.3 * abs(y - centre) / size
                out += bytes(int(c * shade) for c in COLOUR) + b"\xff"
            else:
                out += b"\x00\x00\x00\x00"
    _set_preview(datablock, size, size, bytes(out))


def _preview(datablock, prefab) -> None:
    """The thumbnail of the first game model in the prefab, else a badge."""
    try:
        built = library.Library()
    except Exception:   # noqa: BLE001 - no asset library: badges only
        built = None
    if built is not None:
        try:
            for _full, item in world.walk([prefab]):
                game = getattr(item, "game", "")
                if not game:
                    continue
                path = built.thumb_for("model", world.Instance((0, 0, 0), model=game).model_ref()[1])
                if path and Path(path).is_file():
                    width, height, rgba = png.read_rgba(Path(path).read_bytes())
                    _set_preview(datablock, width, height, rgba)
                    return
        except (ValueError, OSError):
            pass
        finally:
            built.close()
    _badge(datablock)


def rebuild(root: Path | None) -> int:
    """Write the open project's prefabs and assets into the palette's My prefabs and My assets;
    returns how many."""
    folder = palette_dir()
    if not folder.is_dir():
        return 0
    _ensure_catalog()
    target = folder / FILE_NAME
    names = world.library_names(root / "source") if root else []
    stand_ins = set()
    # Object names are unique in a file and the asset browser shows the stand-in's name, so an
    # object of the map with a prefab's name (a placed copy) steps aside while the file is written.
    renamed = {}
    for name in names:
        clash = bpy.data.objects.get(name)
        if clash is not None:
            renamed[clash] = name
            clash.name = f"{name}__boz_library_tmp"
        try:
            prefab, _meshes = world.load_prefab(root / "source", name)
        except world.WorldError:
            continue
        obj = bpy.data.objects.new(name, None)
        obj.empty_display_type = "CUBE"
        obj.empty_display_size = 40.0
        obj["boz_asset_kind"] = "prefab"
        obj["boz_prefab"] = name
        obj.asset_mark()
        obj.asset_data.catalog_id = catalog_id()
        parts = len(prefab.parts)
        obj.asset_data.description = f"Your prefab: {parts} part{'s' if parts != 1 else ''}" + \
            (f", script {prefab.script}" if prefab.script else "")
        _preview(obj, prefab)
        stand_ins.add(obj)
    for name, obj in _asset_stand_ins(root):
        renamed_clash = bpy.data.objects.get(name)
        if renamed_clash is not None and renamed_clash is not obj:
            renamed[renamed_clash] = renamed_clash.name
            renamed_clash.name = f"{name}__boz_library_tmp"
        obj.name = name
        stand_ins.add(obj)
    try:
        if stand_ins:
            bpy.data.libraries.write(str(target), stand_ins, fake_user=True, compress=True)
        elif target.exists():
            target.unlink()
    finally:
        for obj in stand_ins:
            bpy.data.objects.remove(obj)
        for obj, name in renamed.items():
            obj.name = name
    refresh_browsers()
    return len(stand_ins)


def _asset_preview(datablock, source: Path, name: str) -> None:
    """A three-quarter view of the asset's game version, coloured by its textures."""
    try:
        model, textures = assets.load_game(source, name)
        colours = []
        for texture in textures:
            data = texture.bgra
            colours.append(tuple(sum(data[i::4][:4096]) // max(1, len(data[i::4][:4096]))
                                 for i in (2, 1, 0)))
        flat = type("Flat", (), {"vertices": model.vertices, "triangles": model.triangles})
        image = library.render_model(flat, lambda i: colours[model.materials[i]] if model.materials
                                     else colours[0])
    except Exception:   # noqa: BLE001 - no Pillow or no game version: a badge
        image = None
    if image is None:
        _badge(datablock)
        return
    width, height = image.size
    _set_preview(datablock, width, height, image.convert("RGBA").tobytes())


def _asset_stand_ins(root: Path | None):
    """(name, stand-in) for each made asset of the project, in the My assets catalog."""
    if root is None:
        return []
    source = root / "source"
    out = []
    folder = assets.assets_dir(source)
    for path in sorted(folder.glob("*.json")) if folder.is_dir() else []:
        try:
            asset = assets.load_def(source, path.stem)
        except assets.AssetError:
            continue
        if not assets.has_game(source, asset.name):
            continue
        obj = bpy.data.objects.new(asset.name, None)
        obj.empty_display_type = "CUBE"
        obj.empty_display_size = 30.0
        obj["boz_asset_kind"] = "asset"
        obj["boz_asset"] = asset.name
        obj.asset_mark()
        obj.asset_data.catalog_id = catalog_id(ASSET_CATALOG)
        stats = assets.load_stats(source, asset.name)
        obj.asset_data.description = f"Your {asset.kind}: {stats.get('triangles', '?')} triangles"
        _asset_preview(obj, source, asset.name)
        out.append((asset.name, obj))
    return out


def refresh_browsers() -> None:
    for window in getattr(bpy.context.window_manager, "windows", []):
        for area in window.screen.areas:
            if area.type == "FILE_BROWSER" and area.ui_type == "ASSETS":
                try:
                    with bpy.context.temp_override(window=window, area=area):
                        bpy.ops.asset.library_refresh()
                except RuntimeError:
                    pass
