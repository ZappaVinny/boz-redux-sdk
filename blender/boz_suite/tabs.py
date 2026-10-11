"""The editor's tabs (one Blender workspace each) and how the startup file lays them out.

``startup.blend`` is generated, not hand-made: ``generate()`` runs in a background Blender
(``tools/build_suite.py``) and turns the factory workspaces into the tabs by renaming them and
changing their areas' editor types. Background Blender cannot split areas or change the active
workspace, so every tab reuses a factory workspace whose areas already sit where the tab needs
them, and the factory "Layout" (active at startup) becomes World.
"""
from __future__ import annotations

import bpy

LOG_TEXT = "BOZ Log"

# (workspace name, factory workspace it is made from, {area type: new editor}, main forms area)
TABS = [
    ("Game", "Rendering", {"IMAGE_EDITOR": "FORMS", "PROPERTIES": "OUTLINER", "DOPESHEET_EDITOR": "LOG"}),
    ("World", "Layout", {"DOPESHEET_EDITOR": "LOG"}),
    ("Weapons", "Modeling", {}),
    ("Characters", "Sculpting", {}),
    ("Assets", "UV Editing", {}),
    ("Effects", "Texture Paint", {}),
    ("Animation", "Animation", {}),
    ("Scripts", "Scripting", {"CONSOLE": "LOG", "INFO": "FILES"}),
    ("Audio", "Compositing", {"NODE_EDITOR": "FORMS", "IMAGE_EDITOR": "VIEW_3D",
                              "PROPERTIES": "OUTLINER", "DOPESHEET_EDITOR": "LOG"}),
    ("UI / HUD", "Geometry Nodes", {"NODE_EDITOR": "IMAGE_EDITOR", "SPREADSHEET": "FORMS",
                                    "DOPESHEET_EDITOR": "LOG"}),
]
TAB_NAMES = [name for name, _source, _changes in TABS]
UNUSED_FACTORY = ("Shading",)

# Properties editor tabs the editor keeps. Everything else (render, output, scene, world,
# physics, particles, constraints, ...) cannot reach the game.
OBJECT_TABS = ("object", "modifiers", "data", "material")
PROPERTY_TABS = [prop.identifier[len("show_properties_"):]
                 for prop in bpy.types.SpaceProperties.bl_rna.properties
                 if prop.identifier.startswith("show_properties_")]


def log_text():
    text = bpy.data.texts.get(LOG_TEXT)
    if text is None:
        text = bpy.data.texts.new(LOG_TEXT)
        text.write("Build output and the game's log (boz-log.txt) appear here.\n")
    return text


def setup_properties(space, forms: bool) -> None:
    """Show only the tabs the editor uses: object tabs, or (for a tab's forms area) the scene
    tab, where that tab's panels live."""
    keep = ("scene",) if forms else OBJECT_TABS
    for tab in PROPERTY_TABS:
        attribute = f"show_properties_{tab}"
        if hasattr(space, attribute):
            try:
                setattr(space, attribute, tab in keep)
            except (AttributeError, TypeError):
                pass
    try:
        space.context = "SCENE" if forms else "OBJECT"
    except TypeError:
        pass


def space_of(area):
    """The area's space for its current editor type (area.spaces.active can lag behind a type
    change in background Blender)."""
    return next((space for space in area.spaces if space.type == area.type), area.spaces.active)


FORMS_TABS = ("Game", "Audio", "UI / HUD")


def _configured(space) -> bool:
    """Whether the editor already set this space up (stock defaults show the render tab, a 1000
    unit clip distance, and so on)."""
    if space.type == "PROPERTIES":
        return not space.show_properties_render
    if space.type == "VIEW_3D":
        return space.clip_end == 200000.0
    if space.type == "TEXT_EDITOR":
        return space.text is not None
    return True


def setup_area(area, workspace_name: str, screen=None) -> None:
    """Configure an area's editor for its tab, unless that was done before. Areas made in
    background Blender get their space only when their tab is first shown, so this runs then."""
    space = space_of(area)
    if space.type != area.type:
        return
    if space.type == "VIEW_3D" and space.shading.type == "SOLID" and \
            space.shading.color_type == "TEXTURE" and space.clip_end == 200000.0:
        space.shading.type = "MATERIAL"   # maps saved before game materials were shown
    if _configured(space):
        return
    if area.type == "VIEW_3D":
        space.show_region_ui = True
        space.clip_start = 1.0
        space.clip_end = 200000.0
        # Game materials (vertex colours, lightmaps) only show in material preview.
        space.shading.type = "MATERIAL"
        space.shading.use_scene_world = False
        space.shading.studiolight_intensity = 1.0
    elif area.type == "PROPERTIES":
        others = [a for a in (screen.areas if screen else []) if a.type == "PROPERTIES"]
        largest = max(others, key=lambda a: a.width * a.height) if others else area
        setup_properties(space, workspace_name in FORMS_TABS and area == largest)
    elif area.type == "TEXT_EDITOR":
        # Text areas show the log, except the tallest one in Scripts: the script editor.
        texts = [a for a in (screen.areas if screen else []) if a.type == "TEXT_EDITOR"]
        tallest = max(texts, key=lambda a: a.height) if texts else None
        if workspace_name != "Scripts" or area != tallest:
            space.text = log_text()
            space.show_word_wrap = True
            space.show_line_numbers = False
    elif area.type == "IMAGE_EDITOR":
        try:
            space.mode = "VIEW"
        except TypeError:
            pass


def setup_screen(screen, workspace_name: str) -> None:
    for area in screen.areas:
        try:
            setup_area(area, workspace_name, screen)
        except (AttributeError, TypeError, RuntimeError):
            pass


LAYOUT_KEY = "boz_layout"  # workspace property: "pending" until its areas are converted


def apply_layout(window, workspace) -> None:
    """Change the tab's areas to its editors. Background Blender can only do this for the active
    screen (other areas lose the change when saved), so the rest happens the first time a tab is
    on screen."""
    changes = next((c for name, _source, c in TABS if name == workspace.name), {})
    screen = window.screen
    for area in list(screen.areas):
        change = changes.get(area.type)
        if not change:
            continue
        editor = {"LOG": "TEXT_EDITOR", "FORMS": "PROPERTIES"}.get(change, change)
        with bpy.context.temp_override(window=window, screen=screen, area=area):
            area.ui_type = editor
    workspace[LAYOUT_KEY] = "done"


PALETTE_KEY = "boz_palette"   # World: "done" once its asset browser (the palettes) exists


def add_palette_area(window) -> None:
    """Split the World tab's viewport to put the palettes (an asset browser) on its left."""
    screen = window.screen
    views = [a for a in screen.areas if a.type == "VIEW_3D"]
    if not views:
        return
    view = max(views, key=lambda a: a.width * a.height)
    before = set(screen.areas[:])
    with bpy.context.temp_override(window=window, screen=screen, area=view):
        bpy.ops.screen.area_split(direction="VERTICAL", factor=0.24)
    pair = [a for a in screen.areas if a.type == "VIEW_3D" and (a == view or a not in before)]
    palette = min(pair, key=lambda a: a.width)
    with bpy.context.temp_override(window=window, screen=screen, area=palette):
        palette.ui_type = "ASSETS"
    space = space_of(palette)
    for attribute, value in (("asset_library_reference", "BOZ Game"), ("display_size", "MEDIUM")):
        try:
            setattr(space.params, attribute, value)
        except (TypeError, AttributeError):
            pass
    window.workspace[PALETTE_KEY] = "done"


def refresh_windows() -> float:
    """Timer: lay out and set up the tabs on screen (cheap when nothing is new)."""
    for window in bpy.context.window_manager.windows:
        workspace = window.workspace
        try:
            if workspace.get(LAYOUT_KEY) == "pending":
                apply_layout(window, workspace)
            if workspace.name == "World" and workspace.get(PALETTE_KEY) != "done":
                add_palette_area(window)
            setup_screen(window.screen, workspace.name)
        except (AttributeError, TypeError, RuntimeError) as exc:
            print(f"boz_suite: could not lay out {workspace.name}: {exc}")
            workspace[LAYOUT_KEY] = "failed"
    return 1.0


def generate() -> None:
    """Turn the factory startup's workspaces into the editor's tabs (background Blender)."""
    workspaces = bpy.data.workspaces
    for name, source, changes in TABS:
        workspace = workspaces[source]
        workspace.name = name
        workspace.object_mode = "OBJECT"
        screen = workspace.screens[0]
        active = screen == bpy.context.window_manager.windows[0].screen
        if active:
            for area in screen.areas:
                change = changes.get(area.type)
                if change:
                    area.ui_type = {"LOG": "TEXT_EDITOR", "FORMS": "PROPERTIES"}.get(change, change)
            setup_screen(screen, name)
        workspace[LAYOUT_KEY] = "done" if active or not changes else "pending"
    for name in UNUSED_FACTORY:
        if name in workspaces:
            bpy.data.batch_remove([workspaces[name]])
    for scene in bpy.data.scenes:
        units = scene.unit_settings
        units.system = "METRIC"
        units.scale_length = 0.01      # one Blender unit is one game centimetre
        units.length_unit = "METERS"
        # The game's colours show only under a neutral view transform (as the map tools set).
        scene.view_settings.view_transform = "Standard"
        scene.view_settings.look = "None"
    # The default cube, light and camera are not game content.
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj)
