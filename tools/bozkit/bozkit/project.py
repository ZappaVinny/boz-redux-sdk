"""SDK projects, validation, deterministic mod builds, and installation."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

PROJECT_FILE = 'boz-project.toml'
PROJECT_SCHEMA = 2
SUPPORTED_SCHEMAS = (1, 2)
KINDS = ('script', 'map')
MAP_TEMPLATES = ('empty', 'debug', 'kino', 'callofthedead', 'ascension', 'tutorial')
GAME_VERSION = '1.0.11'
BUILD_REPORT = 'boz-build.json'
ID_RE = re.compile(r'^[a-z][a-z0-9_-]*$')
SDK_ROOT = Path(__file__).resolve().parents[3]


class ProjectError(ValueError):
    """An invalid SDK project or unsafe build operation."""


@dataclass(frozen=True)
class ModMetadata:
    id: str
    name: str
    version: str
    author: str
    game: str
    description: str = ''


@dataclass(frozen=True)
class Dependency:
    id: str
    version: str = ''


@dataclass(frozen=True)
class Provenance:
    path: str
    kind: str
    note: str = ''


@dataclass(frozen=True)
class Project:
    root: Path
    schema: int
    mod: ModMetadata
    scripts: Path
    assets: Path
    include_standard_library: bool
    dependencies: tuple[Dependency, ...] = ()
    provenance: tuple[Provenance, ...] = ()
    kind: str = 'script'
    map_name: str = ''
    map_template: str = ''
    data: dict = field(default_factory=dict, compare=False, repr=False)


@dataclass
class ValidationResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict:
        return {'ok': self.ok, 'errors': self.errors, 'warnings': self.warnings}


def _safe_relative(value: str, label: str) -> Path:
    path = Path(value)
    if path.is_absolute() or '..' in path.parts:
        raise ProjectError(f'{label} must stay inside the project: {value}')
    return path


def load_project(path: str | Path = '.') -> Project:
    """Load and validate the shape of a ``boz-project.toml`` file."""
    candidate = Path(path).resolve()
    manifest = candidate if candidate.is_file() else candidate / PROJECT_FILE
    if not manifest.is_file():
        raise ProjectError(f'project manifest not found: {manifest}')
    try:
        data = tomllib.loads(manifest.read_text(encoding='utf-8'))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ProjectError(f'cannot read {manifest}: {exc}') from exc
    schema = data.get('schema')
    if schema not in SUPPORTED_SCHEMAS:
        raise ProjectError(f'unsupported project schema {schema!r}; expected {PROJECT_SCHEMA}')
    raw_mod = data.get('mod', {})
    required = ('id', 'name', 'version', 'author', 'game')
    missing = [key for key in required if not isinstance(raw_mod.get(key), str) or not raw_mod[key]]
    if missing:
        raise ProjectError(f'missing [mod] values: {", ".join(missing)}')
    paths = data.get('paths', {})
    scripts = _safe_relative(paths.get('scripts', 'scripts'), 'paths.scripts')
    assets = _safe_relative(paths.get('assets', 'assets'), 'paths.assets')
    build = data.get('build', {})
    dependencies = tuple(Dependency(str(item.get('id', '')), str(item.get('version', '')))
                         for item in data.get('dependencies', []))
    provenance = tuple(Provenance(str(item.get('path', '')), str(item.get('kind', 'unknown')),
                                  str(item.get('note', '')))
                       for item in data.get('provenance', []))
    kind = str(data.get('project', {}).get('kind', 'script'))
    if kind not in KINDS:
        raise ProjectError(f'unknown project kind {kind!r}; expected script or map')
    raw_map = data.get('map', {})
    root = manifest.parent
    return Project(
        root=root,
        schema=schema,
        mod=ModMetadata(*(raw_mod[key] for key in required), str(raw_mod.get('description', ''))),
        scripts=root / scripts,
        assets=root / assets,
        include_standard_library=bool(build.get('include_standard_library', True)),
        dependencies=dependencies,
        provenance=provenance,
        kind=kind,
        map_name=str(raw_map.get('name', '')),
        map_template=str(raw_map.get('template', '')),
        data=data,
    )


SCRIPT_TEMPLATES = {
    'blank': ('Blank', 'An empty main.lua with commented examples'),
    'round': ('Round hook', 'Runs code at the start of every round'),
    'hotkey': ('Hotkey', 'Runs a console line when you press a key'),
    'settings': ('Settings menu', 'Adds a slider and a checkbox to the pause menu'),
}


def _script_template(template: str, mod_id: str) -> str:
    """The starting main.lua for a script template."""
    if template == 'round':
        return f'''-- {mod_id}: runs code at the start of every round.

hook.add("CWaveManager::StartWave", {{after = function(call)
    local manager = call:arg(1)
    local round = game.read("u32", manager + 0x78)  -- CWaveManager round number
    log("round " .. round .. " started")
end}})

log("{mod_id} loaded")
'''
    if template == 'hotkey':
        return f'''-- {mod_id}: press F5 to run a console line (here: turn the power on).
-- Every console command is listed in the console reference.

local console = require("boz.console")

input.bind("F5", function()
    local output, err = console.exec("SwitchPowerOn")
    log(output or err)
end)

log("{mod_id} loaded")
'''
    if template == 'settings':
        return f'''-- {mod_id}: settings in the game's own pause menu (pause > Settings), saved with the mod.

local pause_settings = require("boz.pause_settings")

pause_settings.add_slider{{
    id = "speed",
    label = "Game speed",
    min = 50,
    max = 200,
    step = 10,
    get = function() return settings.get("speed", 100) end,
    set = function(value)
        settings.set("speed", value)
        require("boz.rounds").set_time_scale(value / 100)
    end,
}}

pause_settings.add_checkbox{{
    id = "greeting",
    label = "Log a greeting",
    get = function() return settings.get("greeting", true) end,
    set = function(value) settings.set("greeting", value) end,
}}

log("{mod_id} loaded")
'''
    return f'''-- {mod_id}: runs once when the game starts, before the first frame.
-- Set things up here: event handlers, key bindings, hooks and settings.
-- The standard library (scripts/boz) wraps common game features; see its docs.

-- local player = require("boz.player")

-- events.on("frame", function(dt)
--     -- runs every frame
-- end)

-- input.bind("F5", function()
--     log("F5 pressed")
-- end)

log("{mod_id} loaded")
'''


def _toml_value(value) -> str:
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, (list, tuple)):
        return '[' + ', '.join(_toml_value(item) for item in value) + ']'
    raise ProjectError(f'cannot write {type(value).__name__} to a project manifest')


def manifest_text(data: dict) -> str:
    """A ``boz-project.toml`` for *data*: top-level values, then tables, then arrays of tables."""
    lines = [f'{key} = {_toml_value(value)}' for key, value in data.items()
             if not isinstance(value, dict) and not (isinstance(value, list) and value
                                                     and isinstance(value[0], dict))]
    for key, value in data.items():
        if isinstance(value, dict):
            lines += ['', f'[{key}]'] + [f'{k} = {_toml_value(v)}' for k, v in value.items()]
    for key, value in data.items():
        if isinstance(value, list) and value and isinstance(value[0], dict):
            for item in value:
                lines += ['', f'[[{key}]]'] + [f'{k} = {_toml_value(v)}' for k, v in item.items()]
    return '\n'.join(lines) + '\n'


def save_manifest(root: str | Path, data: dict) -> Project:
    """Write *data* as the project manifest in *root* and load it back."""
    root = Path(root)
    (root / PROJECT_FILE).write_text(manifest_text(data), encoding='utf-8', newline='\n')
    return load_project(root)


def copy_standard_library(project: Project) -> Path:
    """Copy the SDK's standard library into the project's scripts/boz (replacing an older copy)
    and write .luarc.json so Lua editors find it."""
    target = project.scripts / 'boz'
    if target.exists():
        shutil.rmtree(target)
    _copy_tree(standard_library_path(), target)
    luarc = {
        '$schema': 'https://raw.githubusercontent.com/LuaLS/vscode-lua/master/setting/schema.json',
        'runtime.version': 'Lua 5.4',
        'runtime.path': ['?.lua', '?/init.lua'],
        'workspace.library': ['boz'],
        'diagnostics.globals': ['mod', 'log', 'events', 'input', 'gamedef', 'game', 'hook',
                                'settings', 'overlay', 'ui', 'assets', 'shared'],
    }
    (project.scripts / '.luarc.json').write_text(json.dumps(luarc, indent=2) + '\n',
                                                 encoding='utf-8', newline='\n')
    return target


def create_project(path: str | Path, mod_id: str, name: str, author: str,
                   version: str = '0.1.0', description: str = '', kind: str = 'script',
                   template: str = '', bundle_standard_library: bool = True,
                   game=None) -> Project:
    """Create a project without overwriting existing files.

    *kind* is ``script`` (a Lua mod; *template* is a SCRIPT_TEMPLATES key) or ``map`` (a level
    made in the editor; *template* is a MAP_TEMPLATES key). With *bundle_standard_library* the
    project carries its own copy of the standard library in scripts/boz. *game* reads the
    game's groups (``bozkit.library.open_game``); the debug template needs it.
    """
    if not ID_RE.fullmatch(mod_id):
        raise ProjectError('mod id must start with a lower-case letter and contain only a-z, 0-9, _ or -')
    if not name or not author or not version:
        raise ProjectError('mod name, author and version are required')
    if kind not in KINDS:
        raise ProjectError(f'unknown project kind {kind!r}; expected script or map')
    template = template or ('blank' if kind == 'script' else 'empty')
    if template not in (SCRIPT_TEMPLATES if kind == 'script' else MAP_TEMPLATES):
        raise ProjectError(f'unknown {kind} template {template!r}')
    starting_world = None
    if kind == 'map':
        from . import levels, world
        try:
            levels.check_name(mod_id.replace('-', '_'))
        except levels.LevelError as exc:
            raise ProjectError(f'mod id {mod_id!r} cannot be a level name: {exc}') from None
        try:
            starting_world = world.template_world(template, game)
        except (world.WorldError, levels.LevelError, KeyError) as exc:
            raise ProjectError(str(exc)) from None
    root = Path(path).resolve()
    if root.exists() and any(root.iterdir()):
        raise ProjectError(f'directory is not empty: {root}')
    root.mkdir(parents=True, exist_ok=True)
    (root / 'scripts').mkdir()
    (root / 'assets').mkdir()
    data = {
        'schema': PROJECT_SCHEMA,
        'mod': {'id': mod_id, 'name': name, 'version': version, 'author': author,
                'game': GAME_VERSION, 'description': description},
        'project': {'kind': kind},
        'paths': {'scripts': 'scripts', 'assets': 'assets'},
        'build': {'include_standard_library': not bundle_standard_library},
    }
    if kind == 'map':
        data['map'] = {'name': mod_id.replace('-', '_'), 'template': template}
    project = save_manifest(root, data)
    (root / 'scripts' / 'main.lua').write_text(
        _script_template(template if kind == 'script' else 'blank', mod_id), encoding='utf-8',
        newline='\n')
    (root / '.gitignore').write_text('/build/\n', encoding='utf-8')
    if starting_world is not None:
        from . import world
        world.save(starting_world, root / 'source')
    if bundle_standard_library:
        copy_standard_library(project)
    return project


def validate_project(project: Project, profile: str = 'development') -> ValidationResult:
    """Validate a project. Distribution checks warn but never reject derived assets."""
    if profile not in ('development', 'distribution'):
        raise ProjectError(f'unknown validation profile: {profile}')
    result = ValidationResult()
    mod = project.mod
    if not ID_RE.fullmatch(mod.id):
        result.errors.append('mod.id must start with a lower-case letter and contain only a-z, 0-9, _ or -')
    if '/' in mod.version or '\\' in mod.version:
        result.errors.append('mod.version must not contain path separators')
    if mod.game != GAME_VERSION:
        result.errors.append(f'mod.game must be {GAME_VERSION}; no other game version is supported')
    if project.scripts.exists() and not project.scripts.is_dir():
        result.errors.append(f'scripts path is not a directory: {project.scripts}')
    if project.assets.exists() and not project.assets.is_dir():
        result.errors.append(f'assets path is not a directory: {project.assets}')
    has_scripts = project.scripts.is_dir() and any(p.is_file() for p in project.scripts.rglob('*'))
    has_assets = project.assets.is_dir() and any(p.is_file() for p in project.assets.rglob('*'))
    if not has_scripts and not has_assets:
        result.warnings.append('project has no scripts or assets')
    if has_scripts and not (project.scripts / 'main.lua').is_file():
        result.warnings.append('scripts exist but scripts/main.lua is missing')
    if project.kind == 'map':
        from . import world
        try:
            result.errors.extend(world.validate(world.load(project.root / 'source')))
        except world.WorldError as exc:
            result.errors.append(str(exc))
    seen_dependencies: set[str] = set()
    for dep in project.dependencies:
        if not ID_RE.fullmatch(dep.id):
            result.errors.append(f'invalid dependency id: {dep.id!r}')
        elif dep.id == mod.id:
            result.errors.append('a mod cannot depend on itself')
        elif dep.id in seen_dependencies:
            result.errors.append(f'duplicate dependency: {dep.id}')
        seen_dependencies.add(dep.id)
    for entry in project.provenance:
        if not entry.path:
            result.errors.append('provenance.path must not be empty')
            continue
        try:
            relative = _safe_relative(entry.path, 'provenance.path')
        except ProjectError as exc:
            result.errors.append(str(exc))
            continue
        if not (project.root / relative).exists():
            result.warnings.append(f'provenance path does not exist: {entry.path}')
        if profile == 'distribution' and entry.kind in ('game', 'game-derived', 'extracted'):
            result.warnings.append(f'{entry.path}: contains {entry.kind} game content; review distribution rights')
    return result


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _mod_manifest(project: Project) -> str:
    mod = project.mod
    lines = [
        f'id = {_toml_string(mod.id)}', f'name = {_toml_string(mod.name)}',
        f'version = {_toml_string(mod.version)}', f'author = {_toml_string(mod.author)}',
        f'game = {_toml_string(mod.game)}', f'description = {_toml_string(mod.description)}',
    ]
    if project.dependencies:
        lines.extend(['', '[sdk]', f'project_schema = {PROJECT_SCHEMA}', '', '[[sdk.dependencies]]'])
        dependency_lines: list[str] = []
        for index, dep in enumerate(project.dependencies):
            if index:
                dependency_lines.append('[[sdk.dependencies]]')
            dependency_lines.append(f'id = {_toml_string(dep.id)}')
            if dep.version:
                dependency_lines.append(f'version = {_toml_string(dep.version)}')
        lines.extend(dependency_lines)
    return '\n'.join(lines) + '\n'


def _copy_tree(source: Path, destination: Path) -> None:
    if not source.is_dir():
        return
    for item in sorted(source.rglob('*')):
        if item.is_symlink():
            raise ProjectError(f'symlinks are not supported in project sources: {item}')
        if item.is_file():
            target = destination / item.relative_to(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(item, target)


def standard_library_path() -> Path:
    """Find the Lua standard library in a checkout or an installed SDK."""
    candidates = (
        *((Path(os.environ['BOZ_SDK_ROOT']) / 'lib' / 'boz',) if os.environ.get('BOZ_SDK_ROOT')
          else ()),
        SDK_ROOT / 'lib' / 'boz',
        Path(sys.executable).parent / 'lib' / 'boz',  # the SDK release (frozen launcher)
        Path(sys.prefix) / 'share' / 'boz-redux-sdk' / 'lib' / 'boz',
    )
    for candidate in candidates:
        if (candidate / 'player.lua').is_file():
            return candidate
    raise ProjectError('BOZ standard library is missing from this SDK installation')


def _hash_files(root: Path) -> list[dict]:
    files = []
    for item in sorted(p for p in root.rglob('*') if p.is_file() and p.name != BUILD_REPORT):
        files.append({'path': item.relative_to(root).as_posix(),
                      'size': item.stat().st_size,
                      'sha256': hashlib.sha256(item.read_bytes()).hexdigest()})
    return files


def compile_map(project: Project, game, fixed=None):
    """The game's groups for a map project's world (``bozkit.levels.LevelFiles``). *game*
    reads the shipped groups: ``bozkit.library.open_game``."""
    from . import levels, weapons, world
    if project.kind != 'map':
        raise ProjectError(f'{project.mod.id} is not a map project')
    if game is None:
        raise ProjectError('building a map needs the game data: build the asset library or '
                           'install the game files in the client')
    source = project.root / 'source'
    try:
        defs = weapons.load_defs(source)
        index = weapons.load_index(source) or []
        start, reserve = weapons.load_start(source)
        files = world.compile_world(game, project.map_name, world.load(source), fixed,
                                    weapons=defs)
    except (world.WorldError, levels.LevelError, weapons.WeaponError) as exc:
        raise ProjectError(str(exc)) from None
    built = files.groups.get(f'weapons_{project.map_name}.group.bin')
    if built is not None and weapons._hash_of(start) not in weapons._hashes(built):
        # The game gives the starting weapon without checking it exists: it would crash.
        raise ProjectError(f'the starting weapon {start} is not one of the map\'s weapons')
    files.runtime['weapons'] = weapons.runtime(defs, index)
    files.runtime['start_weapon'] = {'name': start, 'reserve': reserve, 'level': project.map_name}
    return files


MAP_RUNTIME = 'require("boz.world").start()'


MAP_RUNTIME_MODULES = ('world', 'prefabs', 'objects', 'components', 'hash', 'weapons', 'console')


def lua_value(value, indent: str = '') -> str:
    """A Lua literal for JSON-like data (tables, strings, numbers, booleans)."""
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value)   # JSON string escapes are valid Lua
    if value is None:
        return 'nil'
    inner = indent + '    '
    if isinstance(value, dict):
        if not value:
            return '{}'
        items = []
        for key, item in value.items():
            key = str(key)
            label = key if key.isidentifier() else f'[{json.dumps(key)}]'
            items.append(f'{inner}{label} = {lua_value(item, inner)},')
        return '{\n' + '\n'.join(items) + f'\n{indent}}}'
    if isinstance(value, (list, tuple)):
        if not value:
            return '{}'
        if all(not isinstance(item, (dict, list, tuple)) for item in value):
            return '{' + ', '.join(lua_value(item) for item in value) + '}'
        return '{\n' + '\n'.join(f'{inner}{lua_value(item, inner)},' for item in value) + \
            f'\n{indent}}}'
    raise TypeError(f'cannot write {type(value).__name__} as Lua')


def world_data_lua(runtime: dict) -> str:
    """boz/world_data.lua: the map's start state and scripted objects, read by boz.world and
    boz.prefabs when the level starts (world.compile_world's runtime)."""
    data = {key: list(runtime.get(key, [])) for key in ('hidden', 'no_collision', 'blocked')}
    data['objects'] = list(runtime.get('objects', []))
    data['names'] = list(runtime.get('names', []))
    data['weapons'] = list(runtime.get('weapons', []))
    if runtime.get('start_weapon'):
        data['start_weapon'] = dict(runtime['start_weapon'])
    return ('-- Generated by the SDK from the map: what boz.world does when the level starts.\n'
            'return ' + lua_value(data) + '\n')


def _map_runtime(scripts: Path, runtime: dict | None = None) -> None:
    """Map projects run boz.world (behaviour the world asks for that the game's data cannot
    express, and the start state of objects scripts change): the SDK's current copies go in,
    with the map's world_data.lua, and main.lua starts it."""
    (scripts / 'boz').mkdir(parents=True, exist_ok=True)
    for module in MAP_RUNTIME_MODULES:
        shutil.copyfile(standard_library_path() / f'{module}.lua', scripts / 'boz' / f'{module}.lua')
    (scripts / 'boz' / 'world_data.lua').write_text(world_data_lua(runtime or {}),
                                                     encoding='utf-8', newline='\n')
    main = scripts / 'main.lua'
    text = main.read_text(encoding='utf-8') if main.is_file() else ''
    if MAP_RUNTIME not in text:
        main.write_text(f'{MAP_RUNTIME}  -- added by the SDK for map projects\n' + text,
                        encoding='utf-8', newline='\n')


def build_project(project: Project, output: str | Path | None = None,
                  profile: str = 'development', game=None) -> tuple[Path, dict]:
    """Compile a project into a deterministic client mod directory. Map projects need *game*
    (``bozkit.library.open_game``): their world compiles into the mod's assets."""
    validation = validate_project(project, profile)
    if not validation.ok:
        raise ProjectError('; '.join(validation.errors))
    level_files = compile_map(project, game) if project.kind == 'map' else None
    target = Path(output).resolve() if output else project.root / 'build' / project.mod.id
    if target == project.root or target in project.root.parents:
        raise ProjectError('build output cannot replace the project or one of its parent directories')
    if any(target == source or source in target.parents for source in (project.scripts, project.assets)):
        raise ProjectError('build output cannot replace the project or a source directory')
    if target.exists():
        if not target.is_dir():
            raise ProjectError(f'build output is not a directory: {target}')
        entries = list(target.iterdir())
        marker = target / BUILD_REPORT
        if entries and not marker.is_file():
            raise ProjectError(f'refusing to replace a directory not created by bozkit: {target}')
        if marker.is_file():
            try:
                previous = json.loads(marker.read_text(encoding='utf-8'))
                previous_id = previous['mod']['id']
            except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
                raise ProjectError(f'invalid build marker in {target}') from exc
            if previous_id != project.mod.id:
                raise ProjectError(f'build output belongs to mod {previous_id}, not {project.mod.id}')
        shutil.rmtree(target)
    target.mkdir(parents=True)
    (target / 'mod.toml').write_text(_mod_manifest(project), encoding='utf-8', newline='\n')
    _copy_tree(project.scripts, target / 'scripts')
    _copy_tree(project.assets, target / 'assets')
    if project.include_standard_library:
        _copy_tree(standard_library_path(), target / 'scripts' / 'boz')
    if level_files is not None:
        level_files.write(target / 'assets')
        _map_runtime(target / 'scripts', level_files.runtime)
    report = {
        'schema': 1,
        'project_schema': project.schema,
        'profile': profile,
        'mod': {'id': project.mod.id, 'version': project.mod.version, 'game': project.mod.game},
        'dependencies': [dep.__dict__ for dep in project.dependencies],
        'provenance': [entry.__dict__ for entry in project.provenance],
        'warnings': validation.warnings + list((level_files.runtime if level_files else {})
                                               .get('warnings', [])),
        'files': _hash_files(target),
    }
    (target / BUILD_REPORT).write_text(json.dumps(report, indent=2, sort_keys=True) + '\n',
                                       encoding='utf-8', newline='\n')
    return target, report


def package_project(project: Project, output: str | Path | None = None,
                    profile: str = 'distribution', game=None) -> tuple[Path, dict]:
    """Build a project and write a reproducible ZIP archive."""
    build_dir, report = build_project(project, profile=profile, game=game)
    archive = Path(output).resolve() if output else project.root / 'build' / f'{project.mod.id}-{project.mod.version}.zip'
    archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for item in sorted(p for p in build_dir.rglob('*') if p.is_file()):
            relative = PurePosixPath(project.mod.id) / PurePosixPath(item.relative_to(build_dir).as_posix())
            info = zipfile.ZipInfo(str(relative), (1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            zf.writestr(info, item.read_bytes(), compresslevel=9)
    return archive, report


def install_project(project: Project, client: str | Path, force: bool = False,
                    profile: str = 'development', game=None) -> Path:
    """Build and install a mod in a client checkout or installed game root."""
    root = Path(client).resolve()
    if not root.is_dir():
        raise ProjectError(f'client root does not exist: {root}')
    built, _ = build_project(project, profile=profile, game=game)
    destination = root / 'mods' / project.mod.id
    if destination.exists() and not force:
        raise ProjectError(f'mod is already installed: {destination}; pass --force to replace it')
    if destination.exists():
        shutil.rmtree(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(built, destination)
    return destination


def extract_asset(source: str | Path, output: str | Path, kind: str = 'auto') -> None:
    """Extract a DZ archive or resource group through dade without deleting the source."""
    source_path = Path(source).resolve()
    output_path = Path(output).resolve()
    selected = kind
    if selected == 'auto':
        selected = 'dz' if source_path.suffix.lower() == '.dz' else 'group'
    command = ['dade', 'marmalade', 'extract-dz', '--no-delete', str(source_path), str(output_path)]
    if selected == 'group':
        command = ['dade', 'marmalade', 'extract-group', str(source_path), str(output_path)]
    elif selected != 'dz':
        raise ProjectError(f'unknown extraction kind: {selected}')
    try:
        subprocess.run(command, check=True)
    except FileNotFoundError as exc:
        raise ProjectError('dade is not installed; install tools/destin before extracting assets') from exc
    except subprocess.CalledProcessError as exc:
        raise ProjectError(f'dade extraction failed with exit code {exc.returncode}') from exc
