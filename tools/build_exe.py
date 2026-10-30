#!/usr/bin/env python3
"""Build the SDK launcher as a standalone program with PyInstaller (one folder: boz-sdk[.exe]
and _internal/, with Python, PySide6 and bozkit inside). It runs from the SDK release folder,
which it treats as the SDK (bozkit.schema.sdk_root).

    python3 tools/build_exe.py          -> build/exe/boz-sdk/

Needs `pip install pyinstaller` and the SDK installed with its desktop extra.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRANDING = ROOT / 'tools' / 'bozkit' / 'bozkit' / 'branding'
ICON = BRANDING / 'boz-redux-sdk.ico'


def main() -> int:
    import PyInstaller.__main__
    work = ROOT / 'build' / 'pyinstaller'
    PyInstaller.__main__.run([
        str(ROOT / 'tools' / 'sdk_app.py'),
        '--name', 'boz-sdk',
        '--windowed',
        '--noconfirm',
        '--icon', str(ICON),
        '--paths', str(ROOT / 'tools' / 'bozkit'),
        # The icon, logo and fonts, where bozkit.desktop_style looks for them.
        '--add-data', f'{BRANDING}{os.pathsep}bozkit/branding',
        '--distpath', str(ROOT / 'build' / 'exe'),
        '--workpath', str(work),
        '--specpath', str(work),
    ])
    print(ROOT / 'build' / 'exe' / 'boz-sdk')
    return 0


if __name__ == '__main__':
    sys.exit(main())
