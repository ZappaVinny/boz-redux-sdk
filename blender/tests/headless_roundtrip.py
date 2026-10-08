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
import boz_redux  # noqa: E402
from bozkit import collision, group, map_resources, native, navigation, reflect, resources  # noqa: E402
from bozkit.hashing import iw_hash  # noqa: E402
from bozkit.blender_scene import _reconcile_model_positions  # noqa: E402


def fixture() -> bytes:
    model = native.Model([(0, 0, 0), (10, 0, 0), (0, 10, 0)], [(0, 1, 2)],
                         [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)])
    portal = map_resources.Portal(
        [(0.0, 0.0, 0.0), (0.0, 10.0, 0.0), (0.0, 0.0, 10.0)],
        (1.0, 0.0, 0.0), 0.0, 'front', 'back')
    collision_mesh = collision.CollisionMesh(
        b'bullet', [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
        [0, 1, 2], b'\0', ['default'])
    component = resources.Component(
        resources.COLLISION_MESH_SPEC, 0, iw_hash('CIsCollisionMeshSpec'), [],
        collision.encode(collision_mesh))
    def typed(owner, type_name, name, value):
        prop = reflect.Property(iw_hash(owner), iw_hash(type_name), iw_hash(name), b'')
        reflect.set_typed_value(prop, value)
        return prop
    transform = reflect.Blob(iw_hash('CIsTransform'), [
        typed('CIsTransform', 'CIwFVec3', 'm_localPosition', (100.0, 200.0, 300.0)),
        typed('CIsTransform', 'CIwFQuat', 'm_localRotation', (0.0, 0.0, 0.0, 1.0)),
    ])
    asset = reflect.Blob(iw_hash('CIsRenderableAsset'), [
        typed('CIsRenderableAsset', 'unsigned int', 'model', iw_hash('model')),
    ])
    assets = reflect.Property(iw_hash('CIsRenderableModel'), iw_hash('asset_list'),
                              iw_hash('assets'), b'', elements=[asset])
    renderable = reflect.Blob(iw_hash('CIsRenderableModel'), [assets])
    placed_spec = resources.EntitySpec([
        resources.Component(iw_hash('CIsComponentSpec'), 0, iw_hash('CIsTransform'), [transform]),
        resources.Component(iw_hash('CIsComponentSpec'), 0, iw_hash('CIsRenderableModel'), [renderable]),
    ])
    types = [
        group.ResourceType(iw_hash('CIwModel'), 0, 1, [
            group.Resource(iw_hash('model'), iw_hash('model'), native.encode_model(model))]),
        group.ResourceType(iw_hash('CIsPortal'), 0, 1, [
            group.Resource(iw_hash('portal'), iw_hash('portal'),
                           map_resources.encode_portal(portal))]),
        group.ResourceType(iw_hash('CIsEntitySpec'), 0, 1, [
            group.Resource(iw_hash('placed'), iw_hash('placed'),
                           resources.encode_entity_spec(placed_spec)),
            group.Resource(iw_hash('collision'), iw_hash('collision'),
                           resources.encode_entity_spec(resources.EntitySpec([component])))]),
        group.ResourceType(iw_hash('CIsNavMeshConnection'), 0, 1, [
            group.Resource(iw_hash('jump'), iw_hash('jump'), navigation.encode_connection(
                navigation.NavMeshConnection((0.0, 0.0, 0.0), (1.0, 2.0, 3.0),
                                             (0.0, 0.0, 0.0, 1.0), 1, 2, 3.0, 4.0,
                                             True, False)))]),
    ]
    value = group.Group(bytes((0x3D, 0, 0, 0, 0, 0)),
                        [group.Section(group.RESOURCES, b'', types)])
    return group.encode(value)


with tempfile.TemporaryDirectory() as directory:
    seam_model = native.Model([(0, 0, 0), (5, 0, 0), (0, 0, 0)], [],
                              position_remap=[0, 1, 0])
    assert _reconcile_model_positions(seam_model, [(7, 0, 0), (5, 0, 0), (0, 0, 0)]) == [
        (7, 0, 0), (5, 0, 0), (7, 0, 0)]
    source = Path(directory) / 'synthetic.group.bin'
    output = Path(directory) / 'synthetic-unchanged.group.bin'
    edited = Path(directory) / 'synthetic-edited.group.bin'
    source.write_bytes(fixture())
    boz_redux.register()
    assert bpy.ops.boz.import_group(filepath=str(source), include_models=True) == {'FINISHED'}
    objects = [obj for obj in bpy.context.scene.objects if 'boz_kind' in obj]
    assert len(objects) == 4
    assert {obj['boz_kind'] for obj in objects} == {
        'placed_model', 'portal', 'collision', 'navigation_connection'}
    assert bpy.ops.boz.validate_scene() == {'FINISHED'}
    assert bpy.ops.boz.export_group(filepath=str(output)) == {'FINISHED'}
    assert source.read_bytes() == output.read_bytes()
    placed_object = next(obj for obj in objects if obj['boz_kind'] == 'placed_model')
    assert tuple(placed_object.location) == (100.0, -300.0, 200.0)
    placed_object.location.x += 25.0
    # Blender may discard both UV data collections while retaining their definitions after Edit
    # Mode work. Geometry and transforms must still export while bozkit preserves source UVs.
    native_uvs = placed_object.data.attributes.get('boz_native_uv')
    if native_uvs is not None:
        placed_object.data.attributes.remove(native_uvs)
    while placed_object.data.uv_layers:
        placed_object.data.uv_layers.remove(placed_object.data.uv_layers[0])
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
    rebuilt = __import__('bozkit.blender_scene', fromlist=['import_group']).import_group(edited)
    rebuilt_collision = next(item for item in rebuilt.meshes if item.kind == 'collision')
    assert rebuilt_collision.vertices[0] == (0.0, 0.0, 2.0)
    rebuilt_placed = next(item for item in rebuilt.meshes if item.kind == 'placed_model')
    assert rebuilt_placed.location == (125.0, -300.0, 200.0)
    assert rebuilt_placed.uvs == [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)]
    boz_redux.unregister()
    print('BOZ_BLENDER_HEADLESS_OK')
