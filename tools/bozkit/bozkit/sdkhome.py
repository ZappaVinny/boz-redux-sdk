"""The launcher's model: SDK settings, the project list, and the BOZ Redux client it works with.

No Qt here, so it can be tested and reused (the Blender suite reads the same settings).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from . import project as sdk_project

SETTINGS_FILE = 'settings.json'
# The data packs the client needs, with their sizes (runtime/src/launcher/game_files.cpp).
PACKS = {'blackops_etc.dz': 487603915, 'blackops_gles1.dz': 337594086}
DEVELOPER_MOD = 'developer'


def data_dir() -> Path:
    """Where the SDK keeps its settings and the asset library (BOZ_SDK_HOME overrides it)."""
    override = os.environ.get('BOZ_SDK_HOME')
    if override:
        return Path(override)
    if sys.platform == 'win32':
        return Path(os.environ.get('APPDATA', Path.home())) / 'BOZ Redux SDK'
    if sys.platform == 'darwin':
        return Path.home() / 'Library' / 'Application Support' / 'BOZ Redux SDK'
    return Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local' / 'share')) / 'boz-redux-sdk'


def sdk_root() -> Path:
    """The SDK folder: BOZ_SDK_ROOT (set for the editor), the release folder next to the
    launcher, or the repository checkout."""
    if os.environ.get('BOZ_SDK_ROOT'):
        return Path(os.environ['BOZ_SDK_ROOT'])
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent
    return sdk_project.SDK_ROOT


def default_projects_dir() -> Path:
    return Path.home() / 'BOZ Projects'


# Settings and the project list


@dataclass
class ProjectEntry:
    path: Path
    last_opened: float = 0.0


@dataclass
class Settings:
    client: str = ''
    author: str = ''
    projects_dir: str = ''
    projects: list[ProjectEntry] = field(default_factory=list)
    blender: str = ''        # the editor's Blender; empty: the SDK's own, else blender on PATH

    @classmethod
    def load(cls) -> 'Settings':
        try:
            data = json.loads((data_dir() / SETTINGS_FILE).read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return cls()
        entries = [ProjectEntry(Path(item['path']), float(item.get('last_opened', 0)))
                   for item in data.get('projects', []) if isinstance(item, dict) and item.get('path')]
        return cls(str(data.get('client', '')), str(data.get('author', '')),
                   str(data.get('projects_dir', '')), entries, str(data.get('blender', '')))

    def save(self) -> None:
        folder = data_dir()
        folder.mkdir(parents=True, exist_ok=True)
        data = {'client': self.client, 'author': self.author, 'projects_dir': self.projects_dir,
                'blender': self.blender,
                'projects': [{'path': str(entry.path), 'last_opened': entry.last_opened}
                             for entry in self.projects]}
        temporary = folder / (SETTINGS_FILE + '.tmp')
        temporary.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')
        temporary.replace(folder / SETTINGS_FILE)

    @property
    def first_run(self) -> bool:
        return not self.client

    def projects_folder(self) -> Path:
        return Path(self.projects_dir) if self.projects_dir else default_projects_dir()

    def entry(self, path: Path) -> ProjectEntry | None:
        resolved = Path(path).resolve()
        return next((entry for entry in self.projects if entry.path.resolve() == resolved), None)

    def add_project(self, path: Path, opened: bool = True) -> ProjectEntry:
        entry = self.entry(path)
        if entry is None:
            entry = ProjectEntry(Path(path).resolve())
            self.projects.append(entry)
        if opened:
            entry.last_opened = time.time()
        return entry

    def remove_project(self, path: Path) -> None:
        resolved = Path(path).resolve()
        self.projects = [entry for entry in self.projects if entry.path.resolve() != resolved]


@dataclass
class ListedProject:
    """A project in the list: loaded, or with the reason it could not be."""
    entry: ProjectEntry
    project: sdk_project.Project | None = None
    error: str = ''

    @property
    def name(self) -> str:
        return self.project.mod.name if self.project else self.entry.path.name

    @property
    def kind(self) -> str:
        return self.project.kind if self.project else ''

    @property
    def icon(self) -> Path | None:
        if self.project is None:
            return None
        for name in ('icon.png', 'thumbnail.png'):
            candidate = self.project.root / name
            if candidate.is_file():
                return candidate
        return None


def list_projects(settings: Settings) -> list[ListedProject]:
    listed = []
    for entry in settings.projects:
        try:
            listed.append(ListedProject(entry, sdk_project.load_project(entry.path)))
        except sdk_project.ProjectError as exc:
            listed.append(ListedProject(entry, error=str(exc)))
    return listed


def suggest_id(name: str) -> str:
    """A valid mod id made from a display name."""
    text = re.sub(r'[^a-z0-9_-]+', '_', name.lower()).strip('_-')
    if not text:
        return 'my_mod'
    return text if text[0].isalpha() else 'mod_' + text


# Project operations


def _manifest_data(project: sdk_project.Project) -> dict:
    data = json.loads(json.dumps(project.data))  # deep copy
    data['schema'] = sdk_project.PROJECT_SCHEMA
    data.setdefault('project', {})['kind'] = project.kind
    return data


def update_metadata(project: sdk_project.Project, **mod_fields: str) -> sdk_project.Project:
    """Change [mod] fields (name, version, author, description) and rewrite the manifest."""
    allowed = {'name', 'version', 'author', 'description'}
    unknown = set(mod_fields) - allowed
    if unknown:
        raise sdk_project.ProjectError(f'cannot change {", ".join(sorted(unknown))}')
    if not all(mod_fields.get(key, 'x') for key in ('name', 'version', 'author')):
        raise sdk_project.ProjectError('mod name, author and version are required')
    data = _manifest_data(project)
    data['mod'].update(mod_fields)
    return sdk_project.save_manifest(project.root, data)


def rename_project(project: sdk_project.Project, name: str,
                   folder: Path | None = None) -> sdk_project.Project:
    """Give the project a new display name and, if *folder* is given, move it there."""
    renamed = update_metadata(project, name=name)
    if folder is None or Path(folder).resolve() == project.root.resolve():
        return renamed
    folder = Path(folder).resolve()
    if folder.exists():
        raise sdk_project.ProjectError(f'{folder} already exists')
    shutil.move(str(project.root), str(folder))
    return sdk_project.load_project(folder)


def duplicate_project(project: sdk_project.Project, destination: Path, mod_id: str,
                      name: str) -> sdk_project.Project:
    """Copy a project (without its build output) under a new id and name."""
    if not sdk_project.ID_RE.fullmatch(mod_id):
        raise sdk_project.ProjectError(
            'mod id must start with a lower-case letter and contain only a-z, 0-9, _ or -')
    destination = Path(destination).resolve()
    if destination.exists() and any(destination.iterdir()):
        raise sdk_project.ProjectError(f'directory is not empty: {destination}')
    if destination == project.root or project.root in destination.parents:
        raise sdk_project.ProjectError('a copy cannot go inside the project it copies')
    shutil.copytree(project.root, destination, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns('build', '__pycache__'))
    data = _manifest_data(project)
    data['mod'].update(id=mod_id, name=name)
    if 'map' in data:
        data['map']['name'] = mod_id.replace('-', '_')
    return sdk_project.save_manifest(destination, data)


def external_editor_command(folder: Path) -> list[str] | None:
    """VS Code on the folder if it is installed; None means the system's default handler."""
    for name in ('code', 'codium', 'code-oss'):
        found = shutil.which(name)
        if found:
            return [found, str(folder)]
    return None


# The client


@dataclass
class ClientMod:
    id: str
    name: str
    version: str
    author: str
    description: str
    folder: Path
    enabled: bool


@dataclass
class ClientStatus:
    root: Path
    kind: str = ''               # 'release', 'checkout' or '' (not a client)
    image: bool = False          # the game image is installed (assets/boz.s3e.unpacked)
    packs: dict[str, bool] = field(default_factory=dict)
    mods: list[ClientMod] = field(default_factory=list)

    @property
    def is_client(self) -> bool:
        return bool(self.kind)

    @property
    def game_ready(self) -> bool:
        return self.image and all(self.packs.values())

    @property
    def missing(self) -> list[str]:
        missing = [] if self.image else ['the game image (boz.s3e, from your APK)']
        return missing + [name for name, present in self.packs.items() if not present]

    @property
    def kind_label(self) -> str:
        return {'release': 'Release', 'checkout': 'Development checkout'}.get(self.kind,
                                                                             'Not a BOZ Redux client')


def _launcher_names() -> tuple[str, ...]:
    return ('boz-redux.exe', 'boz-redux') if sys.platform == 'win32' else ('boz-redux',)


def client_kind(root: Path) -> str:
    """'release' (an unpacked client download), 'checkout' (the boz-redux repo) or ''."""
    root = Path(root)
    if (root / 'runtime' / 'scripts' / 'run-launcher.sh').is_file():
        return 'checkout'
    if any((root / name).is_file() for name in _launcher_names()):
        return 'release'
    return ''


def _ini_lines(root: Path) -> list[str]:
    try:
        return (Path(root) / 'client.ini').read_text(encoding='utf-8').splitlines()
    except OSError:
        return []


def ini_get(root: Path, section: str, key: str) -> str:
    current = ''
    for line in _ini_lines(root):
        text = line.strip()
        if text.startswith('[') and text.endswith(']'):
            current = text[1:-1].strip()
        elif current == section and '=' in text and not text.startswith(('#', ';')):
            name, value = text.split('=', 1)
            if name.strip() == key:
                return value.strip()
    return ''


def ini_set(root: Path, section: str, key: str, value: str) -> None:
    """Set one client.ini value in place, keeping comments and everything else."""
    lines = _ini_lines(root)
    current, section_end, found = '', None, False
    for index, line in enumerate(lines):
        text = line.strip()
        if text.startswith('[') and text.endswith(']'):
            if current == section and section_end is None:
                section_end = index
            current = text[1:-1].strip()
        elif current == section and '=' in text and not text.startswith(('#', ';')):
            if text.split('=', 1)[0].strip() == key:
                lines[index] = f'{key} = {value}'
                found = True
                break
    if not found:
        if current == section and section_end is None:
            section_end = len(lines)
        if section_end is None:
            lines += ([''] if lines and lines[-1].strip() else []) + [f'[{section}]']
            section_end = len(lines)
        while section_end > 0 and not lines[section_end - 1].strip():
            section_end -= 1
        lines.insert(section_end, f'{key} = {value}')
    (Path(root) / 'client.ini').write_text('\n'.join(lines) + '\n', encoding='utf-8')


def _id_list(text: str) -> list[str]:
    return [item.strip() for item in text.split(',') if item.strip()]


def client_mods(root: Path) -> list[ClientMod]:
    """The mods in the client's mods/ folder, in the client's load order."""
    root = Path(root)
    disabled = set(_id_list(ini_get(root, 'mods', 'disabled')))
    order = _id_list(ini_get(root, 'mods', 'order'))
    mods = []
    folder = root / 'mods'
    for item in sorted(folder.iterdir()) if folder.is_dir() else ():
        manifest = item / 'mod.toml'
        if not manifest.is_file():
            continue
        try:
            data = tomllib.loads(manifest.read_text(encoding='utf-8'))
        except (OSError, tomllib.TOMLDecodeError):
            data = {}
        mod_id = str(data.get('id') or item.name)
        mods.append(ClientMod(mod_id, str(data.get('name') or mod_id), str(data.get('version', '')),
                              str(data.get('author', '')), str(data.get('description', '')),
                              item, mod_id not in disabled))
    mods.sort(key=lambda mod: (order.index(mod.id) if mod.id in order else len(order), mod.id))
    return mods


def set_mod_enabled(root: Path, mod_id: str, enabled: bool) -> None:
    disabled = [item for item in _id_list(ini_get(root, 'mods', 'disabled')) if item != mod_id]
    if not enabled:
        disabled.append(mod_id)
    ini_set(root, 'mods', 'disabled', ', '.join(disabled))


def client_status(root: str | Path) -> ClientStatus:
    root = Path(root).expanduser()
    status = ClientStatus(root, client_kind(root))
    if not status.is_client:
        return status
    assets = root / 'assets'
    status.image = (assets / 'boz.s3e.unpacked').exists()
    for name, size in PACKS.items():
        try:
            status.packs[name] = (assets / name).stat().st_size == size
        except OSError:
            status.packs[name] = False
    status.mods = client_mods(root)
    return status


def launcher_command(root: Path) -> list[str] | None:
    """The command that opens the client's own launcher."""
    root = Path(root)
    script = root / 'runtime' / 'scripts' / 'run-launcher.sh'
    if script.is_file():
        return ['bash', str(script)]
    for name in _launcher_names():
        if (root / name).is_file():
            return [str(root / name)]
    return None


def game_command(root: Path) -> list[str] | None:
    """The command that starts the game itself (no launcher)."""
    root = Path(root)
    script = root / 'runtime' / 'scripts' / 'run-desktop.sh'
    if script.is_file():
        return ['bash', str(script), str(root)]
    for name in ('codboz_s3e_loader.exe', 'codboz_s3e_loader'):
        loader = root / name
        if loader.is_file():
            return [str(loader), '--root', str(root), '--run',
                    str(root / 'assets' / 'boz.s3e.unpacked')]
    return None


def start_detached(command: list[str], cwd: Path, log: Path | None = None,
                   env: dict | None = None) -> subprocess.Popen:
    output = open(log, 'w') if log else subprocess.DEVNULL
    options = {'creationflags': 0x00000008} if sys.platform == 'win32' else {'start_new_session': True}
    return subprocess.Popen(command, cwd=cwd, stdout=output, stderr=subprocess.STDOUT,
                            stdin=subprocess.DEVNULL, env=env, **options)


def game_running() -> bool:
    if sys.platform == 'win32':
        result = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq codboz_s3e_loader.exe'],
                                capture_output=True, text=True)
        return 'codboz_s3e_loader' in result.stdout
    if not shutil.which('pgrep'):
        return False
    return subprocess.run(['pgrep', '-f', 'codboz_s3e_loader'], capture_output=True).returncode == 0


def ensure_developer_mod(root: Path) -> Path | None:
    """Install the SDK's Developer mod into the client if it is missing; returns its folder."""
    target = Path(root) / 'mods' / DEVELOPER_MOD
    if (target / 'mod.toml').is_file():
        return target
    source = sdk_root() / 'mods' / DEVELOPER_MOD
    if not (source / 'mod.toml').is_file():
        return None
    shutil.copytree(source, target, ignore=shutil.ignore_patterns('assets'))
    return target


def set_mod_setting(root: Path, mod_id: str, key: str, value: str) -> None:
    """Set one string value in a mod's saved settings (saves/mods/<id>.cfg), keeping the rest."""
    saves = Path(os.environ.get('BOZ_SAVES') or Path(root) / 'saves')
    path = saves / 'mods' / f'{mod_id}.cfg'
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    if path.is_file():
        lines = [line for line in path.read_text(errors='ignore').splitlines()
                 if line and not line.startswith(f'{key}=')]
    lines.append(f'{key}=s:{value}')
    path.write_text('\n'.join(lines) + '\n')


def load_last(root: Path, mod_id: str) -> None:
    """Make *mod_id* load after every other mod, so its files win (the client loads the [mods]
    order list first, then unlisted mods alphabetically)."""
    present = [mod.id for mod in client_mods(root)]
    order = [item for item in _id_list(ini_get(root, 'mods', 'order')) if item in present]
    rest = sorted((item for item in present if item not in order), key=str.lower)
    new = [item for item in order + rest if item != mod_id] + [mod_id]
    ini_set(root, 'mods', 'order', ', '.join(new))


def start_vars_text(start_vars: dict | None) -> str:
    """Console variables for the level start, as the Developer mod reads them."""
    return ';'.join(f'{name}={value}' for name, value in (start_vars or {}).items())


def run_in_game(project: sdk_project.Project, root: str | Path,
                start_vars: dict | None = None) -> str:
    """Install a project (and the Developer mod) into the client and start the game. A map
    project is compiled first, and the Developer mod starts its level once the menu is up."""
    from . import library

    root = Path(root).expanduser().resolve()
    status = client_status(root)
    if not status.is_client:
        raise sdk_project.ProjectError(f'{root} is not a BOZ Redux client')
    if not status.game_ready:
        raise sdk_project.ProjectError('the game data is not installed: ' + ', '.join(status.missing))
    if game_running():
        raise sdk_project.ProjectError('the game is already running; close it first')
    command = game_command(root)
    if command is None:
        raise sdk_project.ProjectError(f'no game executable found in {root}')
    game = library.open_game(root) if project.kind == 'map' else None
    installed = sdk_project.install_project(project, root, force=True, game=game)
    set_mod_enabled(root, project.mod.id, True)
    developer = ensure_developer_mod(root)
    if developer is not None:
        set_mod_enabled(root, DEVELOPER_MOD, True)
    message = f'installed {installed.name} and started the game'
    if project.kind == 'map':
        if developer is None or not (developer / 'scripts' / 'boz' / 'levels.lua').is_file():
            raise sdk_project.ProjectError('the Developer mod in the client is too old to start '
                                           'levels; replace it with the SDK\'s copy')
        load_last(root, project.mod.id)
        set_mod_setting(root, DEVELOPER_MOD, 'autostart_level', project.map_name)
        set_mod_setting(root, DEVELOPER_MOD, 'autostart_vars', start_vars_text(start_vars))
        message = f'built {project.map_name}; the game starts it after the main menu'
    start_detached(command, root, root / 'boz-log.txt')
    return message


# The editor


def find_blender(settings: Settings) -> Path | None:
    """The Blender the editor runs in: the settings' choice, the SDK's own, or one on PATH."""
    candidates = [Path(settings.blender)] if settings.blender else []
    names = ('blender.exe',) if sys.platform == 'win32' else ('blender',)
    candidates += [sdk_root() / 'blender' / name for name in names]
    found = shutil.which('blender')
    if found:
        candidates.append(Path(found))
    return next((path for path in candidates if path.is_file()), None)


def suite_dir() -> Path:
    """The assembled editor (a Blender user scripts folder): the release's suite/, or the
    checkout's build/suite (tools/build_suite.py)."""
    release = sdk_root() / 'suite'
    return release if release.is_dir() else sdk_root() / 'build' / 'suite'


def editor_command(project: sdk_project.Project, settings: Settings) -> tuple[list[str], dict]:
    """The command and environment that open *project* in the editor."""
    blender = find_blender(settings)
    if blender is None:
        raise sdk_project.ProjectError('Blender was not found: choose it in Settings')
    suite = suite_dir()
    if not (suite / 'scripts' / 'startup' / 'bl_app_templates_user' / 'boz_suite').is_dir():
        raise sdk_project.ProjectError(f'the editor is missing from {suite}')
    env = dict(os.environ)
    env.update({'BLENDER_USER_SCRIPTS': str(suite / 'scripts'),
                'BLENDER_USER_CONFIG': str(data_dir() / 'blender' / 'config'),
                'BOZ_PROJECT': str(project.root), 'BOZ_SDK_ROOT': str(sdk_root()),
                'BOZ_SDK_HOME': str(data_dir()), 'BOZ_CLIENT': settings.client})
    command = [str(blender), '--offline-mode', '--app-template', 'boz_suite']
    blend = project.root / 'map.blend'
    if blend.is_file():
        command.append(str(blend))
    return command, env


def prepare_editor(settings: Settings) -> None:
    """In an SDK checkout, rebuild the editor (tools/build_suite.py) when its sources changed."""
    script = sdk_root() / 'tools' / 'build_suite.py'
    if getattr(sys, 'frozen', False) or not script.is_file():
        return
    import importlib.util
    spec = importlib.util.spec_from_file_location('boz_build_suite', script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if module.stale():
        blender = find_blender(settings)
        if blender is None:
            raise sdk_project.ProjectError('Blender was not found: choose it in Settings')
        try:
            module.build(blender)
        except RuntimeError as exc:
            raise sdk_project.ProjectError(str(exc)) from None


def open_editor(project: sdk_project.Project, settings: Settings):
    """Start the editor on a map project (building it first in a checkout)."""
    if project.kind != 'map':
        raise sdk_project.ProjectError('only map projects open in the editor')
    prepare_editor(settings)
    command, env = editor_command(project, settings)
    log = data_dir() / 'editor-log.txt'
    log.parent.mkdir(parents=True, exist_ok=True)
    return start_detached(command, project.root, log, env)
