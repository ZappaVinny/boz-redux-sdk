"""Every planned editor feature that is not built yet, as a real panel in its tab.

This list is the source of the placeholder checklist (docs/internal/creator-suite-progress.md):
when a feature lands, its entry is removed here and its real panel takes the spot.
Blockers: "UI" (buildable now), "RE" (needs reverse engineering), "client" (needs the client),
"stdlib" (needs standard library events), "later".
"""
from __future__ import annotations

import bpy
from bpy.types import Operator, Panel

# (tab, title, what it will do, blocker)
PLACEHOLDERS = [
    ("Game", "Level info", "Display name, loading screen image, starting weapon, power at start", "UI"),
    ("Game", "Rounds", "Zombies per round, health and speed scaling, with a round-by-round graph", "UI"),
    ("Game", "Special rounds", "Dog rounds and their frequency; custom special rounds as a hook", "UI"),
    ("Game", "Zombie types", "Zombie configurations and which spawn types they use", "UI"),
    ("Game", "Pickups and economy", "Drop rates, allowed pickups, points, perk and box costs", "RE"),
    ("Game", "Hooks", "Every standard library event, with a button that creates or opens its Lua stub", "stdlib"),
    ("World", "Palettes", "Drag props, models, textures, effects and triggers from the game into the world", "UI"),
    ("World", "Make prop", "Turn a model into a prop with its own textures, collision and script stub", "UI"),
    ("World", "Rooms", "Rooms as collections and portals in doorways, for big maps", "UI"),
    ("Weapons", "Your own models", "Replace a gun's model with your own, moving with its rig", "RE"),
    ("Weapons", "Animations", "Idle, fire, reload, draw, sprint and aim animations from the Animation tab; "
     "single-shot fire rate and reload time come from these", "RE"),
    ("Characters", "Model replacement", "Replace player arms, characters and zombies with your models", "RE"),
    ("Characters", "Skeleton and preview", "Map bones to the game skeleton and preview animations", "RE"),
    ("Assets", "Import", "Bring in FBX, glTF, OBJ, PNG and JPG files", "UI"),
    ("Assets", "Game checks", "Triangles, vertex limits, scale, UVs and textures, with one-click fixes", "UI"),
    ("Assets", "Texture testing", "Swap textures on a model and preview the game's texture formats", "UI"),
    ("Assets", "Downscaling", "Turn high-quality models and textures into game-sized ones", "later"),
    ("Assets", "Lightmaps", "Bake lighting into the game's lightmap textures", "later"),
    ("Effects", "Effects", "Browse, preview, edit and add particle effects", "RE"),
    ("Animation", "Export animations", "Write object, weapon and character animations in the game's format", "RE"),
    ("Scripts", "Lua completions", "boz.* suggestions while typing in the script editor", "UI"),
    ("Scripts", "Object scripts", "Every object with a script stub; jump between the object and its script", "UI"),
    ("Scripts", "Reload in game", "Reload the project's scripts in the running game", "client"),
    ("Audio", "Sounds", "Replace the game's sounds and place ambient sound emitters", "later"),
    ("UI / HUD", "Loading screen", "Design the level's loading screen", "later"),
    ("UI / HUD", "HUD", "Change the in-game HUD", "later"),
]
FORMS_TABS = ("Game", "Audio", "UI / HUD")  # their panels go in the tab's big Properties area
BLOCKERS = {"UI": "Coming in a later SDK update", "RE": "Needs more reverse engineering first",
            "client": "Needs a client update first", "stdlib": "Grows with the standard library",
            "later": "Planned for later"}


def in_tab(context, tab: str) -> bool:
    workspace = getattr(context, "workspace", None)
    return workspace is not None and workspace.name == tab


class BOZ_OT_coming(Operator):
    bl_idname = "boz.coming"
    bl_label = "Coming soon"
    bl_description = "This part of the editor is not built yet"
    bl_options = {"INTERNAL"}

    feature: bpy.props.StringProperty()

    def execute(self, context):
        self.report({"INFO"}, f"{self.feature or 'This'} is coming in a later SDK update")
        return {"FINISHED"}


def _tab_poll(tab: str):
    def poll(cls, context):
        return in_tab(context, tab)
    return poll


def _panel_class(index: int, tab: str, title: str, description: str, blocker: str):
    forms = tab in FORMS_TABS

    def draw(self, context):
        layout = self.layout
        column = layout.column(align=True)
        for line in _wrap(description, 44):
            column.label(text=line)
        row = layout.row()
        row.enabled = False
        row.operator(BOZ_OT_coming.bl_idname, text=BLOCKERS[blocker], icon="TIME").feature = title

    attributes = {
        "bl_idname": f"BOZ_PT_placeholder_{index}",
        "bl_label": title,
        "bl_order": 100 + index,
        "poll": classmethod(_tab_poll(tab)),
        "draw": draw,
    }
    if forms:
        attributes.update(bl_space_type="PROPERTIES", bl_region_type="WINDOW", bl_context="scene")
    else:
        attributes.update(bl_space_type="VIEW_3D", bl_region_type="UI", bl_category="BOZ")
    return type(f"BOZ_PT_placeholder_{index}", (Panel,), attributes)


def _wrap(text: str, width: int) -> list[str]:
    lines, line = [], ""
    for word in text.split():
        if line and len(line) + 1 + len(word) > width:
            lines.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    return lines + ([line] if line else [])


CLASSES = [BOZ_OT_coming] + [_panel_class(i, *entry) for i, entry in enumerate(PLACEHOLDERS)]


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
