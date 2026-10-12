"""The editor (boz_suite app template) in background Blender. Run with run_suite_test.py, which
builds the suite, makes a map project and starts Blender with it."""
import os
import sys
from pathlib import Path

import bpy

suite = sys.modules["bl_app_templates_user.boz_suite"]
link, tabs, placeholders, convert = suite.link, suite.tabs, suite.placeholders, suite.convert
objects_ui = suite.objects
world = link.world
LIBRARY = bool(os.environ.get("BOZ_TEST_LIBRARY"))
PICKUP = "ingame/pickups/pickups.group.bin#0x105caeb0"


def check(condition, message):
    if not condition:
        print(f"BOZ_SUITE_FAILED: {message}")
        sys.exit(1)


def select_only(*objects, active=None):
    for other in bpy.context.selected_objects:
        other.select_set(False)
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = active or objects[-1]


def same_rotation(a, b):
    return abs(sum(x * y for x, y in zip(a, b))) > 0.9999   # q and -q are the same rotation


project = Path(os.environ["BOZ_PROJECT"])
scene = bpy.context.scene

# The shell
check(set(tabs.TAB_NAMES) <= {w.name for w in bpy.data.workspaces}, "every tab exists")
check("Shading" not in bpy.data.workspaces, "unused factory workspaces are gone")
check("boz_redux" in bpy.context.preferences.addons, "the shipped-map add-on is enabled")
registered = [name for name in dir(bpy.types) if name.startswith("BOZ_PT_placeholder")]
check(len(registered) == len(placeholders.PLACEHOLDERS), "every placeholder has a panel")
check(not bpy.types.OBJECT_PT_relations.poll(bpy.context), "stock object panels are hidden")
check(bpy.types.TOPBAR_HT_upper_bar.draw_left.__module__.endswith("shell"), "the top bar is ours")
check(scene.unit_settings.scale_length < 0.011, "one unit is a centimetre")

source = world.load(project / "source")


def build_and_compile(label):
    bpy.ops.wm.save_as_mainfile(filepath=str(project / "map.blend"))
    saved = world.load(project / "source")
    check(world.validate(saved) == [], f"{label}: the saved world is valid ({world.validate(saved)})")
    if LIBRARY:
        sdk_project = link.sdk_project
        built = sdk_project.load_project(project)
        output, _report = sdk_project.build_project(built, game=suite.palette.library.LibraryPack())
        data = (output / "scripts" / "boz" / "world_data.lua").read_text()
        check((output / "scripts" / "boz" / "prefabs.lua").is_file(),
              f"{label}: the map runtime is installed")
        return saved, data
    return saved, ""


class FakeLayout:
    """Stands in for a panel's layout: accepts every call, and checks that the properties it is
    asked to show exist (catches typos in draw code, which only runs with a window)."""

    def __getattr__(self, name):
        return lambda *args, **kwargs: FakeLayout()

    def prop(self, data, name, **kwargs):
        if name.startswith('["'):
            check(name[2:-2] in data.keys(), f"panel shows a missing custom property {name}")
        else:
            check(hasattr(data, name), f"panel shows a missing property {name}")
        return FakeLayout()


class FakeContext:
    def __init__(self, obj):
        self.object = obj
        self.scene = scene
        self.window_manager = bpy.context.window_manager


def draw_panels(label):
    """Every object panel, for one object of each kind in the scene."""
    seen = {}
    for obj in scene.objects:
        key = (obj.boz.role, bool(obj.boz.source), obj.boz.original, obj.type)
        seen.setdefault(key, obj)
    panels = [objects_ui.BOZ_PT_object, link.BOZ_PT_textures]
    for obj in seen.values():
        for panel in panels:
            fake = type("Panel", (), {"layout": FakeLayout()})()
            if panel is link.BOZ_PT_textures and obj.type != "MESH":
                continue
            try:
                panel.draw(fake, FakeContext(obj))
            except Exception as exc:   # noqa: BLE001 - report what broke and where
                check(False, f"{label}: {panel.__name__} fails for {obj.name}: {exc!r}")
    fake = type("Panel", (), {"layout": FakeLayout()})()
    objects_ui.BOZ_MT_prefab_library.draw(fake, FakeContext(None))
    suite.preview.BOZ_PT_show.draw(fake, FakeContext(None))
    return len(seen)


def prefab_checks(anchor):
    """Make prefab, a script with properties, Save as new prefab, place an independent copy."""
    bpy.ops.boz.add_shape(kind="wall")
    wall = bpy.context.view_layer.objects.active
    wall.location = (anchor[0], anchor[1], anchor[2])
    check(wall.boz.role == "model" and not wall.boz.source and wall.boz.collision == "solid"
          and wall.boz.shape == "box", "a game shape is a model of your own, colliding as a box")
    wall.boz.padding = 10.0
    bpy.context.view_layer.update()
    corners = suite.preview.collision_box(wall)
    span = max(c.x for c in corners) - min(c.x for c in corners)
    check(abs(span - 320.0) < 0.5, f"the drawn collision box is the wall plus its padding ({span})")
    trigger = convert.volume_object(world.Volume("Skull", "hit", size=(40.0, 40.0, 40.0)), scene)
    trigger.location = (anchor[0], anchor[1], anchor[2] + 150.0)
    check(trigger.type == "EMPTY" and trigger.instance_type == "COLLECTION"
          and trigger.instance_collection.name == "BOZ Volume: hit",
          "a volume is an Empty showing its kind's box (its own outliner icon)")
    old_style = bpy.data.objects.new("OldUse", convert.volume_mesh())
    scene.collection.objects.link(old_style)
    old_style.boz.role, old_style.boz.volume, old_style.boz.cost = "volume", "use", 250
    old_style.scale = (2.0, 1.0, 1.0)
    check(convert.migrate_volumes(scene) == 1, "a volume saved as a mesh migrates")
    migrated = scene.objects["OldUse"]
    check(migrated.type == "EMPTY" and migrated.boz.cost == 250 and migrated.scale[0] == 2.0
          and migrated.instance_collection.name == "BOZ Volume: use",
          "the migrated volume keeps its settings and size")
    bpy.data.objects.remove(migrated)
    select_only(wall, trigger)
    bpy.ops.boz.make_prefab()
    prefab = bpy.context.view_layer.objects.active
    check(convert.is_prefab_group(prefab) and set(prefab.children) == {wall, trigger},
          "Make prefab groups the selection")
    check(bpy.ops.boz.make_prefab() == {"CANCELLED"} and prefab.parent is None,
          "Make prefab does not wrap a single prefab again")
    check(all(o.users_collection[0].name == convert.MAP_COLLECTION for o in (prefab, wall, trigger)),
          "the prefab and its parts sit in the Map collection")
    prefab.name = "Vault"
    convert.sync_part_names(scene)
    check(trigger.name == "Vault" + convert.PART_SEPARATOR + trigger.boz.part_name,
          f"parts are named after their prefab in the outliner ({trigger.name})")
    wall.boz.part_name = "Door"
    check(wall.name == "Vault › Door", f"a new part name renames its object ({wall.name})")
    wall.boz.blocks = True
    wall.boz.block_margin = 55.0
    # A script with properties (made as New script would).
    relative = objects_ui.scripts.new_script(project / "scripts", "Vault")
    (project / "scripts" / relative).write_text(
        '---@property delay number 2 "Seconds"\n---@property armed bool true\n'
        'function on_hit(volume, info)\n    self:part("Door"):hide()\nend\n')
    prefab.boz.script = relative
    objects_ui.sync_properties(prefab)
    check(prefab.get("boz_p:delay") == 2.0 and prefab.get("boz_p:armed") is True,
          "the script's properties show with their defaults")
    prefab["boz_p:delay"] = 5.0
    # Scripts are edited in the Scripts tab; saving the map writes them to their files.
    text = objects_ui.show_script(bpy.context, project / "scripts" / relative)
    check(objects_ui.watch_browser() == 0.25, "the Scripts file browser watcher runs")
    text.write("\n-- edited in the Scripts tab\n")
    check(objects_ui.save_scripts() == 1 and "edited in the Scripts tab"
          in (project / "scripts" / relative).read_text(), "an edited script is saved to its file")
    problems = []
    back = link.scene_to_world(scene, problems)
    vault = next((p for p in back.prefabs if p.name == "Vault"), None)
    check(vault is not None and [p.name for p in vault.parts] == ["Door", "Skull"]
          and vault.properties == {"delay": 5.0, "armed": True} and vault.script == relative,
          f"the prefab is written with its parts and property values ({vault}, {problems})")
    door = vault.parts[0]
    check(abs(door.position[1]) < 0.01 and door.start == {"blocks": True} and door.padding == 10.0
          and door.block_margin == 55.0,
          f"parts are written in the prefab's space, with their padding ({door})")
    # The library: save, place a copy at the cursor, edit the copy only.
    select_only(prefab)
    check(bpy.ops.boz.save_prefab(name="Vault") == {"FINISHED"}, "Save as new prefab")
    check(world.library_names(project / "source") == ["Vault"], "the prefab is in the library")
    if LIBRARY:
        # In the asset browser: My prefabs holds it as a marked asset, and dropping it pastes it.
        asset_file = suite.prefab_library.palette_dir() / suite.prefab_library.FILE_NAME
        with bpy.data.libraries.load(str(asset_file), assets_only=True) as (found, _wanted):
            check(list(found.objects) == ["Vault"], f"My prefabs lists it ({list(found.objects)})")
        stand_in = bpy.data.objects.new("Vault drop", None)
        stand_in["boz_asset_kind"] = "prefab"
        stand_in["boz_prefab"] = "Vault"
        stand_in.location = (anchor[0] - 600.0, anchor[1], anchor[2])
        scene.collection.objects.link(stand_in)
        suite.palette.realize()
        dropped = bpy.context.view_layer.objects.active
        bpy.context.view_layer.update()
        check(convert.is_prefab_group(dropped) and len(dropped.children) == 2
              and abs(dropped.matrix_world.translation.x - (anchor[0] - 600.0)) < 0.5,
              "a prefab dropped from the asset browser lands where it was dropped")
    scene.cursor.location = (anchor[0] + 600.0, anchor[1], anchor[2])
    bpy.ops.boz.place_prefab(name="Vault")
    copy = bpy.context.view_layer.objects.active
    check(convert.is_prefab_group(copy) and copy is not prefab and len(copy.children) == 2
          and copy.get("boz_library") == "Vault", "placing makes an independent copy")
    bpy.context.view_layer.update()
    check(abs(copy.matrix_world.translation.x - (anchor[0] + 600.0)) < 0.5, "it lands at the cursor")
    copy["boz_p:delay"] = 9.0
    back = link.scene_to_world(scene, [])
    delays = sorted(p.properties.get("delay") for p in back.prefabs if p.script == relative)
    check(delays == ([5.0, 5.0, 9.0] if LIBRARY else [5.0, 9.0]),
          f"each copy has its own values ({delays})")
    # An accidental wrapper (a prefab holding only one prefab) is removed when the map opens.
    select_only(copy)
    wrapper = bpy.data.objects.new("Wrapper", None)
    wrapper.boz.role = "prefab"
    convert.map_collection(scene).objects.link(wrapper)
    copy.parent = wrapper
    check(convert.unwrap_single_prefabs(scene) == 1 and copy.parent is None, "a lone wrapper is unwrapped")
    # Ungroup and group again.
    name, parts = copy.name, list(copy.children)
    select_only(copy)
    bpy.ops.boz.ungroup_prefab()
    check(name not in scene.objects and all(o.parent is None and not o.boz.part_name
                                            and convert.PART_SEPARATOR not in o.name for o in parts),
          "Ungroup takes it apart, and the parts get their own names back")
    return prefab


if source.inherit:
    # An original-map template: rooms read only, the base level's entities editable.
    shown = [o for o in scene.objects if o.boz.role == "reference"]
    check(len(shown) > 100 and all(o.hide_select for o in shown), "the rooms are read only")
    base = [o for o in scene.objects if o.boz.role == "prefab" and o.boz.original]
    check(len(base) > 100 and not any(o.hide_select for o in base),
          f"the base level's entities are editable game prefabs ({len(base)})")
    problems = []
    back = link.scene_to_world(scene, problems)
    check(back.inherit and not back.models and not back.volumes and not back.prefabs
          and not back.removed and not problems,
          f"an untouched inherited map writes nothing ({problems}, {back.prefabs[:2]})")
    perk = next(o for o in base if o.get("boz_piece") == "juggernog")
    door = next(o for o in base if str(o.get("boz_piece", "")).startswith("door"))
    window = next(o for o in base if o.get("boz_category") == "barricade")
    perk.location.x += 100.0
    perk["boz_f:CPerk.m_perkSinglePCost"] = 1500
    perk.boz.start_visible = False
    removed = door.boz.source
    bpy.data.objects.remove(door)
    twin = window.copy()
    twin.location.y += 300.0
    window.users_collection[0].objects.link(twin)
    bpy.context.view_layer.update()
    back = link.scene_to_world(scene, [])
    check(back.removed == [removed], f"a deleted base entity is removed ({back.removed})")
    moved = next(p for p in back.prefabs if p.source == perk.boz.source)
    check(moved.base and moved.fields == {"CPerk.m_perkSinglePCost": 1500}
          and moved.start == {"visible": False} and moved.name == perk["boz_entity_name"],
          f"a moved, repriced, hidden perk is written ({moved})")
    copies = [p for p in back.prefabs if p.source == window.boz.source]
    check(len(copies) == 2 and copies[0].base and not copies[1].base,
          "a copied base entity writes the original and the copy")
    pickup = convert.model_object(world.Model("Insta_kill", game=PICKUP), scene)
    check(pickup.type == "MESH", "a pickup model shows")
    prefab_checks((-1100.0, -1300.0, 30.0))
    check(draw_panels("inherited") > 5, "panels draw for every kind")
    saved, data = build_and_compile("inherited")
    check(perk["boz_entity_name"] in data, "the hidden perk is in the start state")
    # The scripted wall that blocks: its floor is a tagged area (not a hole) a script opens.
    built_project = link.sdk_project.load_project(project)
    statics = next((project / "build").glob(f"*/assets/{built_project.map_name}_statics.group.bin"))
    from importlib import import_module
    package = suite.convert.world.__name__.rsplit(".", 1)[0]
    group, levels_mod, nav = (import_module(f"{package}.{n}") for n in ("group", "levels", "navigation"))
    parsed = group.parse(statics.read_bytes())
    mesh = nav.decode(next(r for t in parsed.types() if t.class_hash == levels_mod.NAVMESH
                           for r in t.resources).body)
    want = world.iw_hash("Vault.Door")
    tagged = sum(1 for tile in mesh.tiles for poly, _tri in nav.decode_tile(tile.data).triangles()
                 if poly.extra == want)
    check(tagged > 0, f"the blocking scripted wall's floor is tagged for its script ({tagged})")
    message = suite.preview.build(bpy.context)
    navmesh = bpy.data.collections[suite.preview.COLLECTIONS["navmesh"]]
    check(navmesh.objects, f"the walkable area shows ({message})")
    suite.prefab_library.rebuild(None)   # the tests used the real palette folder: clear it
    print("BOZ_SUITE_OK")
    sys.exit(0)

# A generated map: models, game prefabs from the world source.
models = [o for o in scene.objects if o.boz.role == "model"]
prefabs = [o for o in scene.objects if o.boz.role == "prefab"]
check(len(models) == len(source.models) and len(prefabs) == len(source.prefabs),
      f"scene built from world.json ({len(models)} models, {len(prefabs)} prefabs)")
problems = []
back = link.scene_to_world(scene, problems)
check(not problems, f"no problems in a fresh template: {problems}")
check(back.meshes[0].vertices == source.meshes[0].vertices, "mesh vertices survive")
check(back.models[0].collision == source.models[0].collision, "collision survives")
for a, b in zip(source.prefabs, back.prefabs):
    check(a.source == b.source and all(abs(x - y) < 0.01 for x, y in zip(a.position, b.position))
          and same_rotation(a.quaternion(), b.quaternion()), f"prefab {a.name} survives")

spawn = next(o for o in prefabs if o.boz.source == "spawn_player_1")
spawn.location.x += 50.0
bpy.ops.wm.save_as_mainfile(filepath=str(project / "map.blend"))
saved = world.load(project / "source")
moved = next(p for p in saved.prefabs if p.source == "spawn_player_1")
check(abs(moved.position[0] - (source.prefabs[0].position[0] + 50.0)) < 0.01,
      "saving writes source/world.json")

floor = models[0]
floor_data = floor.data
bpy.data.objects.remove(floor)
bpy.ops.boz.check_world()
check(any("walkable" in message for message, _ in link.problems_of(scene)),
      "a missing floor is reported")
floor = bpy.data.objects.new("floor", floor_data)
floor.boz.role = "model"
floor.boz.collision = "floor"
scene.collection.objects.link(floor)
twin = floor.copy()                    # Alt+D: shares the mesh
twin.location.x += 900.0
scene.collection.objects.link(twin)
back = link.scene_to_world(scene, [])
check(len(back.meshes) == 1 and len(back.models) == 2 and back.models[0].mesh == back.models[1].mesh,
      f"copies sharing a mesh write it once ({len(back.meshes)} meshes)")

if LIBRARY:
    palette = suite.palette
    built = palette.library.Library()
    perk = built.search("perk", kind="prop", limit=1)[0]
    model = next(a for a in built.search(kind="model", limit=50) if a.triangles > 20)
    texture = built.search(kind="texture", limit=1)[0]
    built.close()
    for kind, src, extra in (("entity", f"0x{perk.hash:08x}", perk.groups[0]),
                             ("model", f"{model.groups[0]}#0x{model.hash:08x}", ""),
                             ("model", PICKUP, ""), ("volume", "", "")):
        stand_in = bpy.data.objects.new(f"dropped {kind}", None)
        stand_in["boz_asset_kind"] = kind
        stand_in["boz_source"] = src
        if kind == "volume":
            stand_in["boz_volume"] = "use"
        if extra:
            stand_in["boz_group"] = extra
        stand_in.location = (100.0, 200.0, 0.0)
        scene.collection.objects.link(stand_in)
    material = bpy.data.materials.new("dropped texture")
    material["boz_asset_texture"] = f"{texture.groups[0]}#0x{texture.hash:08x}"
    floor.data.materials.append(material)
    fourth = next((o for o in scene.objects if o.boz.source == "spawn_player_4"), None)
    if fourth is not None:
        bpy.data.objects.remove(fourth)
    for key in ("juggernog", "pack_a_punch", "player_spawn", "wall_buy"):
        stand_in = bpy.data.objects.new(f"piece {key}", None)
        stand_in["boz_asset_kind"] = "piece"
        stand_in["boz_piece"] = key
        scene.collection.objects.link(stand_in)
    palette.realize()
    check(not any("boz_asset_kind" in o for o in scene.objects), "stand-ins are gone")
    dropped = [o for o in scene.objects if o.name.startswith("dropped")]
    check(sorted(o.boz.role for o in dropped) == ["model", "model", "prefab", "volume"],
          f"drops become models, a game prefab and a volume ({[o.boz.role for o in dropped]})")
    bpy.context.view_layer.update()
    for obj in dropped:
        if obj.boz.role == "model":
            corners = [obj.matrix_world @ v.co for v in obj.data.vertices]
            spot = ((min(c.x for c in corners) + max(c.x for c in corners)) / 2,
                    (min(c.y for c in corners) + max(c.y for c in corners)) / 2,
                    min(c.z for c in corners))
        else:
            spot = tuple(obj.matrix_world.translation)
        check(abs(spot[0] - 100.0) < 0.5 and abs(spot[1] - 200.0) < 0.5 and abs(spot[2]) < 0.5,
              f"{obj.name} landed at the drop point ({tuple(round(c, 1) for c in spot)})")
    pieces = {o.get("boz_piece"): o for o in scene.objects if o.get("boz_piece")}
    check(set(pieces) >= {"juggernog", "pack_a_punch", "player_spawn", "wall_buy"},
          f"game prefabs are placed ({sorted(pieces)})")
    check(pieces["wall_buy"].type == "MESH" and pieces["wall_buy"].get("boz_f:boz.weapon"),
          "a wall buy shows its weapon")
    select_only(pieces["wall_buy"])
    bpy.ops.boz.choose_weapon(weapon="Commando")
    drawn = [c for c in pieces["wall_buy"].children if c.get("boz_chalk")]
    check(drawn and drawn[0].data.name.startswith("BOZ game chalk"), "a drawn chalk for Commando")
    pieces["juggernog"]["boz_f:CPerk.m_perkSinglePCost"] = 1234
    pieces["juggernog"]["boz_f:CPerk.powerSwitch"] = False
    game_model = next(o for o in dropped if o.boz.role == "model" and o.boz.source != PICKUP)
    select_only(game_model)
    bpy.ops.boz.make_editable(name="my_rock")
    check(not game_model.boz.source and game_model.data.name == "my_rock",
          "Make editable gives a game model its own mesh")
    dropped_on = floor.material_slots[-1].material
    check(dropped_on is not None and dropped_on.name.startswith("BOZ Material"),
          "a dropped texture becomes a game-shaded material")
    back = link.scene_to_world(scene, [])
    jug = next(p for p in back.prefabs if p.piece == "juggernog")
    check({"CPerk.m_perkSinglePCost": 1234, "CPerk.powerSwitch": "boz_no_power"}.items()
          <= jug.fields.items(), f"game prefab settings are written ({jug.fields})")
    spawns = sorted(p.source for p in back.prefabs if p.source.startswith("spawn_player"))
    check(spawns == [f"spawn_player_{n}" for n in range(1, 5)], f"a dropped spawn takes the free name ({spawns})")
    check(any(v.kind_of == "use" for v in back.volumes), "the dropped volume is written")
    prefab = prefab_checks((0.0, -600.0, 0.0))
    # A game prefab inside your prefab.
    select_only(pieces["pack_a_punch"], prefab)
    bpy.ops.boz.make_prefab()
    outer = bpy.context.view_layer.objects.active
    outer.name = "Shrine"
    back = link.scene_to_world(scene, [])
    shrine = next(p for p in back.prefabs if p.name == "Shrine")
    check(sorted(p.name for p in shrine.parts) == ["Vault", "pack_a_punch"] or
          {p.kind for p in shrine.parts} == {"prefab"}, f"prefabs nest ({[p.name for p in shrine.parts]})")
    check(draw_panels("generated") > 5, "panels draw for every kind")
    saved, data = build_and_compile("generated")
    check("Shrine.Vault" in data, "the nested prefab is in the runtime data")
if LIBRARY:
    suite.prefab_library.rebuild(None)   # the tests used the real palette folder: clear it
print("BOZ_SUITE_OK")
