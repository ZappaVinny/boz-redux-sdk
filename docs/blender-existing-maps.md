# Editing existing maps in Blender

The BOZ Redux add-on targets Blender 5.2 LTS and uses the same `bozkit` codecs as the command-line
and desktop tools. It never overwrites the groups it imports. Format details are in
[asset formats](asset-formats.md).

## Build and install

```bash
cd /home/zappa/Work/boz/boz-redux-sdk
python3 tools/build_blender_addon.py
```

Install `build/blender/boz-redux-blender.zip` from **Edit > Preferences > Add-ons > Install from
Disk**, enable **BOZ Redux Map Tools**, and restart Blender. The tools are in the **BOZ Redux** tab
of the 3D View sidebar. The ZIP bundles the map-format part of `bozkit`; Blender needs nothing else.

## Extract the game data

```bash
.venv/bin/bozkit extract \
  /home/zappa/Work/boz/boz-redux/original/obb/blackops_etc.dz /tmp/boz-etc --kind dz
```

Extracted and edited groups are for local use only and must never be committed.

## Import a level

A map is spread over many groups. Kino der Toten's `levels/kino` folder has 25: `kino_statics`
places objects whose models live in `kino_dynamics` and in the shared `ingame` group, and every
room (`theatre_shared`, `lobby_shared`, ...) has its own geometry, portals and lightmaps.

1. Start from a fresh scene and choose **BOZ Redux > Import level folder**.
2. Select `/tmp/boz-etc/levels/kino`. With **Shared in-game group** enabled, the add-on also reads
   `/tmp/boz-etc/ingame/ingame.group.bin` and the level's weapon groups
   (`ingame/weapons/*_kino.group.bin`, for the wall-buy displays) to resolve placements, but
   imports none of their own content.
3. The Outliner gets one **BOZ &lt;group&gt;** collection per group, holding **Placed Models**,
   **Markers**, **Shapes**, **Collision**, **Portals** and **Navigation**. Only the models are
   visible after import. The sidebar's **Show** switches turn each overlay on across the whole
   level: Markers, Badges, Areas, Links, Shapes, Collision, Portals and Nav. **Marker types**
   narrows markers and badges to the kinds you want (for example only perks and doors).
4. Switch the viewport to **Material Preview**.

Kino takes a few seconds and produces about 600 placed models. The importer reports anything it
could not resolve, such as placements whose model is in a group outside the folder, as warnings in
Blender's status bar instead of silently dropping them.

**Import native group** imports a single `.group.bin`. That suits self-contained groups such as
`levels/tutorial/tutorial_statics.group.bin` or one room.

## What you see

**Placed models.** Every renderable entity becomes an object at its native position, rotation and
scale. All placements of one model share one Blender mesh, so editing the geometry of one changes
them all, exactly as in the game. Entities nested inside other entities keep their parent: a
non-renderable parent becomes an empty, and children move with it.

**Shading.** The preview follows the game's GLES1 material path:

- The primary texture is multiplied by the vertex colour. Vertex colours carry the baked lighting
  of unlit models.
- Lightmapped materials add the second texture, a baked lightmap atlas, through the model's second
  UV set (`UVMap2`), combined the way the material's flags select (usually multiply, or multiply ×2).
- Alpha blending, additive and inverse blending, and the alpha-test cutout follow the material's
  blend mode.

The colours are computed in the game's display encoding and decoded once, so import switches the
scene's view transform to **Standard**. Filmic or AgX would wash the result out.

The preview does not reproduce real-time lights on dynamic objects, fog, or the rare dot3
normal-map path.

**Markers.** Every entity without a model of its own becomes a small coloured diamond in
**&lt;group&gt; Markers**, and every model with a gameplay job (perk machines, doors, the power
switch, box locations, traps, Pack-a-Punch, barricades) gets a locked diamond badge above it that
moves with the model. Names say what the thing is, using the level designer's own names where the
data has them, for example `Quick Revive perk "QuickRevive"` or `Door 750 "Lobby_To_Atrium"`; the
`boz_description` custom property explains it (`Quick Revive perk machine, 500 points, linked to
the power switch`) and `boz_components` lists everything the entity contains. Colours by job:

| Colour | Job | Colour | Job |
| --- | --- | --- | --- |
| purple | perk machine | magenta | Pack-a-Punch |
| cyan | mystery box location | orange | door or debris |
| yellow | power switch | red | trap or trap switch |
| green | wall buy | brown | barricade |
| blue | teleporter | pink | Easter egg |
| dark red | zombie or player spawn | light blue | particle effect |
| lime | interact point | teal | sound |
| white | zombie jump point | grey | locator, camera, group |

Markers move, rotate and save like objects. A perk machine's glow and particles are separate
effect markers next to it, so select them together when you move the machine. Entities attached
to a bone are placed at their parent's origin.

**Links and areas.** Entities refer to each other by name, and **Show > Links** draws those
references as lines (by default only for the selected objects):

| Colour | Link | Meaning |
| --- | --- | --- |
| yellow | power | needs the power switch (doors, perks, Pack-a-Punch, trap switches, teleporters, TVs) |
| red | traps | a trap switch fires these traps |
| orange | siblings | doors that open together |
| cyan | unlocks | the areas a door opens |
| violet | members | an area's spawn points, perk machines, teleport points, shortcuts and locators |

Areas (zones such as `lobby` or `theatre`) appear as violet diamonds at the centre of their
members when **Show > Areas** is on. Spawns in an area only activate once a door unlocks it.

The **Selected** panel under BOZ Redux describes the active object, lists its links with a button
to select each target, an **×** to remove a link and **+** to link the other selected objects
(select the targets first, the object to link from last; a single link such as power is
replaced). **Linked from** lists everything that refers to it. Only entities with a game name can
be linked to. Link edits are saved with the rest.

**Shapes.** Collision boxes, spheres and capsules on entities and each interaction point's reach
are translucent children of their entity in **&lt;group&gt; Shapes**, hidden until you turn on
**Show > Shapes**. Their colour gives the role: red for solid collision, green for ghost
(pass-through trigger) volumes, yellow discs for how close a player must be to interact. They move
with their entity in the game. Edit them to change the game's values: a box's scale is its half
size and its position its centre; a sphere's uniform scale is its radius; a capsule's X/Y scale is
its radius and Z its half height; a reach disc's scale is the interaction distance and its height
the height offset. Shapes cannot be rotated relative to their entity. The level's world collision
(orange wire) is separate from these shapes.

**Collision.** A level's world collision is one mesh, cooked from the render models: in Kino, 82%
of its triangles lie exactly on one placed model. Those triangles are imported as a hidden wire
child of that model (`<model> collision`), so moving, rotating or scaling the model carries its
collision with it. Collision that belongs to no single model (invisible walls, simplified
surfaces) stays in the level's collision object. Saving stitches everything back into the one
mesh the game loads, in the original triangle order; where a moved piece shared a vertex with a
still one, the vertex is split. In Call of the Dead and Ascension the collision object has its own
position.

**Portals** show their front and back sector names in the `boz_front_sector` and
`boz_back_sector` custom properties. **Navigation connections** (window and barricade climbs) are
two-point edges.

## Edit

Supported:

- **Transforms:** move, rotate and scale placed models, entity empties and collision objects.
  Rotation mode may be changed; export reads the final transform.
- **Model geometry:** vertex positions and both UV sets, with unchanged topology. Native models
  duplicate vertices at UV seams; moving one copy moves all copies of that position, and moving
  copies to different places is rejected.
- **Collision:** move pieces with their models, or edit vertex positions and per-face material
  slots of any collision object, with unchanged topology. Deleting a collision piece is rejected
  on save. Collision
  decides what bullets and other ray casts hit; export updates both copies the game loads (the
  ray-cast arrays and the Bullet physics shape). It does not decide where players and zombies can
  walk: that is the navmesh, which cannot be edited yet.
- **Portals:** vertices and sector names.
- **Navigation connections:** either endpoint.

Not supported yet:

- Adding or removing vertices or faces, applying modifiers, or reassigning model materials.
- Re-parenting objects. An object must keep the parent it was imported with.
- Editing Detour navmesh polygons. Their tiles are preserved byte-for-byte.

## Save, reload and play

The sidebar's **Client** field is your BOZ Redux client folder (set it once; Blender remembers it)
and **Mod** names the mod your edits go into (`blender_edits` by default).

1. **Validate BOZ scene** reports non-triangle faces, empty geometry, duplicated identities,
   changed parents and objects from an older add-on version.
2. **Save to mod** writes every changed group into `<client>/mods/<mod>/assets/` under its game
   file name, creating the mod if needed. Unchanged groups are not written. Saving again replaces
   the mod's earlier copies; the game's own files are never written.
3. **Import level folder** has **Include mod edits** enabled by default: groups already saved to
   your mod are loaded instead of the game's copies, exactly as the client does. Continue editing
   and save again.
4. Start the game. New mods are enabled automatically (the launcher's Mods tab can disable it),
   so the edits appear the next time the level loads.

Every unknown section and unsupported resource body stays byte-identical. Editing the geometry of
a model that lives in the shared `ingame` group saves a new `ingame.group.bin` in the mod; moving
it changes only the group that places it.

Under **Files**, **Import native group** opens a single `.group.bin`, **Export edited level** writes
changed groups into any folder (for example an SDK project's `assets/`), and **Export edited
group** writes one group to a new file (`<name>-edited.group.bin`, byte-identical without edits).

## Practical checks

All in Blender's sidebar and the game:

1. Set **Client** to your `boz-redux` folder. **Import level folder** on `levels/kino`.
2. Move two objects, rotate one, scale one, and raise a small wall of floor collision in
   kino_statics by about a player's height. **Validate**, then **Save to mod**; the status line
   names the groups it saved.
3. **File > New**, then **Import level folder** on `levels/kino` again: every edit is still there.
4. Play Kino with the mod: the objects sit where you put them, and shots stop on the raised
   collision. You can still walk through it, because walking follows the navmesh.
5. Disable the mod in the launcher and play again: everything is back to normal.

## Automated checks

```bash
cd /home/zappa/Work/boz/boz-redux-sdk
for test in headless_roundtrip texture_sampling texture_pixels; do
  ALSOFT_DRIVERS=null blender -b --factory-startup --python-exit-code 1 \
    --python blender/tests/$test.py
done
```

Each prints `BOZ_..._OK`. The tests use synthetic resources only. They cover the single-group and
level workflows, shared meshes, transform and scale edits, Edit Mode collision edits that update the
Bullet shape, byte-identical untouched export, the GL texture-row convention, and that a
display-encoded texel renders unchanged.
