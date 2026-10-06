"""SDK projects, validation, deterministic mod builds, and installation."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
import tomllib
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

PROJECT_FILE = 'boz-project.toml'
PROJECT_SCHEMA = 1
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
    if schema != PROJECT_SCHEMA:
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
    )


def create_project(path: str | Path, mod_id: str, name: str, author: str,
                   version: str = '0.1.0', description: str = '') -> Project:
    """Create a minimal Lua mod project without overwriting existing files."""
    if not ID_RE.fullmatch(mod_id):
        raise ProjectError('mod id must start with a lower-case letter and contain only a-z, 0-9, _ or -')
    if not name or not author or not version:
        raise ProjectError('mod name, author and version are required')
    root = Path(path).resolve()
    if root.exists() and any(root.iterdir()):
        raise ProjectError(f'directory is not empty: {root}')
    root.mkdir(parents=True, exist_ok=True)
    (root / 'scripts').mkdir()
    (root / 'assets').mkdir()
    manifest = f'''schema = {PROJECT_SCHEMA}

[mod]
id = {json.dumps(mod_id)}
name = {json.dumps(name)}
version = {json.dumps(version)}
author = {json.dumps(author)}
game = {json.dumps(GAME_VERSION)}
description = {json.dumps(description)}

[paths]
scripts = "scripts"
assets = "assets"

[build]
include_standard_library = true
'''
    (root / PROJECT_FILE).write_text(manifest, encoding='utf-8')
    (root / 'scripts' / 'main.lua').write_text(
        '-- Register mod events, hooks, and settings here.\nlog("' + mod_id + ' loaded")\n',
        encoding='utf-8')
    (root / '.gitignore').write_text('/build/\n', encoding='utf-8')
    return load_project(root)


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
        SDK_ROOT / 'lib' / 'boz',
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


def build_project(project: Project, output: str | Path | None = None,
                  profile: str = 'development') -> tuple[Path, dict]:
    """Compile a project into a deterministic client mod directory."""
    validation = validate_project(project, profile)
    if not validation.ok:
        raise ProjectError('; '.join(validation.errors))
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
    report = {
        'schema': 1,
        'project_schema': project.schema,
        'profile': profile,
        'mod': {'id': project.mod.id, 'version': project.mod.version, 'game': project.mod.game},
        'dependencies': [dep.__dict__ for dep in project.dependencies],
        'provenance': [entry.__dict__ for entry in project.provenance],
        'warnings': validation.warnings,
        'files': _hash_files(target),
    }
    (target / BUILD_REPORT).write_text(json.dumps(report, indent=2, sort_keys=True) + '\n',
                                       encoding='utf-8', newline='\n')
    return target, report


def package_project(project: Project, output: str | Path | None = None,
                    profile: str = 'distribution') -> tuple[Path, dict]:
    """Build a project and write a reproducible ZIP archive."""
    build_dir, report = build_project(project, profile=profile)
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
                    profile: str = 'development') -> Path:
    """Build and install a mod in a client checkout or installed game root."""
    root = Path(client).resolve()
    if not root.is_dir():
        raise ProjectError(f'client root does not exist: {root}')
    built, _ = build_project(project, profile=profile)
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
