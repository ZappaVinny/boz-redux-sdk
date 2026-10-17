"""The BOZ Redux SDK launcher: projects, the client and (later) the asset library.

PySide6 frontend over bozkit.sdkhome and bozkit.project; it never writes game formats itself.
"""
from __future__ import annotations

import html
import sys
import time
from pathlib import Path

from . import library as asset_library
from . import maps
from . import project as sdk_project
from . import sdkhome

APP_NAME = 'BOZ Redux SDK'
MISSING_DATA = ('Game data not installed. Open the client launcher → Game files → Install, then '
                'Download. Maps can\'t be built without it; script-only projects still work.')
COMING = 'Coming in a later SDK update'


def main() -> int:
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        print('PySide6 is required for the SDK launcher: pip install -e ".[desktop]"', file=sys.stderr)
        return 1
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyle('Fusion')
    window = _build_window()
    window.show()
    window.start()
    return app.exec()


def _build_window():
    from PySide6.QtCore import QFile, QSize, Qt, QThread, QTimer, QUrl, Signal
    from PySide6.QtGui import QColor, QDesktopServices, QFont, QIcon, QPainter, QPixmap
    from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QDialog,
                                   QDialogButtonBox, QFileDialog, QFormLayout, QFrame, QGridLayout,
                                   QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit,
                                   QListWidget, QListWidgetItem, QMainWindow, QMenu, QMessageBox,
                                   QPlainTextEdit, QProgressBar, QPushButton, QRadioButton,
                                   QSplitter, QStackedWidget,
                                   QTextBrowser, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
                                   QWidget)

    # Helpers

    def heading(text: str, size: int = 16) -> QLabel:
        label = QLabel(text)
        font = label.font()
        font.setPointSize(size)
        font.setBold(True)
        label.setFont(font)
        return label

    def muted(text: str) -> QLabel:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setStyleSheet('color: palette(placeholder-text);')
        return label

    def button(text: str, callback=None, tooltip: str = '', enabled: bool = True) -> QPushButton:
        widget = QPushButton(text)
        if callback:
            widget.clicked.connect(callback)
        if tooltip:
            widget.setToolTip(tooltip)
        widget.setEnabled(enabled)
        return widget

    def coming(text: str) -> QPushButton:
        widget = button(text, tooltip=COMING, enabled=False)
        return widget

    def kind_icon(kind: str, size: int = 48) -> QIcon:
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor('#7a3b2e' if kind == 'map' else '#2e5a7a' if kind else '#555'))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(0, 0, size, size, 8, 8)
        painter.setPen(QColor('white'))
        font = QFont()
        font.setBold(True)
        font.setPixelSize(size // 2)
        painter.setFont(font)
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter,
                         {'map': 'M', 'script': 'S'}.get(kind, '?'))
        painter.end()
        return QIcon(pixmap)

    def project_icon(listed: sdkhome.ListedProject) -> QIcon:
        if listed.icon:
            return QIcon(str(listed.icon))
        return kind_icon(listed.kind)

    def open_path(path: Path) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def check_mark(ok: bool) -> str:
        return '<span style="color:#4caf50">✔</span>' if ok else '<span style="color:#e57373">✘</span>'

    # Dialogs

    class WelcomeDialog(QDialog):
        """First run: pick the client folder and check its game data."""

        def __init__(self, parent, settings: sdkhome.Settings) -> None:
            super().__init__(parent)
            self.setWindowTitle(f'Welcome to the {APP_NAME}')
            self.setMinimumWidth(620)
            self.settings = settings
            layout = QVBoxLayout(self)
            layout.addWidget(heading('Welcome'))
            layout.addWidget(muted(
                'The SDK makes maps and mods for the BOZ Redux client. Choose the folder you '
                'unpacked the client into (the one with the client\'s launcher, boz-redux).'))
            row = QHBoxLayout()
            self.folder = QLineEdit(settings.client)
            self.folder.setPlaceholderText('BOZ Redux client folder')
            self.folder.textChanged.connect(self.check)
            row.addWidget(self.folder)
            row.addWidget(button('Browse…', self.browse))
            layout.addLayout(row)
            self.status = QLabel()
            self.status.setWordWrap(True)
            self.status.setTextFormat(Qt.TextFormat.RichText)
            layout.addWidget(self.status)
            self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                            | QDialogButtonBox.StandardButton.Cancel)
            self.buttons.accepted.connect(self.accept)
            self.buttons.rejected.connect(self.reject)
            layout.addWidget(self.buttons)
            self.check()

        def browse(self) -> None:
            chosen = QFileDialog.getExistingDirectory(self, 'Choose the BOZ Redux client folder',
                                                      self.folder.text() or str(Path.home()))
            if chosen:
                self.folder.setText(chosen)

        def check(self) -> None:
            text = self.folder.text().strip()
            ok = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
            if not text:
                self.status.setText('')
                ok.setEnabled(False)
                return
            status = sdkhome.client_status(text)
            if not status.is_client:
                self.status.setText(f'{check_mark(False)} This folder has no BOZ Redux client in it.')
                ok.setEnabled(False)
                return
            ok.setEnabled(True)
            if status.game_ready:
                self.status.setText(f'{check_mark(True)} Client found ({status.kind_label}), and the '
                                    'game data is installed.')
            else:
                self.status.setText(
                    f'{check_mark(True)} Client found ({status.kind_label}).<br>'
                    f'<b style="color:#e0a040">⚠ {html.escape(MISSING_DATA)}</b><br>'
                    f'Missing: {html.escape(", ".join(status.missing))}')

        def chosen(self) -> str:
            return str(Path(self.folder.text().strip()).expanduser().resolve())

    class NewProjectDialog(QDialog):
        def __init__(self, parent, settings: sdkhome.Settings, game_ready: bool,
                     maps: dict | None = None) -> None:
            super().__init__(parent)
            self.setWindowTitle('New project')
            self.setMinimumSize(720, 560)
            self.settings = settings
            self.id_edited = False
            self.icon_path = ''
            layout = QVBoxLayout(self)

            kinds = QHBoxLayout()
            self.kind_group = QButtonGroup(self)
            self.map_kind = QRadioButton('Map\nA level made in the editor')
            self.script_kind = QRadioButton('Script-only mod\nLua code, opened in your code editor')
            for widget in (self.map_kind, self.script_kind):
                widget.setStyleSheet('QRadioButton { padding: 10px; }')
                self.kind_group.addButton(widget)
                kinds.addWidget(widget)
            self.map_kind.setChecked(True)
            self.kind_group.buttonToggled.connect(self.fill_templates)
            layout.addLayout(kinds)

            form = QFormLayout()
            self.name = QLineEdit()
            self.name.setPlaceholderText('My Map')
            self.name.textChanged.connect(self.name_changed)
            self.mod_id = QLineEdit()
            self.mod_id.textEdited.connect(self.id_changed)
            self.author = QLineEdit(settings.author)
            self.version = QLineEdit('0.1.0')
            self.description = QPlainTextEdit()
            self.description.setPlaceholderText('What this adds or changes')
            self.description.setFixedHeight(70)
            location = QHBoxLayout()
            self.location = QLineEdit(str(settings.projects_folder()))
            self.location.textChanged.connect(self.update_path)
            location.addWidget(self.location)
            location.addWidget(button('Browse…', self.browse_location))
            icon_row = QHBoxLayout()
            self.icon_label = QLabel('None')
            icon_row.addWidget(self.icon_label, 1)
            icon_row.addWidget(button('Choose…', self.choose_icon))
            form.addRow('Name', self.name)
            form.addRow('Id', self.mod_id)
            form.addRow('Author', self.author)
            form.addRow('Version', self.version)
            form.addRow('Description', self.description)
            form.addRow('Location', location)
            self.path_label = muted('')
            form.addRow('', self.path_label)
            form.addRow('Icon (optional)', icon_row)
            layout.addLayout(form)

            layout.addWidget(QLabel('Template'))
            self.templates = QListWidget()
            self.templates.setIconSize(QSize(56, 32))
            self.templates.setFixedHeight(150)
            layout.addWidget(self.templates)
            self.game_ready = game_ready
            self.maps = maps or {}  # library map name -> thumbnail path
            self.note = muted('')
            layout.addWidget(self.note)

            buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
            self.create = buttons.addButton('Create', QDialogButtonBox.ButtonRole.AcceptRole)
            buttons.accepted.connect(self.accept)
            buttons.rejected.connect(self.reject)
            layout.addWidget(buttons)
            self.fill_templates()
            self.update_path()

        @property
        def kind(self) -> str:
            return 'map' if self.map_kind.isChecked() else 'script'

        def fill_templates(self, *_args) -> None:
            self.templates.clear()
            if self.kind == 'map':
                entries = [('empty', 'Empty', 'A 6 m floor and the player spawns; the Colt is '
                            'the only weapon', True),
                           ('debug', 'Debug arena', 'A walled arena with zombie spawns, Juggernog '
                            'and power: the quickest way to test', bool(self.maps))]
                for key, label in maps.LABELS.items():
                    entries.append((key, label, 'The whole original map to change and add to '
                                    '(a fresh copy)', key in self.maps))
                self.note.setText('Open in Editor to build the map; Build && Run compiles it and '
                                  'starts the game in it.'
                                  + ('' if self.maps else ' The debug arena and original maps '
                                     'need the asset library (Library page).'))
            else:
                entries = [(key, label, text, True)
                           for key, (label, text) in sdk_project.SCRIPT_TEMPLATES.items()]
                self.note.setText('The project gets main.lua from the template and a copy of the '
                                  'standard library (scripts/boz) so your editor can autocomplete it.')
            for key, label, text, enabled in entries:
                thumb = self.maps.get(key) if self.kind == 'map' else None
                icon = QIcon(str(thumb)) if thumb else kind_icon(self.kind, 32)
                item = QListWidgetItem(icon, f'{label} — {text}')
                item.setData(Qt.ItemDataRole.UserRole, key)
                if not enabled:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
                self.templates.addItem(item)
            self.templates.setCurrentRow(0)
            if not self.name.text():
                self.name.setPlaceholderText('My Map' if self.kind == 'map' else 'My Mod')

        def name_changed(self, text: str) -> None:
            if not self.id_edited:
                self.mod_id.setText(sdkhome.suggest_id(text) if text else '')
            self.update_path()

        def id_changed(self, _text: str) -> None:
            self.id_edited = True
            self.update_path()

        def browse_location(self) -> None:
            chosen = QFileDialog.getExistingDirectory(self, 'Where new projects go',
                                                      self.location.text())
            if chosen:
                self.location.setText(chosen)

        def choose_icon(self) -> None:
            chosen, _ = QFileDialog.getOpenFileName(self, 'Project icon', str(Path.home()),
                                                    'Images (*.png)')
            if chosen:
                self.icon_path = chosen
                self.icon_label.setText(Path(chosen).name)

        def target(self) -> Path:
            return Path(self.location.text().strip()).expanduser() / (self.mod_id.text().strip()
                                                                      or 'project')

        def update_path(self, *_args) -> None:
            self.path_label.setText(f'Creates {self.target()}')

        def template(self) -> str:
            item = self.templates.currentItem()
            return item.data(Qt.ItemDataRole.UserRole) if item else ''

        def accept(self) -> None:
            try:
                created = sdk_project.create_project(
                    self.target(), self.mod_id.text().strip(),
                    self.name.text().strip() or self.name.placeholderText(),
                    self.author.text().strip(), self.version.text().strip(),
                    self.description.toPlainText().strip(), kind=self.kind,
                    template=self.template(),
                    game=asset_library.open_game(self.settings.client) if self.kind == 'map'
                    else None)
            except (OSError, sdk_project.ProjectError) as exc:
                QMessageBox.warning(self, 'New project', str(exc))
                return
            if self.icon_path:
                try:
                    (created.root / 'icon.png').write_bytes(Path(self.icon_path).read_bytes())
                except OSError as exc:
                    QMessageBox.warning(self, 'New project', f'The icon was not copied: {exc}')
            self.created = created
            self.settings.author = self.author.text().strip()
            self.settings.projects_dir = self.location.text().strip()
            super().accept()

    # Pages

    class ProjectsPage(QWidget):
        def __init__(self, window) -> None:
            super().__init__()
            self.main = window
            layout = QVBoxLayout(self)
            top = QHBoxLayout()
            top.addWidget(heading('Projects'))
            top.addStretch(1)
            top.addWidget(button('New project…', window.new_project))
            top.addWidget(button('Add existing…', window.add_existing,
                                 'Add a project folder (one with boz-project.toml) to the list'))
            layout.addLayout(top)
            bar = QHBoxLayout()
            self.search = QLineEdit()
            self.search.setPlaceholderText('Search projects')
            self.search.textChanged.connect(self.refresh)
            self.sort = QComboBox()
            self.sort.addItems(['Last opened', 'Name', 'Kind'])
            self.sort.currentIndexChanged.connect(self.refresh)
            bar.addWidget(self.search, 1)
            bar.addWidget(QLabel('Sort'))
            bar.addWidget(self.sort)
            layout.addLayout(bar)
            self.tree = QTreeWidget()
            self.tree.setHeaderLabels(['Name', 'Kind', 'Last opened', 'Folder'])
            self.tree.setIconSize(QSize(40, 40))
            self.tree.setRootIsDecorated(False)
            self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
            self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
            self.tree.header().setStretchLastSection(True)
            self.tree.itemDoubleClicked.connect(lambda *_: self.open_selected())
            self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            self.tree.customContextMenuRequested.connect(self.menu)
            self.tree.itemSelectionChanged.connect(self.update_buttons)
            layout.addWidget(self.tree, 1)
            self.empty = muted('No projects yet. Click New project to make a map or a mod.')
            layout.addWidget(self.empty)
            actions = QHBoxLayout()
            self.actions = [
                button('Open', self.open_selected),
                button('Duplicate…', lambda: window.duplicate(self.selected())),
                button('Rename…', lambda: window.rename(self.selected())),
                button('Delete…', lambda: window.delete(self.selected())),
                button('Show in file manager', lambda: open_path(self.selected().entry.path)),
                button('Remove from list', lambda: window.forget(self.selected()),
                       'Take the project off this list; its folder stays'),
            ]
            for widget in self.actions:
                actions.addWidget(widget)
            actions.addStretch(1)
            layout.addLayout(actions)

        def selected(self) -> sdkhome.ListedProject | None:
            item = self.tree.currentItem()
            return item.data(0, Qt.ItemDataRole.UserRole) if item else None

        def update_buttons(self) -> None:
            listed = self.selected()
            for widget in self.actions:
                widget.setEnabled(listed is not None)
            if listed is not None and listed.project is None:
                for widget in self.actions[:3]:
                    widget.setEnabled(False)

        def open_selected(self) -> None:
            listed = self.selected()
            if listed is None:
                return
            if listed.project is None:
                QMessageBox.warning(self, APP_NAME, f'This project cannot be opened:\n{listed.error}')
                return
            self.main.open_project(listed.project)

        def menu(self, point) -> None:
            if self.selected() is None:
                return
            menu = QMenu(self)
            for widget in self.actions:
                action = menu.addAction(widget.text())
                action.setEnabled(widget.isEnabled())
                action.triggered.connect(widget.click)
            menu.exec(self.tree.viewport().mapToGlobal(point))

        def refresh(self, *_args) -> None:
            listed = sdkhome.list_projects(self.main.settings)
            needle = self.search.text().strip().lower()
            if needle:
                listed = [item for item in listed
                          if needle in item.name.lower() or needle in str(item.entry.path).lower()]
            order = self.sort.currentText()
            if order == 'Name':
                listed.sort(key=lambda item: item.name.lower())
            elif order == 'Kind':
                listed.sort(key=lambda item: (item.kind, item.name.lower()))
            else:
                listed.sort(key=lambda item: -item.entry.last_opened)
            self.tree.clear()
            for item in listed:
                opened = (time.strftime('%Y-%m-%d %H:%M', time.localtime(item.entry.last_opened))
                          if item.entry.last_opened else '')
                kind = {'map': 'Map', 'script': 'Script-only'}.get(item.kind, 'Missing or broken')
                row = QTreeWidgetItem([item.name, kind, opened, str(item.entry.path)])
                row.setIcon(0, project_icon(item))
                row.setData(0, Qt.ItemDataRole.UserRole, item)
                if item.project is None:
                    row.setToolTip(0, item.error)
                    row.setForeground(0, QColor('#e57373'))
                self.tree.addTopLevelItem(row)
            self.empty.setVisible(not self.main.settings.projects)
            self.update_buttons()

    class ProjectPage(QWidget):
        def __init__(self, window) -> None:
            super().__init__()
            self.main = window
            self.project: sdk_project.Project | None = None
            layout = QVBoxLayout(self)
            top = QHBoxLayout()
            top.addWidget(button('← Projects', window.show_projects))
            self.icon = QLabel()
            top.addWidget(self.icon)
            self.title = heading('')
            top.addWidget(self.title)
            self.kind = muted('')
            top.addWidget(self.kind)
            top.addStretch(1)
            top.addWidget(button('Show in file manager', lambda: open_path(self.project.root)))
            layout.addLayout(top)

            self.actions = QHBoxLayout()
            layout.addLayout(self.actions)

            form_frame = QFrame()
            form_frame.setFrameShape(QFrame.Shape.StyledPanel)
            form = QFormLayout(form_frame)
            self.mod_id = QLabel()
            self.mod_id.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.name = QLineEdit()
            self.version = QLineEdit()
            self.author = QLineEdit()
            self.description = QPlainTextEdit()
            self.description.setFixedHeight(60)
            self.template = QLabel()
            self.folder = QLabel()
            self.folder.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            form.addRow('Id', self.mod_id)
            form.addRow('Name', self.name)
            form.addRow('Version', self.version)
            form.addRow('Author', self.author)
            form.addRow('Description', self.description)
            form.addRow('Template', self.template)
            form.addRow('Folder', self.folder)
            save = QHBoxLayout()
            save.addStretch(1)
            save.addWidget(button('Save details', self.save))
            form.addRow(save)
            layout.addWidget(form_frame)

            log_bar = QHBoxLayout()
            log_bar.addWidget(QLabel('Game log'))
            self.log_filter = QCheckBox('Only this mod and errors')
            self.log_filter.setChecked(True)
            self.log_filter.toggled.connect(self.reload_log)
            log_bar.addStretch(1)
            log_bar.addWidget(self.log_filter)
            log_bar.addWidget(button('Clear view', lambda: self.log.clear()))
            layout.addLayout(log_bar)
            self.log = QTextBrowser()
            self.log.setFont(QFont('monospace'))
            self.log.setPlaceholderText('The client\'s boz-log.txt appears here while the game runs.')
            layout.addWidget(self.log, 1)
            self.log_size = -1
            self.timer = QTimer(self)
            self.timer.setInterval(1000)
            self.timer.timeout.connect(self.poll_log)

        def show_project(self, project: sdk_project.Project) -> None:
            self.project = project
            listed = sdkhome.ListedProject(sdkhome.ProjectEntry(project.root), project)
            self.icon.setPixmap(project_icon(listed).pixmap(40, 40))
            self.title.setText(project.mod.name)
            self.kind.setText('Map' if project.kind == 'map' else 'Script-only mod')
            self.mod_id.setText(project.mod.id)
            self.name.setText(project.mod.name)
            self.version.setText(project.mod.version)
            self.author.setText(project.mod.author)
            self.description.setPlainText(project.mod.description)
            template = project.map_template if project.kind == 'map' else ''
            self.template.setText(template or '—')
            self.folder.setText(str(project.root))
            while self.actions.count():
                widget = self.actions.takeAt(0).widget()
                if widget:
                    widget.deleteLater()
            if project.kind == 'map':
                widgets = [button('Open in Editor', self.open_editor,
                                  'Opens the map in the BOZ Redux editor (Blender)'),
                           button('▶ Build && Run', self.run_in_game,
                                  'Compiles the map into a mod, installs it with the Developer '
                                  'mod and starts the game straight into the level'),
                           button('Open folder', self.open_folder)]
            else:
                widgets = [button('Open folder', self.open_folder,
                                  'Opens VS Code if it is installed, else your file manager'),
                           button('▶ Run in game', self.run_in_game,
                                  'Installs this mod and the Developer mod into the client, '
                                  'then starts the game')]
            widgets.append(coming('Export…'))
            for widget in widgets:
                self.actions.addWidget(widget)
            self.actions.addStretch(1)
            self.log_size = -1
            self.log.clear()
            self.reload_log()
            self.timer.start()

        def hideEvent(self, event) -> None:
            self.timer.stop()
            super().hideEvent(event)

        def open_folder(self) -> None:
            folder = self.project.root
            command = sdkhome.external_editor_command(folder)
            if command:
                sdkhome.start_detached(command, folder)
            else:
                open_path(folder)

        def open_editor(self) -> None:
            from PySide6.QtWidgets import QApplication
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                sdkhome.open_editor(self.project, self.main.settings)
            except (OSError, sdk_project.ProjectError) as exc:
                QApplication.restoreOverrideCursor()
                QMessageBox.warning(self, 'Open in Editor', str(exc))
                return
            QApplication.restoreOverrideCursor()
            self.main.statusBar().showMessage('Opening the editor…', 8000)

        def run_in_game(self) -> None:
            from PySide6.QtWidgets import QApplication
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                message = sdkhome.run_in_game(self.project, self.main.settings.client)
            except (OSError, ValueError, sdk_project.ProjectError) as exc:
                QApplication.restoreOverrideCursor()
                QMessageBox.warning(self, 'Build & Run' if self.project.kind == 'map'
                                    else 'Run in game', str(exc))
                return
            QApplication.restoreOverrideCursor()
            self.main.statusBar().showMessage(message, 8000)
            self.log_size = -1
            self.log.clear()

        def save(self) -> None:
            try:
                self.project = sdkhome.update_metadata(
                    self.project, name=self.name.text().strip(), version=self.version.text().strip(),
                    author=self.author.text().strip(),
                    description=self.description.toPlainText().strip())
            except (OSError, sdk_project.ProjectError) as exc:
                QMessageBox.warning(self, APP_NAME, str(exc))
                return
            self.show_project(self.project)
            self.main.statusBar().showMessage('Saved', 4000)

        def log_path(self) -> Path | None:
            if not self.main.settings.client:
                return None
            return Path(self.main.settings.client) / 'boz-log.txt'

        def reload_log(self, *_args) -> None:
            self.log_size = -1
            self.log.clear()
            self.poll_log()

        def wanted(self, line: str) -> bool:
            if not self.log_filter.isChecked():
                return True
            mod_id = self.project.mod.id if self.project else ''
            lowered = line.lower()
            return (f'] {mod_id}' in line or f'{mod_id}:' in line or 'error' in lowered
                    or 'fault' in lowered or 'traceback' in lowered)

        def poll_log(self) -> None:
            path = self.log_path()
            if path is None or not path.is_file():
                return
            size = path.stat().st_size
            if size == self.log_size:
                return
            start = self.log_size if 0 <= self.log_size <= size else 0
            if start == 0:
                self.log.clear()
            with open(path, 'rb') as stream:
                stream.seek(start)
                text = stream.read().decode('utf-8', 'replace')
            self.log_size = size
            for line in text.splitlines():
                if not self.wanted(line):
                    continue
                lowered = line.lower()
                colour = ('#e57373' if 'error' in lowered or 'fault' in lowered
                          else '#e0a040' if 'warn' in lowered
                          else '#81c784' if '[lua]' in line else None)
                escaped = html.escape(line)
                self.log.append(f'<span style="color:{colour}">{escaped}</span>' if colour
                                else escaped)

    class ClientPage(QWidget):
        def __init__(self, window) -> None:
            super().__init__()
            self.main = window
            layout = QVBoxLayout(self)
            top = QHBoxLayout()
            top.addWidget(heading('Client'))
            top.addStretch(1)
            top.addWidget(button('Refresh', self.refresh))
            top.addWidget(button('Change folder…', window.choose_client))
            self.launch = button('Open client launcher', self.open_launcher,
                                 'Install game files, change settings and play')
            top.addWidget(self.launch)
            layout.addLayout(top)
            self.summary = QLabel()
            self.summary.setTextFormat(Qt.TextFormat.RichText)
            self.summary.setWordWrap(True)
            self.summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            layout.addWidget(self.summary)
            layout.addWidget(heading('Installed mods', 12))
            layout.addWidget(muted('Tick a mod to switch it on. The client\'s launcher has the same '
                                   'list (Mods tab) and sets the load order.'))
            self.mods = QTreeWidget()
            self.mods.setHeaderLabels(['Mod', 'Version', 'Author', 'Folder'])
            self.mods.setRootIsDecorated(False)
            self.mods.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
            self.mods.itemChanged.connect(self.toggled)
            layout.addWidget(self.mods, 1)
            self.filling = False

        def refresh(self) -> None:
            client = self.main.settings.client
            status = sdkhome.client_status(client) if client else None
            self.main.client_status = status
            if status is None or not status.is_client:
                self.summary.setText(f'{check_mark(False)} No client chosen, or the folder is not a '
                                     'BOZ Redux client. Click <b>Change folder</b>.')
                self.launch.setEnabled(False)
                self.mods.clear()
                return
            self.launch.setEnabled(sdkhome.launcher_command(status.root) is not None)
            lines = [f'<b>Folder:</b> {html.escape(str(status.root))}',
                     f'<b>Client:</b> {status.kind_label}',
                     f'{check_mark(status.image)} Game image (boz.s3e from your 1.0.11 APK)']
            lines += [f'{check_mark(ok)} {html.escape(name)}' for name, ok in status.packs.items()]
            if not status.game_ready:
                lines.append(f'<b style="color:#e0a040">⚠ {html.escape(MISSING_DATA)}</b>')
            if sdkhome.game_running():
                lines.append('The game is running.')
            self.summary.setText('<br>'.join(lines))
            self.filling = True
            self.mods.clear()
            for mod in status.mods:
                row = QTreeWidgetItem([mod.name, mod.version, mod.author, str(mod.folder)])
                row.setCheckState(0, Qt.CheckState.Checked if mod.enabled else Qt.CheckState.Unchecked)
                row.setToolTip(0, mod.description)
                row.setData(0, Qt.ItemDataRole.UserRole, mod.id)
                self.mods.addTopLevelItem(row)
            self.filling = False

        def toggled(self, item, column) -> None:
            if self.filling or column != 0:
                return
            enabled = item.checkState(0) == Qt.CheckState.Checked
            try:
                sdkhome.set_mod_enabled(Path(self.main.settings.client),
                                        item.data(0, Qt.ItemDataRole.UserRole), enabled)
            except OSError as exc:
                QMessageBox.warning(self, APP_NAME, f'client.ini could not be written: {exc}')

        def open_launcher(self) -> None:
            root = Path(self.main.settings.client)
            command = sdkhome.launcher_command(root)
            if command:
                sdkhome.start_detached(command, root)

    class LibraryWorker(QThread):
        progressed = Signal(float, str)
        done = Signal(str)  # empty on success, else the error

        def __init__(self, client: str) -> None:
            super().__init__()
            self.client = client
            self.stop = False

        def run(self) -> None:
            try:
                asset_library.build(self.client, progress=self.progressed.emit,
                                    cancelled=lambda: self.stop)
            except asset_library.Cancelled:
                self.done.emit('cancelled')
                return
            except Exception as exc:  # report anything; the old library stays in place
                self.done.emit(f'{type(exc).__name__}: {exc}')
                return
            self.done.emit('')

    class LibraryPage(QWidget):
        def __init__(self, window) -> None:
            super().__init__()
            self.main = window
            self.library: asset_library.Library | None = None
            layout = QVBoxLayout(self)
            top = QHBoxLayout()
            top.addWidget(heading('Library'))
            self.summary = muted('')
            top.addWidget(self.summary, 1)
            self.rebuild = button('Rebuild library', window.build_library,
                                  'Read your game files again and rebuild every preview')
            top.addWidget(self.rebuild)
            layout.addLayout(top)
            self.progress_row = QWidget()
            row = QHBoxLayout(self.progress_row)
            row.setContentsMargins(0, 0, 0, 0)
            self.progress = QProgressBar()
            self.progress.setRange(0, 1000)
            self.progress_text = muted('')
            row.addWidget(self.progress, 1)
            row.addWidget(self.progress_text, 2)
            row.addWidget(button('Cancel', window.cancel_library))
            layout.addWidget(self.progress_row)
            self.progress_row.hide()
            bar = QHBoxLayout()
            self.search = QLineEdit()
            self.search.setPlaceholderText('Search names, descriptions or 0x hashes')
            self.search.textChanged.connect(lambda *_: self.timer.start())
            self.kind = QComboBox()
            self.kind.addItem('Everything', '')
            for kind in asset_library.KINDS:
                self.kind.addItem(asset_library.KIND_LABELS[kind], kind)
            self.level = QComboBox()
            self.level.addItem('All maps', '')
            for name, label in maps.LABELS.items():
                self.level.addItem(label, name)
            self.level.addItem('Shared (every map)', 'shared')
            self.named = QCheckBox('Named only')
            for widget in (self.kind, self.level):
                widget.currentIndexChanged.connect(self.run_search)
            self.named.toggled.connect(self.run_search)
            bar.addWidget(self.search, 1)
            bar.addWidget(self.kind)
            bar.addWidget(self.level)
            bar.addWidget(self.named)
            layout.addLayout(bar)
            self.timer = QTimer(self)
            self.timer.setSingleShot(True)
            self.timer.setInterval(250)
            self.timer.timeout.connect(self.run_search)
            splitter = QSplitter()
            self.results = QListWidget()
            self.results.setViewMode(QListWidget.ViewMode.IconMode)
            self.results.setIconSize(QSize(96, 96))
            self.results.setGridSize(QSize(124, 136))
            self.results.setResizeMode(QListWidget.ResizeMode.Adjust)
            self.results.setMovement(QListWidget.Movement.Static)
            self.results.setUniformItemSizes(True)
            self.results.setWordWrap(True)
            self.results.currentItemChanged.connect(self.show_details)
            splitter.addWidget(self.results)
            details = QWidget()
            column = QVBoxLayout(details)
            self.preview = QLabel()
            self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.preview.setMinimumHeight(140)
            self.details = QLabel()
            self.details.setWordWrap(True)
            self.details.setTextFormat(Qt.TextFormat.RichText)
            self.details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.details.setAlignment(Qt.AlignmentFlag.AlignTop)
            copy_row = QHBoxLayout()
            self.copy_name = button('Copy name', lambda: self.copy('name'))
            self.copy_hash = button('Copy hash', lambda: self.copy('hash'))
            copy_row.addWidget(self.copy_name)
            copy_row.addWidget(self.copy_hash)
            column.addWidget(self.preview)
            column.addWidget(self.details, 1)
            column.addLayout(copy_row)
            details.setMinimumWidth(260)
            splitter.addWidget(details)
            splitter.setStretchFactor(0, 3)
            splitter.setStretchFactor(1, 1)
            layout.addWidget(splitter, 1)
            self.count = muted('')
            layout.addWidget(self.count)
            self.empty = muted('')
            layout.addWidget(self.empty)
            self.icons: dict[str, QIcon] = {}
            self.show_details(None)

        def refresh(self) -> None:
            if self.library is None:
                try:
                    self.library = asset_library.Library()
                except asset_library.LibraryError:
                    self.library = None
            building = self.main.library_worker is not None
            self.rebuild.setEnabled(not building and bool(self.main.client_status
                                                          and self.main.client_status.game_ready))
            if self.library is None:
                self.summary.setText('')
                self.results.clear()
                self.empty.setText(
                    'The library is being built from your game files.' if building else
                    'No library yet. It is built from your own game files: install them in the '
                    'client (Client page), then click Rebuild library.')
                self.empty.show()
                return
            self.empty.hide()
            counts = self.library.counts()
            info = self.library.info()
            self.summary.setText(', '.join(f'{counts.get(kind, 0)} {asset_library.KIND_LABELS[kind].lower()}'
                                           for kind in asset_library.KINDS)
                                 + f' · built {info.get("built", "?")}')
            self.run_search()

        def close_library(self) -> None:
            if self.library is not None:
                self.library.close()
                self.library = None
            self.icons.clear()

        def icon(self, asset) -> QIcon:
            path = self.library.thumb_path(asset) if self.library else None
            if path is None:
                return kind_icon('', 96)
            key = str(path)
            if key not in self.icons:
                self.icons[key] = QIcon(key)
            return self.icons[key]

        def run_search(self, *_args) -> None:
            if self.library is None:
                return
            found = self.library.search(self.search.text(), self.kind.currentData() or '',
                                        self.level.currentData() or '', self.named.isChecked(),
                                        limit=600)
            self.results.clear()
            for asset in found:
                item = QListWidgetItem(self.icon(asset), asset.title)
                item.setToolTip(f'{asset.title}\n{asset.details}' if asset.details else asset.title)
                item.setData(Qt.ItemDataRole.UserRole, asset)
                self.results.addItem(item)
            self.count.setText('Showing the first 600 matches: search to narrow them down'
                               if len(found) == 600 else f'{len(found)} matches')

        def show_details(self, item, _previous=None) -> None:
            asset = item.data(Qt.ItemDataRole.UserRole) if item else None
            self.copy_name.setEnabled(bool(asset and asset.name))
            self.copy_hash.setEnabled(asset is not None)
            if asset is None:
                self.preview.clear()
                self.details.setText('<i>Select an asset to see its details.</i>')
                return
            path = self.library.thumb_path(asset)
            self.preview.setPixmap(QPixmap(str(path)) if path else QPixmap())
            maps = ', '.join(maps.LABELS.get(name, 'Shared') for name in asset.maps)
            rows = [f'<b>{html.escape(asset.title)}</b>',
                    asset_library.KIND_LABELS[asset.kind][:-1],
                    f'Name: {html.escape(asset.name) if asset.name else "<i>not stored in the game</i>"}',
                    f'Hash: {asset.hash_text}']
            if asset.details:
                rows.append(html.escape(asset.details))
            if asset.width:
                rows.append(f'Size: {asset.width} × {asset.height}')
            if asset.triangles:
                rows.append(f'Triangles: {asset.triangles}')
            rows.append(f'Maps: {html.escape(maps)}')
            rows.append('Groups:<br>' + '<br>'.join(html.escape(g) for g in asset.groups[:8])
                        + ('<br>…' if len(asset.groups) > 8 else ''))
            self.details.setText('<br>'.join(rows))

        def copy(self, what: str) -> None:
            from PySide6.QtWidgets import QApplication
            item = self.results.currentItem()
            asset = item.data(Qt.ItemDataRole.UserRole) if item else None
            if asset is not None:
                QApplication.clipboard().setText(asset.name if what == 'name' else asset.hash_text)
                self.main.statusBar().showMessage('Copied', 2000)

        def show_progress(self, fraction: float, message: str) -> None:
            self.progress_row.show()
            self.progress.setValue(int(fraction * 1000))
            self.progress_text.setText(message)

    def placeholder_page(title: str, text: str, items: list[str]) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(heading(title))
        layout.addWidget(muted(text))
        for item in items:
            layout.addWidget(QLabel('•  ' + item))
        layout.addStretch(1)
        return page

    class LearnPage(QWidget):
        def __init__(self, window) -> None:
            super().__init__()
            layout = QVBoxLayout(self)
            layout.addWidget(heading('Learn'))
            layout.addWidget(muted('Guides and references for making mods, and the SDK\'s own mods '
                                   'to read as examples.'))
            grid = QGridLayout()
            docs = sdkhome.sdk_root() / 'docs'
            entries = [('Making mods (guide)', docs / 'making-mods.md'),
                       ('Standard library (boz.*)', docs / 'standard-library.md'),
                       ('Client Lua API', docs / 'lua-api.md'),
                       ('Console commands and variables', docs / 'console-reference.md')]
            for row, (label, path) in enumerate(entries):
                grid.addWidget(QLabel(label), row, 0)
                grid.addWidget(button('Open', lambda _=False, p=path: open_path(p),
                                      enabled=path.is_file()), row, 1)
            layout.addLayout(grid)
            layout.addWidget(heading('Example mods', 12))
            examples = QGridLayout()
            mods = sdkhome.sdk_root() / 'mods'
            for row, (label, text, folder) in enumerate([
                    ('Developer', 'The console overlay, cheats and noclip', mods / 'developer')]):
                examples.addWidget(QLabel(f'<b>{label}</b> — {text}'), row, 0)
                examples.addWidget(button('Open', lambda _=False, f=folder: self.open_example(f),
                                          enabled=folder.is_dir()), row, 1)
            layout.addLayout(examples)
            layout.addWidget(muted('Examples are the SDK\'s own copies: read them, but make your '
                                   'changes in a project of your own.'))
            layout.addStretch(1)

        def open_example(self, folder: Path) -> None:
            command = sdkhome.external_editor_command(folder)
            if command:
                sdkhome.start_detached(command, folder)
            else:
                open_path(folder)

    class SettingsPage(QWidget):
        def __init__(self, window) -> None:
            super().__init__()
            self.main = window
            layout = QVBoxLayout(self)
            layout.addWidget(heading('Settings'))
            form = QFormLayout()
            client = QHBoxLayout()
            self.client = QLabel()
            self.client.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            client.addWidget(self.client, 1)
            client.addWidget(button('Change…', window.choose_client))
            form.addRow('Client folder', client)
            projects = QHBoxLayout()
            self.projects = QLineEdit()
            self.projects.editingFinished.connect(self.save)
            projects.addWidget(self.projects, 1)
            projects.addWidget(button('Browse…', self.browse_projects))
            form.addRow('New projects go in', projects)
            self.author = QLineEdit()
            self.author.editingFinished.connect(self.save)
            form.addRow('Default author', self.author)
            blender_row = QHBoxLayout()
            self.blender = QLineEdit()
            self.blender.setPlaceholderText('Automatic: the SDK\'s own Blender, else blender on PATH')
            self.blender.editingFinished.connect(self.save)
            blender_row.addWidget(self.blender, 1)
            blender_row.addWidget(button('Browse…', self.browse_blender))
            form.addRow('Editor (Blender)', blender_row)
            data = QLabel(str(sdkhome.data_dir()))
            data.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            form.addRow('SDK data folder', data)
            library_row = QHBoxLayout()
            library_row.addWidget(QLabel(str(asset_library.library_dir())), 1)
            self.rebuild = button('Rebuild library', window.build_library)
            library_row.addWidget(self.rebuild)
            form.addRow('Asset library', library_row)
            layout.addLayout(form)
            layout.addStretch(1)

        def refresh(self) -> None:
            settings = self.main.settings
            self.rebuild.setEnabled(self.main.library_worker is None and bool(
                self.main.client_status and self.main.client_status.game_ready))
            self.client.setText(settings.client or 'Not chosen')
            self.projects.setText(str(settings.projects_folder()))
            self.author.setText(settings.author)
            self.blender.setText(settings.blender)

        def browse_projects(self) -> None:
            chosen = QFileDialog.getExistingDirectory(self, 'Where new projects go',
                                                      self.projects.text())
            if chosen:
                self.projects.setText(chosen)
                self.save()

        def browse_blender(self) -> None:
            chosen, _ = QFileDialog.getOpenFileName(self, 'Blender 5.2', str(Path.home()))
            if chosen:
                self.blender.setText(chosen)
                self.save()

        def save(self) -> None:
            self.main.settings.projects_dir = self.projects.text().strip()
            self.main.settings.author = self.author.text().strip()
            self.main.settings.blender = self.blender.text().strip()
            self.main.settings.save()

    # The window

    class Window(QMainWindow):
        def __init__(self) -> None:
            super().__init__()
            self.setWindowTitle(APP_NAME)
            self.resize(1100, 720)
            self.settings = sdkhome.Settings.load()
            self.client_status: sdkhome.ClientStatus | None = None
            self.library_worker = None
            central = QWidget()
            outer = QHBoxLayout(central)
            self.nav = QListWidget()
            self.nav.setFixedWidth(170)
            self.nav.setIconSize(QSize(20, 20))
            self.stack = QStackedWidget()
            self.projects = ProjectsPage(self)
            self.project_page = ProjectPage(self)
            self.client_page = ClientPage(self)
            self.settings_page = SettingsPage(self)
            self.library_page = LibraryPage(self)
            pages = [
                ('Projects', self.projects),
                ('Client', self.client_page),
                ('Library', self.library_page),
                ('Learn', LearnPage(self)),
                ('Settings', self.settings_page),
            ]
            for label, page in pages:
                self.nav.addItem(label)
                self.stack.addWidget(page)
            self.stack.addWidget(self.project_page)
            self.nav.currentRowChanged.connect(self.nav_changed)
            outer.addWidget(self.nav)
            outer.addWidget(self.stack, 1)
            self.setCentralWidget(central)
            self.statusBar()
            self.status_progress = QProgressBar()
            self.status_progress.setRange(0, 1000)
            self.status_progress.setMaximumWidth(220)
            self.status_progress.hide()
            self.statusBar().addPermanentWidget(self.status_progress)

        def start(self) -> None:
            if self.settings.first_run:
                self.choose_client(first_run=True)
            self.refresh_all()
            self.nav.setCurrentRow(0)
            self.build_library_if_needed()

        def build_library_if_needed(self) -> None:
            status = self.client_status
            if status and status.game_ready and asset_library.needs_build(status.root):
                self.build_library()

        def build_library(self) -> None:
            status = self.client_status
            if self.library_worker is not None or not status or not status.game_ready:
                return
            self.library_page.close_library()
            worker = self.library_worker = LibraryWorker(str(status.root))
            worker.progressed.connect(self.library_progress)
            worker.done.connect(self.library_done)
            self.status_progress.show()
            self.library_progress(0.0, 'Building the asset library from your game files')
            worker.start()
            self.library_page.refresh()
            self.settings_page.refresh()

        def cancel_library(self) -> None:
            if self.library_worker is not None:
                self.library_worker.stop = True

        def library_progress(self, fraction: float, message: str) -> None:
            self.status_progress.setValue(int(fraction * 1000))
            self.statusBar().showMessage(f'Asset library: {message}')
            self.library_page.show_progress(fraction, message)

        def library_done(self, error: str) -> None:
            self.library_worker.wait()
            self.library_worker = None
            self.status_progress.hide()
            self.library_page.progress_row.hide()
            if error == 'cancelled':
                self.statusBar().showMessage('Asset library build cancelled', 6000)
            elif error:
                self.statusBar().showMessage('The asset library could not be built', 10000)
                QMessageBox.warning(self, 'Asset library', f'The library could not be built:\n{error}')
            else:
                self.statusBar().showMessage('Asset library ready', 6000)
            self.library_page.refresh()
            self.settings_page.refresh()

        def library_maps(self) -> dict:
            try:
                built = asset_library.Library()
            except asset_library.LibraryError:
                return {}
            try:
                return {item.name: built.thumb_path(item) for item in built.maps()}
            finally:
                built.close()

        def closeEvent(self, event) -> None:
            if self.library_worker is not None:
                self.library_worker.stop = True
                self.library_worker.wait()
            super().closeEvent(event)

        def nav_changed(self, row: int) -> None:
            if row < 0:
                return
            self.stack.setCurrentIndex(row)
            page = self.stack.currentWidget()
            if hasattr(page, 'refresh'):
                page.refresh()

        def refresh_all(self) -> None:
            self.client_page.refresh()
            self.projects.refresh()
            self.settings_page.refresh()
            status = self.client_status
            if status is None or not status.is_client:
                self.statusBar().showMessage('No client chosen: Settings → Client folder')
            elif not status.game_ready:
                self.statusBar().showMessage('⚠ ' + MISSING_DATA)
            else:
                self.statusBar().showMessage(f'Client ready: {status.root}')

        def choose_client(self, first_run: bool = False) -> None:
            dialog = WelcomeDialog(self, self.settings)
            if not first_run:
                dialog.setWindowTitle('Client folder')
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self.settings.client = dialog.chosen()
                self.settings.save()
                self.refresh_all()
                if not first_run:
                    self.build_library_if_needed()

        def show_projects(self) -> None:
            self.nav.setCurrentRow(0)
            self.stack.setCurrentWidget(self.projects)
            self.projects.refresh()

        def open_project(self, project: sdk_project.Project) -> None:
            self.settings.add_project(project.root)
            self.settings.save()
            self.nav.clearSelection()
            self.nav.setCurrentRow(-1)
            self.project_page.show_project(project)
            self.stack.setCurrentWidget(self.project_page)

        def new_project(self) -> None:
            ready = bool(self.client_status and self.client_status.game_ready)
            dialog = NewProjectDialog(self, self.settings, ready,
                                      self.library_maps() if self.library_worker is None else {})
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self.settings.add_project(dialog.created.root)
                self.settings.save()
                self.open_project(dialog.created)

        def add_existing(self) -> None:
            chosen = QFileDialog.getExistingDirectory(self, 'Choose a project folder',
                                                      str(self.settings.projects_folder()))
            if not chosen:
                return
            try:
                loaded = sdk_project.load_project(chosen)
            except sdk_project.ProjectError as exc:
                QMessageBox.warning(self, 'Add existing project', str(exc))
                return
            self.settings.add_project(loaded.root, opened=False)
            self.settings.save()
            self.projects.refresh()

        def duplicate(self, listed: sdkhome.ListedProject | None) -> None:
            if listed is None or listed.project is None:
                return
            source = listed.project
            name, ok = QInputDialog.getText(self, 'Duplicate project', 'Name of the copy',
                                            text=f'{source.mod.name} copy')
            if not ok or not name.strip():
                return
            mod_id = sdkhome.suggest_id(name)
            target = source.root.parent / mod_id
            try:
                copied = sdkhome.duplicate_project(source, target, mod_id, name.strip())
            except (OSError, sdk_project.ProjectError) as exc:
                QMessageBox.warning(self, 'Duplicate project', str(exc))
                return
            self.settings.add_project(copied.root, opened=False)
            self.settings.save()
            self.projects.refresh()
            self.statusBar().showMessage(f'Copied to {copied.root}', 6000)

        def rename(self, listed: sdkhome.ListedProject | None) -> None:
            if listed is None or listed.project is None:
                return
            source = listed.project
            dialog = QDialog(self)
            dialog.setWindowTitle('Rename project')
            form = QFormLayout(dialog)
            name = QLineEdit(source.mod.name)
            move = QCheckBox(f'Also rename the folder ({source.root.name})')
            form.addRow('Name', name)
            form.addRow('', move)
            form.addRow(muted('The mod id stays the same, so saves and settings keep working.'))
            buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                       | QDialogButtonBox.StandardButton.Cancel)
            buttons.accepted.connect(dialog.accept)
            buttons.rejected.connect(dialog.reject)
            form.addRow(buttons)
            if dialog.exec() != QDialog.DialogCode.Accepted or not name.text().strip():
                return
            folder = source.root.parent / sdkhome.suggest_id(name.text()) if move.isChecked() else None
            try:
                renamed = sdkhome.rename_project(source, name.text().strip(), folder)
            except (OSError, sdk_project.ProjectError) as exc:
                QMessageBox.warning(self, 'Rename project', str(exc))
                return
            if renamed.root != source.root:
                entry = self.settings.entry(source.root)
                if entry:
                    entry.path = renamed.root
            self.settings.save()
            self.projects.refresh()

        def delete(self, listed: sdkhome.ListedProject | None) -> None:
            if listed is None:
                return
            path = listed.entry.path
            answer = QMessageBox.question(
                self, 'Delete project',
                f'Move "{listed.name}" to the trash?\n\n{path}\n\nYou can restore it from the '
                'trash later.')
            if answer != QMessageBox.StandardButton.Yes:
                return
            if path.exists() and not QFile.moveToTrash(str(path)):
                QMessageBox.warning(self, 'Delete project',
                                    'The folder could not be moved to the trash.')
                return
            self.settings.remove_project(path)
            self.settings.save()
            self.projects.refresh()

        def forget(self, listed: sdkhome.ListedProject | None) -> None:
            if listed is None:
                return
            self.settings.remove_project(listed.entry.path)
            self.settings.save()
            self.projects.refresh()

    return Window()


if __name__ == '__main__':
    raise SystemExit(main())
