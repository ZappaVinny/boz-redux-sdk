"""The palettes: the game's props, triggers, effects, models and textures as a Blender asset
library ("BOZ Game") shown in the World tab's asset browser.

The asset file is built from the SDK's asset library by palette_build.py in a background
Blender, the first time the editor opens and whenever the library changes. Assets are light
stand-ins; when one is dropped into the world it becomes the real entity, model or texture.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import bpy
from bpy.app.handlers import persistent

from ._bozkit import library, world

from . import convert, game
from . import link

LIBRARY_NAME = "BOZ Game"
PALETTE_VERSION = 6   # 6: My prefabs catalog
_build = {"process": None}


def palette_dir() -> Path:
    return library.library_dir() / "blender"


def _stamp() -> dict | None:
    try:
        source = json.loads((library.library_dir() / "stamp.json").read_text())
    except (OSError, ValueError):
        return None
    return {"palette": PALETTE_VERSION, "library": source}


def needs_build() -> bool:
    stamp = _stamp()
    if stamp is None:
        return False      # no asset library yet: nothing to build from
    try:
        return json.loads((palette_dir() / "stamp.json").read_text()) != stamp
    except (OSError, ValueError):
        return True


def register_library() -> None:
    libraries = bpy.context.preferences.filepaths.asset_libraries
    entry = libraries.get(LIBRARY_NAME)
    if entry is None:
        entry = libraries.new(name=LIBRARY_NAME, directory=str(palette_dir()))
    entry.path = str(palette_dir())
    entry.import_method = "APPEND"
    show_palette()


def show_palette() -> None:
    """Point every asset browser at the game's palette (not Blender's own assets)."""
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type != "FILE_BROWSER" or area.ui_type != "ASSETS":
                continue
            for space in area.spaces:
                params = getattr(space, "params", None)
                if params is not None and hasattr(params, "asset_library_reference"):
                    try:
                        params.asset_library_reference = LIBRARY_NAME
                    except TypeError:
                        pass
            area.tag_redraw()


def start_build() -> bool:
    """Start building the palette in the background; False when one is running or not needed."""
    if _build["process"] is not None or not needs_build():
        return False
    here = Path(__file__).resolve().parent
    vendor = here / "_vendor"
    bozkit_dir = vendor if (vendor / "bozkit").is_dir() else here.parents[1] / "tools" / "bozkit"
    command = [bpy.app.binary_path, "-b", "--factory-startup", "--python",
               str(here / "palette_build.py"), "--", str(bozkit_dir), str(library.library_dir()),
               str(palette_dir())]
    _build["process"] = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                         text=True)
    return True


def poll_build():
    """Timer: finish a background palette build."""
    process = _build["process"]
    if process is None:
        if needs_build():
            start_build()
            _log("palette", "building the palettes from the asset library (about a minute)")
        elif palette_dir().is_dir():
            register_library()
            return None
        return 2.0
    if process.poll() is None:
        return 2.0
    output = process.stdout.read() if process.stdout else ""
    _build["process"] = None
    if "BOZ_PALETTE_OK" in output:
        (palette_dir() / "stamp.json").write_text(json.dumps(_stamp(), indent=2) + "\n")
        register_library()
        from . import link, prefab_library
        prefab_library.rebuild(link.project_root())
        count = output.split("BOZ_PALETTE_OK", 1)[1].split()[0]
        _log("palette", f"palettes ready: {count} game assets in the World tab's asset browser")
        return None
    _log("palette", "the palettes could not be built: " + output.strip().splitlines()[-1:][0]
         if output.strip() else "the palettes could not be built")
    return None


def _log(tag: str, text: str) -> None:
    from . import link
    link.append_log(f"{tag:<5} {text}")


def _pending(scene) -> bool:
    return any("boz_asset_kind" in obj for obj in scene.objects) or any(
        "boz_asset_texture" in m and not m.get("boz_realized") for m in bpy.data.materials
        if m.users)


def realize() -> None:
    """Turn dropped palette assets into the real entity, model or texture."""
    scene = link.map_scene()
    for obj in [o for o in scene.objects if "boz_asset_kind" in o]:
        kind, source = obj["boz_asset_kind"], obj.get("boz_source", "")
        position, rotation, _scale = convert.game_transform(obj)
        label = obj.name.split(".")[0]
        made = None
        if kind == "piece":
            made = _place_piece(scene, obj["boz_piece"], label, position, rotation)
        elif kind == "entity":
            made = convert.game_prefab_object(world.Prefab(label, position, rotation,
                                                           source=source,
                                                           group=obj.get("boz_group", "")),
                                              scene.boz.base, scene)
        elif kind == "prefab":
            from . import objects
            made = objects.place_library_prefab(scene, obj.get("boz_prefab", ""), position, rotation)
            if made is not None:
                label = made.name
        elif kind == "asset":
            from . import assets_tab
            made = assets_tab.place_asset(scene, obj.get("boz_asset", ""), position, rotation)
            if made is not None:
                label = made.name
        elif kind == "volume":
            made = convert.volume_object(world.Volume(label, obj.get("boz_volume", "trigger"),
                                                      position, rotation), scene)
        else:
            made = convert.model_object(world.Model(label, position, rotation, game=source,
                                                    collision="solid", shape="box"), scene)
            _land_at(made, convert.world_matrix(obj).translation)
        bpy.data.objects.remove(obj)
        if made is None:
            continue
        if kind not in ("prefab", "asset"):
            made.name = convert.clean_name(label)
        for other in bpy.context.selected_objects:
            other.select_set(False)
        made.select_set(True)
        bpy.context.view_layer.objects.active = made
    for material in [m for m in bpy.data.materials if "boz_asset_texture" in m
                     and not m.get("boz_realized") and m.users]:
        path, _, value = material["boz_asset_texture"].partition("#")
        built = game.texture_material(path, int(value, 16))
        material["boz_realized"] = True
        if built is None:
            continue
        # The dropped stand-in gives way to a game-shaded material on every object using it.
        for obj in scene.objects:
            if obj.type != "MESH":
                continue
            for slot in obj.material_slots:
                if slot.material == material:
                    slot.material = built
                    game.ensure_colour(obj.data)
        if material.users == 0:
            bpy.data.materials.remove(material)


def _land_at(obj, point) -> None:
    """Move a dropped game model so its geometry (often far from its own origin: rooms are built
    in place) sits where it was dropped: the bottom centre of its bounds at *point*."""
    if obj.type != "MESH" or not obj.data.vertices:
        return
    from mathutils import Vector

    # Just made: neither matrix_world nor bound_box is evaluated yet, so use the object's own
    # transform and its mesh's vertices.
    matrix = convert.world_matrix(obj)
    points = [v.co for v in obj.data.vertices]
    low = Vector(tuple(min(p[i] for p in points) for i in range(3)))
    high = Vector(tuple(max(p[i] for p in points) for i in range(3)))
    corners = [matrix @ Vector((x, y, z)) for x in (low.x, high.x) for y in (low.y, high.y)
               for z in (low.z, high.z)]
    bottom = Vector(((min(c.x for c in corners) + max(c.x for c in corners)) / 2,
                     (min(c.y for c in corners) + max(c.y for c in corners)) / 2,
                     min(c.z for c in corners)))
    obj.location += point - bottom


def _place_piece(scene, key: str, label: str, position, rotation):
    """A toolkit piece resolved on the project's base level, with its settings."""
    found = game.resolve_piece(scene.boz.base, key)
    if found is None:
        _log("check", f"{label} is not available on the {scene.boz.base} base level")
        return None
    source = found.name
    if key == "player_spawn":
        taken = {world.Placement(o.boz.source, (0, 0, 0)).hash for o in scene.objects
                 if o.boz.role == "prefab" and o.boz.source}
        free = [f"spawn_player_{n}" for n in range(1, 5)
                if world.Placement(f"spawn_player_{n}", (0, 0, 0)).hash not in taken]
        if not free:
            _log("check", "the map already has all four player spawns")
            return None
        source = free[0]
    return convert.game_prefab_object(world.Prefab(label, position, rotation, source=source,
                                                   group=found.group, piece=key,
                                                   settings=dict(found.defaults)),
                                      scene.boz.base, scene)


def _realize_timer():
    try:
        realize()
    except (ReferenceError, RuntimeError, ValueError, KeyError) as exc:
        print(f"boz_suite: a dropped asset could not be placed: {exc}")
    return None


@persistent
def on_depsgraph(scene, _depsgraph=None):
    if _pending(scene) and not bpy.app.timers.is_registered(_realize_timer):
        bpy.app.timers.register(_realize_timer, first_interval=0.05)


def register():
    bpy.app.handlers.depsgraph_update_post.append(on_depsgraph)
    if not bpy.app.background:
        bpy.app.timers.register(poll_build, first_interval=3.0, persistent=True)


def unregister():
    if on_depsgraph in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(on_depsgraph)
    if bpy.app.timers.is_registered(poll_build):
        bpy.app.timers.unregister(poll_build)
