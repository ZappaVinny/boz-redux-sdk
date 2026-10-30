"""bozkit: asset tools for Call of Duty: Black Ops Zombies (1.0.11) data. No game data included."""
import importlib.util as _importlib_util
import sys as _sys
from pathlib import Path as _Path

# Blender's own Python has no Pillow; the editor build (tools/build_suite.py) puts wheels for
# Linux and Windows next to its copy of bozkit, used when no Pillow is installed.
if _importlib_util.find_spec('PIL') is None:
    _pillow = _Path(__file__).resolve().parent.parent / (
        'pillow-windows' if _sys.platform == 'win32' else 'pillow-linux')
    if _pillow.is_dir():
        _sys.path.append(str(_pillow))
