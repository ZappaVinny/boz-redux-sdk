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
from ._bozkit import blender_scene, hashing, links

SET_KEY = "boz_link_set"     # the links the user set: JSON {kind: [world names]}
NAME_KEY = "boz_link_name"   # the world name links knew the object by (to follow renames)

_components: dict = {}   # (base, source, group) -> component names, or None (no game data yet)


def world_name(obj) -> str:
    """The name the world (and scripts, and links) know an object by: '<Prefab>.<Part>' for a
    part."""
    if convert.is_part(obj):
        return f"{world_name(obj.parent)}.{convert.object_name(obj)}"
    return convert.object_name(obj)


def is_linkable(obj) -> bool:
    return obj is not None and obj.boz.role == "prefab" and bool(obj.boz.source) \
        and not obj.boz.original


def components(obj, base: str) -> list:
    """The component names of a game prefab's entity (cached)."""
    from . import game
    key = (base, obj.boz.source, obj.boz.group)
    if _components.get(key) is None:
        source = obj.boz.source
        value = int(source, 16) if source.startswith("0x") else hashing.iw_hash(source)
        spec = game.entity_spec(base, value, obj.boz.group)
        _components[key] = blender_scene.component_names(spec) if spec is not None else None
    return _components[key] or []


def kinds(obj, base: str) -> list:
    return links.kinds_for(components(obj, base)) if is_linkable(obj) else []


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
    return sorted((obj for obj in scene.objects if is_linkable(obj)
                   and links.can_target(kind, components(obj, base), obj.get("boz_piece", ""))),
                  key=world_name)


def by_world_name(scene) -> dict:
    return {world_name(obj).lower(): obj for obj in scene.objects if is_linkable(obj)}


def follow_renames(scene) -> int:
    """Point links at objects' new names after a rename (on every change and before saving).
    Returns how many objects were renamed."""
    renames = {}
    for obj in scene.objects:
        if not is_linkable(obj):
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


def _changed(context, obj, kind_name, change) -> None:
    values = set_links(obj)
    kind = links.BY_NAME[kind_name]
    current = list(values.get(kind_name, []))
    current = change(current)
    values[kind_name] = current if kind.many else current[-1:]
    write(obj, values)
    for area in context.screen.areas if context.screen else []:
        area.tag_redraw()


_items: list = []   # Blender needs dynamic enum strings kept alive while the menu is open


def _target_items(self, context):
    global _items
    kind = links.BY_NAME.get(self.kind)
    obj = context.object
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
        kind = links.BY_NAME[self.kind]
        base = context.scene.boz.base
        picked = [world_name(other) for other in context.selected_objects
                  if other is not obj and is_linkable(other)
                  and links.can_target(kind, components(other, base), other.get("boz_piece", ""))]
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


@bpy.app.handlers.persistent
def _on_change(scene, _depsgraph=None):
    try:
        follow_renames(scene)
    except Exception as exc:   # a handler must never break editing
        print(f"BOZ Redux: links could not follow a rename: {exc}")


CLASSES = (BOZ_OT_prefab_link_add, BOZ_OT_prefab_link_selected, BOZ_OT_prefab_link_remove,
           BOZ_OT_prefab_link_default, BOZ_OT_prefab_link_select)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.app.handlers.depsgraph_update_post.append(_on_change)


def unregister():
    if _on_change in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_on_change)
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
