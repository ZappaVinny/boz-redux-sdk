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


def _synthetic_gun(path):
    """A high-quality test gun: a dense textured tube (colour and normal maps) skinned to an
    armature with tag_weapon and tag_clip (no magazine mesh), written to *path*."""
    import bmesh
    mesh = bpy.data.meshes.new("HQ gun")
    shape = bmesh.new()
    bmesh.ops.create_cone(shape, cap_ends=True, segments=64, radius1=4.0, radius2=4.0, depth=60.0)
    bmesh.ops.subdivide_edges(shape, edges=shape.edges[:], cuts=6, use_grid_fill=True)
    shape.to_mesh(mesh)
    shape.free()
    mesh.uv_layers.new(name="UVMap")
    for loop, uv in zip(mesh.loops, mesh.uv_layers[0].data):
        co = mesh.vertices[loop.vertex_index].co
        uv.uv = ((co.x + 4) / 8, (co.z + 30) / 60)
    colour = bpy.data.images.new("hq_gun_c", 1024, 1024)
    colour.pixels.foreach_set([0.6, 0.3, 0.2, 1.0] * (1024 * 1024))
    normal = bpy.data.images.new("hq_gun_n", 256, 256)
    normal.pixels.foreach_set([0.5, 0.5, 1.0, 1.0] * (256 * 256))
    for image in (colour, normal):
        image.pack()
    material = bpy.data.materials.new("hq_gun")
    material.use_nodes = True
    nodes = material.node_tree.nodes
    principled = nodes["Principled BSDF"]
    tex = nodes.new("ShaderNodeTexImage")
    tex.image = colour
    material.node_tree.links.new(tex.outputs["Color"], principled.inputs["Base Color"])
    ntex = nodes.new("ShaderNodeTexImage")
    ntex.image = normal
    nmap = nodes.new("ShaderNodeNormalMap")
    material.node_tree.links.new(ntex.outputs["Color"], nmap.inputs["Color"])
    material.node_tree.links.new(nmap.outputs["Normal"], principled.inputs["Normal"])
    mesh.materials.append(material)
    gun = bpy.data.objects.new("HQ gun", mesh)
    rig_data = bpy.data.armatures.new("Joints")
    rig = bpy.data.objects.new("Joints", rig_data)
    bpy.context.scene.collection.objects.link(rig)
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="EDIT")
    for name, head in (("tag_weapon", (0, 0, 0)), ("tag_clip", (0, 0, -10))):
        bone = rig_data.edit_bones.new(name)
        bone.head, bone.tail = head, (head[0], head[1] + 5, head[2])
    rig_data.edit_bones["tag_clip"].parent = rig_data.edit_bones["tag_weapon"]
    bpy.ops.object.mode_set(mode="OBJECT")
    group = gun.vertex_groups.new(name="tag_weapon")
    group.add(range(len(mesh.vertices)), 1.0, "REPLACE")
    gun.modifiers.new("Armature", "ARMATURE").object = rig
    gun.parent = rig
    bpy.data.libraries.write(str(path), {gun, rig}, fake_user=True)
    triangles = sum(len(p.vertices) - 2 for p in mesh.polygons)
    for obj in (gun, rig):
        bpy.data.objects.remove(obj)
    return triangles


IDGUN = Path(os.environ.get("BOZ_SDK_ROOT", ".")).parent / "boz-redux" / "original" / "idgun_world.blend"


def asset_checks(label):
    """The Assets tab: import a high-quality model, make its game version (both presets), the
    checks, Save edits, place it in the map."""
    at = suite.assets_tab
    assets_mod = at.assets
    source_path = project.parent / f"hq_gun_{label}.blend"
    high = _synthetic_gun(source_path)
    check(high > 4000, f"{label}: the test gun is high quality ({high} triangles)")
    bpy.ops.boz.asset_import("EXEC_DEFAULT", filepath=str(source_path), kind="weapon", preset="stock")
    names = [i.name for i in scene.boz_assets]
    check(names == [f"hq_gun_{label}"], f"{label}: the asset is listed ({names})")
    name = names[0]
    stats = at.stats_of(name)
    check(stats and not stats["errors"], f"{label}: the game version is made ({stats})")
    check(stats["triangles"] <= 1500 and max(max(t) for t in stats["textures"]) <= 512,
          f"{label}: the stock preset's budget and textures ({stats['triangles']}, {stats['textures']})")
    check(any("magazine" in w for w in stats["warnings"]), f"{label}: the missing magazine warns")
    print(f"BOZ_SUITE_INFO {label} asset: {high} -> {stats['triangles']} triangles")
    check((project / "assets" / name / source_path.name).is_file(), f"{label}: the source is copied")
    scene.boz_asset_settings.preset = "pc"
    bpy.ops.boz.asset_make()
    stats = at.stats_of(name)
    check(1500 < stats["triangles"] <= 4000 and max(max(t) for t in stats["textures"]) <= 1024,
          f"{label}: the PC preset ({stats['triangles']}, {stats['textures']})")
    view = bpy.data.scenes.get(link.ASSET_SCENE)
    check(view is not None and view.objects.get(at.GAME_OBJECT) is not None
          and any(o.get("boz_preview") == "asset_high" for o in view.objects),
          f"{label}: the Assets view shows both versions")
    check(not any(o.get("boz_preview") for o in scene.objects), f"{label}: the map is untouched")
    game_obj = view.objects[at.GAME_OBJECT]
    game_obj.data.vertices[0].co.z += 5.0
    bpy.ops.boz.asset_save_edits()
    check(at.asset_def(name).edited, f"{label}: Save edits keeps the hand edit")
    model, _textures = assets_mod.load_game(project / "source", name)
    check(model.weights and len(model.weights) == len(model.vertices), f"{label}: edits keep bone weights")
    scene.cursor.location = (0.0, -300.0, 0.0)
    bpy.ops.boz.asset_place(name=name)
    copy = next((o for o in scene.objects if o.get("boz_asset") == name), None)
    check(copy is not None and copy.type == "MESH" and copy.data.materials,
          f"{label}: the asset is placed in the map")
    try:
        bpy.ops.boz.asset_remove("EXEC_DEFAULT")
    except RuntimeError:
        pass        # refused (reported as an error)
    check(at.asset_def(name) is not None, f"{label}: an asset placed in the map is not removed")
    stand_in = bpy.data.objects.new("dropped asset", None)   # dragged from My assets
    stand_in["boz_asset_kind"], stand_in["boz_asset"] = "asset", name
    convert.map_collection(scene).objects.link(stand_in)
    stand_in.location = (200.0, -300.0, 0.0)
    suite.palette.realize()
    copies = [o for o in scene.objects if o.get("boz_asset") == name]
    check(len(copies) == 2 and "dropped asset" not in bpy.data.objects,
          f"{label}: an asset dropped from the palette is placed ({[o.name for o in copies]})")
    back = link.scene_to_world(scene, [])
    placed = [m for m in back.models if m.asset == name]
    check(placed and placed[0].collision == "solid", f"{label}: the placed asset is written ({placed})")
    fake = type("Panel", (), {"layout": FakeLayout()})()
    for panel in (at.BOZ_PT_assets, at.BOZ_PT_asset_settings, at.BOZ_PT_asset_checks):
        try:
            panel.draw(fake, FakeContext(None))
        except Exception as exc:   # noqa: BLE001
            check(False, f"{label}: {panel.__name__} fails: {exc!r}")
    if IDGUN.is_file() and label == "inherited":   # local only: never committed
        bpy.ops.boz.asset_import("EXEC_DEFAULT", filepath=str(IDGUN), kind="weapon", preset="stock")
        stats = at.stats_of("idgun_world")
        check(stats and not stats["errors"] and stats.get("see_through", 1) <= 0.05,
              f"the idgun's game version is made with nothing see-through ({stats})")
        print(f"BOZ_SUITE_INFO idgun: {stats['high_triangles']} -> {stats['triangles']} triangles "
              f"({stats['see_through']}% see-through), "
              f"textures {stats['textures']}, warnings {stats['warnings']}")
    return name


def own_model_checks(label, asset_name):
    """A weapon made from the Thundergun with your Weapon asset on its own skeleton in the rig:
    fitted in the hand, the original reload moving it, a gun change of its own, built."""
    wt = suite.weapons_tab
    wv = suite.weapon_view
    from mathutils import Vector
    names = [i.name for i in scene.boz_weapons]
    if "thundergun" not in names:
        return None
    wm = bpy.context.window_manager
    scene.boz_weapon_index = names.index("thundergun")
    bpy.ops.boz.weapon_new("EXEC_DEFAULT", name="hq_wonder")
    scene.boz_weapon_index = [i.name for i in scene.boz_weapons].index("hq_wonder")
    wv.flush()
    wm.boz_weapon_model = asset_name
    wv.flush()
    weapon = {d.name: d for d in wt.wp.load_defs(project / "source")}["hq_wonder"]
    check(weapon.model.get("asset") == asset_name and weapon.model.get("fit", {}).get("scale"),
          f"{label}: the weapon uses your model, fitted ({weapon.model})")
    model, _textures = wt.assets.load_game(project / "source", asset_name)
    rig_obj = bpy.data.objects[wv.RIG]
    check(all(f"gun {b.name}" in rig_obj.data.bones for b in model.bones),
          f"{label}: the rig has your model's bones under the gun position")
    check(len(bpy.data.objects[wv.GUN].data.vertices) == len(model.vertices), f"{label}: the view shows your model")
    view = bpy.data.scenes[link.VIEW_SCENE]
    states = {i[1].split("  (")[0]: i[0] for i in wv._state_items(None, bpy.context)}
    wm.boz_anim_state = states["reloading"]
    depsgraph = view.view_layers[0].depsgraph

    def gun_points(frame):
        view.frame_set(frame)
        depsgraph.update()
        gun = bpy.data.objects[wv.GUN].evaluated_get(depsgraph)
        mesh = gun.to_mesh()
        points = [gun.matrix_world @ v.co for v in mesh.vertices]
        gun.to_mesh_clear()
        return points

    idle = gun_points(0)
    best = max(max((a - b).length for a, b in zip(idle, gun_points(f))) for f in range(5, view.frame_end, 10))
    check(best > 1.0, f"{label}: the original reload moves your model ({best:.1f})")
    # Fit model in hand: a rigid copy to move, the stock gun see-through, kept when done.
    before = list(weapon.model["fit"]["location"])
    wm.boz_fit_edit = True
    fit_obj = bpy.data.objects.get(wv.FIT_MODEL)
    check(fit_obj is not None and bpy.data.objects.get(wv.GHOST) is not None
          and view.view_layers[0].objects.active == fit_obj, f"{label}: Fit model in hand shows your model to move")
    fit_obj.location.x += 100.0
    wm.boz_fit_edit = False
    wv.flush()
    after = {d.name: d for d in wt.wp.load_defs(project / "source")}["hq_wonder"].model["fit"]["location"]
    check(abs(after[0] - before[0] - 100.0) < 0.5, f"{label}: moving your model moves the fit ({before} -> {after})")
    wm.boz_fit_location = (after[0] - 100.0, after[1], after[2])
    wv.flush()
    again = {d.name: d for d in wt.wp.load_defs(project / "source")}["hq_wonder"].model["fit"]["location"]
    check(abs(again[0] - before[0]) < 0.5, f"{label}: the Position field sets the fit")
    # A gun change of its own: the magazine lower from frame 10 on.
    rig_obj = bpy.data.objects[wv.RIG]
    wm.boz_anim_state = states["reloading"]
    clip_name = next((f"gun {b.name}" for b in model.bones if b.name.lower() == "tag_clip"), None)
    if clip_name is not None:
        bone = rig_obj.pose.bones[clip_name]
        view.frame_set(10)
        bone.location.z -= 30.0
        changed = Vector(bone.location)
        view.frame_set(30)
        held = (Vector(bone.location) - changed).length
        check([c["frame"] for c in wv._state["edits"]["gun"]] == [10] and held < 0.01,
              f"{label}: the magazine change holds from frame 10 ({held:.4f} off)")
        bpy.ops.boz.weapon_anim_save()
        stored = wv.weapon_anim.load_clips(project / "source", "hq_wonder").get(int(states["reloading"]), {})
        pose = stored.get("edits", {}).get("gun", [{}])[0].get("pose", {})
        check("tag_clip" in {k.lower() for k in pose} and stored.get("gun"),
              f"{label}: your change is stored by your bone's name ({sorted(pose)})")
    wv.BOZ_PT_weapon_model.draw(type("Panel", (), {"layout": FakeLayout()})(), FakeContext(None))
    print(f"BOZ_SUITE_INFO {label} own model: reload moves it up to {best:.0f} units")
    return "hq_wonder"

def weapon_checks(label):
    """The Weapons tab: the list, a changed value, a new weapon, an import, a script, the box pool."""
    wt = suite.weapons_tab
    wp = wt.wp
    context = bpy.context
    wt.refresh(context)
    names = [item.name for item in scene.boz_weapons]
    if scene.boz.inherit:
        check("mp40" in names and len(names) > 20, f"{label}: an original map lists its guns ({len(names)})")
    else:
        # The Colt alone, plus what the test listed for its wall buy.
        check(names[0] == "colt45" and set(names) <= {"colt45", "commando"},
              f"{label}: a new map lists the Colt alone ({names})")
    scene.boz_weapon_index = names.index("colt45")
    rows = {row.key: row for row in scene.boz_weapon_fields}
    check(rows["m_clipSize"].value_int == 8 and rows["behaviour"].value_enum == "1",
          f"{label}: the Colt's values show")
    rows["m_clipSize"].value_int = 12
    saved_defs = {d.name: d for d in wp.load_defs(project / "source")}
    check(saved_defs["colt45"].fields == {"m_clipSize": 12}, f"{label}: a changed value is saved")
    rows = {row.key: row for row in scene.boz_weapon_fields}
    rows["m_clipSize"].value_int = 8
    check("colt45" not in {d.name for d in wp.load_defs(project / "source")},
          f"{label}: changing it back drops the weapon's file")
    rows = {row.key: row for row in scene.boz_weapon_fields}
    rows["m_damage.m_headDamage"].value_int = 250
    rows = {row.key: row for row in scene.boz_weapon_fields}
    rows["behaviour"].value_enum = "2"
    rows = {row.key: row for row in scene.boz_weapon_fields}
    rows["autoROF"].value_int = 600
    bpy.ops.boz.weapon_new("EXEC_DEFAULT", name="colt_auto")
    made = {d.name: d for d in wp.load_defs(project / "source")}["colt_auto"]
    check(made.source == "colt45" and made.fields.get("behaviour") == 2,
          f"{label}: New weapon copies the selected one ({made})")
    check("colt_auto" in wp.load_index(project / "source"), f"{label}: the new weapon is listed")
    if wt.level_weapons("callofthedead"):
        bpy.ops.boz.weapon_import("EXEC_DEFAULT", choice="callofthedead:humangun")
        imported = {d.name: d for d in wp.load_defs(project / "source")}.get("humangun")
        check(imported is not None and imported.level == "callofthedead",
              f"{label}: a weapon of another map is imported")
        # No Pack-a-Punch version: its Upgrade shows None (an empty choice once broke this).
        bpy.ops.boz.weapon_import("EXEC_DEFAULT", choice="callofthedead:Wunderwaffe")
        scene.boz_weapon_index = [i.name for i in scene.boz_weapons].index("Wunderwaffe")
        upgrade = next(r for r in scene.boz_weapon_fields if r.key == "Upgrade")
        check(upgrade.value_enum == wt.NONE and wt._row_value(upgrade) == "",
              f"{label}: a weapon without an upgrade shows None")
    scene.boz_weapon_index = [i.name for i in scene.boz_weapons].index("colt_auto")
    bpy.ops.boz.weapon_script_new()
    check((project / "scripts" / "weapons" / "colt_auto.lua").is_file()
          and {d.name: d for d in wp.load_defs(project / "source")}["colt_auto"].script,
          f"{label}: Add script makes the weapon's script")
    # The view: one rig (arms, the gun under the gun position, grips), the models skinned by Blender.
    wv = suite.weapon_view
    from mathutils import Vector
    scene.boz_weapon_index = [i.name for i in scene.boz_weapons].index("colt45")
    stale = bpy.data.objects.new("BOZ bone bone 9", None)    # what an older version left behind
    wv.view_scene().collection.objects.link(stale)
    message = wt.show_preview(bpy.context)
    check("BOZ bone bone 9" not in bpy.data.objects, f"{label}: the view clears what older versions left")
    view = bpy.data.scenes.get(link.VIEW_SCENE)
    names = sorted(o.name for o in view.objects) if view else []
    check({wv.RIG, wv.ARMS, wv.GUN, wv.VIEW_CAMERA} <= set(names), f"{label}: the view is built ({names}, {message})")
    rig_obj = bpy.data.objects[wv.RIG]
    check(rig_obj.data.bones["gun root"].parent.name == wv.TAG and "hand L" in rig_obj.data.bones,
          f"{label}: the gun and the grips hang from the gun position")
    check(not any(o.get("boz_preview") for o in scene.objects), f"{label}: the map is untouched")
    wm = bpy.context.window_manager
    states = {i[1].split("  (")[0]: i[0] for i in wv._state_items(None, bpy.context)}
    check({"idle", "reloading", "shooting"} <= set(states), f"{label}: the animations are listed ({sorted(states)})")
    reload_state = int(states["reloading"])
    wm.boz_anim_state = states["reloading"]
    rig = wv._state["rig"]
    reload_anim = rig._anim(rig.arm_anims, rig.arm_states, reload_state)
    depsgraph = view.view_layers[0].depsgraph
    worst = 0.0
    for number in (0, len(reload_anim.keyframes) // 2, len(reload_anim.keyframes) - 1):
        frame = wv.weapon_anim.frame_of(reload_anim.keyframes[number].time)
        view.frame_set(frame)
        depsgraph.update()
        arms = bpy.data.objects[wv.ARMS].evaluated_get(depsgraph)
        mesh = arms.to_mesh()
        want = rig.pose(reload_state, number)[0].positions
        worst = max(worst, max((v.co - Vector(suite.convert.blender_scene.to_blender(p))).length
                               for v, p in zip(mesh.vertices, want)))
        arms.to_mesh_clear()
    size = max(bpy.data.objects[wv.ARMS].dimensions)
    check(worst < size * 0.002, f"{label}: Blender skins the arms as the game does ({worst:.2f} off, {size:.0f} across)")
    print(f"BOZ_SUITE_INFO {label} skinning: Blender within {worst:.2f} of the game's ({size:.0f} across)")
    camera = bpy.data.cameras[wv.VIEW_CAMERA]
    check(camera.sensor_fit == "HORIZONTAL" and abs(__import__("math").degrees(camera.angle) - 71.3) < 0.5,
          f"{label}: the camera frames the game's view")
    wm.boz_view_fov = 90.0
    check(abs(camera.angle - wv.viewmodel.view_angle(90.0)) < 1e-4, f"{label}: the field of view slider sets the camera")
    wm.boz_view_fov = 50.0
    wm.boz_view_free = True
    check(bpy.data.objects[wv.VIEW_CAMERA].hide_viewport, f"{label}: the free view hides the camera")
    wm.boz_view_arms = False
    check(bpy.data.objects[wv.ARMS].hide_viewport, f"{label}: the arms can be hidden")
    wm.boz_view_arms, wm.boz_view_free = True, False
    # Position on screen: clicking the arms picks the rig; moved, saved, kept on a rebuild.
    layer = view.view_layers[0]
    layer.objects.active = bpy.data.objects[wv.ARMS]
    wv._picked()
    check(layer.objects.active == rig_obj and wm.boz_arms_edit, f"{label}: clicking the arms picks the rig to place it")
    rig_obj.location.z -= 50.0
    wv._position_changed()
    wm.boz_arms_edit = False
    saved_arms = {d.name: d for d in wp.load_defs(project / "source")}["colt45"].arms
    check(saved_arms and abs(saved_arms["location"][1] + 50.0) < 0.5, f"{label}: the position is saved ({saved_arms})")
    wt.show_preview(bpy.context)
    rig_obj = bpy.data.objects[wv.RIG]
    check(abs(rig_obj.location.z + 50.0) < 0.5, f"{label}: the position stays after a rebuild")
    wm.boz_anim_state = states["reloading"]
    view.frame_set(0)
    bpy.ops.boz.weapon_anim_play()
    check(wm.boz_anim_playing, f"{label}: Play starts the animation")
    wv._play_tick()
    check(view.frame_current == 1, f"{label}: playing steps the frames")
    bpy.ops.boz.weapon_anim_play()
    check(not wm.boz_anim_playing, f"{label}: Play again pauses")
    # Editing: a change holds forward from its frame; earlier frames never move.
    hand = rig_obj.pose.bones["hand L"]
    view.frame_set(10)
    before_10 = Vector(hand.location)
    view.frame_set(20)
    original_20 = Vector(hand.location)
    hand.location.z += 4.0
    edited_20 = Vector(hand.location)
    view.frame_set(25)                                 # leaving the frame keeps the change
    edits = wv._state["edits"]
    check([c["frame"] for c in edits["arms"]] == [20] and not edits["gun"],
          f"{label}: leaving the frame keeps the arms change ({edits})")
    check((Vector(hand.location) - edited_20).length < 1e-3, f"{label}: the change holds on frame 25")
    view.frame_set(10)
    check((Vector(hand.location) - before_10).length < 1e-3, f"{label}: frame 10 (before) is unchanged")
    # The gun's own timeline: moving the gun position changes only the gun's.
    view.frame_set(40)
    gun_bone = rig_obj.pose.bones[wv.TAG]
    gun_bone.location.x += 3.0
    view.frame_set(45)
    check([c["frame"] for c in wv._state["edits"]["gun"]] == [40] and
          [c["frame"] for c in wv._state["edits"]["arms"]] == [20],
          f"{label}: arms and gun keep their own timelines ({wv._state['edits']})")
    depsgraph.update()
    evaluated = rig_obj.evaluated_get(depsgraph)
    wrist = evaluated.pose.bones["wrist L"].matrix.to_translation()
    grip = evaluated.pose.bones["hand L"].matrix.to_translation()
    check((wrist - grip).length < 2.0, f"{label}: the hand stays on the gun ({(wrist - grip).length:.2f})")
    # Back to original, copy and paste, original frames.
    view.frame_set(60)
    bpy.ops.boz.weapon_original(part="arms")
    check(wv.weapon_anim.source_of(wv._state["edits"]["arms"], 70)[0] == "original",
          f"{label}: back to original from 60")
    wm.boz_copy_part, wm.boz_copy_source = "ARMS", "ORIGINAL"
    view.frame_set(5)
    bpy.ops.boz.weapon_copy_pose()
    view.frame_set(80)
    bpy.ops.boz.weapon_paste_pose()
    check(80 in [c["frame"] for c in wv._state["edits"]["arms"]], f"{label}: a pose pastes at 80")
    wm.boz_copy_part = "BOTH"
    wm.boz_copy_from, wm.boz_copy_to = 0, 10
    view.frame_set(90)
    bpy.ops.boz.weapon_copy_frames()
    check(wv.weapon_anim.source_of(wv._state["edits"]["gun"], 95) == ("original", 5),
          f"{label}: original frames play from 90 ({wv._state['edits']['gun']})")
    bpy.ops.boz.weapon_anim_save()
    stored = wv.weapon_anim.load_clips(project / "source", "colt45").get(reload_state, {})
    check(stored.get("edits", {}).get("arms") and stored.get("arms") and stored.get("gun") and
          len(stored["arms"].frames[0][1]) == len(rig.arm_bones),
          f"{label}: the changes and the result at every frame are stored")
    for workspace in ("Weapons", "Animation"):
        wv.BOZ_PT_weapon_animations.draw(type("Panel", (), {"layout": FakeLayout()})(),
                                         FakeContext(None, workspace))
    wv.BOZ_PT_weapon_model.draw(type("Panel", (), {"layout": FakeLayout()})(), FakeContext(None))
    bpy.ops.boz.weapon_reset_anim("EXEC_DEFAULT")
    check(reload_state not in wv.weapon_anim.load_clips(project / "source", "colt45"),
          f"{label}: Reset gives the original back")
    view.frame_set(30)                                 # one change kept, for the build
    rig_obj.pose.bones["hand R"].location.y += 2.0
    view.frame_set(31)
    bpy.ops.boz.weapon_anim_save()
    window = bpy.context.window_manager.windows[0]
    window.scene = view                 # as when the Weapons tab is on screen
    check(link.map_scene() == scene, f"{label}: the map is still the map while the view shows")
    bpy.ops.wm.save_as_mainfile(filepath=str(project / "map.blend"))
    check(world.load(project / "source").base == scene.boz.base,
          f"{label}: saving from the Weapons tab writes the map")
    window.scene = scene
    scene.boz_weapon_index = [i.name for i in scene.boz_weapons].index("colt_auto")
    bpy.ops.boz.weapon_start()
    check(wp.load_start(project / "source")[0] == "colt_auto", f"{label}: the starting weapon is ticked")
    scene.boz_start_reserve = 120
    check(wp.load_start(project / "source") == ("colt_auto", 120), f"{label}: its spare rounds are saved")
    fake = type("Panel", (), {"layout": FakeLayout()})()
    for panel in (wt.BOZ_PT_weapons, wt.BOZ_PT_weapon_properties, wt.BOZ_PT_weapon_script,
                  *wt.GROUP_PANELS):
        try:
            panel.draw(fake, FakeContext(None))
        except Exception as exc:   # noqa: BLE001
            check(False, f"{label}: {panel.__name__} fails: {exc!r}")
    box = next((o for o in scene.objects if o.get("boz_piece") == "mystery_box"
                or (o.boz.role == "prefab" and o.get(convert.FIELD_PREFIX + "CMysteryBox.m_Cost") is not None)), None)
    if box is not None:
        items = bpy.context.window_manager.boz_pool_items
        items.clear()
        for name in ("colt45", "colt_auto"):
            item = items.add()
            item.name, item.enabled = name, True
        with bpy.context.temp_override(object=box):
            bpy.ops.boz.box_pool("EXEC_DEFAULT")
        check(box.get(convert.FIELD_PREFIX + "CMysteryBox.m_Weapons") == "colt45,colt_auto",
              f"{label}: the box pool is set")


def weapon_build_checks(label, data):
    if not LIBRARY:
        return
    from importlib import import_module
    package = suite.convert.world.__name__.rsplit(".", 1)[0]
    group_mod = import_module(f"{package}.group")
    wp = suite.weapons_tab.wp
    built_project = link.sdk_project.load_project(project)
    path = next((project / "build").glob(f"*/assets/weapons_{built_project.map_name}.group.bin"))
    listed = {w.name: w for w in wp.read_group(group_mod.parse(path.read_bytes()),
                                                extra_names=["colt_auto"])}
    auto = listed.get("colt_auto")
    check(auto is not None and auto.values["behaviour"] == 2 and auto.values["autoROF"] == 600
          and auto.values["m_damage.m_headDamage"] == 250,
          f"{label}: the new weapon is built with its values")
    if suite.weapons_tab.level_weapons("callofthedead"):
        check("humangun" in listed, f"{label}: the imported weapon is in the map's weapons")
    check('script = "weapons.colt_auto"' in data, f"{label}: the weapon script is in the runtime data")
    check('name = "colt_auto"' in data and "reserve = 120" in data,
          f"{label}: the starting weapon is in the runtime data")


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
    def __init__(self, obj, workspace="Weapons"):
        self.workspace = bpy.data.workspaces.get(workspace)
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


def sound_checks(label):
    """Audio tab: import a recording, shape it, save it, put it in a game sound's slot."""
    import math
    import struct
    import tempfile
    import wave
    tab = suite.sounds_tab
    snd = tab.sound
    recording = Path(tempfile.mkdtemp()) / "Roar Take 2.wav"
    with wave.open(str(recording), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(44100)
        frames = b"".join(struct.pack("<hh", int(9000 * math.sin(i / 9)), int(6000 * math.sin(i / 7)))
                          for i in range(22050))
        w.writeframes(frames)
    bpy.ops.boz.sound_import("EXEC_DEFAULT", filepath=str(recording))
    item = tab.selected_sound(scene)
    check(item is not None and item.name == "roar_take_2" and not item.saved,
          f"{label}: an imported recording waits to be saved ({item and item.name})")
    settings = scene.boz_sound_settings
    settings.rate, settings.fade_out = "11025", 0.1
    values, rate = snd.preview(tab.source_dir(), item.name, tab._from_settings(settings))
    check(rate == 11025 and abs(len(values) - 5512) < 4, f"{label}: the preview is the game's ({len(values)})")
    check(bpy.ops.boz.sound_preview("EXEC_DEFAULT") == {"FINISHED"}, f"{label}: Preview runs")
    bpy.ops.boz.sound_save("EXEC_DEFAULT")
    item = tab.selected_sound(scene)
    check(item.saved and snd.is_saved(tab.source_dir(), item.name), f"{label}: Save makes the game version")
    settings.trim_start = 0.1
    tab._wave_of_sound(item.name)
    image = bpy.data.images.get(tab.WAVE_IMAGE)
    pixels = list(image.pixels[:]) if image else []
    orange = sum(1 for i in range(0, len(pixels), 4) if pixels[i] > 0.9 and 0.5 < pixels[i + 1] < 0.7)
    grey = sum(1 for i in range(0, len(pixels), 4) if 0.6 < pixels[i] < 0.64 and pixels[i + 2] > 0.7)
    check(orange > 1000 and grey > 1000, f"{label}: the wave view draws the recording and the game version ({grey}, {orange})")
    if os.environ.get("BOZ_TEST_WAVE"):
        image.filepath_raw = os.environ["BOZ_TEST_WAVE"]
        image.file_format = "PNG"
        image.save()
    settings.trim_start = 0.0
    if not LIBRARY:
        return None
    bpy.ops.boz.sounds_refresh("EXEC_DEFAULT")
    slots = tab.catalog(bpy.context)
    categories = {s.category for s in slots}
    check(len(slots) > 200 and {"shared", "map"} <= categories,
          f"{label}: the map's sounds are slots ({len(slots)}, {sorted(categories)})")
    check(any(": Fire" in s.label for s in slots), f"{label}: weapon sounds are named after the weapon")
    scene.boz_sound_category = "weapons"
    check(len(scene.boz_sound_slots) and all(": " in i.users for i in scene.boz_sound_slots),
          f"{label}: the Weapons filter shows weapon sounds")
    scene.boz_sound_category = "all"
    target = next(s for s in slots if s.category == "shared")
    bpy.ops.boz.sound_slot_replace("EXEC_DEFAULT", key=target.key, sound=item.name)
    check(snd.load_slots(tab.source_dir()) == {target.key: item.name}, f"{label}: Replace with fills the slot")
    shown = next(i for i in scene.boz_sound_slots if i.key == target.key)
    check(shown.replaced == item.name, f"{label}: the slot shows its replacement")
    # A weapon's own reload sound (its own sequence; the weapon it is made from keeps its sounds).
    wt = suite.weapons_tab
    own_weapon = sorted(wt.defs())[0]
    scene.boz_weapon_index = [i.name for i in scene.boz_weapons].index(own_weapon)
    bpy.ops.boz.weapon_sound_set("EXEC_DEFAULT", field="reloadSoundSequence", sound=item.name)
    check(wt.weapon_def(bpy.context, own_weapon).sounds == {"reloadSoundSequence": item.name},
          f"{label}: Use one sound gives {own_weapon} its own reload sound")
    target.weapon = own_weapon
    for panel, workspace in ((tab.BOZ_PT_sound_slots, "Audio"), (tab.BOZ_PT_sound_processor, "Audio"),
                             (tab.BOZ_PT_weapon_sounds, "Weapons")):
        fake = type("Panel", (), {"layout": FakeLayout()})()
        try:
            panel.draw(fake, FakeContext(None, workspace))
        except Exception as exc:   # noqa: BLE001
            check(False, f"{label}: {panel.__name__} fails: {exc!r}")
    return target


def effect_checks(label):
    """Effects tab: find the Gersch device, use it in this map under a name, get its script line."""
    tab = suite.effects_tab
    fx = tab.effects
    if not LIBRARY:
        return None
    bpy.ops.boz.effects_refresh("EXEC_DEFAULT")
    check(len(tab.catalog()) > 50, f"{label}: the game's effects are listed ({len(tab.catalog())})")
    scene.boz_effect_kind = "projectile"
    check(all(i.kind == "projectile" for i in scene.boz_effect_entries), f"{label}: the Projectiles filter")
    names = [i.label for i in scene.boz_effect_entries]
    gersch = next(i for i, e in enumerate(scene.boz_effect_entries) if e.label.startswith("bh_bomb"))
    scene.boz_effect_index = gersch
    scene.boz_effect_new_name = "gersch"
    bpy.ops.boz.effect_use("EXEC_DEFAULT")
    stored = fx.load(tab.source_dir())
    check([(u.name, u.level, u.behaviour) for u in stored] == [("gersch", "ascension", 6)],
          f"{label}: Use in this map stores the black hole ({stored})")
    scene.boz_effect_rename = "black_hole"
    check([u.name for u in fx.load(tab.source_dir())] == ["black_hole"], f"{label}: renaming it")
    scene.boz_effect_rename = "gersch"
    scene.boz_effect_hidden = True
    scene.boz_effect_anchored = True
    stored = fx.load(tab.source_dir())
    check(stored[0].hidden and stored[0].anchored, f"{label}: Hide its model and Stays where spawned are stored")
    item = tab.selected(scene.boz_effects_used, scene.boz_effect_used_index)
    check(tab.snippet(item) == 'effects.projectile("gersch", effects.aim(), {trigger = "open", lifetime = 6, raise = 200})',
          f"{label}: its script line ({tab.snippet(item)})")
    for panel in (tab.BOZ_PT_effects_game, tab.BOZ_PT_effects_used):
        fake = type("Panel", (), {"layout": FakeLayout()})()
        try:
            panel.draw(fake, FakeContext(None, "Effects"))
        except Exception as exc:   # noqa: BLE001
            check(False, f"{label}: {panel.__name__} fails: {exc!r}")
    scene.boz_effect_kind = "all"
    return stored[0]


def effect_build_checks(label, used, data):
    """The built map carries the black hole and tells boz.effects its name."""
    snd = suite.sounds_tab.sound
    from importlib import import_module
    package = snd.__name__.rsplit(".", 1)[0]
    group = import_module(package + ".group")
    output = next((project / "build").glob("*/assets"))
    projectiles = group.parse(next(output.glob("weapon_projectiles_*.group.bin")).read_bytes())
    held = {r.in_group_hash for t in projectiles.types() for r in t.resources}
    check(used.hash in held and world.iw_hash("gersch_opens") in held,
          f"{label}: the black hole and its sounds are carried into the map")
    check(used.spawn_hash in held, f"{label}: the map's own copy without the model and physics is built")
    check('name = "gersch"' in data and str(used.spawn_hash) in data, f"{label}: boz.effects knows it")
    scripts = output.parent / "scripts" / "boz"
    check((scripts / "effects.lua").is_file(), f"{label}: boz.effects is installed")


def sound_build_checks(label, target):
    """The built mod carries the replaced sound in a patched copy of its game group."""
    tab = suite.sounds_tab
    snd = tab.sound
    output = next((project / "build").glob("*/assets"))
    patched = output / target.group.rsplit("/", 1)[-1]
    check(patched.is_file(), f"{label}: the replaced sound's group is in the mod ({patched.name})")
    from importlib import import_module
    group = import_module(snd.__name__.rsplit(".", 1)[0] + ".group")
    body = snd._resources(group.parse(patched.read_bytes()), snd.DATA)[target.data]
    count = snd.decode_data(body).count
    check(abs(count - 5512) < 4, f"{label}: the slot plays the saved sound ({count} samples)")
    sources = [d.name for d in suite.assets_tab.defs() if (output / d.name).exists()]
    check(not sources, f"{label}: asset sources stay out of the mod ({sources})")
    print(f"BOZ_SUITE_INFO sounds: {target.label} replaced in {patched.name} ({count} samples)")
    weapons_file = next(output.glob("weapons_*.group.bin"))
    parsed = group.parse(weapons_file.read_bytes())
    sequence = world.iw_hash(f"{target.weapon}_reloadSoundSequence_seq")
    own = world.iw_hash(f"{target.weapon}_reloadSoundSequence")
    sequences = snd._resources(parsed, snd.SEQUENCE)
    check(sequence in sequences and snd.decode_sequence(sequences[sequence]) == [("play", own)],
          f"{label}: the weapon's own reload sequence is built")
    check(abs(snd.decode_data(snd._resources(parsed, snd.DATA)[own]).count - 5512) < 4,
          f"{label}: it plays the saved sound")
    wp = import_module(snd.__name__.rsplit(".", 1)[0] + ".weapons")
    found = next(w for w in wp.read_group(parsed) if w.name == target.weapon)
    check(found.values.get("reloadSoundSequence") == sequence, f"{label}: the weapon's Reload points at it")


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
    weapon_checks("inherited")
    asset_name = asset_checks("inherited")
    own = own_model_checks("inherited", asset_name)
    replaced_sound = sound_checks("inherited")
    used_effect = effect_checks("inherited")
    saved, data = build_and_compile("inherited")
    if replaced_sound is not None:
        sound_build_checks("inherited", replaced_sound)
    if used_effect is not None:
        effect_build_checks("inherited", used_effect, data)
    if own:
        built_group = next((project / "build").glob(f"*/assets/weapons_*.group.bin")).read_bytes()
        for name in ("hq_wonder_model", "hq_wonder_skel", "hq_wonder_gun"):
            check(world.iw_hash(name).to_bytes(4, "little") in built_group, f"{name} is built")
        check(b"hq_wonder_gun" in built_group, "the weapon plays its own state machine")
        arms_group = next((project / "build").glob(f"*/assets/arms_*.group.bin")).read_bytes()
        check(b"colt45_arms" in built_group and world.iw_hash("colt45_arms").to_bytes(4, "little") in arms_group,
              "the colt's own arms animations are built")
    check(any(m.asset == asset_name for m in saved.models), "the placed asset is saved")
    weapon_build_checks("inherited", data)
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
    # A wall buy sells the project's weapons: list the Commando first (Weapons tab, Import).
    bpy.ops.boz.weapon_import("EXEC_DEFAULT", choice=f"{suite.weapons_tab.base_level(bpy.context)}:commando")
    bpy.ops.boz.choose_weapon(weapon="commando")
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
    weapon_checks("generated")
    own_model_checks("generated", asset_checks("generated"))
    saved, data = build_and_compile("generated")
    weapon_build_checks("generated", data)
    check("Shrine.Vault" in data, "the nested prefab is in the runtime data")
if LIBRARY:
    suite.prefab_library.rebuild(None)   # the tests used the real palette folder: clear it
print("BOZ_SUITE_OK")
