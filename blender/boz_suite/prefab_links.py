"""The Links box: links the user sets between game prefabs (bozkit.links), saved with the world
(Prefab.links) by object name. Which power switch a machine waits for, which traps a switch runs,
which doors open together, which window spawns climb in through a barricade. A link left unset
keeps its default (the prefab's own link from its home map, or the map's power switch)."""
from __future__ import annotations

import json

import bpy
from bpy.props import StringProperty, EnumProperty
from bpy.types import Operator

from . import convert
from ._bozkit import blender_scene, hashing, links, scripts, toolkit

SET_KEY = "boz_link_set"     # the links the user set: JSON {kind: [world names]}
NAME_KEY = "boz_link_name"   # the world name links knew the object by (to follow renames)

_components: dict = {}   # (base, source, group) -> component names ([] when not found)


def world_name(obj) -> str:
    """The name the world (and scripts, and links) know an object by: '<Prefab>.<Part>' for a
    part."""
    if convert.is_part(obj):
        return f"{world_name(obj.parent)}.{convert.object_name(obj)}"
    return convert.object_name(obj)


def is_linkable(obj) -> bool:
    """It can have links: a prefab, the game's or yours."""
    return obj is not None and obj.boz.role == "prefab" and not obj.boz.original


def is_target(obj) -> bool:
    """It can be linked to: any object of the map (a prefab, model or volume)."""
    return obj is not None and obj.boz.role in ("prefab", "model", "volume") \
        and not obj.boz.original and not convert.is_helper(obj)


def components(obj, base: str) -> list:
    """The component names of a game prefab's entity (cached); [] for your own objects."""
    from . import game
    if not obj.boz.source or obj.boz.role != "prefab":
        return []
    key = (base, obj.boz.source, obj.boz.group)
    if key not in _components:
        if game.game_models() is None:
            return []   # the asset library is not loaded yet: asked again later
        source = obj.boz.source
        value = int(source, 16) if source.startswith("0x") else hashing.iw_hash(source)
        spec = game.entity_spec(base, value, obj.boz.group)
        _components[key] = blender_scene.component_names(spec) if spec is not None else []
    return _components[key]


def object_kinds(obj, base: str) -> set:
    """What the object is, by the palette's names (bozkit.links.OBJECT_KINDS)."""
    if obj.boz.role == "prefab" and obj.boz.source:
        return links.kinds_of(components(obj, base), obj.get("boz_piece", ""))
    return links.kinds_of(role=obj.boz.role, piece=str(obj.get("boz_piece", "")))


_declared: dict = {}   # script path -> (mtime, its ---@link kinds)


def declared_links(obj) -> list:
    """The links its script declares (---@link), [] without one or when it cannot be read."""
    from . import link
    project = link.current_project()
    if not obj.boz.script or project is None:
        return []
    path = project.scripts / obj.boz.script
    try:
        stamp = path.stat().st_mtime
    except OSError:
        return []
    cached = _declared.get(str(path))
    if cached is None or cached[0] != stamp:
        try:
            cached = (stamp, scripts.read_links(path))
        except scripts.ScriptError:
            cached = (stamp, [])
        _declared[str(path)] = cached
    return cached[1]


def kinds(obj, base: str) -> list:
    """Its link kinds: the built-in ones for what it is, then its script's."""
    return links.kinds_for(object_kinds(obj, base), declared_links(obj)) if is_linkable(obj) else []


def kind_named(obj, base: str, name: str):
    return next((kind for kind in kinds(obj, base) if kind.name == name), None)


def set_links(obj) -> dict:
    try:
        return links.clean(json.loads(obj.get(SET_KEY, "{}")))
    except ValueError:
        return {}


def write(obj, values: dict) -> None:
    values = links.clean(values)
    if values:
        obj[SET_KEY] = json.dumps(values, sort_keys=True)
    elif SET_KEY in obj:
        del obj[SET_KEY]
    obj[NAME_KEY] = world_name(obj)


def candidates(scene, kind) -> list:
    """The scene's objects a link of *kind* may point at, by world name."""
    base = scene.boz.base
    return sorted((obj for obj in scene.objects if is_target(obj)
                   and links.can_target(kind, object_kinds(obj, base), obj.get("boz_piece", ""))),
                  key=world_name)


def by_world_name(scene) -> dict:
    return {world_name(obj).lower(): obj for obj in scene.objects if is_target(obj)}


def follow_renames(scene) -> int:
    """Point links at objects' new names after a rename (on every change and before saving).
    Returns how many objects were renamed."""
    renames = {}
    for obj in scene.objects:
        if not is_target(obj):
            continue
        old, new = obj.get(NAME_KEY), world_name(obj)
        if old != new:
            if old:
                renames[old] = new
            obj[NAME_KEY] = new
    if renames:
        for obj in scene.objects:
            values = set_links(obj) if SET_KEY in obj else None
            if not values:
                continue
            for old, new in renames.items():
                values = links.renamed(values, old, new)
            obj[SET_KEY] = json.dumps(values, sort_keys=True)
    return len(renames)


SPAWN_REACH = 600.0   # cm: a window spawn this far from its barricade is never used (the build)


def check(scene) -> tuple[list, list]:
    """(problems that stop the build, warnings) of the scene's links, as (message, object name):
    a link to an object the map does not have, or that cannot be one, stops it as the compiler
    would; a trap switch with no trap and a window spawn far from its barricade are warned."""
    base = scene.boz.base
    found = by_world_name(scene)
    problems, warnings = [], []
    for obj in scene.objects:
        if not is_linkable(obj):
            continue
        own = world_name(obj)
        values = set_links(obj)
        for kind_name, targets in values.items():
            kind = kind_named(obj, base, kind_name)
            if kind is None:
                continue   # its script no longer declares it: ignored by the build too
            for target in targets:
                other = found.get(target.lower())
                if other is None:
                    problems.append((f"{own}: its {kind.label} link names {target}, which is not "
                                     "in the map", obj.name))
                elif not links.can_target(kind, object_kinds(other, base), other.get("boz_piece", "")):
                    problems.append((f"{own}: its {kind.label} link names {target}, which cannot "
                                     "be one", obj.name))
                elif kind_name == "spawns" and (other.matrix_world.translation
                                                - obj.matrix_world.translation).length > SPAWN_REACH:
                    warnings.append((f"{target} is more than {SPAWN_REACH / 100:g} m from {own}, "
                                     "the barricade it is linked to", obj.name))
        if "traps" in values and not values["traps"]:
            warnings.append((f"trap switch {own} runs no trap: set its Traps link", obj.name))
        elif "traps" not in values and "CTrapSwitch" in components(obj, base):
            warnings.append((f"trap switch {own} has no Traps link: it runs only its own map's "
                             "traps, if they are placed", obj.name))
    return problems, warnings


def lines(scene) -> list:
    """(kind name, source object, target object) of every set link, for the overlay."""
    found = by_world_name(scene)
    out = []
    for obj in scene.objects:
        if SET_KEY not in obj:
            continue
        for kind_name, targets in set_links(obj).items():
            out.extend((kind_name, obj, found[t.lower()]) for t in targets if t.lower() in found)
    return out


def default_lines(scene) -> list:
    """(kind name, source, target) of the links a prefab keeps when the user has not set them,
    resolved as the compiler does (world_compile.rewire_links): power goes to the map's power
    switch; a home-map trap or door counts only if it was placed from that same map."""
    base = scene.boz.base
    linkable = [obj for obj in scene.objects if is_linkable(obj)]
    switch = next((obj for obj in linkable if "CPowerSwitch" in components(obj, base)), None)
    placed = {}   # (group, source name hash) -> object
    for obj in linkable:
        source = obj.boz.source
        value = int(source, 16) if source.startswith("0x") else hashing.iw_hash(source)
        placed.setdefault((obj.boz.group, value), obj)
    no_power = hashing.iw_hash(toolkit.NO_POWER)
    out = []
    for obj in linkable:
        own = set_links(obj) if SET_KEY in obj else {}
        try:
            home = json.loads(obj.get("boz_links", "[]"))
        except ValueError:
            continue
        for link in home:
            kind_name = link["kind"]
            if kind_name in own:
                continue
            if kind_name == "power":
                if switch is not None and any(t and t != no_power for t in link["targets"]):
                    out.append((kind_name, obj, switch))
                continue
            for target in link["targets"]:
                other = placed.get((obj.boz.group, target))
                if other is not None and other is not obj:
                    out.append((kind_name, obj, other))
    return out


def _changed(context, obj, kind_name, change) -> None:
    values = set_links(obj)
    kind = kind_named(obj, context.scene.boz.base, kind_name)
    current = list(values.get(kind_name, []))
    current = change(current)
    values[kind_name] = current if kind.many else current[-1:]
    write(obj, values)
    found = by_world_name(context.scene)
    for target in values[kind_name]:   # targets remember their name too, to follow a rename
        other = found.get(target.lower())
        if other is not None and NAME_KEY not in other:
            other[NAME_KEY] = world_name(other)
    for area in context.screen.areas if context.screen else []:
        area.tag_redraw()


_items: list = []   # Blender needs dynamic enum strings kept alive while the menu is open


def _target_items(self, context):
    global _items
    obj = context.object
    kind = kind_named(obj, context.scene.boz.base, self.kind) if obj else None
    names = [world_name(other) for other in candidates(context.scene, kind)
             if other is not obj] if kind else []
    _items = [(name, name, "") for name in names] or [("", "(nothing in the map can be linked)", "")]
    return _items


class BOZ_OT_prefab_link_add(Operator):
    bl_idname = "boz.prefab_link_add"
    bl_label = "Add link"
    bl_description = "Pick an object in the map to link to (a single link is replaced)"
    bl_options = {"REGISTER", "UNDO"}
    bl_property = "target"

    kind: StringProperty()
    target: EnumProperty(items=_target_items)

    def invoke(self, context, event):
        context.window_manager.invoke_search_popup(self)
        return {"FINISHED"}

    def execute(self, context):
        if not self.target:
            return {"CANCELLED"}
        _changed(context, context.object, self.kind,
                 lambda current: current + ([self.target] if self.target not in current else []))
        return {"FINISHED"}


class BOZ_OT_prefab_link_selected(Operator):
    bl_idname = "boz.prefab_link_selected"
    bl_label = "Link selected"
    bl_description = ("Link the other selected objects that can be linked here (select them, "
                      "then this one last)")
    bl_options = {"REGISTER", "UNDO"}

    kind: StringProperty()

    def execute(self, context):
        obj = context.object
        base = context.scene.boz.base
        kind = kind_named(obj, base, self.kind)
        picked = [world_name(other) for other in context.selected_objects
                  if other is not obj and is_target(other)
                  and links.can_target(kind, object_kinds(other, base), other.get("boz_piece", ""))]
        if not picked:
            self.report({"ERROR"}, f"Select what to link ({kind.label.lower()}), then "
                                   f"{world_name(obj)} last")
            return {"CANCELLED"}
        _changed(context, obj, self.kind,
                 lambda current: current + [name for name in picked if name not in current])
        return {"FINISHED"}


class BOZ_OT_prefab_link_remove(Operator):
    bl_idname = "boz.prefab_link_remove"
    bl_label = "Remove link"
    bl_description = "Take this object out of the link"
    bl_options = {"REGISTER", "UNDO"}

    kind: StringProperty()
    target: StringProperty()

    def execute(self, context):
        _changed(context, context.object, self.kind,
                 lambda current: [name for name in current if name != self.target])
        return {"FINISHED"}


class BOZ_OT_prefab_link_default(Operator):
    bl_idname = "boz.prefab_link_default"
    bl_label = "Use the default"
    bl_description = "Forget this link: the prefab uses its default again"
    bl_options = {"REGISTER", "UNDO"}

    kind: StringProperty()

    def execute(self, context):
        obj = context.object
        values = set_links(obj)
        values.pop(self.kind, None)
        write(obj, values)
        return {"FINISHED"}


class BOZ_OT_prefab_link_select(Operator):
    bl_idname = "boz.prefab_link_select"
    bl_label = "Select"
    bl_description = "Select this object"

    target: StringProperty()

    def execute(self, context):
        other = by_world_name(context.scene).get(self.target.lower())
        if other is None:
            self.report({"ERROR"}, f"{self.target} is not in the map")
            return {"CANCELLED"}
        for obj in context.selected_objects:
            obj.select_set(False)
        other.select_set(True)
        context.view_layer.objects.active = other
        return {"FINISHED"}


def draw(layout, obj, context) -> None:
    """The Links box of a game prefab (nothing for prefabs without links)."""
    scene = context.scene
    found = kinds(obj, scene.boz.base)
    if not found:
        return
    values = set_links(obj)
    present = by_world_name(scene)
    box = layout.box()
    box.label(text="Links", icon="LINKED")
    for kind in found:
        row = box.row(align=True)
        row.label(text=kind.label)
        add = row.operator(BOZ_OT_prefab_link_add.bl_idname, text="", icon="ADD")
        add.kind = kind.name
        pick = row.operator(BOZ_OT_prefab_link_selected.bl_idname, text="", icon="RESTRICT_SELECT_OFF")
        pick.kind = kind.name
        if kind.name not in values:
            box.label(text=f"   Default: {kind.default}")
            continue
        row.operator(BOZ_OT_prefab_link_default.bl_idname, text="", icon="LOOP_BACK").kind = kind.name
        if not values[kind.name]:
            box.label(text="   None")
        for target in values[kind.name]:
            row = box.row(align=True)
            row.separator()
            missing = target.lower() not in present
            select = row.operator(BOZ_OT_prefab_link_select.bl_idname, text=target,
                                  icon="ERROR" if missing else "OBJECT_DATA")
            select.target = target
            remove = row.operator(BOZ_OT_prefab_link_remove.bl_idname, text="", icon="X")
            remove.kind, remove.target = kind.name, target
            if missing:
                box.label(text=f"   {target} is not in the map: the build stops", icon="ERROR")
    incoming = sorted(world_name(other) for other in scene.objects if SET_KEY in other
                      and any(t.lower() == world_name(obj).lower()
                              for targets in set_links(other).values() for t in targets))
    if incoming:
        box.label(text="Linked from: " + ", ".join(incoming[:6]) + ("…" if len(incoming) > 6 else ""))


# Renames are followed when an object's name changes (a message bus subscription: nothing runs
# while objects move) and before saving (convert.scene_to_world).
_owner = object()


def _on_rename():
    try:
        from . import link
        follow_renames(link.map_scene())
    except Exception as exc:   # never break editing
        print(f"BOZ Redux: links could not follow a rename: {exc}")


def _subscribe() -> None:
    bpy.msgbus.clear_by_owner(_owner)
    bpy.msgbus.subscribe_rna(key=(bpy.types.Object, "name"), owner=_owner, args=(),
                             notify=_on_rename)


@bpy.app.handlers.persistent
def _on_load(_dummy=None):
    _subscribe()   # a loaded file starts with no subscriptions
    _on_rename()   # every linkable object remembers its name from the start


CLASSES = (BOZ_OT_prefab_link_add, BOZ_OT_prefab_link_selected, BOZ_OT_prefab_link_remove,
           BOZ_OT_prefab_link_default, BOZ_OT_prefab_link_select)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.app.handlers.load_post.append(_on_load)
    _subscribe()


def unregister():
    if _on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load)
    bpy.msgbus.clear_by_owner(_owner)
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
