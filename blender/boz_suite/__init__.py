"""BOZ Redux editor: a Blender application template for making Black Ops Zombies maps.

The SDK launcher starts Blender with this template (``--app-template boz_suite``) and the
project's folder in BOZ_PROJECT. ``tools/build_suite.py`` assembles it with the BOZ Redux
add-on and the bozkit modules it needs, and generates ``startup.blend`` from ``tabs.py``.
"""
from __future__ import annotations

import os

import bpy

from . import link, objects, palette, placeholders, preview, shapes, shell, tabs

ADDON = "boz_redux"


def _enable_addon() -> None:
    import sys

    import addon_utils

    for path in addon_utils.paths():  # not on sys.path yet while Blender starts up
        if path not in sys.path:
            sys.path.append(path)
    if ADDON not in {module.__name__ for module in addon_utils.modules(refresh=False)}:
        addon_utils.modules(refresh=True)
    addon_utils.enable(ADDON, default_set=True, persistent=True)
    addon = bpy.context.preferences.addons.get(ADDON)
    client = os.environ.get("BOZ_CLIENT")
    if addon is not None and client and not addon.preferences.client_root:
        addon.preferences.client_root = client


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
    try:
        _enable_addon()
    except Exception as exc:  # the editor still works without the shipped-map tools
        print(f"boz_suite: the {ADDON} add-on could not be enabled: {exc}")
    link.register()
    objects.register()
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
    objects.unregister()
    link.unregister()
