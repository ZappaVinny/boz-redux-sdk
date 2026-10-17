"""The SDK launcher's look: the BOZ Redux SDK brand (branding/: icon, logo, Barlow fonts) and the
Qt style sheet in its colours."""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QFont, QFontDatabase, QIcon, QPixmap
from PySide6.QtWidgets import QApplication

BRANDING = Path(__file__).resolve().parent / 'branding'

RED = '#e31c29'
RED_HOVER = '#f03440'
RED_DARK = '#a8141f'
BLACK = '#0d0e10'
PANEL = '#16181b'
RAISED = '#202328'
LINE = '#2e3238'
WHITE = '#e9eaeb'
GREY = '#8b9098'
OK = '#3ec46d'
WARN = '#e8a838'
ERROR = '#ff5c62'

BODY_FAMILY = 'Barlow'
HEADING_FAMILY = 'Barlow Condensed'

STYLE_SHEET = f"""
* {{ font-family: "{BODY_FAMILY}"; font-size: 10.5pt; color: {WHITE}; }}
QMainWindow, QDialog, QStackedWidget > QWidget {{ background: {BLACK}; }}
QWidget#sidebar {{ background: {PANEL}; border-right: 1px solid {LINE}; }}
QLabel#version {{ color: {GREY}; font-size: 9pt; }}
QLabel#muted {{ color: {GREY}; }}
QLabel#heading {{ font-family: "{HEADING_FAMILY}"; font-weight: 700; font-size: 21pt;
    letter-spacing: 1px; }}
QLabel#subheading {{ font-family: "{HEADING_FAMILY}"; font-weight: 700; font-size: 13.5pt;
    letter-spacing: 0.5px; color: {WHITE}; }}
QListWidget#nav {{ background: transparent; border: none; outline: 0; padding-top: 6px;
    font-family: "{HEADING_FAMILY}"; font-weight: 700; font-size: 13.5pt; }}
QListWidget#nav::item {{ color: {GREY}; padding: 10px 18px; border-left: 3px solid transparent; }}
QListWidget#nav::item:hover {{ color: {WHITE}; background: {RAISED}; }}
QListWidget#nav::item:selected {{ color: {WHITE}; background: {RAISED}; border-left: 3px solid {RED}; }}
QPushButton {{ background: {RAISED}; border: 1px solid {LINE}; border-radius: 3px;
    padding: 6px 14px; min-height: 20px; }}
QPushButton:hover {{ background: {LINE}; }}
QPushButton:pressed {{ background: {RED_DARK}; border-color: {RED_DARK}; }}
QPushButton:disabled {{ color: #5b6068; background: {PANEL}; border-color: {RAISED}; }}
QPushButton:default, QPushButton[primary="true"] {{ background: {RED}; border-color: {RED}; font-weight: 600; }}
QPushButton:default:hover, QPushButton[primary="true"]:hover {{ background: {RED_HOVER}; border-color: {RED_HOVER}; }}
QPushButton[primary="true"]:pressed {{ background: {RED_DARK}; border-color: {RED_DARK}; }}
QPushButton[primary="true"]:disabled {{ background: #4a1a1e; border-color: #4a1a1e; color: #9a8a8b; }}
QLineEdit, QPlainTextEdit, QTextBrowser, QComboBox, QSpinBox {{ background: {PANEL};
    border: 1px solid {LINE}; border-radius: 3px; padding: 5px 8px;
    selection-background-color: {RED_DARK}; }}
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus {{ border-color: {RED}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{ background: {PANEL}; border: 1px solid {LINE};
    selection-background-color: {RED_DARK}; }}
QListWidget, QTreeWidget, QTableView {{ background: {PANEL}; border: 1px solid {LINE};
    border-radius: 3px; alternate-background-color: #1a1c20; outline: 0; }}
QListWidget::item, QTreeWidget::item {{ padding: 4px; }}
QListWidget::item:selected, QTreeWidget::item:selected {{ background: rgba(227, 28, 41, 0.28);
    color: {WHITE}; }}
QListWidget::item:hover, QTreeWidget::item:hover {{ background: {RAISED}; }}
QHeaderView::section {{ background: {RAISED}; color: {GREY}; border: none;
    border-right: 1px solid {LINE}; padding: 6px 8px; font-weight: 600; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: 16px; height: 16px; }}
QCheckBox::indicator {{ border: 1px solid {LINE}; border-radius: 3px; background: {PANEL}; }}
QCheckBox::indicator:checked {{ background: {RED}; border-color: {RED}; }}
QRadioButton::indicator {{ border: 1px solid {LINE}; border-radius: 8px; background: {PANEL}; }}
QRadioButton::indicator:checked {{ background: {RED}; border: 4px solid {PANEL};
    outline: 1px solid {RED}; }}
QProgressBar {{ background: {PANEL}; border: 1px solid {LINE}; border-radius: 3px;
    text-align: center; height: 14px; }}
QProgressBar::chunk {{ background: {RED}; border-radius: 2px; }}
QScrollBar:vertical {{ background: {BLACK}; width: 11px; margin: 0; }}
QScrollBar:horizontal {{ background: {BLACK}; height: 11px; margin: 0; }}
QScrollBar::handle {{ background: {LINE}; border-radius: 4px; min-height: 30px; min-width: 30px; }}
QScrollBar::handle:hover {{ background: {GREY}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
QSplitter::handle {{ background: {LINE}; }}
QStatusBar {{ background: {PANEL}; border-top: 1px solid {LINE}; color: {GREY}; }}
QStatusBar::item {{ border: none; }}
QToolTip {{ background: {PANEL}; color: {WHITE}; border: 1px solid {LINE}; padding: 5px; }}
QMenu {{ background: {PANEL}; border: 1px solid {LINE}; padding: 4px; }}
QMenu::item {{ padding: 6px 18px; }}
QMenu::item:selected {{ background: {RED_DARK}; }}
QFrame[frameShape="4"], QFrame[frameShape="5"] {{ color: {LINE}; }}
QDialogButtonBox {{ dialogbuttonbox-buttons-have-icons: 0; }}
QDialogButtonBox QPushButton {{ min-width: 80px; }}
QMessageBox QLabel {{ min-width: 260px; }}
"""


def app_icon() -> QIcon:
    icon = QIcon()
    for size in (16, 32, 48, 64, 256, 1024):
        path = BRANDING / 'icons' / f'boz-redux-sdk-{size}.png'
        if path.is_file():
            icon.addFile(str(path), QSize(size, size))
    return icon


def logo_pixmap(height: int, ratio: float = 1.0) -> QPixmap:
    """The SDK logo scaled to *height* logical pixels (sharp on high-DPI screens)."""
    pixmap = QPixmap(str(BRANDING / 'boz-redux-sdk-logo.png'))
    if pixmap.isNull():
        return pixmap
    scaled = pixmap.scaledToHeight(int(height * ratio), Qt.TransformationMode.SmoothTransformation)
    scaled.setDevicePixelRatio(ratio)
    return scaled


def heading_font(size: int) -> QFont:
    font = QFont(HEADING_FAMILY)
    font.setPointSize(size)
    font.setBold(True)
    return font


def install(app: QApplication) -> None:
    """Fonts, icon, palette and style sheet for the whole application."""
    for name in ('Barlow-Regular.ttf', 'Barlow-SemiBold.ttf', 'BarlowCondensed-Bold.ttf'):
        QFontDatabase.addApplicationFont(str(BRANDING / 'fonts' / name))
    app.setStyle('Fusion')
    app.setFont(QFont(BODY_FAMILY, 10))
    app.setWindowIcon(app_icon())
    app.setDesktopFileName('boz-redux-sdk')  # matches boz-sdk --add-to-menu
    app.setStyleSheet(STYLE_SHEET)
    if sys.platform == 'win32':
        # Its own taskbar identity, so Windows shows the SDK icon instead of Python's.
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('BOZRedux.SDK')
        except (AttributeError, OSError):
            pass
