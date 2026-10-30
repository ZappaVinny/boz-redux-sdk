"""The BOZ Redux SDK launcher: projects, the client and the asset library (bozkit.desktop_window).

PySide6 frontend over bozkit.sdkhome and bozkit.project; it never writes game formats itself.
`boz-sdk --add-to-menu` adds the launcher, with its icon, to the Linux desktop's application menu;
`boz-sdk --check` reports whether it finds the SDK's files (exit code 1 when one is missing).
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from .schema import sdk_root

DESKTOP_ID = 'boz-redux-sdk'


def add_to_menu() -> int:
    branding = Path(__file__).resolve().parent / 'branding'
    command = sys.executable if getattr(sys, 'frozen', False) else shutil.which('boz-sdk')
    if command is None:
        checkout = sdk_root() / 'boz-sdk'
        command = str(checkout) if checkout.is_file() else f'{sys.executable} -m bozkit.desktop'
    apps = Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local' / 'share') / 'applications'
    apps.mkdir(parents=True, exist_ok=True)
    entry = apps / f'{DESKTOP_ID}.desktop'
    entry.write_text('\n'.join([
        '[Desktop Entry]',
        'Type=Application',
        'Name=BOZ Redux SDK',
        'Comment=Make maps and mods for BOZ Redux',
        f'Exec={command}',
        f'Icon={branding / "icons" / "boz-redux-sdk-256.png"}',
        'Terminal=false',
        'Categories=Development;Game;',
        f'StartupWMClass={DESKTOP_ID}',
    ]) + '\n', encoding='utf-8', newline='\n')
    print(f'Added the BOZ Redux SDK to the application menu ({entry}).')
    return 0


def check() -> int:
    from . import navbuild, project, schema, sdkhome
    root = sdk_root()
    items = {
        'SDK folder': root,
        'game definition': schema.gamedef_file('symbols'),
        'standard library': root / 'lib' / 'boz' / 'player.lua',
        'editor': sdkhome.suite_dir() / 'scripts' / 'startup' / 'bl_app_templates_user'
                  / 'boz_suite',
        'branding': Path(__file__).resolve().parent / 'branding' / 'boz-redux-sdk.ico',
    }
    try:
        items['navmesh helper'] = navbuild.helper_path()
    except FileNotFoundError:
        items['navmesh helper'] = root / 'tools' / 'navmesh' / 'build' / 'boz-navmesh'
    missing = [name for name, path in items.items() if not Path(path).exists()]
    if sys.stdout is not None:   # a windowed exe has no console
        for name, path in items.items():
            print(f'{"ok" if name not in missing else "MISSING":8} {name}: {path}')
    return 1 if missing else 0


def main() -> int:
    if '--add-to-menu' in sys.argv[1:]:
        return add_to_menu()
    if '--check' in sys.argv[1:]:
        return check()
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        print('PySide6 is required for the SDK launcher: pip install -e ".[desktop]"', file=sys.stderr)
        return 1
    from . import desktop_style
    from .desktop_window import APP_NAME, Window
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    desktop_style.install(app)
    window = Window()
    window.show()
    window.start()
    return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
