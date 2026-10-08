# Blender existing-map tools

The add-on targets Blender 5.2 LTS and delegates all native parsing and writing to the bundled
`bozkit` modules. Build the installable ZIP from the repository root:

```bash
python3 tools/build_blender_addon.py
```

In Blender, open **Edit > Preferences > Add-ons**, install
`build/blender/boz-redux-blender.zip`, and enable **BOZ Redux Map Tools**. The **BOZ Redux** tab in
the 3D View sidebar provides import, validation, and export.

Import currently creates separate collections for:

- independently movable `CIwModel` instances placed by `CIsEntitySpec` transform/renderable
  components;
- optional unmatched local-space `CIwModel` asset geometry;
- `CIsCollisionMeshSpec` collision geometry;
- `CIsPortal` visibility portals, including front/back sector properties.
- `CIsNavMeshConnection` traversal links as editable two-point edges.

Every object stores schema version, source group, class hash, resource index, and resource hash as
custom properties. Placed models additionally retain their entity-spec identity, allowing object
transforms and shared geometry to be written to the correct separate resources. Export writes a
new group and preserves unsupported and unchanged resources byte-for-byte. Model and collision
topology must remain unchanged in this first slice; transforms and vertex edits are supported.
Portal geometry and sector names are editable.

Coordinates are rotated losslessly from the game's right-handed Y-up basis into Blender's Z-up
basis, then rotated back during export.

Placed and local models resolve every native material triangle list. Raw BGRA8888/RGB565 and
cooked ETC1/DXT1 textures are decoded inside the add-on and packed into the Blender project; no
external texture converter or Pillow installation is required. Each GL primitive's serialized
material-array index is honored directly. Native render-vertex colours are copied to Blender face
corners and retained as `boz_native_colour`. The default editing preview displays the primary
decoded texture directly. It deliberately does not combine the colour stream with only texture
stage zero: shipped materials commonly use a second stage or shader technique, and presenting an
incomplete composition would make valid geometry misleadingly dark.

Do not save extracted game content inside this repository. Blender projects may contain it for
local development, but official BOZ repositories must not track those `.blend` files or exports.
