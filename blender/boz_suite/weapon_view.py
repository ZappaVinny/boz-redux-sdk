"""The weapon view (Weapons and Animation tabs): the selected weapon as one Blender armature.

The Weapons tab has a scene of its own (link.VIEW_SCENE) with:

- "BOZ rig": one armature: the arms' skeleton (rest = the game's bind pose, model units) and,
  under its TAG_WEAPON bone ("gun position"), the gun's skeleton (your model's own, or the stock
  gun's). Each arm has IK to a grip point fixed to the gun ("hand L", "hand R"), so moving the
  gun brings the hands, and moving a hand changes the grip;
- "BOZ arms" and "BOZ gun": the models on it (Armature modifier; the game's skin as vertex
  groups: Blender's skinning is the game's when the rest pose is the bind pose);
- the first-person camera (the game's projection: viewmodel.view_angle).

Animations (Animation tab): each part, arms and gun, has its own timeline of changes
(bozkit.weapon_anim Timelines). Before a part's first change it plays the original; when you
change a pose and leave the frame, that pose holds from that frame on until your next change;
earlier frames never move. The rig plays one dense action made from the timelines; the game gets
the result at every frame (with the IK baked in) when you save.

Placement (Weapons tab): Position on screen moves the whole rig in front of the camera (the
weapon's "arms" entry); Fit model in hand places your model relative to the hand (its "fit").
"""
from __future__ import annotations

import math

import bpy
from bpy.props import (BoolProperty, CollectionProperty, EnumProperty, FloatProperty,
                       FloatVectorProperty, IntProperty, StringProperty)
from bpy.types import Operator, Panel, PropertyGroup

from . import link

from ._bozkit import anim, assets, viewmodel, weapon_anim, weapon_model
from ._bozkit import hashing
iw_hash = hashing.iw_hash

WORKSPACES = ("Weapons", "Animation")
VIEW_CAMERA = "BOZ view camera"
VIEW_KEY = "boz_weapon_view"       # a workspace: its viewport is set up
RIG, ARMS, GUN = "BOZ rig", "BOZ arms", "BOZ gun"
FIT_MODEL, GHOST = "BOZ fit", "BOZ stock gun"
TAG = "gun position"               # the arms' TAG_WEAPON bone, which the gun hangs from
GRIPS = {"L": 6, "R": 15}          # side -> wrist bone of the arms' skeleton
CHAINS = {"L": (4, 5), "R": (13, 14)}   # side -> (upper arm, forearm)
ARM_NAMES = ("root", "view", "view tip", "torso",
             "upper arm L", "forearm L", "wrist L", "finger L 1", "finger L 1 tip", "finger L 2",
             "finger L 2 tip", "thumb L", "thumb L tip",
             "upper arm R", "forearm R", "wrist R", "finger R 1", "finger R 1 tip", "finger R 2",
             "finger R 2 tip", "thumb R", "thumb R tip", TAG)
HIDDEN = {"root", "view", "view tip", "wrist L", "wrist R", "gun root", "ik L", "ik R"}
_state: dict = {"key": None, "rig": None, "asset": None, "cache": {}, "items": None,
                "shown": None, "guard": False, "busy": False, "preview": "", "frame": 0,
                "baked": {}, "edits": {"arms": [], "gun": []}, "length": 0, "dirty": False,
                "clipboard": None, "state": None}


def wt():
    from . import weapons_tab
    return weapons_tab


def _C():
    from mathutils import Matrix
    return Matrix(((1, 0, 0, 0), (0, 0, -1, 0), (0, 1, 0, 0), (0, 0, 0, 1)))


def to_bl(matrix):
    c = _C()
    return c @ matrix @ c.inverted()


def from_bl(matrix):
    c = _C()
    return c.inverted() @ matrix @ c


def game_matrix(position, rotation, unit: float = anim.SKEL_SCALE):
    from mathutils import Matrix, Quaternion, Vector
    return Matrix.Translation(Vector(position) / unit) @ Quaternion(rotation).normalized().to_matrix().to_4x4()


def _game(matrix):
    """(position in skeleton units, rotation) of a Blender matrix (model units)."""
    location, rotation, _scale = from_bl(matrix).decompose()
    return tuple(c * anim.SKEL_SCALE for c in location), tuple(rotation)


def _compose(a, b):
    position, rotation = a
    offset = anim.quat_rotate(rotation, b[0])
    return (tuple(p + o for p, o in zip(position, offset)), anim.quat_mul(rotation, b[1]))


def _inverse(t):
    position, rotation = t
    inverse = anim.quat_conj(rotation)
    return (tuple(-c for c in anim.quat_rotate(inverse, position)), inverse)


# --- The weapon's data ---------------------------------------------------------------------

def _weapon():
    item = wt().selected(link.map_scene())
    return (item, wt().weapon_def(bpy.context, item.name)) if item else (None, None)


class Bones:
    """The rig's bones in game terms: per bone its Blender name, game parent (index or None) and
    bind (position, rotation) relative to it, which part it belongs to, how clips name it."""

    def __init__(self, rig, asset, fit):
        self.names, self.parents, self.binds, self.part, self.keys = [], [], [], [], []
        arms = rig.arm_bones
        index_of = {b.name: i for i, b in enumerate(arms)}
        tag = index_of.get(iw_hash("TAG_WEAPON"))
        standard = len(arms) == len(ARM_NAMES) and tag == len(ARM_NAMES) - 1
        for i, bone in enumerate(arms):
            self.names.append(ARM_NAMES[i] if standard else (TAG if i == tag else f"arm {i}"))
            self.parents.append(index_of.get(bone.parent))
            self.binds.append((tuple(bone.position), tuple(bone.rotation)))
            self.part.append("gun" if i == tag else "arms")
            self.keys.append(str(i))
        self.tag = tag
        self.arm_count = len(arms)
        # The gun's skeleton under TAG_WEAPON: your model's own (game space) or the stock one.
        if asset is not None:
            gun = weapon_anim.own_skeleton(asset, fit)
            labels = [weapon_anim.ROOT] + weapon_anim.bone_names(asset)
        else:
            gun = rig.gun_bones
            labels = [weapon_model.bone_label(gun, i) for i in range(len(gun))]
        self.gun_bones = gun
        self.gun_start = len(self.names)
        gun_index = {b.name: i for i, b in enumerate(gun)}
        seen = set(self.names)
        for i, bone in enumerate(gun):
            name = "gun root" if i == 0 else f"gun {labels[i]}"
            while name in seen:
                name += "."
            seen.add(name)
            self.names.append(name)
            parent = gun_index.get(bone.parent)
            self.parents.append(self.gun_start + parent if parent is not None else tag)
            self.binds.append((tuple(bone.position), tuple(bone.rotation)))
            self.part.append("gun")
            self.keys.append(str(i))
        self.index = {name: i for i, name in enumerate(self.names)}

    def worlds(self, locals_):
        """Game-space worlds of every bone from {index: (position, rotation)} locals."""
        out = []
        for i, parent in enumerate(self.parents):
            local = locals_.get(i, self.binds[i])
            out.append(_compose(out[parent], local) if parent is not None else local)
        return out


def load(context) -> bool:
    """Read the selected weapon's skeletons and animations (cached by weapon)."""
    import json
    item, weapon = _weapon()
    if item is None or wt()._pack() is None:
        return False
    level = weapon.level or wt().base_level(context)
    key = (item.name, level, weapon.source, json.dumps(weapon.model, sort_keys=True))
    if _state["key"] == key and _state["rig"] is not None:
        return True
    rig = viewmodel.Rig(wt()._pack().read, level, weapon.source)
    asset, error = None, ""
    if weapon.model.get("asset"):
        try:
            asset, _textures = assets.load_game(wt().source_dir(), weapon.model["asset"])
            if not asset.bones:
                asset, error = None, f"{weapon.model['asset']} has no bones: make it as a Weapon"
        except (assets.AssetError, KeyError, ValueError) as exc:
            error = str(exc)
    fit = weapon.model.get("fit") or {}
    _state.update(key=key, rig=rig, asset=asset, error=error, cache={}, items=None,
                  bones=Bones(rig, asset, fit), fit=fit, bone_map=weapon.model.get("bones") or {})
    return True


def states():
    """[(state hash, label, frames, looping)] of the weapon's animations."""
    rig = _state["rig"]
    if rig is None:
        return []
    if _state["items"] is None:
        out = []
        for view_state in rig.states():
            arms = rig._anim(rig.arm_anims, rig.arm_states, view_state.name)
            gun = rig._anim(rig.gun_anims, rig.gun_states, view_state.name)
            length = max((weapon_anim.frame_of(a.duration or (a.keyframes[-1].time if a.keyframes else 0))
                          for a in (arms, gun) if a is not None), default=0)
            out.append((view_state.name, view_state.label, length, view_state.looping))
        _state["items"] = out
    return _state["items"]


def current_state():
    try:
        return int(bpy.context.window_manager.boz_anim_state)
    except (TypeError, ValueError):
        return None


def _original(part: str, state: int):
    """The original clip of a part: arms by arm bone; the gun by bone of the rig's gun skeleton
    (the stock motion moved onto your model's own skeleton). The idle one where it has none."""
    key = ("original", part, state)
    cache = _state["cache"]
    if key in cache:
        return cache[key]
    rig = _state["rig"]
    clip = None
    if part == "arms":
        found = rig._anim(rig.arm_anims, rig.arm_states, state) or \
            rig._anim(rig.arm_anims, rig.arm_states, rig.idle())
        if found is not None:
            clip = weapon_anim.stock_clip(found, rig.arm_bones)
    else:
        found = rig._anim(rig.gun_anims, rig.gun_states, state) or \
            rig._anim(rig.gun_anims, rig.gun_states, rig.idle())
        if found is not None:
            if _state["asset"] is not None:
                follow = weapon_anim.follow_list(_state["asset"], rig.gun_bones, _state["bone_map"])
                clip = weapon_anim.retarget(rig.gun_bones, found, _state["bones"].gun_bones, follow)
            else:
                clip = weapon_anim.stock_clip(found, rig.gun_bones)
    cache[key] = clip
    return clip


def _gun_keys_to_game(values: dict) -> dict:
    """Stored gun pose values ({clip key: key}) as {gun bone index: key} in game space."""
    if _state["asset"] is not None:
        names = set(weapon_anim.bone_names(_state["asset"]))
        named = {k: v for k, v in values.items() if k in names}
        clip = weapon_anim.gun_clip_to_game(weapon_anim.Clip([(0, named)]), _state["asset"], _state["fit"])
        return {i: v for i, v in clip.frames[0][1].items() if i != 0}
    return {int(k): v for k, v in values.items() if str(k).isdigit()}


def _gun_game_to_keys(values: dict) -> dict:
    """{gun bone index: game key} as stored pose values (your model's: by name, its own space)."""
    if _state["asset"] is not None:
        clip = weapon_anim.game_clip_to_asset(weapon_anim.Clip([(0, values)]), _state["asset"], _state["fit"])
        return clip.frames[0][1]
    return {str(i): v for i, v in values.items()}


def _arm_parts(locals_: dict) -> tuple:
    """(arms values, gun values) to store from rig-wide game locals (and grips)."""
    bones = _state["bones"]
    arms = {str(i): v for i, v in locals_.items() if i < bones.arm_count and i != bones.tag}
    gun = {"TAG_WEAPON": locals_[bones.tag]}
    gun.update(_gun_game_to_keys({i - bones.gun_start: v for i, v in locals_.items()
                                  if i >= bones.gun_start}))
    return arms, gun


def frame_locals(state: int, frame: int, entry: dict | None = None, edits: dict | None = None) -> tuple:
    """({rig bone index: game local}, {side: grip local}, IK on) of *state* at *frame*."""
    bones = _state["bones"]
    edits = _state["edits"] if edits is None else edits
    entry = entry or {}
    out, grips = {}, {}
    defaults_arms = {i: bones.binds[i] for i in range(bones.arm_count)}
    arm_kind, arm_value = weapon_anim.source_of(edits["arms"], frame)
    if arm_kind == "pose":
        values = weapon_anim.pose_values(arm_value)
        arms_locals = dict(defaults_arms)
        arms_locals.update({int(k): v for k, v in values.items() if k.isdigit()})
        grips = {k[-1]: v for k, v in values.items() if k.startswith("hand ")}
    else:
        arms_locals = weapon_anim.sample(_original("arms", state), arm_value, defaults_arms)
    for i, value in arms_locals.items():
        if i != bones.tag:
            out[i] = value
    if not grips:     # the arms' own grip on the gun: wrist relative to TAG_WEAPON in that data
        worlds = bones.worlds(arms_locals)
        for side, wrist in GRIPS.items():
            grips[side] = _compose(_inverse(worlds[bones.tag]), worlds[wrist])
    gun_kind, gun_value = weapon_anim.source_of(edits["gun"], frame)
    defaults_gun = {i: (tuple(b.position), tuple(b.rotation)) for i, b in enumerate(bones.gun_bones)}
    if gun_kind == "pose":
        values = weapon_anim.pose_values(gun_value)
        tag = values.get("TAG_WEAPON", arms_locals.get(bones.tag, bones.binds[bones.tag]))
        gun_locals = dict(defaults_gun)
        gun_locals.update(_gun_keys_to_game(values))
    else:
        original_arms = weapon_anim.sample(_original("arms", state), gun_value, defaults_arms)
        tag = original_arms.get(bones.tag, bones.binds[bones.tag])
        gun_locals = weapon_anim.sample(_original("gun", state), gun_value, defaults_gun)
    out[bones.tag] = tag
    for i, value in gun_locals.items():
        out[bones.gun_start + i] = value
    ik = weapon_anim.is_yours(edits["arms"], frame) or weapon_anim.is_yours(edits["gun"], frame)
    return out, grips, ik


# --- Building the view ---------------------------------------------------------------------

def view_scene():
    scene = bpy.data.scenes.get(link.VIEW_SCENE)
    if scene is None:
        scene = bpy.data.scenes.new(link.VIEW_SCENE)
        scene.render.resolution_x, scene.render.resolution_y = 1280, 720   # the game's frame
        scene.view_settings.view_transform = "Standard"
        world = bpy.data.worlds.get(link.VIEW_SCENE) or bpy.data.worlds.new(link.VIEW_SCENE)
        world.color = (0.05, 0.05, 0.06)
        scene.world = world
    scene.render.fps = weapon_anim.FPS
    scene.render.fps_base = 1.0
    return scene


def _remove(name: str) -> None:
    obj = bpy.data.objects.get(name)
    if obj is None:
        return
    data = obj.data
    bpy.data.objects.remove(obj)
    if isinstance(data, bpy.types.Mesh) and data.users == 0:
        bpy.data.meshes.remove(data)
    elif isinstance(data, bpy.types.Armature) and data.users == 0:
        bpy.data.armatures.remove(data)


def _link(view, obj):
    for collection in list(obj.users_collection):
        if collection is not view.collection:
            collection.objects.unlink(obj)
    if obj.name not in view.collection.objects:
        view.collection.objects.link(obj)
    obj["boz_preview"] = "weapon"
    if hasattr(obj, "boz"):
        obj.boz.role = "reference"
    return obj


def _edit_mode(view, obj, mode: str) -> None:
    """Switch *obj* (in the weapon scene) to *mode*: the window shows the weapon scene while the
    mode changes (Blender changes modes in the window's scene)."""
    if obj.mode == mode:
        return
    wm = bpy.context.window_manager
    window = bpy.context.window or (wm.windows[0] if wm.windows else None)
    layer = view.view_layers[0]
    shown = window.scene if window is not None else None
    if window is not None and shown != view:
        window.scene = view
    try:
        layer.objects.active = obj
        overrides = {"window": window} if window is not None else {}
        overrides.update(scene=view, view_layer=layer, active_object=obj, object=obj)
        with bpy.context.temp_override(**overrides):
            bpy.ops.object.mode_set(mode=mode)
    finally:
        if window is not None and shown is not None and window.scene != shown:
            window.scene = shown


def _build_rig(view):
    """The one armature: arms, the gun under TAG_WEAPON, grips and IK."""
    from mathutils import Vector
    bones = _state["bones"]
    _remove(RIG)
    data = bpy.data.armatures.new(RIG)
    obj = _link(view, bpy.data.objects.new(RIG, data))
    worlds = bones.worlds({})
    rests = [to_bl(game_matrix(*w)) for w in worlds]
    _edit_mode(view, obj, "EDIT")
    try:
        for i, name in enumerate(bones.names):
            edit = data.edit_bones.new(name)
            edit.head, edit.tail = (0.0, 0.0, 0.0), (0.0, 2.0 if i < bones.arm_count else 8.0, 0.0)
            edit.matrix = rests[i]
        for i, parent in enumerate(bones.parents):
            if parent is not None:
                data.edit_bones[bones.names[i]].parent = data.edit_bones[bones.names[parent]]
        tag = data.edit_bones[TAG]
        for side, wrist in GRIPS.items():
            grip = data.edit_bones.new(f"hand {side}")
            grip.head, grip.tail = (0.0, 0.0, 0.0), (0.0, 12.0, 0.0)
            grip.matrix = rests[wrist]
            grip.parent = tag
            _upper, forearm = CHAINS[side]
            helper = data.edit_bones.new(f"ik {side}")
            helper.head = rests[forearm].to_translation()
            helper.tail = rests[wrist].to_translation()
            if (helper.tail - helper.head).length < 1e-3:
                helper.tail = helper.head + Vector((0.0, 1.0, 0.0))
            helper.parent = data.edit_bones[bones.names[forearm]]
    finally:
        _edit_mode(view, obj, "OBJECT")
    for pose_bone in obj.pose.bones:
        pose_bone.rotation_mode = "QUATERNION"
    for side, wrist in GRIPS.items():
        helper = obj.pose.bones[f"ik {side}"]
        helper.lock_ik_x = helper.lock_ik_y = helper.lock_ik_z = True
        ik = helper.constraints.new("IK")
        ik.name = "IK"
        ik.target, ik.subtarget = obj, f"hand {side}"
        ik.chain_count = 3
        ik.influence = 0.0
        hand = obj.pose.bones[bones.names[wrist]]
        copy = hand.constraints.new("COPY_ROTATION")
        copy.name = "Grip"
        copy.target, copy.subtarget = obj, f"hand {side}"
        copy.influence = 0.0
    for bone in data.bones:
        bone.hide = bone.name in HIDDEN
    data.display_type = "STICK"
    data.show_names = True
    obj.show_in_front = True
    obj.hide_select = False
    _state["rests"] = {b.name: (b.parent.matrix_local.inverted() @ b.matrix_local if b.parent
                                else b.matrix_local.copy()) for b in data.bones}
    return obj


def _skin_mesh(view, name: str, data, rig_obj, weights_of):
    """The model on the rig: vertex groups from the skin, an Armature modifier."""
    _remove(name)
    obj = _link(view, bpy.data.objects.new(name, data))
    groups: dict = {}
    by_bone: dict = {}
    for vertex, weights in enumerate(weights_of):
        for bone, weight in weights:
            if weight > 0:
                by_bone.setdefault((bone, round(weight, 4)), []).append(vertex)
    for (bone, weight), vertices in by_bone.items():
        group = groups.get(bone) or obj.vertex_groups.new(name=bone)
        groups[bone] = group
        group.add(vertices, weight, "REPLACE")
    modifier = obj.modifiers.new("Armature", "ARMATURE")
    modifier.object = rig_obj
    obj.parent = rig_obj
    obj.hide_select = False
    return obj


def _skin_weights(skin, model, count: int, names: list):
    """Per render vertex [(bone name, weight)] from a game skin (which indexes unique positions)."""
    per_unique: dict = {}
    for skin_set in skin.sets:
        for index, _locals, weights in skin_set.vertices:
            total = sum(weights) or 1.0
            per_unique[index] = [(names[b] if b < len(names) else names[0], w / total)
                                 for b, w in zip(skin_set.bones, weights)]
    remap = model.position_remap or list(range(count))
    return [per_unique.get(remap[v] if v < len(remap) else v, [(names[0], 1.0)]) for v in range(count)]


def arms_matrix(arms: dict):
    from mathutils import Matrix, Quaternion, Vector
    m = (Matrix.Translation(Vector((arms or {}).get("location", (0.0, 0.0, 0.0))))
         @ Quaternion((arms or {}).get("rotation", (1.0, 0.0, 0.0, 0.0))).normalized().to_matrix().to_4x4())
    return to_bl(m)


def fit_matrix(fit: dict):
    from mathutils import Matrix, Quaternion, Vector
    m = (Matrix.Translation(Vector(fit.get("location", (0.0, 0.0, 0.0))))
         @ Quaternion(fit.get("rotation", (1.0, 0.0, 0.0, 0.0))).normalized().to_matrix().to_4x4()
         @ Matrix.Scale(float(fit.get("scale", 1.0)), 4))
    return to_bl(m)


def fit_from_matrix(matrix) -> dict:
    location, rotation, scale = from_bl(matrix).decompose()
    return {"location": [round(c, 3) for c in location],
            "rotation": [round(c, 6) for c in rotation],
            "scale": round(sum(scale) / 3, 6)}


def show_preview(context) -> str:
    """Build the selected weapon's view: the rig, the arms and gun models, the camera."""
    from . import game
    store(context)
    if not load(context):
        return "No weapon selected"
    rig = _state["rig"]
    bones = _state["bones"]
    view = view_scene()
    item, weapon = _weapon()
    wm = context.window_manager
    for obj in list(view.objects):      # everything: also what older versions left in the file
        _remove(obj.name)
    rig_obj = _build_rig(view)
    rig_obj.matrix_basis = arms_matrix(weapon.arms)       # Position on screen (saved)
    _state["arms_basis"] = [list(r) for r in rig_obj.matrix_basis]
    arm_names = bones.names[:bones.arm_count]
    base = game.model_mesh(rig.arms_path, rig.arm_model_hash) if rig.arm_model is not None else None
    if base is not None:
        data = base.copy()
        data.name = ARMS
        _skin_mesh(view, ARMS, data, rig_obj,
                   _skin_weights(rig.arm_skin, rig.arm_model, len(data.vertices), arm_names))
    tag_rest = to_bl(game_matrix(*bones.worlds({})[bones.tag]))
    gun_names = bones.names[bones.gun_start:]
    if _state["asset"] is not None:
        from . import assets_tab
        data = assets_tab.build_mesh(weapon.model["asset"], GUN, unit_scale=1.0)
        if data is not None:
            data.transform(tag_rest @ fit_matrix(_state["fit"]))   # rest: in the hand, fitted
            model = _state["asset"]
            order = {name: i + 1 for i, name in enumerate(weapon_anim.bone_names(model))}
            remap = [order.get(b.name, 0) for b in model.bones]
            weights = [[(gun_names[remap[b]] if b < len(remap) else gun_names[0], w) for b, w in vertex]
                       or [(gun_names[0], 1.0)] for vertex in model.weights] or \
                [[(gun_names[0], 1.0)]] * len(data.vertices)
            _skin_mesh(view, GUN, data, rig_obj, weights)
    elif rig.gun_model is not None:
        base = game.model_mesh(rig.weapons_path, rig.gun_model_hash)
        if base is not None:
            data = base.copy()
            data.name = GUN
            data.transform(tag_rest)
            _skin_mesh(view, GUN, data, rig_obj,
                       _skin_weights(rig.gun_skin, rig.gun_model, len(data.vertices), gun_names))
    _camera(view)
    _state["shown"] = item.name
    _state["preview"] = f"{item.label}: " + ("your model, " if _state["asset"] is not None else "") + \
        "first-person view"
    _state["guard"] = True
    try:
        wm.boz_anim_state = str(rig.idle())
    except TypeError:
        pass
    finally:
        _state["guard"] = False
    show_state(context, rig.idle())
    apply_visibility(context)
    refresh_model_panel(context)
    for window in wm.windows:
        if window.workspace.name in WORKSPACES:
            window.workspace[VIEW_KEY] = False
    _state["frame_gun"] = True
    return _state["preview"]


def _pending_preview():
    try:
        show_preview(bpy.context)
    except (ReferenceError, RuntimeError, AttributeError, KeyError, ValueError) as exc:
        print(f"boz_suite: the weapon view could not be built: {exc}")
    return None


def request_preview() -> None:
    """Build the view soon (from a timer): property updates must not run operators, and
    building armatures switches modes."""
    if not bpy.app.timers.is_registered(_pending_preview):
        bpy.app.timers.register(_pending_preview, first_interval=0.01)


def flush() -> None:
    """Build a requested view now (tests; background Blender runs no timers)."""
    if bpy.app.timers.is_registered(_pending_preview):
        bpy.app.timers.unregister(_pending_preview)
        _pending_preview()


def _camera(view):
    data = bpy.data.cameras.get(VIEW_CAMERA) or bpy.data.cameras.new(VIEW_CAMERA)
    data.sensor_fit = "HORIZONTAL"   # the game's field of view spans the screen's width
    data.angle = viewmodel.view_angle(bpy.context.window_manager.boz_view_fov)
    data.clip_start, data.clip_end = 5.0, 100000.0
    camera = bpy.data.objects.get(VIEW_CAMERA)
    if camera is None:
        camera = bpy.data.objects.new(VIEW_CAMERA, data)
    _link(view, camera)
    camera.location = (0.0, 0.0, 0.0)
    camera.rotation_euler = (math.pi / 2, 0.0, math.pi)   # the game's eye looks down +Z (Y up)
    camera.hide_select = True
    view.camera = camera


# --- The animation shown -------------------------------------------------------------------

def _entry(state: int) -> dict:
    item, _weapon_ = _weapon()
    if item is None or wt().source_dir() is None:
        return {}
    try:
        return weapon_anim.load_clips(wt().source_dir(), item.name).get(state, {})
    except weapon_anim.WeaponAnimError:
        return {}


def edited_states() -> set:
    item, _weapon_ = _weapon()
    if item is None or wt().source_dir() is None:
        return set()
    try:
        return set(weapon_anim.load_clips(wt().source_dir(), item.name))
    except weapon_anim.WeaponAnimError:
        return set()


def show_state(context, state: int) -> None:
    """Play *state*: read its changes (or none) and bake it onto the rig."""
    entry = _entry(state)
    edits = {part: list(entry.get("edits", {}).get(part, [])) for part in ("arms", "gun")}
    original = max((s[2] for s in states() if s[0] == state), default=0)
    _state.update(edits=edits, entry=entry, state=state, dirty=False,
                  length=int(entry.get("length") or original) or 1)
    bake(context)


def bake(context) -> None:
    """The rig's action: every frame of the animation from its timelines (dense), and the IK on
    where either part is yours."""
    view = view_scene()
    rig_obj = view.objects.get(RIG)
    state = _state.get("state")
    if rig_obj is None or state is None:
        return
    bones = _state["bones"]
    rests = _state["rests"]
    entry = _state.get("entry") or {}
    length = max(1, _state["length"])
    names = bones.names + [f"hand {side}" for side in GRIPS]
    tracks = {name: [[] for _ in range(7)] for name in names}
    influence = []
    baked = {}
    previous: dict = {}
    for frame in range(0, length + 1):
        locals_, grips, ik = frame_locals(state, frame, entry)
        frame_values = {name: locals_.get(i, bones.binds[i]) for i, name in enumerate(bones.names)}
        for side, grip in grips.items():
            frame_values[f"hand {side}"] = grip
        baked_frame = {}
        for name, (position, rotation) in frame_values.items():
            basis = rests[name].inverted() @ to_bl(game_matrix(position, rotation))
            location, quaternion, _scale = basis.decompose()
            last = previous.get(name)
            if last is not None and last.dot(quaternion) < 0:
                quaternion.negate()
            previous[name] = quaternion
            baked_frame[name] = (tuple(location), tuple(quaternion))
            for channel, value in enumerate(list(location) + list(quaternion)):
                tracks[name][channel] += [frame, value]
        baked[frame] = baked_frame
        influence += [frame, 1.0 if ik else 0.0]
    action = bpy.data.actions.get("BOZ weapon animation")
    if action is not None:
        bpy.data.actions.remove(action)
    action = bpy.data.actions.new("BOZ weapon animation")
    slot = action.slots.new(id_type="OBJECT", name=rig_obj.name)
    bag = action.layers.new("Layer").strips.new(type="KEYFRAME").channelbag(slot, ensure=True)

    def curve(path, index, points, group, constant=False):
        fcurve = bag.fcurves.new(path, index=index, group_name=group)
        fcurve.keyframe_points.add(len(points) // 2)
        fcurve.keyframe_points.foreach_set("co", points)
        mode = "CONSTANT" if constant else "LINEAR"
        for point in fcurve.keyframe_points:
            point.interpolation = mode
        fcurve.update()

    for name, channels in tracks.items():
        if name not in rig_obj.pose.bones:
            continue
        for channel, points in enumerate(channels):
            path = "location" if channel < 3 else "rotation_quaternion"
            curve(f'pose.bones["{name}"].{path}', channel % 3 if channel < 3 else channel - 3, points, name)
    for side, wrist in GRIPS.items():
        curve(f'pose.bones["ik {side}"].constraints["IK"].influence', 0, influence, f"ik {side}", True)
        curve(f'pose.bones["{bones.names[wrist]}"].constraints["Grip"].influence', 0, influence,
              bones.names[wrist], True)
    rig_obj.animation_data_create()
    rig_obj.animation_data.action = action
    rig_obj.animation_data.action_slot = slot
    _state["baked"] = baked
    _state["busy"] = True
    try:
        view.frame_start, view.frame_end = 0, length
        if view.frame_current > length:
            view.frame_current = 0
        view.frame_set(view.frame_current)
        _state["frame"] = view.frame_current
        _state["guard"] = True
        try:
            context.window_manager.boz_anim_length = length
        finally:
            _state["guard"] = False
    finally:
        _state["busy"] = False


# --- Changes: kept when you leave a frame ----------------------------------------------------

def _group_of(name: str) -> str | None:
    if name.startswith("hand "):
        return "arms"
    bones = _state["bones"]
    index = bones.index.get(name)
    if index is None or name == "gun root":
        return None
    return bones.part[index]


def _current_values(rig_obj, group: str) -> dict:
    """The group's pose as stored values: arms by arm bone ("3") and grip ("hand L"); the gun by
    TAG_WEAPON and your model's bone names (its own space) or the stock gun's numbers."""
    bones = _state["bones"]
    rests = _state["rests"]
    values, gun = {}, {}
    for pose_bone in rig_obj.pose.bones:
        name = pose_bone.name
        if _group_of(name) != group:
            continue
        local = _game(rests[name] @ pose_bone.matrix_basis)
        if name.startswith("hand "):
            values[name] = local
        elif name == TAG:
            values["TAG_WEAPON"] = local
        elif bones.index[name] >= bones.gun_start:
            gun[bones.index[name] - bones.gun_start] = local
        else:
            values[str(bones.index[name])] = local
    if gun:
        gun[0] = (tuple(bones.gun_bones[0].position), tuple(bones.gun_bones[0].rotation))
        values.update({k: v for k, v in _gun_game_to_keys(gun).items()})
    return values


def _group_changed(rig_obj, group: str, frame: int) -> bool:
    from mathutils import Quaternion, Vector
    baked = _state["baked"].get(frame, {})
    for pose_bone in rig_obj.pose.bones:
        if _group_of(pose_bone.name) != group or pose_bone.name not in baked:
            continue
        location, rotation = baked[pose_bone.name]
        if (Vector(location) - pose_bone.location).length > 1e-3:
            return True
        if Quaternion(rotation).rotation_difference(pose_bone.rotation_quaternion).angle > 1e-3:
            return True
    return False


def capture(context=None, frame: int | None = None) -> bool:
    """Keep what you changed at *frame* (the frame shown): a pose of that part, held from there."""
    view = bpy.data.scenes.get(link.VIEW_SCENE)
    rig_obj = view.objects.get(RIG) if view else None
    if rig_obj is None or _state.get("state") is None or _state["busy"] or not _state["baked"]:
        return False
    frame = _state["frame"] if frame is None else frame
    changed = False
    for group in ("arms", "gun"):
        if _group_changed(rig_obj, group, frame):
            _state["edits"][group] = weapon_anim.add_pose(_state["edits"][group], frame,
                                                          _current_values(rig_obj, group))
            changed = True
    if changed:
        _state["dirty"] = True
        store_edits()
        bake(context or bpy.context)
    return changed


def _stored_edits() -> dict:
    return {part: list(changes) for part, changes in _state["edits"].items()}


def store_edits() -> None:
    """Write the changes now (the result at every frame follows when you save: store())."""
    item, _weapon_ = _weapon()
    state = _state.get("state")
    if item is None or state is None or wt().source_dir() is None or item.name != _state.get("shown"):
        return
    labels = {s[0]: s[1] for s in states()}
    entry = _state.get("entry") or {}
    weapon_anim.save_state(wt().source_dir(), item.name, state, labels.get(state, ""),
                           {part: entry.get(part) for part in ("arms", "gun")}, _stored_edits(),
                           _state["length"])


def store(context=None) -> bool:
    """Save the animation shown: its changes and the result at every frame (the IK baked in)."""
    view = bpy.data.scenes.get(link.VIEW_SCENE)
    rig_obj = view.objects.get(RIG) if view else None
    if rig_obj is None or _state.get("state") is None or _state.get("shown") is None:
        return False
    capture(context)
    if not _state["dirty"]:
        return False
    item, _weapon_ = _weapon()
    if item is None or item.name != _state["shown"] or wt().source_dir() is None:
        return False
    bones = _state["bones"]
    state = _state["state"]
    shown = view.frame_current
    arms_frames, gun_frames = [], []
    depsgraph = view.view_layers[0].depsgraph
    _state["busy"] = True
    try:
        for frame in range(0, max(1, _state["length"]) + 1):
            view.frame_set(frame)
            depsgraph.update()
            evaluated = rig_obj.evaluated_get(depsgraph)
            worlds = {i: _game(evaluated.pose.bones[name].matrix) for i, name in enumerate(bones.names)}
            arms_keys, gun_keys = {}, {}
            for i, parent in enumerate(bones.parents):
                local = _compose(_inverse(worlds[parent]), worlds[i]) if parent is not None else worlds[i]
                if i < bones.arm_count:
                    arms_keys[str(i)] = local
                else:
                    gun_keys[i - bones.gun_start] = local
            arms_frames.append((frame, arms_keys))
            gun_frames.append((frame, _gun_game_to_keys(gun_keys)))
        view.frame_set(shown)
    finally:
        _state["busy"] = False
    labels = {s[0]: s[1] for s in states()}
    weapon_anim.save_state(wt().source_dir(), item.name, state, labels.get(state, ""),
                           {"arms": weapon_anim.Clip(arms_frames), "gun": weapon_anim.Clip(gun_frames)},
                           _stored_edits(), _state["length"])
    _state["dirty"] = False
    _state["entry"] = _entry(state)
    return True


@bpy.app.handlers.persistent
def _before_frame(scene, _depsgraph=None):
    if scene.name == link.VIEW_SCENE and not _state["busy"]:
        try:
            capture()
        except (ReferenceError, RuntimeError, KeyError, AttributeError) as exc:
            print(f"boz_suite: a weapon pose was not kept: {exc}")


@bpy.app.handlers.persistent
def _after_frame(scene, _depsgraph=None):
    if scene.name == link.VIEW_SCENE and not _state["busy"]:
        _state["frame"] = scene.frame_current


@bpy.app.handlers.persistent
def _before_save(_dummy=None):
    try:
        store(bpy.context)
    except (ReferenceError, RuntimeError, AttributeError, OSError, KeyError) as exc:
        print(f"boz_suite: weapon animations not stored: {exc}")


# --- Playback and the timeline ------------------------------------------------------------

def _play_tick():
    wm = bpy.context.window_manager
    view = bpy.data.scenes.get(link.VIEW_SCENE)
    if not wm.boz_anim_playing or view is None:
        wm.boz_anim_playing = False
        return None
    frame = view.frame_current + 1
    if frame > view.frame_end:
        if not wm.boz_anim_loop:
            wm.boz_anim_playing = False
            return None
        frame = view.frame_start
    view.frame_set(frame)
    return 1.0 / weapon_anim.FPS


def stop_playing() -> None:
    wm = bpy.context.window_manager
    if wm.boz_anim_playing:
        wm.boz_anim_playing = False
    if bpy.app.timers.is_registered(_play_tick):
        bpy.app.timers.unregister(_play_tick)


def _state_items(self, context):
    edited = edited_states()
    items = [(str(name), label + ("  (edited)" if name in edited else ""),
              f"{frames} frames, {frames / weapon_anim.FPS:.1f} s" + (", loops" if looping else ""))
             for name, label, frames, looping in states()]
    _state["enum_items"] = items or [("0", "No animations", "")]
    return _state["enum_items"]


def _state_changed(self, context):
    if _state["guard"]:
        return
    store(context)
    name = current_state()
    if name is not None and _state["rig"] is not None:
        _state["busy"] = True
        try:
            view_scene().frame_current = 0
        finally:
            _state["busy"] = False
        show_state(context, name)


def _length_changed(self, context):
    if _state["guard"] or _state.get("state") is None:
        return
    capture(context)
    _state["length"] = max(1, context.window_manager.boz_anim_length)
    _state["dirty"] = True
    store_edits()
    bake(context)


class BOZ_OT_weapon_anim_play(Operator):
    bl_idname = "boz.weapon_anim_play"
    bl_label = "Play"
    bl_description = "Play the animation in the view (again to pause)"

    def execute(self, context):
        wm = context.window_manager
        if wm.boz_anim_playing:
            stop_playing()
            return {"FINISHED"}
        capture(context)
        view = view_scene()
        if view.frame_current >= view.frame_end:
            view.frame_set(view.frame_start)
        wm.boz_anim_playing = True
        if not bpy.app.timers.is_registered(_play_tick):
            bpy.app.timers.register(_play_tick, first_interval=1.0 / weapon_anim.FPS)
        return {"FINISHED"}


class BOZ_OT_weapon_step(Operator):
    bl_idname = "boz.weapon_step"
    bl_label = "Step"
    bl_description = "Go a frame back or forward, or to the previous or next change (what you " \
                     "changed here is kept)"
    bl_options = {"INTERNAL"}

    forward: BoolProperty(default=True)
    to_change: BoolProperty(default=False)

    def execute(self, context):
        stop_playing()
        view = view_scene()
        here = view.frame_current
        if self.to_change:
            capture(context)
            frames = sorted({f for part in ("arms", "gun")
                             for f in weapon_anim.change_frames(_state["edits"][part])} - {here})
            targets = [f for f in frames if (f > here if self.forward else f < here)]
            if not targets:
                return {"CANCELLED"}
            view.frame_set(min(targets) if self.forward else max(targets))
        else:
            view.frame_set(max(view.frame_start, min(view.frame_end, here + (1 if self.forward else -1))))
        return {"FINISHED"}


class BOZ_OT_weapon_original(Operator):
    bl_idname = "boz.weapon_original"
    bl_label = "Back to original from here"
    bl_description = "From this frame on, this part plays the original again (until your next change)"
    bl_options = {"INTERNAL"}

    part: StringProperty()

    def execute(self, context):
        capture(context)
        frame = view_scene().frame_current
        _state["edits"][self.part] = weapon_anim.add_original(_state["edits"][self.part], frame)
        _state["dirty"] = True
        store_edits()
        bake(context)
        return {"FINISHED"}


def _parts_of(which: str) -> list:
    return ["arms", "gun"] if which == "BOTH" else [which.lower()]


def _original_values(state: int, frame: int) -> dict:
    locals_, grips, _ik = frame_locals(state, frame, edits={"arms": [], "gun": []})
    arms, gun = _arm_parts(locals_)
    arms.update({f"hand {side}": v for side, v in grips.items()})
    return {"arms": arms, "gun": gun}


class BOZ_OT_weapon_copy_pose(Operator):
    bl_idname = "boz.weapon_copy_pose"
    bl_label = "Copy pose"
    bl_description = "Copy the pose of this frame (from the original or yours) to paste anywhere"

    def execute(self, context):
        capture(context)
        wm = context.window_manager
        state = _state.get("state")
        frame = view_scene().frame_current
        rig_obj = bpy.data.objects.get(RIG)
        if state is None or rig_obj is None:
            return {"CANCELLED"}
        if wm.boz_copy_source == "ORIGINAL":
            copied = _original_values(state, frame)
        else:
            copied = {group: _current_values(rig_obj, group) for group in ("arms", "gun")}
        _state["clipboard"] = {part: copied[part] for part in _parts_of(wm.boz_copy_part)}
        self.report({"INFO"}, f"Copied the {' and '.join(_state['clipboard'])} pose of frame {frame}")
        return {"FINISHED"}


class BOZ_OT_weapon_paste_pose(Operator):
    bl_idname = "boz.weapon_paste_pose"
    bl_label = "Paste pose"
    bl_description = "Put the copied pose here: it holds from this frame on, until your next change"

    @classmethod
    def poll(cls, context):
        return bool(_state.get("clipboard"))

    def execute(self, context):
        capture(context)
        frame = view_scene().frame_current
        rig_obj = bpy.data.objects.get(RIG)
        for part, values in _state["clipboard"].items():
            current = _current_values(rig_obj, part)
            current.update(values)
            _state["edits"][part] = weapon_anim.add_pose(_state["edits"][part], frame, current)
        _state["dirty"] = True
        store_edits()
        bake(context)
        return {"FINISHED"}


class BOZ_OT_weapon_copy_frames(Operator):
    bl_idname = "boz.weapon_copy_frames"
    bl_label = "Copy original frames here"
    bl_description = ("Play the original's frames From..To starting at this frame (for the chosen "
                      "part), then hold its last pose")

    def execute(self, context):
        capture(context)
        wm = context.window_manager
        state = _state.get("state")
        if state is None:
            return {"CANCELLED"}
        start, end = sorted((wm.boz_copy_from, wm.boz_copy_to))
        at = view_scene().frame_current
        last = _original_values(state, end)
        for part in _parts_of(wm.boz_copy_part):
            _state["edits"][part] = weapon_anim.copy_frames(_state["edits"][part], at, start, end, last[part])
        _state["length"] = max(_state["length"], at + (end - start) + 1)
        _state["dirty"] = True
        store_edits()
        bake(context)
        return {"FINISHED"}


class BOZ_OT_weapon_reset_anim(Operator):
    bl_idname = "boz.weapon_reset_anim"
    bl_label = "Reset this animation"
    bl_description = "Throw away every change to this animation: it plays the original again"

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        item, _weapon_ = _weapon()
        state = _state.get("state")
        if item is None or state is None:
            return {"CANCELLED"}
        weapon_anim.save_state(wt().source_dir(), item.name, state, "", {}, {"arms": [], "gun": []}, 0)
        show_state(context, state)
        return {"FINISHED"}


class BOZ_OT_weapon_anim_save(Operator):
    bl_idname = "boz.weapon_anim_save"
    bl_label = "Save animation"
    bl_description = "Store this animation in the project (it is also stored when you save)"

    def execute(self, context):
        capture(context)
        _state["dirty"] = _state["dirty"] or bool(_state["edits"]["arms"] or _state["edits"]["gun"])
        store(context)
        self.report({"INFO"}, "Saved")
        return {"FINISHED"}


def timeline_text(part: str) -> str:
    changes = _state["edits"].get(part, [])
    if not changes:
        return "original"
    pieces = []
    if changes[0]["frame"] > 0:
        pieces.append(f"original 0-{changes[0]['frame'] - 1}")
    for number, change in enumerate(changes):
        end = changes[number + 1]["frame"] - 1 if number + 1 < len(changes) else None
        span = f"{change['frame']}" + (f"-{end}" if end is not None and end != change["frame"] else
                                       "" if end is not None else "+")
        if "pose" in change:
            kind = "yours"
        elif change["original"] == change["frame"]:
            kind = "original"
        else:
            kind = f"original (its {change['original']})"
        pieces.append(f"{kind} {span}")
    return ", ".join(pieces)


# --- Placement (Weapons tab) ------------------------------------------------------------------

def _select(view, obj) -> None:
    if obj is None:
        return
    layer = view.view_layers[0]
    for other in view.objects:
        if other != obj and other.select_get(view_layer=layer):
            other.select_set(False, view_layer=layer)
    obj.hide_select = False
    obj.select_set(True, view_layer=layer)
    layer.objects.active = obj


def _placement_timer():
    try:
        _picked()
        _position_changed()
    except (ReferenceError, AttributeError, RuntimeError):
        pass
    wm = bpy.context.window_manager
    return 0.3 if (wm.boz_arms_edit or wm.boz_fit_edit) else None


def _position_changed() -> None:
    """The rig was moved (Position on screen): keep it as the weapon's arms placement."""
    view = bpy.data.scenes.get(link.VIEW_SCENE)
    rig_obj = view.objects.get(RIG) if view else None
    item, weapon = _weapon()
    if rig_obj is None or weapon is None or _state["guard"]:
        return
    basis = [list(r) for r in rig_obj.matrix_basis]
    if basis == _state.get("arms_basis"):
        return
    location, rotation, scale = from_bl(rig_obj.matrix_basis).decompose()
    if max(abs(c - 1.0) for c in scale) > 1e-4:      # it only moves and turns
        from mathutils import Matrix
        rig_obj.matrix_basis = to_bl(Matrix.Translation(location) @ rotation.to_matrix().to_4x4())
    _state["arms_basis"] = [list(r) for r in rig_obj.matrix_basis]
    weapon.arms = {"location": [round(c, 3) for c in location],
                   "rotation": [round(c, 6) for c in rotation]}
    wt().save(bpy.context, weapon)


def _arms_edit_changed(self, context):
    wm = context.window_manager
    view = view_scene()
    rig_obj = view.objects.get(RIG)
    if wm.boz_arms_edit and rig_obj is not None:
        stop_playing()
        if wm.boz_fit_edit:
            wm.boz_fit_edit = False
        _edit_mode(view, rig_obj, "OBJECT")
        _select(view, rig_obj)
        if not bpy.app.timers.is_registered(_placement_timer):
            bpy.app.timers.register(_placement_timer, first_interval=0.3)
    else:
        _position_changed()


class BOZ_OT_weapon_arms_reset(Operator):
    bl_idname = "boz.weapon_arms_reset"
    bl_label = "Reset position"
    bl_description = "Put the arms and gun back where the game has them"

    def execute(self, context):
        item, weapon = _weapon()
        if weapon is None:
            return {"CANCELLED"}
        weapon.arms = {}
        wt().save(context, weapon)
        rig_obj = bpy.data.objects.get(RIG)
        if rig_obj is not None:
            rig_obj.matrix_basis = arms_matrix({})
            _state["arms_basis"] = [list(r) for r in rig_obj.matrix_basis]
        return {"FINISHED"}


def _hang_from_tag(obj, rig_obj) -> None:
    """Parent an object to the gun position bone at its head (Blender parents to the tail)."""
    from mathutils import Matrix
    bone = rig_obj.data.bones.get(TAG)
    if bone is None:
        return
    obj.parent = rig_obj
    obj.parent_type = "BONE"
    obj.parent_bone = TAG
    obj.matrix_parent_inverse = Matrix.Translation((0.0, -bone.length, 0.0))


def _fit_edit_changed(self, context):
    """Fit model in hand: a rigid copy of your model on the gun position to move, turn and scale;
    the stock gun shows see-through. Turning it off keeps the fit and rebuilds the view."""
    wm = context.window_manager
    view = view_scene()
    rig_obj = view.objects.get(RIG)
    item, weapon = _weapon()
    if wm.boz_fit_edit and rig_obj is not None and _state.get("asset") is not None:
        stop_playing()
        if wm.boz_arms_edit:
            wm.boz_arms_edit = False
        if not wm.boz_view_free:
            wm.boz_view_free = True
        _edit_mode(view, rig_obj, "OBJECT")
        from . import assets_tab, game
        _remove(FIT_MODEL)
        _remove(GHOST)
        data = assets_tab.build_mesh(weapon.model["asset"], FIT_MODEL, unit_scale=1.0)
        if data is not None:
            fit_obj = _link(view, bpy.data.objects.new(FIT_MODEL, data))
            _hang_from_tag(fit_obj, rig_obj)
            fit_obj.matrix_basis = fit_matrix(weapon.model.get("fit") or {})
            _select(view, fit_obj)
        rig = _state["rig"]
        base = game.model_mesh(rig.weapons_path, rig.gun_model_hash) if rig.gun_model is not None else None
        if base is not None:
            ghost_data = base.copy()
            ghost_data.name = GHOST
            ghost = _link(view, bpy.data.objects.new(GHOST, ghost_data))
            _hang_from_tag(ghost, rig_obj)
            ghost.display_type = "WIRE"
            ghost.show_in_front = True
            ghost.hide_select = True
        gun = view.objects.get(GUN)
        if gun is not None:
            gun.hide_viewport = True
        if not bpy.app.timers.is_registered(_placement_timer):
            bpy.app.timers.register(_placement_timer, first_interval=0.3)
    else:
        fit_obj = view.objects.get(FIT_MODEL)
        if fit_obj is not None and weapon is not None and weapon.model.get("asset"):
            weapon.model["fit"] = fit_from_matrix(fit_obj.matrix_basis)
            wt().save(context, weapon)
            _remove(FIT_MODEL)
            _remove(GHOST)
            request_preview()


def _picked(*_args) -> None:
    """The active object changed (Weapons tab): clicking the arms starts Position on screen;
    clicking your gun starts Fit model in hand."""
    view = bpy.data.scenes.get(link.VIEW_SCENE)
    if view is None:
        return
    active = view.view_layers[0].objects.active
    wm = bpy.context.window_manager
    if active is None or active.mode != "OBJECT":
        return
    if active.name == ARMS:
        if not wm.boz_arms_edit:
            wm.boz_arms_edit = True
        else:
            _select(view, view.objects.get(RIG))
    elif active.name == GUN and _state.get("asset") is not None and not wm.boz_fit_edit:
        wm.boz_fit_edit = True


_SUBSCRIBER = object()


def subscribe() -> None:
    bpy.msgbus.clear_by_owner(_SUBSCRIBER)
    bpy.msgbus.subscribe_rna(key=(bpy.types.LayerObjects, "active"), owner=_SUBSCRIBER, args=(),
                             notify=_picked)


@bpy.app.handlers.persistent
def _after_load(_dummy=None):
    subscribe()      # a file load clears subscriptions


def _sync_fit_fields(fit: dict) -> None:
    from mathutils import Quaternion
    wm = bpy.context.window_manager
    _state["guard"] = True
    try:
        wm.boz_fit_location = fit.get("location", (0.0, 0.0, 0.0))
        wm.boz_fit_rotation = Quaternion(fit.get("rotation", (1.0, 0.0, 0.0, 0.0))).to_euler()
        wm.boz_fit_scale = float(fit.get("scale", 1.0))
    finally:
        _state["guard"] = False


def _fit_fields_changed(self, context):
    if _state["guard"]:
        return
    item, weapon = _weapon()
    if weapon is None or not weapon.model.get("asset"):
        return
    wm = context.window_manager
    weapon.model["fit"] = {"location": [round(c, 3) for c in wm.boz_fit_location],
                           "rotation": [round(c, 6) for c in wm.boz_fit_rotation.to_quaternion()],
                           "scale": round(wm.boz_fit_scale, 6)}
    wt().save(context, weapon)
    fit_obj = bpy.data.objects.get(FIT_MODEL)
    if fit_obj is not None:
        fit_obj.matrix_basis = fit_matrix(weapon.model["fit"])
    else:
        request_preview()


def _model_items(self, context):
    from . import assets_tab
    items = [("STOCK", "Stock gun", "The weapon's own model")]
    source = wt().source_dir()
    for asset in assets_tab.defs():
        if asset.kind == "weapon" and source is not None and assets.has_game(source, asset.name):
            items.append((asset.name, asset.name, "Your asset (Assets tab), with its own bones"))
    _state["model_items"] = items
    return items


def auto_model(context, asset_name: str, keep_bones: dict | None = None) -> dict:
    """A weapon model entry for *asset_name*: fitted to the stock gun, each bone told which
    stock bone its original motion comes from."""
    item, weapon = _weapon()
    level = weapon.level or wt().base_level(context)
    stock = viewmodel.Rig(wt()._pack().read, level, weapon.source)
    model, _textures = assets.load_game(wt().source_dir(), asset_name)
    fit = weapon_model.auto_fit({b.name: b.head for b in model.bones}, model.vertices,
                                stock.gun_bones, stock.gun_model.vertices if stock.gun_model else [])
    reload_anim = stock._anim(stock.gun_anims, stock.gun_states, iw_hash("reloading"))
    mover = weapon_model.reload_mover(stock.gun_bones, reload_anim)
    bones = weapon_model.default_bones([b.name for b in model.bones], stock.gun_bones, mover)
    if keep_bones:
        bones.update({k: v for k, v in keep_bones.items() if k in bones})
    return {"asset": asset_name, "fit": fit, "bones": bones}


def _model_choice_changed(self, context):
    if _state["guard"]:
        return
    item, weapon = _weapon()
    if item is None:
        return
    choice = context.window_manager.boz_weapon_model
    weapon.model = {} if choice == "STOCK" else auto_model(context, choice)
    wt().save(context, weapon)
    wt().refresh_list(context, keep=item.name)
    request_preview()


class BOZ_WeaponBone(PropertyGroup):
    """One of your model's bones and the stock bone its original motion comes from."""
    def _items(self, context):
        rig = _state.get("rig")
        if rig is None or not rig.gun_bones:
            return [("#0", "root", "")]
        key = ("bones", id(rig))
        if _state.get("bone_items_key") != key:
            _state["bone_items_key"] = key
            _state["bone_items"] = [(weapon_model.bone_key(rig.gun_bones, i),
                                     f"{i}: {weapon_model.bone_label(rig.gun_bones, i)}", "")
                                    for i in range(len(rig.gun_bones))]
        return _state["bone_items"]

    def _changed(self, context):
        if _state["guard"]:
            return
        item, weapon = _weapon()
        if weapon is None or not weapon.model.get("asset"):
            return
        weapon.model.setdefault("bones", {})[self.name] = self.stock
        wt().save(context, weapon)
        request_preview()

    part: StringProperty()
    stock: EnumProperty(name="Moves like", items=_items, update=_changed,
                        description="The stock gun's bone whose original motion this part follows")


def refresh_model_panel(context) -> None:
    wm = context.window_manager
    item, weapon = _weapon()
    model = weapon.model if weapon else {}
    _state["guard"] = True
    try:
        choice = model.get("asset") or "STOCK"
        if choice in {i[0] for i in _model_items(None, context)}:
            wm.boz_weapon_model = choice
    finally:
        _state["guard"] = False
    _sync_fit_fields(model.get("fit") or {})
    _state["guard"] = True
    try:
        wm.boz_weapon_bones.clear()
        asset_model = _state.get("asset") if model.get("asset") else None
        labels = {"tag_clip": "Magazine", "tag_flash": "Muzzle", "tag_brass": "Shells",
                  "tag_weapon": "Body"}
        for bone in asset_model.bones if asset_model is not None else []:
            row = wm.boz_weapon_bones.add()
            row.name = bone.name
            row.part = labels.get(bone.name.lower(), "")
            try:
                row.stock = (model.get("bones") or {}).get(bone.name, "#0")
            except TypeError:
                pass
    finally:
        _state["guard"] = False


class BOZ_OT_weapon_auto_fit(Operator):
    bl_idname = "boz.weapon_auto_fit"
    bl_label = "Auto fit"
    bl_description = ("Line your model up with the stock gun again: along its barrel, upright, "
                      "as long as it and centred on it")

    def execute(self, context):
        item, weapon = _weapon()
        if weapon is None or not weapon.model.get("asset"):
            return {"CANCELLED"}
        weapon.model["fit"] = auto_model(context, weapon.model["asset"], weapon.model.get("bones"))["fit"]
        wt().save(context, weapon)
        fit_obj = bpy.data.objects.get(FIT_MODEL)
        if fit_obj is not None:
            fit_obj.matrix_basis = fit_matrix(weapon.model["fit"])
            _sync_fit_fields(weapon.model["fit"])
        else:
            show_preview(context)
        return {"FINISHED"}


# --- The viewport ----------------------------------------------------------------------------

def _set_overlay() -> None:
    wm = bpy.context.window_manager
    for window in wm.windows:
        if window.workspace.name not in WORKSPACES:
            continue
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                area.spaces.active.overlay.show_bones = wm.boz_view_bones or \
                    window.workspace.name == "Animation"
                area.tag_redraw()


def apply_visibility(context) -> None:
    wm = context.window_manager
    arms = bpy.data.objects.get(ARMS)
    if arms is not None:
        arms.hide_viewport = not wm.boz_view_arms
    camera = bpy.data.objects.get(VIEW_CAMERA)
    if camera is not None:
        camera.hide_viewport = wm.boz_view_free
    _set_overlay()


def _frame_area(area) -> None:
    """Look at the gun from its side, orbiting around it."""
    from mathutils import Euler, Vector
    gun = bpy.data.objects.get(GUN) or bpy.data.objects.get(ARMS)
    if gun is None or gun.type != "MESH" or not gun.data.vertices:
        return
    corners = [gun.matrix_world @ Vector(c) for c in gun.bound_box]
    low = Vector(tuple(min(c[i] for c in corners) for i in range(3)))
    high = Vector(tuple(max(c[i] for c in corners) for i in range(3)))
    region = area.spaces.active.region_3d
    region.view_perspective = "PERSP"
    region.view_location = (low + high) / 2
    region.view_distance = max((high - low).length * 1.4, 1.0)
    region.view_rotation = Euler((math.radians(75), 0.0, math.radians(125))).to_quaternion()
    area.tag_redraw()


def setup_view(window) -> bool:
    """Show the weapon scene in the window, pinned. Weapons tab: first person (or free), the rig
    in object mode for placement. Animation tab: the small view first person, the big view free,
    the rig posed."""
    view = bpy.data.scenes.get(link.VIEW_SCENE)
    if view is None or view.camera is None:
        return False
    if window.scene != view:
        window.scene = view
    workspace = window.workspace
    if not workspace.use_pin_scene:
        workspace.use_pin_scene = True
    wm = bpy.context.window_manager
    views = [a for a in window.screen.areas if a.type == "VIEW_3D"]
    largest = max(views, key=lambda a: a.width * a.height) if views else None
    animation = workspace.name == "Animation"
    for area in views:
        space = area.spaces.active
        space.use_local_collections = False
        space.use_local_camera = False
        space.overlay.show_floor = False
        space.overlay.show_axis_x = space.overlay.show_axis_y = False
        space.overlay.show_bones = wm.boz_view_bones or animation
        space.clip_start, space.clip_end = 1.0, 100000.0
        if animation:
            area_free = area == largest and len(views) > 1
            space.region_3d.view_perspective = "PERSP" if area_free else "CAMERA"
            if area_free and _state.get("frame_gun"):
                _frame_area(area)
        elif not wm.boz_view_free:
            space.region_3d.view_perspective = "CAMERA"
        area.tag_redraw()
    if animation:
        _state.pop("frame_gun", None)
    elif wm.boz_view_free and _state.pop("frame_gun", False):
        for area in views:
            _frame_area(area)
    rig_obj = view.objects.get(RIG)
    if rig_obj is not None:
        if animation:
            if wm.boz_arms_edit:
                wm.boz_arms_edit = False
            if wm.boz_fit_edit:
                wm.boz_fit_edit = False
            _select(view, rig_obj)
            _edit_mode(view, rig_obj, "POSE")
        elif rig_obj.mode != "OBJECT":
            store(bpy.context)
            _edit_mode(view, rig_obj, "OBJECT")
    workspace[VIEW_KEY] = True
    return True


def leave_view(window) -> None:
    if window.scene is not None and window.scene.name == link.VIEW_SCENE:
        store(bpy.context)
        window.scene = link.map_scene()


def refresh_view(window) -> None:
    """The tabs' timer, while the Weapons or Animation tab is on screen."""
    view = bpy.data.scenes.get(link.VIEW_SCENE)
    rig_obj = view.objects.get(RIG) if view else None
    wanted = "POSE" if window.workspace.name == "Animation" else "OBJECT"
    if not window.workspace.get(VIEW_KEY) or window.scene.name != link.VIEW_SCENE or \
            (rig_obj is not None and rig_obj.mode != wanted):
        if rig_obj is None and wt().selected(link.map_scene()) is not None:
            show_preview(bpy.context)
        setup_view(window)


def _view_changed(self, context):
    apply_visibility(context)
    _state["frame_gun"] = True
    for window in context.window_manager.windows:
        if window.workspace.name in WORKSPACES:
            setup_view(window)


def _arms_changed(self, context):
    apply_visibility(context)


def _bones_changed(self, context):
    _set_overlay()


def _fov_changed(self, context):
    camera = bpy.data.cameras.get(VIEW_CAMERA)
    if camera is not None:
        camera.sensor_fit = "HORIZONTAL"
        camera.angle = viewmodel.view_angle(context.window_manager.boz_view_fov)


def draw_view_header(self, context):
    workspace = context.workspace
    if workspace is None or workspace.name not in WORKSPACES:
        return
    wm = context.window_manager
    layout = self.layout
    layout.separator()
    row = layout.row(align=True)
    if workspace.name == "Weapons":
        row.prop(wm, "boz_view_free", text="", icon="ORIENTATION_GIMBAL" if wm.boz_view_free
                 else "VIEW_CAMERA", toggle=True)
    row.prop(wm, "boz_view_arms", text="", icon="HIDE_OFF" if wm.boz_view_arms else "HIDE_ON", toggle=True)
    row.prop(wm, "boz_view_bones", text="", icon="BONE_DATA", toggle=True)
    if _state.get("rig") is not None:
        layout.operator(BOZ_OT_weapon_anim_play.bl_idname, text="",
                        icon="PAUSE" if wm.boz_anim_playing else "PLAY")


# --- Panels --------------------------------------------------------------------------------

class _ViewPanel:
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "scene"

    @classmethod
    def poll(cls, context):
        return context.workspace is not None and context.workspace.name in WORKSPACES and \
            wt().selected(link.map_scene()) is not None


class BOZ_PT_weapon_model(_ViewPanel, Panel):
    bl_idname = "BOZ_PT_weapon_model"
    bl_label = "Placement"

    @classmethod
    def poll(cls, context):
        return super().poll(context) and context.workspace.name == "Weapons"

    def draw(self, context):
        layout = self.layout
        wm = context.window_manager
        box = layout.box()
        row = box.row(align=True)
        row.prop(wm, "boz_view_free", text="Free view" if wm.boz_view_free else "First person",
                 icon="ORIENTATION_GIMBAL" if wm.boz_view_free else "VIEW_CAMERA", toggle=True)
        row.prop(wm, "boz_view_arms", text="Arms", toggle=True)
        row.prop(wm, "boz_view_bones", text="Bones", toggle=True)
        box.prop(wm, "boz_view_fov", slider=True)
        box = layout.box()
        box.label(text="Position on screen (arms and gun together)", icon="OBJECT_ORIGIN")
        row = box.row(align=True)
        row.prop(wm, "boz_arms_edit", text="Move", toggle=True)
        row.operator(BOZ_OT_weapon_arms_reset.bl_idname, text="", icon="LOOP_BACK")
        if wm.boz_arms_edit:
            box.label(text="G moves, R turns; every animation starts from here")
        box = layout.box()
        box.label(text="Model", icon="MESH_DATA")
        box.prop(wm, "boz_weapon_model", text="")
        if wm.boz_weapon_model == "STOCK":
            if len(_state.get("model_items") or ()) <= 1:
                box.label(text="Import a Weapon asset in the Assets tab to use your own")
            return
        if _state.get("error"):
            box.label(text=_state["error"], icon="ERROR")
        row = box.row(align=True)
        row.prop(wm, "boz_fit_edit", text="Fit model in hand", toggle=True)
        row.operator(BOZ_OT_weapon_auto_fit.bl_idname, icon="SNAP_ON")
        if wm.boz_fit_edit:
            box.label(text="Click your model: G moves, R turns, S scales (wire: the stock gun)")
        column = box.column(align=True)
        column.prop(wm, "boz_fit_location", text="Position")
        column.prop(wm, "boz_fit_rotation", text="Rotation")
        column.prop(wm, "boz_fit_scale", text="Scale")
        sub = box.box()
        sub.label(text="Original motion of your bones comes from:")
        for bone in wm.boz_weapon_bones:
            row = sub.row(align=True)
            row.label(text=bone.name + (f" ({bone.part})" if bone.part else ""))
            row.prop(bone, "stock", text="")


class BOZ_PT_weapon_animations(_ViewPanel, Panel):
    bl_idname = "BOZ_PT_weapon_animations"
    bl_label = "Animation"

    def draw(self, context):
        layout = self.layout
        wm = context.window_manager
        view = bpy.data.scenes.get(link.VIEW_SCENE)
        animation_tab = context.workspace.name == "Animation"
        if _state.get("rig") is None or view is None:
            layout.label(text="Select a weapon in the Weapons tab", icon="INFO")
            return
        layout.prop(wm, "boz_anim_state", text="")
        row = layout.row(align=True)
        step = row.operator(BOZ_OT_weapon_step.bl_idname, text="", icon="PREV_KEYFRAME")
        step.forward, step.to_change = False, True
        step = row.operator(BOZ_OT_weapon_step.bl_idname, text="", icon="TRIA_LEFT")
        step.forward, step.to_change = False, False
        row.operator(BOZ_OT_weapon_anim_play.bl_idname, text="", icon="PAUSE" if wm.boz_anim_playing else "PLAY")
        step = row.operator(BOZ_OT_weapon_step.bl_idname, text="", icon="TRIA_RIGHT")
        step.forward, step.to_change = True, False
        step = row.operator(BOZ_OT_weapon_step.bl_idname, text="", icon="NEXT_KEYFRAME")
        step.forward, step.to_change = True, True
        row.prop(wm, "boz_anim_loop", text="", icon="FILE_REFRESH", toggle=True)
        row = layout.row(align=True)
        row.prop(view, "frame_current", text="Frame")
        row.prop(wm, "boz_anim_length", text="Length")
        if not animation_tab:
            layout.label(text="Change animations in the Animation tab", icon="INFO")
            return
        box = layout.box()
        for part, label in (("arms", "Arms"), ("gun", "Gun")):
            row = box.row(align=True)
            row.label(text=f"{label}: {timeline_text(part)}")
            row.operator(BOZ_OT_weapon_original.bl_idname, text="", icon="LOOP_BACK").part = part
        box = layout.box()
        row = box.row(align=True)
        row.prop(wm, "boz_copy_part", expand=True)
        row = box.row(align=True)
        row.prop(wm, "boz_copy_source", expand=True)
        row = box.row(align=True)
        row.operator(BOZ_OT_weapon_copy_pose.bl_idname, icon="COPYDOWN")
        row.operator(BOZ_OT_weapon_paste_pose.bl_idname, icon="PASTEDOWN")
        row = box.row(align=True)
        row.prop(wm, "boz_copy_from", text="From")
        row.prop(wm, "boz_copy_to", text="To")
        box.operator(BOZ_OT_weapon_copy_frames.bl_idname, icon="DUPLICATE")
        row = layout.row(align=True)
        row.operator(BOZ_OT_weapon_anim_save.bl_idname, icon="FILE_TICK")
        row.operator(BOZ_OT_weapon_reset_anim.bl_idname, icon="TRASH")
        help_box = layout.box()
        for line in ("Click a bone: R turns, G moves (hand L/R: the grip; gun position: the gun).",
                     "Step to another frame: what you changed is kept and holds from there on.",
                     "Arms and gun have their own timelines; the arrow sends one back to the",
                     "original from this frame. Earlier frames never change."):
            help_box.label(text=line)


CLASSES = (BOZ_WeaponBone, BOZ_OT_weapon_arms_reset, BOZ_OT_weapon_anim_play, BOZ_OT_weapon_step,
           BOZ_OT_weapon_original, BOZ_OT_weapon_copy_pose, BOZ_OT_weapon_paste_pose,
           BOZ_OT_weapon_copy_frames, BOZ_OT_weapon_reset_anim, BOZ_OT_weapon_anim_save,
           BOZ_OT_weapon_auto_fit, BOZ_PT_weapon_model, BOZ_PT_weapon_animations)

WM_PROPS = ("boz_arms_edit", "boz_view_fov", "boz_anim_length", "boz_view_free", "boz_view_arms",
            "boz_view_bones", "boz_anim_state", "boz_anim_playing", "boz_anim_loop", "boz_fit_edit",
            "boz_weapon_model", "boz_fit_location", "boz_fit_rotation", "boz_fit_scale",
            "boz_weapon_bones", "boz_copy_part", "boz_copy_source", "boz_copy_from", "boz_copy_to")


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    wm = bpy.types.WindowManager
    wm.boz_view_free = BoolProperty(
        name="Free view", update=_view_changed,
        description="Move around the weapon freely instead of looking through the game's eye")
    wm.boz_view_arms = BoolProperty(name="Arms", default=True, update=_arms_changed,
                                    description="Show the player's arms")
    wm.boz_view_bones = BoolProperty(name="Bones", update=_bones_changed,
                                     description="Show the bones with their names")
    wm.boz_view_fov = FloatProperty(name="Field of view", min=20.0, max=120.0,
                                    default=viewmodel.DEFAULT_FOV, precision=0, update=_fov_changed,
                                    description="The game's field of view setting (50 unless you "
                                                "changed it, e.g. with Redux's pause-menu slider)")
    wm.boz_anim_state = EnumProperty(name="Animation", items=_state_items, update=_state_changed,
                                     description="The animation shown")
    wm.boz_anim_playing = BoolProperty()
    wm.boz_anim_loop = BoolProperty(name="Loop", default=True,
                                    description="Play the animation over and over")
    wm.boz_anim_length = IntProperty(name="Length", min=1, max=3000, update=_length_changed,
                                     description="The animation's last frame (30 a second)")
    wm.boz_arms_edit = BoolProperty(name="Position on screen", update=_arms_edit_changed,
                                    description="Move (G) and turn (R) the arms and gun together in "
                                                "front of the camera; saved with the weapon")
    wm.boz_fit_edit = BoolProperty(name="Fit model in hand", update=_fit_edit_changed,
                                   description="Move, turn and scale your model in the hand")
    wm.boz_weapon_model = EnumProperty(name="Model", items=_model_items, update=_model_choice_changed,
                                       description="The stock gun or one of your Weapon assets")
    wm.boz_fit_location = FloatVectorProperty(name="Position", size=3, step=100,
                                              update=_fit_fields_changed,
                                              description="In the stock gun's model units")
    wm.boz_fit_rotation = FloatVectorProperty(name="Rotation", size=3, subtype="EULER",
                                              update=_fit_fields_changed)
    wm.boz_fit_scale = FloatProperty(name="Scale", min=0.001, default=1.0, step=10,
                                     update=_fit_fields_changed,
                                     description="Model units per unit of your asset")
    wm.boz_weapon_bones = CollectionProperty(type=BOZ_WeaponBone)
    wm.boz_copy_part = EnumProperty(name="Part", default="BOTH", items=[
        ("ARMS", "Arms", ""), ("GUN", "Gun", ""), ("BOTH", "Both", "")])
    wm.boz_copy_source = EnumProperty(name="From", items=[
        ("ORIGINAL", "Original", "The game's own animation at this frame"),
        ("YOURS", "Yours", "What the view shows at this frame")])
    wm.boz_copy_from = IntProperty(name="From", min=0, description="First original frame to copy")
    wm.boz_copy_to = IntProperty(name="To", min=0, description="Last original frame to copy")
    bpy.types.VIEW3D_HT_header.append(draw_view_header)
    bpy.app.handlers.save_pre.append(_before_save)
    bpy.app.handlers.frame_change_pre.append(_before_frame)
    bpy.app.handlers.frame_change_post.append(_after_frame)
    bpy.app.handlers.load_post.append(_after_load)
    subscribe()


def unregister():
    for timer in (_play_tick, _placement_timer, _pending_preview):
        if bpy.app.timers.is_registered(timer):
            bpy.app.timers.unregister(timer)
    for handlers, function in ((bpy.app.handlers.save_pre, _before_save),
                               (bpy.app.handlers.frame_change_pre, _before_frame),
                               (bpy.app.handlers.frame_change_post, _after_frame),
                               (bpy.app.handlers.load_post, _after_load)):
        if function in handlers:
            handlers.remove(function)
    bpy.msgbus.clear_by_owner(_SUBSCRIBER)
    bpy.types.VIEW3D_HT_header.remove(draw_view_header)
    for name in WM_PROPS:
        delattr(bpy.types.WindowManager, name)
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
