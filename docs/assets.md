# Assets: your own models in the game

The **Assets** tab brings your own models into the game at the game's level of detail. You
import a high-quality model, and the editor makes a game version of it: a few thousand triangles
at most and small textures, the way the game's own models are made. You then place the game
version in a map, and (once the Weapons tab can use them) make it a weapon.

## Importing

**Import…** takes a `.blend`, `.fbx`, `.glb`/`.gltf` or `.obj` file. Choose:

- **Kind:** **Prop** (a model to place in maps) or **Weapon** (a gun: its armature, bones and
  bone weights are kept, and its parts are found from the bones).
- **Preset:** how detailed the game version is.

| Preset | Weapon | Prop |
| --- | --- | --- |
| **Stock** (like the game's own) | 1,500 triangles, textures up to 512 | 800 triangles, textures up to 256 |
| **PC** (sharper) | 4,000 triangles, textures up to 1024 | 2,500 triangles, textures up to 512 |

For comparison, the game's guns have about 1,000 to 1,300 triangles and 256 to 512 textures. A
busy model (lots of thin spikes, tentacles, teeth) keeps its shape much better on PC; import a
gun as a Weapon, since a Prop's budget is about half.

The file is copied into the project (`assets/<name>/`), and its original location is remembered,
so **Refresh from source** picks up later changes to it (for example a magazine added to the
gun). The game version is made straight away.

## Making the game version

**Make game version** runs in the background (the editor stays usable; progress shows in the
Log). It:

1. Loads the model's meshes (from a `.blend`: all its meshes, with their armatures). The
   armature with the most bones is the model's; another armature that shares a bone name with it
   (a magazine with its own `tag_clip`, as ripped attachments come) is snapped so that bone lines
   up with the model's, the way the game attaches parts, wherever it sits in the file.
2. Works out the size: the **Source unit** (centimetres, metres, inches, millimetres) is guessed
   from the model's length (a weapon 30 to 200 cm, a prop 10 to 600 cm) unless you set it.
3. Reduces every mesh to its share of the triangle budget (bigger meshes get more; small parts
   such as eyes keep at least a few dozen triangles). Each mesh is welded first, so it reduces as
   one surface without cracks; afterwards every triangle reads its texture coordinates back from
   the original surface, from the texture island under its centre, so no triangle smears the
   texture across a seam. Bone weights are kept.
4. Makes one texture per material: the colour image reduced to a power of two, the biggest
   surfaces getting the preset's size and smaller ones less (about the same detail per
   centimetre everywhere). The game has no normal maps, so with **Bake normal map** on the normal
   map's detail is shaded into the colour (lit from above and in front). Two-channel normal maps
   (Call of Duty's, with an empty blue channel) work too. A material without an image gets a
   small texture of its colour.

5. Closes what reducing opened, so nothing is see-through: reducing rounds corners off and lets
   the borders of the model's open shells (parts tucked into each other) creep back, which opens
   gaps. The reduced surface is pushed out gently to cover the original, and every open border
   grows back a little so neighbouring shells overlap again. Then the game version is drawn as
   the game draws it (one side) from six directions against the original: if anything is
   see-through, it is made again from the original with more triangles (up to five times). Game
   checks says when it needed more triangles than your budget; a model this busy at the Stock
   preset may need two or three times as many.

**Own budget** sets the triangle count yourself; **Textures** caps the texture size.

## The view

The tab has its own scene: the map is never touched. The viewport header switches between
**High quality**, **Game** and **Side by side**. The game version is drawn the way the game draws
it (the texture only, no lighting). The image editor shows its textures.

The game version is an ordinary mesh: you can touch it up by hand and **Save edits** keeps your
changes (bone weights follow the nearest original vertex). Making it again asks first, because
it replaces your edits.

## Game checks

**Game checks** lists the game version's triangles, vertices, textures (and their memory), size
and bones, then:

- **Problems** (they stop the map from building): more than 65,535 vertices, a model more than
  3.2 m from its centre (usually the wrong unit), texture coordinates past -8..8, texture sides
  that are not powers of two from 4 to 1024, a vertex following more than 4 bones.
- **Warnings**: over the triangle budget, textures over the preset, and for weapons a missing
  part (the magazine, `tag_clip`: the reload would show none).

Where there is a one-click fix (reduce the budget, halve the textures, use centimetres), a
**Fix** button sits next to it.

## Using an asset

**Place in map** puts a copy at the 3D cursor in the World tab; **Add → My assets** and the
palette's **My assets** catalog (drag it in) do the same. A placed asset is a model like any
other (collision, start state, scripts, prefabs) that refers to the asset: making the asset
again updates every copy. An asset placed in the map cannot be removed until its copies are
deleted.

The game version is stored in tenths of a centimetre (the game's positions are 16-bit
integers, so this keeps small details) and placed at 0.1 scale, the way the game itself places
some of its models.

## Files

```text
assets/<name>/<file>              the source file (a copy)
source/assets/<name>.json         settings: kind, preset, budget, texture size, unit, ...
source/assets/<name>/model.json   the game version: vertices, uvs, triangles, materials;
                                  weapons also bones, bone weights and parts
source/assets/<name>/textures/    one PNG per material
source/assets/<name>/stats.json   the figures and checks shown in the tab
```

`bozkit.assets` reads and writes these; `blender/boz_suite/asset_build.py` makes the game version.
Third-party models (ripped game models and the like) belong in your project only: do not
publish them.
