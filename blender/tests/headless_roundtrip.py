"""Synthetic headless integration test. Run through Blender, not system Python."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'blender'))
sys.path.insert(0, str(ROOT / 'tools' / 'bozkit'))

import bpy  # noqa: E402
import bmesh  # noqa: E402
import addon_utils  # noqa: E402
import boz_redux  # noqa: E402
from bozkit import (blender_scene, bullet, collision, group, map_resources, native,  # noqa: E402
                    navigation, reflect, resources)
from bozkit.hashing import iw_hash  # noqa: E402
from bozkit.blender_scene import _reconcile_model_positions  # noqa: E402


def typed(owner, type_name, name, value):
    prop = reflect.Property(iw_hash(owner), iw_hash(type_name), iw_hash(name), b'')
    reflect.set_typed_value(prop, value)
    return prop


def placed_spec(model_name, position):
    transform = reflect.Blob(iw_hash('CIsTransform'), [
        typed('CIsTransform', 'CIwFVec3', 'm_localPosition', position),
        typed('CIsTransform', 'CIwFQuat', 'm_localRotation', (0.0, 0.0, 0.0, 1.0)),
    ])
    asset = reflect.Blob(iw_hash('CIsRenderableAsset'), [
        typed('CIsRenderableAsset', 'unsigned int', 'model', iw_hash(model_name)),
    ])
    assets = reflect.Property(iw_hash('CIsRenderableModel'), iw_hash('asset_list'),
                              iw_hash('assets'), b'', elements=[asset])
    renderable = reflect.Blob(iw_hash('CIsRenderableModel'), [assets])
    return resources.EntitySpec([
        resources.Component(iw_hash('CIsComponentSpec'), 0, iw_hash('CIsTransform'), [transform]),
        resources.Component(iw_hash('CIsComponentSpec'), 0, iw_hash('CIsRenderableModel'),
                            [renderable]),
    ])


def encode_group(types) -> bytes:
    return group.encode(group.Group(bytes((0x3D, 0, 0, 0, 0, 0)),
                                    [group.Section(group.RESOURCES, b'', types)]))


def model_type(name):
    model = native.Model([(0, 0, 0), (10, 0, 0), (0, 10, 0)], [(0, 1, 2)],
                         [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
                         uvs2=[(0.25, 0.25), (0.5, 0.25), (0.25, 0.5)])
    return group.ResourceType(iw_hash('CIwModel'), 0, 1, [
        group.Resource(iw_hash(name), iw_hash(name), native.encode_model(model))])


def fixture() -> bytes:
    portal = map_resources.Portal(
        [(0.0, 0.0, 0.0), (0.0, 10.0, 0.0), (0.0, 0.0, 10.0)],
        (1.0, 0.0, 0.0), 0.0, 'front', 'back')
    triangle = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]
    collision_mesh = collision.CollisionMesh(
        bullet.synthetic_triangle_mesh(triangle, [0, 1, 2]), triangle, [0, 1, 2], b'\0',
        ['default'])
    component = resources.Component(
        resources.COLLISION_MESH_SPEC, 0, iw_hash('CIsCollisionMeshSpec'), [],
        collision.encode(collision_mesh))
    return encode_group([
        model_type('model'),
        group.ResourceType(iw_hash('CIsPortal'), 0, 1, [
            group.Resource(iw_hash('portal'), iw_hash('portal'),
                           map_resources.encode_portal(portal))]),
        group.ResourceType(iw_hash('CIsEntitySpec'), 0, 1, [
            group.Resource(iw_hash('placed'), iw_hash('placed'),
                           resources.encode_entity_spec(placed_spec('model', (100.0, 200.0, 300.0)))),
            group.Resource(iw_hash('placed2'), iw_hash('placed2'),
                           resources.encode_entity_spec(placed_spec('model', (0.0, 0.0, 0.0)))),
            group.Resource(iw_hash('collision'), iw_hash('collision'),
                           resources.encode_entity_spec(resources.EntitySpec([component])))]),
        group.ResourceType(iw_hash('CIsNavMeshConnection'), 0, 1, [
            group.Resource(iw_hash('jump'), iw_hash('jump'), navigation.encode_connection(
                navigation.NavMeshConnection((0.0, 0.0, 0.0), (1.0, 2.0, 3.0),
                                             (0.0, 0.0, 0.0, 1.0), 1, 2, 3.0, 4.0,
                                             True, False)))]),
    ])


def boz_objects():
    return [obj for obj in bpy.context.scene.objects if 'boz_kind' in obj]


def clear_scene():
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj)


with tempfile.TemporaryDirectory() as directory:
    directory = Path(directory)
    seam_model = native.Model([(0, 0, 0), (5, 0, 0), (0, 0, 0)], [],
                              position_remap=[0, 1, 0])
    assert _reconcile_model_positions(seam_model, [(7, 0, 0), (5, 0, 0), (0, 0, 0)]) == [
        (7, 0, 0), (5, 0, 0), (7, 0, 0)]
    source = directory / 'synthetic.group.bin'
    output = directory / 'synthetic-unchanged.group.bin'
    edited = directory / 'synthetic-edited'  # the operator appends the .group.bin suffix
    source.write_bytes(fixture())
    addon_utils.enable('boz_redux', default_set=True)
    clear_scene()

    # Single-group workflow.
    assert bpy.ops.boz.import_group(filepath=str(source), include_models=True) == {'FINISHED'}
    objects = boz_objects()
    assert sorted(obj['boz_kind'] for obj in objects) == [
        'collision', 'navigation_connection', 'placed_model', 'placed_model', 'portal']
    placed = [obj for obj in objects if obj['boz_kind'] == 'placed_model']
    assert placed[0].data == placed[1].data, 'instances of one model must share a mesh'
    assert 'UVMap2' in placed[0].data.uv_layers
    assert bpy.context.scene.view_settings.view_transform == 'Standard'
    assert bpy.ops.boz.validate_scene() == {'FINISHED'}
    assert bpy.ops.boz.export_group(filepath=str(output)) == {'FINISHED'}
    assert source.read_bytes() == output.read_bytes()
    placed_object = next(obj for obj in placed if tuple(obj.location) == (100.0, -300.0, 200.0))
    placed_object.location.x += 25.0
    placed_object.rotation_mode = 'XYZ'  # export must read the transform, not a stale quaternion
    placed_object.rotation_euler.z = 1.5707963705062866
    # Blender may discard both UV data collections while retaining their definitions after Edit
    # Mode work. Geometry and transforms must still export while bozkit preserves source UVs.
    mesh = placed_object.data
    for name in ('boz_native_uv', 'boz_native_uv2'):
        if name in mesh.attributes:
            mesh.attributes.remove(mesh.attributes[name])
    while mesh.uv_layers:
        mesh.uv_layers.remove(mesh.uv_layers[0])
    collision_object = next(obj for obj in objects if obj['boz_kind'] == 'collision')
    bpy.context.view_layer.objects.active = collision_object
    collision_object.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    edit_mesh = bmesh.from_edit_mesh(collision_object.data)
    edit_mesh.verts.ensure_lookup_table()
    edit_mesh.verts[0].co.z += 2.0
    bmesh.update_edit_mesh(collision_object.data)
    # Export deliberately remains in Edit Mode: the operator must synchronize BMesh edits.
    assert bpy.ops.boz.export_group(filepath=str(edited)) == {'FINISHED'}
    bpy.ops.object.mode_set(mode='OBJECT')
    edited = edited.with_name(edited.name + '.group.bin')
    assert edited.is_file() and not edited.with_name(edited.name + '.group.bin').exists()
    rebuilt = blender_scene.import_group(edited)
    rebuilt_collision = next(item for item in rebuilt.meshes if item.kind == 'collision')
    assert rebuilt_collision.vertices[0] == (0.0, 0.0, 2.0)
    parsed = group.parse(edited.read_bytes())
    spec = next(resources.decode_entity_spec(item.body) for resource_type in parsed.types()
                if resource_type.class_hash == blender_scene.ENTITY_SPEC
                for item in resource_type.resources if item.name_hash == iw_hash('collision'))
    shape = collision.decode(spec.components[0].extra)
    assert bullet.triangle_mesh(shape.bullet_shape)[0][0] == (0.0, 2.0, 0.0), 'physics copy synced'
    rebuilt_placed = next(item for item in rebuilt.meshes if item.kind == 'placed_model'
                          and item.location[0] == 125.0)
    assert rebuilt_placed.location == (125.0, -300.0, 200.0)
    assert abs(abs(rebuilt_placed.rotation[2]) - 0.7071067) < 1e-5, rebuilt_placed.rotation
    assert rebuilt_placed.uvs == [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)]
    assert rebuilt_placed.uvs2 == [(0.25, 0.25), (0.5, 0.25), (0.25, 0.5)]

    # Scaling an object is a supported transform edit.
    clear_scene()
    assert bpy.ops.boz.import_group(filepath=str(source)) == {'FINISHED'}
    scaled = next(obj for obj in boz_objects() if obj['boz_kind'] == 'placed_model')
    scaled.scale = (2.0, 2.0, 2.0)
    scaled_output = directory / 'synthetic-scaled.group.bin'
    assert bpy.ops.boz.export_group(filepath=str(scaled_output)) == {'FINISHED'}
    assert any(item.scale == (2.0, 2.0, 2.0)
               for item in blender_scene.import_group(scaled_output).meshes)

    # Attached collision: a collision triangle cooked from a placed model follows that model.
    clear_scene()
    vertices = [(100.0, 0.0, 0.0), (110.0, 0.0, 0.0), (100.0, 10.0, 0.0), (100.0, 0.0, 50.0)]
    attached_mesh = collision.CollisionMesh(
        bullet.synthetic_triangle_mesh(vertices, [0, 1, 2, 0, 2, 3]), vertices,
        [0, 1, 2, 0, 2, 3], b'\0\0', ['default'])
    attached = directory / 'attached.group.bin'
    attached.write_bytes(encode_group([model_type('crate'),
        group.ResourceType(iw_hash('CIsEntitySpec'), 0, 1, [
            group.Resource(iw_hash('a'), iw_hash('a'),
                           resources.encode_entity_spec(placed_spec('crate', (100.0, 0.0, 0.0)))),
            group.Resource(iw_hash('collision'), iw_hash('collision'), resources.encode_entity_spec(
                resources.EntitySpec([resources.Component(
                    resources.COLLISION_MESH_SPEC, 0, iw_hash('CIsCollisionMeshSpec'), [],
                    collision.encode(attached_mesh))])))])]))
    assert bpy.ops.boz.import_group(filepath=str(attached)) == {'FINISHED'}
    piece = next(obj for obj in boz_objects() if obj['boz_kind'] == 'collision_piece')
    owner = next(obj for obj in boz_objects() if obj['boz_kind'] == 'placed_model')
    assert piece.parent == owner
    assert bpy.ops.boz.validate_scene() == {'FINISHED'}
    scene = bpy.context.scene
    assert not piece.visible_get()
    scene.boz_show_collision = True
    assert piece.visible_get()
    scene.boz_show_collision = False
    assert not piece.visible_get()
    owner.location.x += 5.0
    attached_out = directory / 'attached-out.group.bin'
    assert bpy.ops.boz.export_group(filepath=str(attached_out)) == {'FINISHED'}
    parsed = group.parse(attached_out.read_bytes())
    spec = next(resources.decode_entity_spec(item.body) for resource_type in parsed.types()
                if resource_type.class_hash == blender_scene.ENTITY_SPEC
                for item in resource_type.resources if item.name_hash == iw_hash('collision'))
    moved = collision.decode(spec.components[0].extra)
    corners = [moved.vertices[i] for i in moved.indices[:3]]
    assert all(abs(a - b) < 1e-3 for corner, expected in zip(
        corners, [(105.0, 0.0, 0.0), (115.0, 0.0, 0.0), (105.0, 10.0, 0.0)])
        for a, b in zip(corner, expected)), corners
    assert [moved.vertices[i] for i in moved.indices[3:]] == [vertices[0], vertices[2], vertices[3]]

    # Markers and shapes: entities without models are markers; trigger sizes are editable.
    clear_scene()
    def component(name, properties):
        return resources.Component(iw_hash('CIsComponentSpec'), 0, iw_hash(name), [
            reflect.Blob(iw_hash(name), [typed(name, t, n, v) for t, n, v in properties])])
    perk = placed_spec('crate', (0.0, 0.0, 0.0))
    perk.components += [component('CPOI', [('float', 'm_MaxDistance', 170.0)]),
                        component('CIsCollisionBox', [('CIwFVec3', 'm_halfAxis', (10.0, 20.0, 30.0))])]
    glow = resources.EntitySpec([perk.components[0], component(
        'CIsRenderableGFXEmitter', [('unsigned int', 'emitterSpec', 7)])])
    markers = directory / 'markers.group.bin'
    markers.write_bytes(encode_group([model_type('crate'),
        group.ResourceType(iw_hash('CIsEntitySpec'), 0, 1, [
            group.Resource(iw_hash('perk'), iw_hash('perk'), resources.encode_entity_spec(perk)),
            group.Resource(iw_hash('glow'), iw_hash('glow'), resources.encode_entity_spec(glow))])]))
    assert bpy.ops.boz.import_group(filepath=str(markers)) == {'FINISHED'}
    effect = next(obj for obj in boz_objects() if obj.get('boz_category') == 'effect')
    assert not effect.visible_get()  # every overlay starts hidden
    scene.boz_show_markers = True
    assert effect.visible_get() and effect.type == 'MESH'
    scene.boz_marker_types = {'perk'}  # the type filter hides other markers
    assert not effect.visible_get()
    scene.boz_marker_types = {item[0] for item in boz_redux.view.MARKER_TYPES}
    assert effect.material_slots[0].material.name == 'BOZ Marker: effect'
    assert effect['boz_description'].startswith('Particle effect')
    shapes = {obj['boz_shape']: obj for obj in boz_objects() if obj['boz_kind'] == 'shape'}
    assert set(shapes) == {'reach', 'box'} and not shapes['box'].visible_get()
    assert shapes['box'].material_slots[0].material.name == 'BOZ Shape: solid'
    assert shapes['reach'].material_slots[0].material.name == 'BOZ Shape: reach'
    scene.boz_show_shapes = True
    assert shapes['box'].visible_get()
    assert bpy.ops.boz.validate_scene() == {'FINISHED'}
    shapes['box'].scale.x = 25.0
    effect.location.x += 40.0
    markers_out = directory / 'markers-out.group.bin'
    assert bpy.ops.boz.export_group(filepath=str(markers_out)) == {'FINISHED'}
    rebuilt = blender_scene.import_group(markers_out)
    assert next(item for item in rebuilt.meshes if item.shape == 'box').scale[0] == 25.0
    assert next(item for item in rebuilt.meshes if item.category == 'effect').location[0] == 40.0

    # Links: a door's power link is shown, removed and re-added through the panel operators.
    clear_scene()
    def named_spec(name, extra, position):
        spec = placed_spec('crate', position)
        spec.components = [spec.components[0],
                           component('CIsNamed', [('string', 'name', name)])] + extra
        return spec
    linked = directory / 'linked.group.bin'
    linked.write_bytes(encode_group([model_type('crate'),
        group.ResourceType(iw_hash('CIsEntitySpec'), 0, 1, [
            group.Resource(iw_hash('power'), iw_hash('power'), resources.encode_entity_spec(
                named_spec('Power', [component('CPowerSwitch', [('bool', 'StartEnabled', False)])],
                           (50.0, 0.0, 0.0)))),
            group.Resource(iw_hash('door'), iw_hash('door'), resources.encode_entity_spec(
                named_spec('Door', [component('CDoor', [('unsigned int', 'powerSwitch',
                                                         iw_hash('Power'))])], (0.0, 0.0, 0.0))))])]))
    assert bpy.ops.boz.import_group(filepath=str(linked)) == {'FINISHED'}
    door = next(obj for obj in boz_objects() if obj.get('boz_category') == 'door')
    power = next(obj for obj in boz_objects() if obj.get('boz_category') == 'power')
    assert boz_redux.view.links_of(door)[0]['targets'] == [iw_hash('Power')]
    bpy.context.view_layer.objects.active = door
    component_index = boz_redux.view.links_of(door)[0]['component']
    assert bpy.ops.boz.link_remove(component=component_index, field='powerSwitch',
                                   target=power['boz_link_id']) == {'FINISHED'}
    assert boz_redux.view.links_of(door)[0]['targets'] == []
    unpowered = directory / 'linked-unpowered.group.bin'
    assert bpy.ops.boz.export_group(filepath=str(unpowered)) == {'FINISHED'}
    assert next(item for item in blender_scene.import_group(unpowered).meshes
                if item.category == 'door').links[0]['targets'] == []
    power.select_set(True)
    door.select_set(True)
    assert bpy.ops.boz.link_add_selected(component=component_index, field='powerSwitch') == {'FINISHED'}
    assert boz_redux.view.links_of(door)[0]['targets'] == [iw_hash('Power')]
    scene.boz_show_links = True  # drawing is skipped in background mode; the switch must exist

    # Level workflow: placements resolve their model from the shared ingame group.
    clear_scene()
    level = directory / 'pack' / 'levels' / 'test'
    level.mkdir(parents=True)
    (directory / 'pack' / 'ingame').mkdir()
    (level / 'test_statics.group.bin').write_bytes(encode_group([
        group.ResourceType(iw_hash('CIsEntitySpec'), 0, 1, [
            group.Resource(iw_hash('a'), iw_hash('a'),
                           resources.encode_entity_spec(placed_spec('crate', (1.0, 2.0, 3.0))))])]))
    (directory / 'pack' / 'ingame' / 'ingame.group.bin').write_bytes(
        encode_group([model_type('crate')]))
    assert bpy.ops.boz.import_level(directory=str(level)) == {'FINISHED'}
    crate = next(obj for obj in boz_objects() if obj['boz_kind'] == 'placed_model')
    assert bpy.ops.boz.validate_scene() == {'FINISHED'}
    exported = directory / 'level-out'
    assert bpy.ops.boz.export_level(directory=str(exported)) == {'FINISHED'}
    assert not exported.exists() or not any(exported.iterdir()), 'unchanged level writes nothing'
    crate.location.z += 5.0
    assert bpy.ops.boz.export_level(directory=str(exported)) == {'FINISHED'}
    assert sorted(path.name for path in exported.iterdir()) == ['test_statics.group.bin']

    # The UI loop the guide describes: save to a mod, start over, import the level with the mod.
    client = directory / 'client'
    client.mkdir()
    preferences = bpy.context.preferences.addons['boz_redux'].preferences
    preferences.client_root = str(client)
    assert bpy.ops.boz.save_to_mod() == {'FINISHED'}
    assert (client / 'mods' / 'developer' / 'mod.toml').is_file()
    clear_scene()
    assert bpy.ops.boz.import_level(directory=str(level)) == {'FINISHED'}
    crate = next(obj for obj in boz_objects() if obj['boz_kind'] == 'placed_model')
    assert abs(crate.location.z - 7.0) < 1e-5, tuple(crate.location)  # native y 2 -> z 2, +5
    crate.location.z += 1.0
    assert bpy.ops.boz.save_to_mod() == {'FINISHED'}  # replaces the mod's own copy
    clear_scene()
    assert bpy.ops.boz.import_level(directory=str(level)) == {'FINISHED'}
    crate = next(obj for obj in boz_objects() if obj['boz_kind'] == 'placed_model')
    assert abs(crate.location.z - 8.0) < 1e-5, tuple(crate.location)

    # Build & Run: saves, writes the one-shot autostart request and starts the client.
    fake = client / 'runtime' / 'scripts'
    fake.mkdir(parents=True)
    started = directory / 'started.txt'
    (fake / 'run-desktop.sh').write_text(f'echo "$@" > {started}\n')
    crate = next(obj for obj in boz_objects() if obj['boz_kind'] == 'placed_model')
    crate.location.z += 1.0
    try:
        bpy.ops.boz.build_and_run()
        raise AssertionError('Build & Run must need the test mod')
    except RuntimeError as exc:
        assert 'test mod' in str(exc), exc
    developer = client / 'mods' / 'developer'
    (developer / 'scripts' / 'boz').mkdir(parents=True)
    (developer / 'mod.toml').write_text('id = "developer"\nname = "Developer"\n')
    (developer / 'scripts' / 'boz' / 'levels.lua').write_text('return {}\n')
    (client / 'saves' / 'mods').mkdir(parents=True)
    (client / 'saves' / 'mods' / 'developer.cfg').write_text('open=b:true\nautostart_level=s:old\n')
    # An older edit mod that loads later and replaces the same group would hide the new save.
    stale = client / 'mods' / 'zz_old_edits'
    (stale / 'assets').mkdir(parents=True)
    (stale / 'mod.toml').write_text('id = "zz_old_edits"\n')
    (stale / 'assets' / 'test_statics.group.bin').write_bytes(b'old')
    (client / 'client.ini').write_text('[display]\nfullscreen = false\n[mods]\norder = developer\n')
    assert bpy.ops.boz.build_and_run() == {'FINISHED'}
    ini = (client / 'client.ini').read_text()
    assert 'order = zz_old_edits, developer' in ini, ini
    assert 'fullscreen = false' in ini
    import time
    for _ in range(50):
        if started.exists():
            break
        time.sleep(0.1)
    assert started.read_text().strip() == str(client), started.read_text()
    assert (client / 'saves' / 'mods' / 'developer.cfg').read_text() == \
        'open=b:true\nautostart_level=s:test\n'
    assert 'Saved' in bpy.context.scene['boz_last_report']
    addon_utils.disable('boz_redux')
    print('BOZ_BLENDER_HEADLESS_OK')
