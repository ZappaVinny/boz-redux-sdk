# Editing existing maps in Blender

The BOZ Redux add-on targets Blender 5.2 LTS and uses the same `bozkit` codecs as the command-line
and desktop tools. It never overwrites an imported `.group.bin`.

## Build and install

From this workspace:

```bash
cd /home/zappa/Work/boz/boz-redux-sdk
python3 tools/build_blender_addon.py
```

Install `/home/zappa/Work/boz/boz-redux-sdk/build/blender/boz-redux-blender.zip` from **Edit >
Preferences > Add-ons > Install from Disk**, then enable **BOZ Redux Map Tools**. Open the **BOZ
Redux** tab in the 3D View sidebar.

The ZIP contains the required map-format portion of `bozkit`; Blender does not need the SDK's
virtual environment or Pillow for map editing.

## Practical tutorial-map test

Extract the archive already installed in this workspace:

```bash
cd /home/zappa/Work/boz/boz-redux-sdk
.venv/bin/bozkit extract \
  /home/zappa/Work/boz/boz-redux/original/obb/blackops_etc.dz \
  /tmp/boz-blender-test --kind dz
```

In Blender:

1. Choose **BOZ Redux > Import native group**.
2. Open `/tmp/boz-blender-test/levels/tutorial/tutorial_statics.group.bin`.
3. Confirm the Outliner contains **BOZ Placed Models**, **BOZ Collision**, and **BOZ Portals**.
   The tutorial group produces 51 independently placed model objects, one world-space collision
   object, and five portals by default.
   Switch the viewport to **Material Preview** to display native ETC1/DXT1 or raw textures. The
   importer builds all native material slots, assigns every material's triangle-list faces, and
   preserves `CIwModelBlockCols` as a face-corner colour attribute. The editing preview displays
   the primary decoded texture without guessing at unimplemented secondary texture/shader stages.
   Primary texture nodes explicitly use the face-corner `UVMap`; the point-domain
   `boz_native_uv` attribute is a preservation copy, not a shader UV input.
   Native blend modes select opaque, alpha, additive, or inverse-colour transmission previews.
   This is not yet game-identical shading: baked vertex lighting, secondary texture stages,
   other native alpha-test thresholds and display colour management can still differ.
   Materials using native opaque mode 5 with a primary texture flagged for alpha
   testing use the game's greater-than-0.75 cutout. This removes the cyan
   background of the hanging theatre decorations while keeping their artwork.
   Texture decode skips the complete native 72-byte platform header;
   all 81 primary material references in the local tutorial test now resolve.
   Collision, portal, and navigation helpers are
   hidden after import so they do not cover the rendered map; enable them in the Outliner when
   editing those systems.
4. Move or rotate a placed model. Its entity transform is exported separately from its shared
   model geometry. You can also move collision vertices. Portal geometry and its
   `boz_front_sector`/`boz_back_sector` custom properties can also be edited.
5. Choose **Validate BOZ scene**. Fix any reported duplicate identity, empty geometry, or
   non-triangle face.
6. Choose **Export edited group** and save it as
   `/tmp/boz-blender-test/levels/tutorial/tutorial_statics-edited.group.bin`.

An export with no edits is byte-identical to the source. An edited export changes only selected
native resources; every unknown section and unsupported resource body remains byte-identical.

BOZ uses a right-handed Y-up coordinate system. Import rotates it into Blender's Z-up system, so
the map floor is horizontal and player-up matches Blender Z. Export applies the exact inverse.

Renderable entity specs are matched to their `CIwModel` references and imported at their native
position and rotation. A model definition without a matching placed entity is hidden unless
**Local asset models** is enabled; those reusable definitions live in **BOZ Local Asset Models**.

Static model and collision topology must currently remain unchanged. Object transforms, vertex
positions, model UVs, collision material assignments, portal topology, and portal sector names are
supported. Apply intentional object transforms through export; do not apply modifiers that add or
remove model/collision vertices.

Native models duplicate render vertices at UV and normal seams. Blender exposes those copies as
separate vertices; moving one copy during a position edit automatically moves every copy backed by
the same native position. Moving different copies to conflicting destinations is rejected.

Groups containing `CIsNavMeshConnection` resources import them into **BOZ Navigation** as
two-point edges. Moving either endpoint is supported; adding vertices or edges is rejected. Recast
profile metadata and Detour tiles are preserved, but tile polygon editing is not implemented yet.

## Automated checks

The committed test uses independently authored synthetic resources:

```bash
cd /home/zappa/Work/boz/boz-redux-sdk
ALSOFT_DRIVERS=null blender -b --factory-startup \
  --python blender/tests/headless_roundtrip.py
```

Success ends with `BOZ_BLENDER_HEADLESS_OK`. The test imports a placed model, collision mesh,
portal, and navigation connection; validates them; round-trips a model transform and an Edit Mode
collision vertex change; and requires the untouched group to remain byte-identical.

Extracted groups, edited groups, and `.blend` projects may be used locally but must not be committed
to an official BOZ Redux repository.
