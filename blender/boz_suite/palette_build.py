"""Build the editor's palettes: a Blender asset library made from the SDK's asset library.

Run in background Blender by palette.py:

    blender -b --factory-startup --python palette_build.py -- <bozkit dir> <library dir> <out dir>

Writes ``<out dir>/boz_game_assets.blend`` and ``blender_assets.cats.txt`` with:

- **Toolkit**: one curated piece for each thing a map needs (bozkit.toolkit), resolved to a
  working entity of the project's base level when it is dropped;
- **Models** and **Textures**: every model and texture in the game, for use anywhere.

Assets are light stand-ins (an empty, or a material without its image) carrying what they place
in custom properties, with the library's preview. palette.py turns a dropped one into the real
thing.
"""
import math
import struct
import sys
import uuid
from pathlib import Path

import bpy

bozkit_dir, library_dir, out_dir = (Path(value) for value in sys.argv[sys.argv.index("--") + 1:][:3])
sys.path.insert(0, str(bozkit_dir))
from bozkit import library, png, toolkit  # noqa: E402
from bozkit.hashing import iw_hash  # noqa: E402

NAMESPACE = uuid.UUID("6d1f1c52-7a0e-4d43-9a58-1f2a6b9c0b11")
ICON_COLOURS = {"Spawns": (200, 60, 60), "Jump points": (230, 230, 230), "Sound": (50, 170, 170),
                "Defence": (150, 110, 70), "Buying": (210, 130, 50), "Machines": (120, 90, 200),
                "Doors": (230, 140, 30), "Barricades": (190, 130, 80),
                "trigger": (50, 215, 190), "hit": (240, 70, 50), "use": (90, 240, 80)}
VOLUMES = (("trigger", "Trigger volume", "An invisible box: scripts hear \"enter\" and \"exit\""),
           ("hit", "Hit volume", "An invisible box: scripts hear \"hit\" when it is shot"),
           ("use", "Use volume", "An invisible box: scripts hear \"use\" when a player presses use"))
catalogs: dict[str, str] = {}


def catalog(path: str) -> str:
    if path not in catalogs:
        catalogs[path] = str(uuid.uuid5(NAMESPACE, path))
    return catalogs[path]


def set_preview(datablock, width: int, height: int, rgba: bytes) -> None:
    rows = [rgba[y * width * 4:(y + 1) * width * 4] for y in range(height)][::-1]
    image = datablock.preview_ensure()
    image.image_size = (width, height)
    image.image_pixels.foreach_set(struct.unpack(f"<{width * height}i", b"".join(rows)))


def preview_file(datablock, path) -> bool:
    if path is None or not Path(path).is_file():
        return False
    try:
        width, height, rgba = png.read_rgba(Path(path).read_bytes())
    except ValueError:
        return False
    set_preview(datablock, width, height, rgba)
    return True


def icon(datablock, colour, size: int = 96) -> None:
    """A plain round badge for pieces that draw nothing in the game (spawns, logic)."""
    out = bytearray()
    centre, radius = (size - 1) / 2, size * 0.42
    for y in range(size):
        for x in range(size):
            distance = math.hypot(x - centre, y - centre)
            if distance <= radius:
                shade = 1.0 - 0.35 * distance / radius
                out += bytes((int(colour[0] * shade), int(colour[1] * shade),
                              int(colour[2] * shade), 255))
            else:
                out += bytes((0, 0, 0, 0))
    set_preview(datablock, size, size, bytes(out))


def describe(datablock, catalog_path: str, description: str, tags=()) -> None:
    datablock.asset_mark()
    data = datablock.asset_data
    data.catalog_id = catalog(catalog_path)
    data.description = description
    for tag in tags:
        data.tags.new(tag, skip_if_exists=True)


def main() -> None:
    built = library.Library(library_dir)
    pack = library.LibraryPack(library_dir)
    names = {}
    for line in (library_dir / "names.txt").read_text(encoding="latin-1").split():
        names.setdefault(iw_hash(line), line)
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj)
    collection = bpy.context.scene.collection
    count = 0
    for piece in toolkit.all_pieces(pack):
        found = None
        for base in ("kino", "callofthedead", "ascension", "tutorial"):
            found = toolkit.resolve(pack, base, piece.key, names)
            if found is not None:
                break
        if found is None:
            continue
        obj = bpy.data.objects.new(piece.label, None)
        obj.empty_display_type = "PLAIN_AXES"
        obj.empty_display_size = 40.0
        obj["boz_asset_kind"] = "piece"
        obj["boz_piece"] = piece.key
        collection.objects.link(obj)
        describe(obj, piece.catalog, piece.description)
        group_name = piece.catalog.split("/")[-1]
        if not (found.model and preview_file(obj, built.thumb_for("model", found.model))):
            icon(obj, ICON_COLOURS.get(group_name, (120, 120, 120)))
        count += 1
    for kind, label, description in VOLUMES:
        obj = bpy.data.objects.new(label, None)
        obj.empty_display_type = "CUBE"
        obj.empty_display_size = 50.0
        obj["boz_asset_kind"] = "volume"
        obj["boz_volume"] = kind
        collection.objects.link(obj)
        describe(obj, "Volumes", description)
        icon(obj, ICON_COLOURS[kind])
        count += 1
    for kind in ("model", "texture"):
        for asset in built.search(kind=kind, limit=100000):
            if not asset.thumb:
                continue
            level = library.MAPS.get(asset.maps[0], "Shared") if asset.maps else "Shared"
            tags = [library.MAPS.get(m, "Shared") for m in asset.maps]
            source = f"{asset.groups[0]}#0x{asset.hash:08x}"
            if kind == "texture":
                material = bpy.data.materials.new(asset.title)
                material["boz_asset_texture"] = source
                describe(material, f"Textures/{level}", asset.label or asset.name, tags)
                preview_file(material, built.thumb_path(asset))
            else:
                obj = bpy.data.objects.new(asset.title, None)
                obj.empty_display_type = "PLAIN_AXES"
                obj.empty_display_size = 40.0
                obj["boz_asset_kind"] = "model"
                obj["boz_source"] = source
                collection.objects.link(obj)
                describe(obj, f"Models/{level}", asset.label or asset.name, tags)
                preview_file(obj, built.thumb_path(asset))
            count += 1
    catalog("My prefabs")   # the open project's prefabs (prefab_library.py writes my_prefabs.blend)
    out_dir.mkdir(parents=True, exist_ok=True)
    lines = ["# Blender asset catalogs, written by the BOZ Redux editor", "VERSION 1", ""]
    for path, identifier in sorted(catalogs.items()):
        lines.append(f"{identifier}:{path}:{path.replace('/', '-')}")
    (out_dir / "blender_assets.cats.txt").write_text("\n".join(lines) + "\n")
    bpy.ops.wm.save_as_mainfile(filepath=str(out_dir / "boz_game_assets.blend"), compress=True)
    print(f"BOZ_PALETTE_OK {count}")


main()
