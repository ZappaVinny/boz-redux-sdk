"""Small PySide6 frontend for the shared BOZ SDK project compiler."""
from __future__ import annotations

import sys
from pathlib import Path

from .project import (ProjectError, build_project, create_project, install_project, load_project,
                      validate_project)


def main() -> int:
    """Start the SDK project window; PySide6 is an optional dependency."""
    try:
        from PySide6.QtCore import QSettings
        from PySide6.QtWidgets import (QApplication, QDialog, QDialogButtonBox, QFileDialog,
                                       QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
                                       QMessageBox, QPushButton, QPlainTextEdit, QVBoxLayout,
                                       QWidget)
    except ImportError:
        print('PySide6 is required for the desktop SDK: pip install -e ".[desktop]"', file=sys.stderr)
        return 1

    class Window(QMainWindow):
        def __init__(self) -> None:
            super().__init__()
            self.setWindowTitle('BOZ Redux SDK')
            self.resize(760, 480)
            self.settings = QSettings('BOZ Redux', 'SDK')
            central = QWidget()
            layout = QVBoxLayout(central)
            layout.addWidget(QLabel('Project folder'))
            project_row = QHBoxLayout()
            self.project = QLineEdit(self.settings.value('project', str(Path.cwd())))
            new_project = QPushButton('Create Project…')
            new_project.clicked.connect(self.new_project)
            choose_project = QPushButton('Open Existing…')
            choose_project.clicked.connect(self.browse_project)
            project_row.addWidget(self.project)
            project_row.addWidget(new_project)
            project_row.addWidget(choose_project)
            layout.addLayout(project_row)
            layout.addWidget(QLabel('Client root (folder containing mods/)'))
            client_row = QHBoxLayout()
            self.client = QLineEdit(self.settings.value('client', ''))
            choose_client = QPushButton('Browse…')
            choose_client.clicked.connect(self.browse_client)
            client_row.addWidget(self.client)
            client_row.addWidget(choose_client)
            layout.addLayout(client_row)
            actions = QHBoxLayout()
            for label, callback in (('Inspect / Validate', self.validate), ('Build', self.build),
                                    ('Install', self.install)):
                button = QPushButton(label)
                button.clicked.connect(callback)
                actions.addWidget(button)
            layout.addLayout(actions)
            self.log = QPlainTextEdit()
            self.log.setReadOnly(True)
            layout.addWidget(self.log)
            self.setCentralWidget(central)

        def browse_project(self) -> None:
            chosen = QFileDialog.getExistingDirectory(self, 'Choose SDK project', self.project.text())
            if chosen:
                self.project.setText(chosen)

        def new_project(self) -> None:
            destination = QFileDialog.getExistingDirectory(
                self, 'Choose an empty folder for the new project', self.project.text())
            if not destination:
                return
            folder_name = Path(destination).name.lower()
            suggested_id = ''.join(char if char.isalnum() or char in '_-' else '_'
                                   for char in folder_name).strip('_')
            if suggested_id and suggested_id[0].isdigit():
                suggested_id = 'mod_' + suggested_id

            dialog = QDialog(self)
            dialog.setWindowTitle('Create BOZ Redux Project')
            dialog.setMinimumSize(560, 390)
            dialog.resize(640, 430)
            form = QFormLayout(dialog)
            form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
            mod_id = QLineEdit(suggested_id)
            name = QLineEdit(Path(destination).name)
            author = QLineEdit(self.settings.value('author', ''))
            version = QLineEdit('0.1.0')
            game = QLabel('1.0.11')
            description = QPlainTextEdit()
            description.setPlaceholderText('What this mod changes or adds')
            description.setMinimumHeight(110)
            for field in (mod_id, name, author, version):
                field.setMinimumWidth(390)
            form.addRow('Mod id', mod_id)
            form.addRow('Display name', name)
            form.addRow('Author', author)
            form.addRow('Version', version)
            form.addRow('Game version', game)
            form.addRow('Description', description)
            buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            buttons.accepted.connect(dialog.accept)
            buttons.rejected.connect(dialog.reject)
            form.addRow(buttons)
            if dialog.exec() != QDialog.Accepted:
                return
            try:
                created = create_project(destination, mod_id.text().strip(), name.text().strip(),
                                         author.text().strip(), version.text().strip(),
                                         description.toPlainText().strip())
                self.settings.setValue('author', author.text().strip())
                self.project.setText(str(created.root))
                self.validate()
            except (OSError, ProjectError) as exc:
                self.show_error(exc)

        def browse_client(self) -> None:
            chosen = QFileDialog.getExistingDirectory(self, 'Choose BOZ Redux client', self.client.text())
            if chosen:
                self.client.setText(chosen)

        def current_project(self):
            self.settings.setValue('project', self.project.text())
            self.settings.setValue('client', self.client.text())
            return load_project(self.project.text())

        def show_error(self, exc: Exception) -> None:
            self.log.appendPlainText(f'ERROR: {exc}')
            QMessageBox.critical(self, 'BOZ Redux SDK', str(exc))

        def validate(self) -> None:
            try:
                project = self.current_project()
                result = validate_project(project)
                assets = (sorted(p.relative_to(project.assets).as_posix()
                                 for p in project.assets.rglob('*') if p.is_file())
                          if project.assets.is_dir() else [])
                self.log.setPlainText(
                    f'{project.mod.name} {project.mod.version} ({project.mod.id})\n'
                    + f'Assets: {len(assets)}\n'
                    + ''.join(f'  {item}\n' for item in assets)
                    + '\n'.join(f'ERROR: {item}' for item in result.errors)
                    + ('\n' if result.errors else '')
                    + '\n'.join(f'WARNING: {item}' for item in result.warnings)
                    + f'\nResult: {"valid" if result.ok else "invalid"}')
            except (OSError, ProjectError) as exc:
                self.show_error(exc)

        def build(self) -> None:
            try:
                output, report = build_project(self.current_project())
                self.log.setPlainText(f'Built {len(report["files"])} files\n{output}')
            except (OSError, ProjectError) as exc:
                self.show_error(exc)

        def install(self) -> None:
            try:
                output = install_project(self.current_project(), self.client.text(), force=True)
                self.log.setPlainText(f'Installed\n{output}')
            except (OSError, ProjectError) as exc:
                self.show_error(exc)

    app = QApplication(sys.argv)
    window = Window()
    window.show()
    return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
