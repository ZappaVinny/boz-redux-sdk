"""The BOZ Redux SDK launcher: projects, the client and the asset library (bozkit.desktop_window).

PySide6 frontend over bozkit.sdkhome and bozkit.project; it never writes game formats itself.
`boz-sdk --add-to-menu` adds the launcher, with its icon, to the Linux desktop's application menu.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

DESKTOP_ID = 'boz-redux-sdk'


def add_to_menu() -> int:
    branding = Path(__file__).resolve().parent / 'branding'
    command = shutil.which('boz-sdk')
    if command is None:
        checkout = Path(__file__).resolve().parents[3] / 'boz-sdk'
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
    ]) + '\n', encoding='utf-8')
    print(f'Added the BOZ Redux SDK to the application menu ({entry}).')
    return 0


def main() -> int:
    if '--add-to-menu' in sys.argv[1:]:
        return add_to_menu()
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
