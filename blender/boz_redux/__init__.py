"""BOZ Redux existing-map tools for Blender 5.2 LTS."""

from __future__ import annotations

bl_info = {
    "name": "BOZ Redux Map Tools",
    "author": "BOZ Redux contributors",
    "version": (0, 1, 0),
    "blender": (5, 2, 0),
    "location": "3D View > Sidebar > BOZ Redux",
    "description": "Import, edit, validate, and export BOZ 1.0.11 native map resources",
    "category": "Import-Export",
}

try:
    import bpy
except ModuleNotFoundError:  # Allows metadata inspection and packaging outside Blender.
    bpy = None


if bpy is not None:
    from .operators import CLASSES

    def register():
        for cls in CLASSES:
            bpy.utils.register_class(cls)


    def unregister():
        for cls in reversed(CLASSES):
            bpy.utils.unregister_class(cls)
