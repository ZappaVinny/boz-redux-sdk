"""The first-person view of a weapon: the player's arms holding the gun, in any of its animation
states (idle, shooting, reloading, ...), as the game shows it (bozkit.anim does the posing).

The arms (``arms_<level>``: one skeleton "armRig", its skins and animations) play the weapon's
arms state machine (CPlayerWeapon m_armsAsm, e.g. "colt45_arms"); the gun (``weapons_<level>``:
its own skeleton, skin and animations) plays its state machine (m_weaponAsm) and hangs from the
arms' TAG_WEAPON bone. The first-person camera sits at the origin of the arms' space looking down
+Z (Y up). The game's field of view is the map camera's FOV (50 by default) turned into a
horizontal angle by its projection (view_angle: about 71 degrees across a 16:9 screen). Keyframes carry their times (bozkit.weapon_anim: a 30 a second grid).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from . import anim, group as group_module, levels, resources, weapons
from .hashing import iw_hash

SKEL = iw_hash('CIwAnimSkel')
SKIN = iw_hash('CIwAnimSkin')
ANIM = iw_hash('CIwAnim')
ASM = iw_hash('CIsAnimStateMachine')
MODEL = levels.MODEL
DEFAULT_FOV = 50.0     # CIsCamera's m_fov when a map leaves it unset (every shipped map)
ASPECT = 16 / 9        # the client's window


def view_angle(fov: float = DEFAULT_FOV) -> float:
    """The horizontal angle (radians) the game shows for a camera FOV of *fov* degrees.
    CWeaponManager::UpdateFov sets the projection to screen width / (2 x atan(fov in radians)):
    atan, not tan(fov / 2), so the half-angle across the width is atan(atan(fov))."""
    return 2.0 * math.atan(math.atan(math.radians(fov)))


@dataclass
class ViewPart:
    label: str            # "arms" or "gun"
    path: str             # the group the model is in
    model: int            # model hash
    positions: list       # posed vertex positions (the model's units, game axes), by vertex index


def _by_class(parsed) -> dict:
    out: dict[int, dict[int, bytes]] = {}
    for resource_type in parsed.types():
        bucket = out.setdefault(resource_type.class_hash, {})
        for resource in resource_type.resources:
            bucket.setdefault(resource.in_group_hash, resource.body)
    return out



# Animation state names (the state machines keep only their hashes; found by hashing the names).
STATE_NAMES = ('idle', 'shooting', 'Firing_From_Idle', 'Aim_Shoot', 'aim_idle', 'Aim_up',
               'aim_down', 'reloading', 'RELOADING', 'reloading_partial', 'reloading_loop_in',
               'Reloading_loop', 'Reloading_Loop_Out', 'raising', 'Lowering', 'sprint_in',
               'sprinting', 'sprint_out', 'MELEE_STAB', 'grenade_idle', 'grenade_throw')
_STATE_LABELS = {iw_hash(name): name.replace('_', ' ').lower() for name in STATE_NAMES}


@dataclass
class ViewState:
    name: int             # state name hash
    label: str            # "reloading", or "state 3" when the name is not known
    frames: int           # keyframes of the longest of its arms and gun animations
    looping: bool


class Rig:
    """A weapon's arms and gun with their skeletons, skins and state machines, ready to pose in
    any state at any keyframe (first_person() is the idle pose)."""

    def __init__(self, read, level: str, weapon: str):
        from . import native
        gear = weapons.GEAR.get(level, level)
        self.weapons_path = f'ingame/weapons/weapons_{gear}.group.bin'
        self.arms_path = f'ingame/characters/arms/arms_{gear}.group.bin'
        gun_data = _by_class(group_module.parse(read(self.weapons_path)))
        arm_data = _by_class(group_module.parse(read(self.arms_path)))
        spec_body = gun_data.get(weapons.ENTITY_SPEC, {}).get(weapons._hash_of(weapon))
        if spec_body is None:
            raise KeyError(f'{level} has no weapon {weapon}')
        blob = weapons._weapon_blob(resources.decode_entity_spec(spec_body))
        asset = weapons._prop(blob, 'renderableAsset')
        gun_model = weapons.get_value(asset.nested, 'model') if asset is not None and asset.nested else None
        gun_skel_hash = weapons.get_value(blob, 'skel')

        arm_skels = arm_data.get(SKEL, {})
        if not arm_skels:
            raise KeyError(f'{level} has no arms skeleton')
        self.arm_bones = anim.decode_skel(next(iter(arm_skels.values())))
        self.arm_anims = arm_data.get(ANIM, {})
        self.arm_states = self._states(arm_data, weapons.get_value(blob, 'm_armsAsm'))
        self.arm_skin = self.arm_model = None
        for skin_hash in sorted(arm_data.get(SKIN, {}))[:1]:
            skin = anim.decode_skin(arm_data[SKIN][skin_hash])
            if skin.model in arm_data.get(MODEL, {}):
                self.arm_skin, self.arm_model_hash = skin, skin.model
                self.arm_model = native.decode_model(arm_data[MODEL][skin.model])

        self.gun_model = self.gun_skin = self.gun_bones = None
        self.gun_anims = gun_data.get(ANIM, {})
        self.gun_states = self._states(gun_data, weapons.get_value(blob, 'm_weaponAsm'))
        if gun_model and gun_model in gun_data.get(MODEL, {}):
            self.gun_model_hash = gun_model
            self.gun_model = native.decode_model(gun_data[MODEL][gun_model])
            skin_body = gun_data.get(SKIN, {}).get(gun_model)
            skel_body = gun_data.get(SKEL, {}).get(gun_skel_hash) if gun_skel_hash else None
            if skin_body is not None and skel_body is not None:
                self.gun_skin = anim.decode_skin(skin_body)
                self.gun_bones = anim.decode_skel(skel_body)
        self._decoded: dict[int, anim.Anim] = {}
        self.custom = False

    def use_model(self, vertices, skin) -> None:
        """Show your own model (model units, the skeleton's bind pose) skinned by *skin* in
        place of the stock gun (bozkit.weapon_model.use_on_rig)."""
        from . import native
        self.gun_model = native.Model(vertices=list(vertices), triangles=[])
        self.gun_skin = skin
        self.gun_model_hash = 0
        self.custom = True

    @staticmethod
    def _states(data, asm_name) -> tuple[dict, int | None]:
        """({state name: State}, the default state's name) of a state machine."""
        body = data.get(ASM, {}).get(iw_hash(asm_name or ''))
        if not body:
            return {}, None
        states, default = anim.decode_asm(body)
        by_name = {}
        for state in states:
            by_name.setdefault(state.name, state)
        default_name = states[default].name if 0 <= default < len(states) else None
        return by_name, default_name

    def _anim(self, anims: dict, states: tuple, name: int | None):
        """The decoded animation a state machine plays in state *name*, or None."""
        state = states[0].get(name) if name is not None else None
        if state is None or state.anim not in anims:
            return None
        if state.anim not in self._decoded:
            self._decoded[state.anim] = anim.decode_anim(anims[state.anim])
        return self._decoded[state.anim]

    def idle(self) -> int:
        """The idle state's name (else the arms' default state)."""
        name = iw_hash('idle')
        return name if name in self.arm_states[0] else (self.arm_states[1] or name)

    def states(self) -> list[ViewState]:
        """The states the arms or the gun animate, in the arms' state machine's order."""
        out, seen, unnamed = [], set(), 0
        for name in list(self.arm_states[0]) + list(self.gun_states[0]):
            if name in seen:
                continue
            seen.add(name)
            arms = self._anim(self.arm_anims, self.arm_states, name)
            gun = self._anim(self.gun_anims, self.gun_states, name)
            if arms is None and gun is None:
                continue
            frames = max(len(a.keyframes) for a in (arms, gun) if a is not None)
            if name in _STATE_LABELS:
                label = _STATE_LABELS[name]
            else:
                unnamed += 1
                label = f'state {unnamed}'
            state = self.arm_states[0].get(name) or self.gun_states[0].get(name)
            out.append(ViewState(name, label, frames, state.looping))
        return out

    def worlds(self, state: int | None = None, frame: int = 0):
        """(arm bone worlds, gun bone worlds) posed in *state* at *frame* (skeleton units)."""
        state = self.idle() if state is None else state

        def keyframe(anims, states):
            found = self._anim(anims, states, state) or self._anim(anims, states, self.idle())
            if found is None or not found.keyframes:
                return None
            return found.keyframes[min(frame, len(found.keyframes) - 1)]

        arm_pose = anim.pose(self.arm_bones, keyframe(self.arm_anims, self.arm_states))
        tag = anim.bone_world(self.arm_bones, arm_pose, 'TAG_WEAPON')
        gun_pose = anim.pose(self.gun_bones, keyframe(self.gun_anims, self.gun_states), root=tag) \
            if self.gun_bones else []
        return arm_pose, gun_pose

    def pose(self, state: int | None = None, frame: int = 0) -> list[ViewPart]:
        """The arms and gun in *state* (default: idle) at keyframe *frame* (held at its last
        keyframe when one animation is shorter). A part without an animation for the state
        keeps its idle pose."""
        state = self.idle() if state is None else state

        def keyframe(anims, states):
            found = self._anim(anims, states, state) or self._anim(anims, states, self.idle())
            if found is None or not found.keyframes:
                return None
            return found.keyframes[min(frame, len(found.keyframes) - 1)]

        parts = []
        arm_pose = anim.pose(self.arm_bones, keyframe(self.arm_anims, self.arm_states))
        if self.arm_model is not None:
            parts.append(ViewPart('arms', self.arms_path, self.arm_model_hash,
                                  anim.skin_positions(self.arm_skin, arm_pose,
                                                      len(self.arm_model.vertices),
                                                      self.arm_model.vertices,
                                                      self.arm_model.position_remap)))
        # The gun: its own skeleton under the arms' TAG_WEAPON bone.
        tag = anim.bone_world(self.arm_bones, arm_pose, 'TAG_WEAPON')
        model = self.gun_model
        if model is not None:
            if self.gun_skin is not None:
                gun_pose = anim.pose(self.gun_bones, keyframe(self.gun_anims, self.gun_states),
                                     root=tag)
                positions = anim.skin_positions(self.gun_skin, gun_pose, len(model.vertices),
                                                model.vertices, model.position_remap)
            else:
                # Not skinned: the model as it is, at the hand.
                offset = tag[0] if tag else (0.0, 0.0, 0.0)
                positions = [tuple(v + o / anim.SKEL_SCALE for v, o in zip(vertex, offset))
                             for vertex in model.vertices]
            parts.append(ViewPart('gun', self.weapons_path, self.gun_model_hash, positions))
        return parts


def first_person(read, level: str, weapon: str) -> list[ViewPart]:
    """The arms and the gun of *weapon* (a name or 0x hash) of *level*'s weapons, posed for the
    first-person view (idle). *read(path)* returns a group file's bytes. Raises anim.AnimError or
    KeyError when the data is missing."""
    return Rig(read, level, weapon).pose()
