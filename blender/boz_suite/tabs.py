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


FORMS_TABS = ("Game", "Audio", "UI / HUD", "Weapons", "Assets", "Animation")
WEAPONS_FORMS_KEY = "boz_weapons_forms"   # Weapons, Assets: the largest Properties area shows the forms


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
        if workspace_name != "Scripts" or screen is None or area != script_area(screen):
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


SCRIPTS_KEY = "boz_scripts_layout3"  # Scripts: the next layout step, "done" or "failed"


def script_area(screen):
    """The Scripts tab's script editor: its tallest text area (the others show the log)."""
    texts = [a for a in screen.areas if a.type == "TEXT_EDITOR"]
    return max(texts, key=lambda a: a.height) if texts else None


def _override(window, screen, area):
    return bpy.context.temp_override(window=window, screen=screen, area=area)


def _split(window, screen, area, direction: str, factor: float) -> None:
    with _override(window, screen, area):
        if bpy.ops.screen.area_split(direction=direction, factor=factor) != {"FINISHED"}:
            raise RuntimeError("could not split an area")


def _top(screen):
    """The areas above the log (the one area touching the bottom)."""
    bottom = min(a.y for a in screen.areas)
    return [a for a in screen.areas if a.y > bottom]


def _scripts_step(window, step: int) -> None:
    """One step of the Scripts layout. A split area's new size is known only after the screen
    refreshes, so each step runs on its own tick and finds its areas by where they are now."""
    screen = window.screen
    if step == 0:       # everything but the script editor closes; it fills the screen
        keep = script_area(screen) or screen.areas[0]
        for other in [a for a in screen.areas if a != keep]:
            with _override(window, screen, other):
                bpy.ops.screen.area_close()
        if len(screen.areas) != 1:
            raise RuntimeError("could not close the areas")
    elif step == 1:     # the log along the whole bottom
        _split(window, screen, screen.areas[0], "HORIZONTAL", 0.2)
    elif step == 2:     # the files on the left
        _split(window, screen, _top(screen)[0], "VERTICAL", 0.2)
    elif step == 3:     # the right column
        _split(window, screen, max(_top(screen), key=lambda a: a.x), "VERTICAL", 0.77)
    elif step == 4:     # properties under the outliner
        _split(window, screen, max(_top(screen), key=lambda a: a.x), "HORIZONTAL", 0.6)
    elif step == LAST_STEP:
        _scripts_editors(window, screen)


LAST_STEP = 5


def _scripts_editors(window, screen) -> None:
    top = _top(screen)
    log = next(a for a in screen.areas if a not in top)
    left, right = min(a.x for a in top), max(a.x for a in top)
    files = next(a for a in top if a.x == left)
    properties, outliner = sorted((a for a in top if a.x == right), key=lambda a: a.y)
    middle = next(a for a in top if left < a.x < right)
    text = space_of(middle).text
    for area, editor in ((log, "TEXT_EDITOR"), (middle, "TEXT_EDITOR"), (files, "FILES"),
                         (properties, "PROPERTIES"), (outliner, "OUTLINER")):
        with _override(window, screen, area):
            area.ui_type = editor
    space = space_of(log)
    space.text = log_text()
    space.show_word_wrap = True
    space.show_line_numbers = False
    space = space_of(middle)
    space.text = text if text is not None and text.name != LOG_TEXT else None
    space.show_line_numbers = True
    space.show_syntax_highlight = True


def layout_scripts(window) -> bool:
    """Lay the Scripts tab out, one step per call: the log along the whole bottom; above it the
    files on the left, the script editor in the middle, and the outliner over the properties on
    the right. Background Blender cannot split areas, so this
    runs while the tab is on screen. Returns whether it is still going."""
    workspace = window.workspace
    step = workspace.get(SCRIPTS_KEY, 0)
    if not isinstance(step, int):
        return False
    if any(a.width <= 1 or a.height <= 1 for a in window.screen.areas):
        return True     # the last split is not on screen yet
    try:
        _scripts_step(window, step)
    except (RuntimeError, StopIteration, ValueError, TypeError) as exc:
        print(f"boz_suite: could not lay out Scripts: {exc}")
        workspace[SCRIPTS_KEY] = "failed"
        return False
    workspace[SCRIPTS_KEY] = step + 1 if step < LAST_STEP else "done"
    return step < LAST_STEP


def refresh_windows() -> float:
    """Timer: lay out and set up the tabs on screen (cheap when nothing is new)."""
    busy = False
    for window in bpy.context.window_manager.windows:
        workspace = window.workspace
        try:
            if workspace.get(LAYOUT_KEY) == "pending":
                apply_layout(window, workspace)
            if workspace.name == "World" and workspace.get(PALETTE_KEY) != "done":
                add_palette_area(window)
            if workspace.name in ("Weapons", "Assets", "Animation") and not workspace.get(WEAPONS_FORMS_KEY):
                areas = [a for a in window.screen.areas if a.type == "PROPERTIES"]
                if areas:
                    setup_properties(space_of(max(areas, key=lambda a: a.width * a.height)), True)
                    workspace[WEAPONS_FORMS_KEY] = True
            from . import assets_tab, weapons_tab
            if workspace.name in ("Weapons", "Animation"):
                weapons_tab.refresh_view(window)
            else:
                weapons_tab.leave_view(window)
            if workspace.name == "Assets":
                assets_tab.refresh_view(window)
            else:
                assets_tab.leave_view(window)
            if workspace.name == "Scripts" and layout_scripts(window):
                busy = True
                continue    # areas mid-layout are set up once it is done
            setup_screen(window.screen, workspace.name)
        except (AttributeError, TypeError, RuntimeError) as exc:
            print(f"boz_suite: could not lay out {workspace.name}: {exc}")
            workspace[LAYOUT_KEY] = "failed"
    return 0.1 if busy else 1.0


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
