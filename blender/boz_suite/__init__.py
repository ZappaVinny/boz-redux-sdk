"""BOZ Redux editor: a Blender application template for making Black Ops Zombies maps.

The SDK launcher starts Blender with this template (``--app-template boz_suite``) and the
project's folder in BOZ_PROJECT. ``tools/build_suite.py`` assembles it with the bozkit modules
it needs, and generates ``startup.blend`` from ``tabs.py``.
"""
from __future__ import annotations

import bpy

from . import (assets_tab, effects_tab, game_tab, link, objects, palette, placeholders, preview,
               scene_view, shapes, shell, shipped_maps, sounds_tab, weapons_tab)


def _offline() -> None:
    """The editor needs no internet: answer Blender's online-access question once."""
    preferences = bpy.context.preferences
    for owner, attribute, value in ((preferences.system, "use_online_access", False),
                                    (getattr(preferences, "extensions", None),
                                     "use_online_access_handled", True)):
        try:
            if owner is not None and hasattr(owner, attribute):
                setattr(owner, attribute, value)
        except (AttributeError, TypeError, RuntimeError):
            pass


def register():
    _offline()
    shipped_maps.register()
    scene_view.register()   # after the Shipped files panel its Selected panel nests in
    link.register()
    objects.register()
    weapons_tab.register()
    assets_tab.register()
    sounds_tab.register()
    effects_tab.register()
    game_tab.register()
    palette.register()
    preview.register()
    shapes.register()
    placeholders.register()
    shell.register()


def unregister():
    shell.unregister()
    placeholders.unregister()
    shapes.unregister()
    preview.unregister()
    palette.unregister()
    game_tab.unregister()
    effects_tab.unregister()
    sounds_tab.unregister()
    assets_tab.unregister()
    weapons_tab.unregister()
    objects.unregister()
    link.unregister()
    scene_view.unregister()
    shipped_maps.unregister()
