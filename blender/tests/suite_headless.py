"""The editor (boz_suite app template) in background Blender. Run with run_suite_test.py, which
builds the suite, makes a map project and starts Blender with it."""
import os
import sys
from pathlib import Path

import bpy

suite = sys.modules["bl_app_templates_user.boz_suite"]
link, tabs, placeholders = suite.link, suite.tabs, suite.placeholders
world = link.world


def check(condition, message):
    if not condition:
        print(f"BOZ_SUITE_FAILED: {message}")
        sys.exit(1)


project = Path(os.environ["BOZ_PROJECT"])

# The shell
check([w.name for w in bpy.data.workspaces if w.name in tabs.TAB_NAMES] and
      set(tabs.TAB_NAMES) <= {w.name for w in bpy.data.workspaces}, "every tab exists")
check("Shading" not in bpy.data.workspaces, "unused factory workspaces are gone")
check("boz_redux" in bpy.context.preferences.addons, "the shipped-map add-on is enabled")
registered = [name for name in dir(bpy.types) if name.startswith("BOZ_PT_placeholder")]
check(len(registered) == len(placeholders.PLACEHOLDERS), "every placeholder has a panel")
check(not bpy.types.OBJECT_PT_relations.poll(bpy.context), "stock object panels are hidden")
check(bpy.types.TOPBAR_HT_upper_bar.draw_left.__module__.endswith("shell"), "the top bar is ours")
check(bpy.context.scene.unit_settings.scale_length < 0.011, "one unit is a centimetre")

# First open: the scene was built from the project's world source.
source = world.load(project / "source")
if source.inherit:
    # An original-map template: the base level is shown read only, and nothing of it is written.
    scene = bpy.context.scene
    convert = suite.convert
    shown = [o for o in scene.objects if o.boz.role == "reference"]
    check(len(shown) > 100, f"the base level is shown ({len(shown)} objects)")
    check(all(o.hide_select for o in shown), "the rooms cannot be selected")
    base = [o for o in scene.objects if o.boz.role == "base"]
    check(len(base) > 100 and not any(o.hide_select for o in base),
          f"the base level's entities can be edited ({len(base)})")
    markers = [o for o in scene.objects if convert.is_marker(o)]
    check(markers and all(o.material_slots[0].material for o in markers),
          f"entities without a model are coloured cubes ({len(markers)})")
    problems = []
    back = link.scene_to_world(scene, problems)
    check(back.inherit and back.base == source.base and not back.meshes and not back.entities
          and not back.removed and not problems,
          f"an untouched inherited map writes nothing of the base ({problems}, {back.entities[:3]})")
    # Edit the base level: move and reprice a perk, take a door out, copy a zombie window.
    perk = next(o for o in base if o.get("boz_piece") == "juggernog")
    door = next(o for o in base if str(o.get("boz_piece", "")).startswith("door"))
    window = next(o for o in base if o.get("boz_category") == "barricade")
    perk.location.x += 100.0
    perk["boz_f:CPerk.m_perkSinglePCost"] = 1500
    removed = door.boz.source
    bpy.data.objects.remove(door)
    twin = window.copy()
    twin.location.y += 300.0
    window.users_collection[0].objects.link(twin)
    bpy.context.view_layer.update()
    back = link.scene_to_world(scene, [])
    edits = {e.source: e for e in back.entities}
    check(back.removed == [removed], f"a deleted base entity is removed ({back.removed})")
    moved = edits.get(perk.boz.source)
    check(moved is not None and not moved.piece and moved.fields == {"CPerk.m_perkSinglePCost": 1500}
          and all(abs(c - 1.0) < 1e-4 for c in moved.scale),
          f"a moved perk is written with its changed setting ({moved})")
    check(sum(1 for e in back.entities if e.source == window.boz.source) == 2,
          "a copied base entity writes the original and the copy")
    bpy.ops.wm.save_as_mainfile(filepath=str(project / "map.blend"))
    saved = world.load(project / "source")
    check(saved.removed == [removed], "the removed list is saved")
    sdk_project = link.sdk_project
    built = sdk_project.load_project(project)
    output, report = sdk_project.build_project(built, game=suite.palette.library.LibraryPack())
    check((output / "assets" / f"{built.map_name}_statics.group.bin").is_file(),
          "the edited base level compiles")
    message = suite.preview.build(bpy.context)
    navmesh = bpy.data.collections[suite.preview.COLLECTIONS["navmesh"]]
    collision = bpy.data.collections[suite.preview.COLLECTIONS["collision"]]
    check(navmesh.objects and collision.objects, f"the walkable area and collision show ({message})")
    print("BOZ_SUITE_OK")
    sys.exit(0)
meshes = [o for o in bpy.context.scene.objects if o.boz.role == "mesh"]
entities = [o for o in bpy.context.scene.objects if o.boz.role == "entity"]
check(len(meshes) == len(source.meshes) and len(entities) == len(source.entities),
      f"scene built from world.json ({len(meshes)} meshes, {len(entities)} entities)")

# Scene back to a world: same geometry, collision settings and placements.
problems = []
back = link.scene_to_world(bpy.context.scene, problems)
check(not problems, f"no problems in a fresh template: {problems}")
original, rebuilt = source.meshes[0], back.meshes[0]
check(sorted(original.vertices) == sorted(rebuilt.vertices), "mesh vertices survive")
check(len(original.triangles) == len(rebuilt.triangles), "mesh triangles survive")
check((rebuilt.collision, rebuilt.double_sided) == (original.collision, original.double_sided),
      "collision settings survive")
check(rebuilt.textures == original.textures, "the texture survives")
def same_rotation(a, b):
    dot = abs(sum(x * y for x, y in zip(a, b)))   # q and -q are the same rotation
    return dot > 0.9999


for a, b in zip(source.entities, back.entities):
    check(a.source == b.source and all(abs(x - y) < 0.01 for x, y in zip(a.position, b.position))
          and same_rotation(a.quaternion(), b.quaternion()), f"entity {a.source} survives")

# Saving writes the source; a moved spawn shows up in world.json.
spawn = bpy.context.scene.objects["spawn_player_1"]
spawn.location.x += 50.0
bpy.ops.wm.save_as_mainfile(filepath=str(project / "map.blend"))
saved = world.load(project / "source")
moved = next(e for e in saved.entities if e.source == "spawn_player_1")
check(abs(moved.position[0] - (source.entities[0].position[0] + 50.0)) < 0.01,
      "saving writes source/world.json")

# Problems: without a floor the build is blocked, and the problem is listed.
floor_data = meshes[0].data
bpy.data.objects.remove(meshes[0])
bpy.ops.boz.check_world()
check(any("floor" in message for message, _ in link.problems_of(bpy.context.scene)),
      "a missing floor is reported")
# Props: Make prop turns a mesh into a prop; a linked duplicate (Alt+D) is a second instance.
floor = bpy.data.objects.new("crate", floor_data.copy())
floor.boz.role = "mesh"
bpy.context.scene.collection.objects.link(floor)
convert = suite.convert
convert.make_prop(floor, "crate")
check(floor.boz.role == "prop" and floor.data.name == "crate", "Make prop makes a prop")
twin = floor.copy()
twin.location.x += 500.0
bpy.context.scene.collection.objects.link(twin)
problems = []
back = link.scene_to_world(bpy.context.scene, problems)
check([p.name for p in back.props] == ["crate"] and len(back.instances) == 2,
      f"two placed copies of one prop ({len(back.props)} props, {len(back.instances)} instances)")
check(abs(abs(back.instances[1].position[0] - back.instances[0].position[0]) - 500.0) < 0.01,
      "instances keep their own positions")

# Game models need the asset library; with one (BOZ_TEST_LIBRARY), entities show them.
if os.environ.get("BOZ_TEST_LIBRARY"):
    meshes_before = [o for o in bpy.context.scene.objects if o.boz.role == "entity" and o.type == "MESH"]
    check(meshes_before, "placed entities show their game model")
    jug = next((o for o in bpy.context.scene.objects if o.boz.source == "Juggernog"), None)
    check(jug is not None and jug.type == "MESH" and len(jug.data.polygons) > 10,
          "Juggernog shows its machine")
    convert.make_prop(jug, "my_jug")
    check(jug.boz.role == "entity" and jug.get("boz_custom_model")
          and not jug.data.name.startswith("BOZ game"),
          "an entity keeps its behaviour and draws an editable mesh")
    back = link.scene_to_world(bpy.context.scene, [])
    placed = next(e for e in back.entities if e.source == "Juggernog")
    check(placed.prop == "my_jug" and any(p.name == "my_jug" for p in back.props),
          "the entity's edited mesh is written as its model")

    # Palette drops: stand-ins become the real entity, model and texture.
    palette = suite.palette
    boz_library = palette.library
    built = boz_library.Library()
    perk = built.search("perk", kind="prop", limit=1)[0]
    model = next(a for a in built.search(kind="model", limit=50) if a.triangles > 20)
    texture = built.search(kind="texture", limit=1)[0]
    built.close()
    for kind, source, extra in (("entity", f"0x{perk.hash:08x}", perk.groups[0]),
                                ("model", f"{model.groups[0]}#0x{model.hash:08x}", "")):
        stand_in = bpy.data.objects.new(f"dropped {kind}", None)
        stand_in["boz_asset_kind"] = kind
        stand_in["boz_source"] = source
        if extra:
            stand_in["boz_group"] = extra
        stand_in.location = (100.0, 200.0, 0.0)
        bpy.context.scene.collection.objects.link(stand_in)
    material = bpy.data.materials.new("dropped texture")
    material["boz_asset_texture"] = f"{texture.groups[0]}#0x{texture.hash:08x}"
    crate_material_target = bpy.context.scene.objects["crate"]
    crate_material_target.data.materials.append(material)
    # Toolkit pieces resolve on the project's base level and carry their settings.
    fourth = bpy.context.scene.objects.get("spawn_player_4")
    if fourth is not None:
        bpy.data.objects.remove(fourth)   # the player spawn piece takes the free name
    for key in ("juggernog", "pack_a_punch", "player_spawn", "wall_buy"):
        stand_in = bpy.data.objects.new(f"piece {key}", None)
        stand_in["boz_asset_kind"] = "piece"
        stand_in["boz_piece"] = key
        bpy.context.scene.collection.objects.link(stand_in)
    palette.realize()
    pieces = {o.get("boz_piece"): o for o in bpy.context.scene.objects if o.get("boz_piece")}
    check(set(pieces) >= {"juggernog", "pack_a_punch", "player_spawn", "wall_buy"},
          f"toolkit pieces are placed ({sorted(pieces)})")
    check(pieces["wall_buy"].type == "MESH" and pieces["wall_buy"].get("boz_f:boz.weapon"),
          "a wall buy shows its weapon and has a weapon setting")
    chalks = [c for c in pieces["wall_buy"].children if c.get("boz_chalk")]
    check(chalks and chalks[0].type == "MESH", "a wall buy shows its chalk")
    bpy.context.view_layer.objects.active = pieces["wall_buy"]
    bpy.ops.boz.choose_weapon(weapon="Commando")
    drawn = [c for c in pieces["wall_buy"].children if c.get("boz_chalk")]
    check(drawn and drawn[0].data.name.startswith("BOZ game chalk"),
          "a weapon without chalk gets one drawn from its model")
    check(pieces["juggernog"].get("boz_f:CPerk.m_perkSinglePCost") == 2500
          and pieces["juggernog"].get("boz_f:CPerk.powerSwitch") is True,
          "a perk machine's settings start at the game's values")
    pieces["juggernog"]["boz_f:CPerk.m_perkSinglePCost"] = 1234
    pieces["juggernog"]["boz_f:CPerk.powerSwitch"] = False
    tilted = convert.model_object(world.Instance((0.0, 0.0, 0.0), model=f"{model.groups[0]}#0x{model.hash:08x}"),
                                  bpy.context.scene)
    tilted.rotation_mode = "XYZ"
    tilted.rotation_euler = (1.5707963, 0.0, 0.0)
    bpy.context.view_layer.update()
    back = link.scene_to_world(bpy.context.scene, [])
    jugs = [e for e in back.entities if e.piece == "juggernog"]
    check(jugs and jugs[0].fields == {"CPerk.m_perkSinglePCost": 1234,
                                      "CPerk.powerSwitch": "boz_no_power"}
          and jugs[0].settings.get("CPerk.powerSwitch") is False,
          f"piece settings are written ({jugs[0].fields if jugs else None})")
    check(sum(1 for e in back.entities if e.source == "Juggernog") == 2,
          "a second Juggernog is a second copy")
    spawns = sorted(e.source for e in back.entities if e.source.startswith("spawn_player"))
    check(spawns == [f"spawn_player_{n}" for n in range(1, 5)],
          f"a dropped player spawn takes the free name ({spawns})")
    rotated = [i for i in back.instances if i.model and i.rotation and abs(i.rotation[0]) > 0.5]
    check(rotated, "a model tilted on its side keeps its full rotation")
    placed = [o for o in bpy.context.scene.objects if o.name.startswith("dropped")]
    roles = sorted(o.boz.role for o in placed)
    check(roles == ["entity", "model"] and all(o.type == "MESH" for o in placed),
          f"dropped assets become an entity and a model with meshes ({roles})")
    check(not any("boz_asset_kind" in o for o in bpy.context.scene.objects), "stand-ins are gone")
    dropped_on = bpy.context.scene.objects["crate"].material_slots[-1].material
    check(dropped_on is not None and dropped_on.name.startswith("BOZ Material")
          and convert.image_of(dropped_on) is not None,
          "a dropped texture becomes a game-shaded material")
    problems = []
    back = link.scene_to_world(bpy.context.scene, problems)
    check(any(i.model for i in back.instances) and any(e.group for e in back.entities),
          "dropped assets are written to the world")

    # The whole edited map compiles: copies, custom models, settings, rotations.
    bpy.ops.wm.save_mainfile()
    sdk_project = link.sdk_project
    built = sdk_project.load_project(project)
    output, report = sdk_project.build_project(built, game=boz_library.LibraryPack())
    statics = output / "assets" / f"{built.map_name}_statics.group.bin"
    check(statics.is_file() and statics.stat().st_size > 100000,
          f"the edited map compiles ({len(report['files'])} files)")
print("BOZ_SUITE_OK")
