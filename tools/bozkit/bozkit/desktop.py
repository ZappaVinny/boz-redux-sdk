"""The BOZ Redux SDK launcher: projects, the client and the asset library (bozkit.desktop_window).

PySide6 frontend over bozkit.sdkhome and bozkit.project; it never writes game formats itself.
"""
from __future__ import annotations

import sys


def main() -> int:
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        print('PySide6 is required for the SDK launcher: pip install -e ".[desktop]"', file=sys.stderr)
        return 1
    from .desktop_window import APP_NAME, Window
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyle('Fusion')
    window = Window()
    window.show()
    window.start()
    return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
