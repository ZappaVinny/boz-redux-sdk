"""BOZ Test: runs mod tests inside the real game and writes a report.

A test is a Lua script in a mod's (or project's) ``tests/`` folder. The client runs it with
``--test FILE`` in the mod's environment, usually without a window, and writes ``result.json``;
the script's steps use ``test.*`` (the client's built-in harness). Settings for the runner come
from ``--! key: value`` comment lines at the top of the script:

    --! timeout: 240        seconds before the test counts as hung (default 300)
    --! touch: true         touch-screen mode (phone controls; test.tap/test.drag reach the game)
    --! players: 2          co-op: a host and a guest client, each running the script
    --! mods: developer     other mods to enable (comma-separated)
    --! arch: x64           only on these builds

Each run gets its own client.ini (``--config``) and a copy of the saves, so the game root's own
settings and saves are never touched. The runner needs the game data in the client root.
"""
from __future__ import annotations

import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from . import png

DEVELOPER_MOD = 'developer'
DEFAULT_TIMEOUT = 300
GUEST_DELAY = 12   # seconds between starting the host and the guest of a co-op test

# The built-in check for a mod without tests: the game starts with it, its map (if any) plays,
# and no mod raises a Lua error.
SMOKE_TEST = '''--! timeout: 240
-- Built-in smoke test (bozkit test): boots with the mod, plays its map, no Lua errors.
local map = MAP_NAME
if map then
    test.start_map(map, {UnlimitedHealth = true})
    test.step("the map starts", function()
        test.wait_until(test.in_match, 180, "the " .. map .. " match")
        local running = require("boz.engine.map").name()
        test.expect(running == map, "the level running is " .. tostring(running))
        test.wait(10)
        test.screenshot("in_match")
    end)
else
    test.step("the game runs", function()
        test.wait(40)
        test.screenshot("menu")
    end)
end
test.step("no Lua errors", function()
    test.expect(test.errors() == 0, test.errors() .. " Lua errors in mods")
end)
'''


class TestError(RuntimeError):
    pass


@dataclass
class TestCase:
    name: str
    file: Path
    mod: str                     # the mod whose environment runs it
    options: dict = field(default_factory=dict)

    @property
    def timeout(self) -> int:
        try:
            return int(self.options.get('timeout', DEFAULT_TIMEOUT))
        except ValueError:
            return DEFAULT_TIMEOUT

    @property
    def players(self) -> int:
        try:
            return max(1, int(self.options.get('players', 1)))
        except ValueError:
            return 1

    @property
    def touch(self) -> bool:
        return str(self.options.get('touch', '')).lower() in ('1', 'true', 'yes')

    @property
    def extra_mods(self) -> list[str]:
        return [item.strip() for item in str(self.options.get('mods', '')).split(',') if item.strip()]

    @property
    def archs(self) -> list[str]:
        return [item.strip() for item in str(self.options.get('arch', '')).split(',') if item.strip()]


@dataclass
class Build:
    arch: str
    loader: Path


@dataclass
class RunResult:
    case: TestCase
    build: str
    status: str                  # passed, failed, timeout, crashed, error
    seconds: float
    clients: list[dict]          # per client: role, status, result, log, screenshots

    @property
    def passed(self) -> bool:
        return self.status == 'passed'


def read_options(path: Path) -> dict:
    """The ``--! key: value`` lines at the top of a test script."""
    options = {}
    try:
        lines = path.read_text(encoding='utf-8').splitlines()
    except OSError:
        return options
    for line in lines:
        text = line.strip()
        if not text:
            continue
        if not text.startswith('--'):
            break
        if text.startswith('--!') and ':' in text:
            key, value = text[3:].split(':', 1)
            options[key.strip().lower()] = value.strip()
    return options


def find_tests(folder: Path, mod: str, only: list[str] | None = None) -> list[TestCase]:
    tests = []
    for path in sorted((folder / 'tests').glob('*.lua')) if (folder / 'tests').is_dir() else ():
        if only and path.stem not in only:
            continue
        tests.append(TestCase(path.stem, path.resolve(), mod, read_options(path)))
    return tests


def mod_manifest(folder: Path) -> dict:
    try:
        return tomllib.loads((folder / 'mod.toml').read_text(encoding='utf-8'))
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def smoke_test(mod_id: str, maps: list[str], work: Path) -> TestCase:
    """The built-in smoke test for a mod (run in the Developer mod's environment)."""
    work.mkdir(parents=True, exist_ok=True)
    path = work / f'smoke_{mod_id}.lua'
    map_name = json.dumps(maps[0]) if maps else 'nil'
    path.write_text(SMOKE_TEST.replace('MAP_NAME', map_name), encoding='utf-8', newline='\n')
    case = TestCase(f'smoke ({mod_id})', path, DEVELOPER_MOD, read_options(path))
    case.options['mods'] = mod_id
    return case


def find_builds(root: Path, wanted: list[str] | None = None) -> list[Build]:
    """The client builds in a checkout (build/<platform>-<arch>/bin) or a release (its loader)."""
    exe = 'codboz_s3e_loader.exe' if sys.platform == 'win32' else 'codboz_s3e_loader'
    platform = 'windows' if sys.platform == 'win32' else 'linux'
    builds = []
    for arch in ('x86', 'x64', 'x64-base'):
        for preset in (f'{platform}-{arch}', f'{platform}-{arch}-msys2'):
            loader = root / 'build' / preset / 'bin' / exe
            if loader.is_file():
                builds.append(Build(arch, loader))
                break
    if not builds and (root / exe).is_file():
        builds.append(Build('installed', root / exe))
    if wanted:
        builds = [build for build in builds if build.arch in wanted]
    return builds


def _client_ini(path: Path, enabled: list[str], all_mods: list[str]) -> None:
    disabled = [mod for mod in all_mods if mod not in enabled]
    path.write_text('\n'.join([
        '[display]', 'fullscreen = false', 'vsync = off', 'fps_limit = 0', 'resolution = 1280x720',
        '[mods]', f'order = {", ".join(enabled)}', f'disabled = {", ".join(disabled)}',
        '[performance]', 'stats = false', '',
    ]), encoding='utf-8', newline='\n')


def _ppm_to_png(source: Path, target: Path) -> bool:
    data = source.read_bytes()
    # The header is four tokens and one whitespace byte; the pixels after it are raw bytes, and
    # dark ones look like whitespace (so no split over the whole file).
    header = re.match(rb'P6\s+(\d+)\s+(\d+)\s+(\d+)\s', data)
    if not header:
        return False
    width, height = int(header.group(1)), int(header.group(2))
    pixels = data[header.end():header.end() + width * height * 3]
    if len(pixels) < width * height * 3:
        return False
    rgba = bytearray(width * height * 4)
    rgba[0::4], rgba[1::4], rgba[2::4] = pixels[0::3], pixels[1::3], pixels[2::3]
    rgba[3::4] = b'\xff' * (width * height)
    target.write_bytes(png.write_rgba(width, height, bytes(rgba)))
    return True


def _start_client(root: Path, build: Build, case: TestCase, role: str, enabled: list[str],
                  all_mods: list[str], work: Path) -> tuple[subprocess.Popen, Path, Path]:
    run = work / role
    if run.exists():
        shutil.rmtree(run)
    out = run / 'out'
    out.mkdir(parents=True)
    saves = run / 'saves'
    if (root / 'saves').is_dir():
        shutil.copytree(root / 'saves', saves)
    else:
        saves.mkdir()
    if role == 'guest':
        (saves / 'device-id.bin').unlink(missing_ok=True)   # each player a device of its own
    config = run / 'client.ini'
    _client_ini(config, enabled, all_mods)
    env = dict(os.environ)
    env['HOME'] = str(saves)
    env.setdefault('XDG_CACHE_HOME', str(Path.home() / '.cache'))
    env['SDL_AUDIODRIVER'] = 'dummy'
    if sys.platform != 'win32':
        env['SDL_VIDEODRIVER'] = 'offscreen'
    if case.touch:
        env['BOZ_TOUCH_SCREEN'] = '1'
    if case.players > 1:
        env['BOZ_PLAYER_NAME'] = f'Test{role.capitalize()}'
    command = [str(build.loader), '--root', str(root), '--config', str(config),
               '--test', str(case.file), '--test-mod', case.mod, '--test-out', str(out),
               '--test-role', role if case.players > 1 else 'solo',
               '--test-timeout', str(case.timeout),
               '--run', str(root / 'assets' / 'boz.s3e.unpacked')]
    log = run / 'log.txt'
    output = open(log, 'w', encoding='utf-8', newline='\n')
    process = subprocess.Popen(command, cwd=run, stdout=output, stderr=subprocess.STDOUT,
                               stdin=subprocess.DEVNULL, env=env)
    output.close()
    return process, out, log


def _wait(process: subprocess.Popen, seconds: float) -> int | None:
    try:
        return process.wait(timeout=max(1.0, seconds))
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
        return None


def _client_report(role: str, code: int | None, out: Path, log: Path, report: Path,
                   prefix: str) -> dict:
    result = None
    try:
        result = json.loads((out / 'result.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        pass
    if result:
        status = result.get('status', 'error')
    elif code is None:
        status = 'timeout'
    else:
        status = 'crashed'
    shots = []
    for ppm in sorted(out.glob('*.ppm')):
        name = f'{prefix}-{role}-{ppm.stem}.png'
        try:
            if _ppm_to_png(ppm, report / name):
                shots.append({'name': ppm.stem, 'file': name})
        except (OSError, ValueError):
            pass
    log_name = f'{prefix}-{role}.log'
    try:
        shutil.copyfile(log, report / log_name)
        lines = log.read_text(encoding='utf-8', errors='replace').splitlines()
    except OSError:
        lines = []
    notable = [line for line in lines if line.startswith(('[test]', '[lua]', '[arm]', '[mods]'))]
    return {'role': role, 'status': status, 'exit': code, 'result': result, 'log': log_name,
            'screenshots': shots, 'notable': notable[-80:], 'tail': lines[-30:]}


def run_case(root: Path, build: Build, case: TestCase, all_mods: list[str], report: Path,
             work: Path, guest_build: Build | None = None) -> RunResult:
    enabled = []
    for mod in [DEVELOPER_MOD, *case.extra_mods, case.mod]:
        if mod in all_mods and mod not in enabled:
            enabled.append(mod)
    if case.mod not in all_mods:
        raise TestError(f'mod {case.mod} is not installed in {root}')
    prefix = f'{case.name}-{build.arch}'.replace(' ', '_').replace('(', '').replace(')', '')
    started = time.monotonic()
    clients = []
    roles = ['host', 'guest'] if case.players > 1 else ['solo']
    running = []
    for index, role in enumerate(roles):
        if index:
            time.sleep(GUEST_DELAY)
        running.append((role, *_start_client(root, guest_build if role == 'guest' and guest_build
                                             else build, case, role, enabled, all_mods,
                                             work / prefix)))
    for role, process, out, log in running:
        remaining = case.timeout + 60 - (time.monotonic() - started)
        code = _wait(process, remaining)
        clients.append(_client_report(role, code, out, log, report, prefix))
    statuses = [client['status'] for client in clients]
    status = next((s for s in ('crashed', 'timeout', 'error', 'failed') if s in statuses), 'passed')
    label = build.arch if not guest_build else f'{build.arch} + {guest_build.arch}'
    return RunResult(case, label, status, time.monotonic() - started, clients)


# --- Report -------------------------------------------------------------------------------------

_STYLE = '''
:root { --bg: #0d0e10; --panel: #16181b; --line: #2e3238; --text: #e9eaeb; --muted: #8b9098;
        --pass: #3fb950; --fail: #e31c29; --warn: #d29922; }
body { background: var(--bg); color: var(--text); font: 15px/1.45 system-ui, sans-serif;
       margin: 0; padding: 24px 16px; }
main { max-width: 1100px; margin: 0 auto; }
h1 { font-size: 24px; margin: 0 0 4px; } h2 { font-size: 18px; margin: 0; }
.muted { color: var(--muted); }
table { border-collapse: collapse; width: 100%; margin: 16px 0 28px; }
td, th { border-bottom: 1px solid var(--line); padding: 6px 8px; text-align: left; }
.badge { display: inline-block; padding: 1px 8px; border-radius: 4px; font-weight: 600;
         font-size: 13px; }
.passed { background: #10301a; color: var(--pass); }
.failed, .crashed, .error { background: #3a1013; color: #ff6b73; }
.timeout { background: #33270c; color: var(--warn); }
section { background: var(--panel); border: 1px solid var(--line); border-radius: 8px;
          padding: 16px; margin: 0 0 16px; }
ul { margin: 8px 0; padding-left: 20px; } li.fail { color: #ff6b73; }
img { max-width: 100%; border: 1px solid var(--line); border-radius: 4px; }
.shots { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 8px; }
figure { margin: 0; } figcaption { color: var(--muted); font-size: 13px; }
pre { background: #0a0b0c; border: 1px solid var(--line); padding: 8px; overflow-x: auto;
      font-size: 12px; max-height: 320px; }
details { margin-top: 8px; }
'''


def _badge(status: str) -> str:
    return f'<span class="badge {html.escape(status)}">{html.escape(status)}</span>'


def write_report(results: list[RunResult], report: Path, title: str) -> Path:
    passed = sum(result.passed for result in results)
    rows, sections = [], []
    for index, result in enumerate(results):
        anchor = f'r{index}'
        rows.append(f'<tr><td><a href="#{anchor}">{html.escape(result.case.name)}</a></td>'
                    f'<td>{html.escape(result.build)}</td><td>{_badge(result.status)}</td>'
                    f'<td>{result.seconds:.0f} s</td></tr>')
        parts = [f'<section id="{anchor}"><h2>{html.escape(result.case.name)} '
                 f'<span class="muted">on {html.escape(result.build)}</span> '
                 f'{_badge(result.status)}</h2>']
        for client in result.clients:
            data = client['result'] or {}
            parts.append(f'<p><b>{html.escape(client["role"])}</b> {_badge(client["status"])}'
                         f' <a href="{html.escape(client["log"])}">log</a></p>')
            steps = (data.get('test') or {}).get('steps') or []
            if steps:
                parts.append('<ul>')
                for step in steps:
                    mark = 'pass' if step.get('passed') else 'fail'
                    parts.append(f'<li class="{mark}">{"✓" if mark == "pass" else "✗"} '
                                 f'{html.escape(str(step.get("name")))} '
                                 f'<span class="muted">{float(step.get("seconds") or 0):.1f} s</span>')
                    for failure in step.get('failures') or []:
                        parts.append(f'<pre>{html.escape(str(failure))}</pre>')
                    parts.append('</li>')
                parts.append('</ul>')
            if data.get('lua_errors'):
                parts.append(f'<p class="muted">{data["lua_errors"]} Lua errors; first: '
                             f'{html.escape(str(data.get("first_lua_error")))}</p>')
            if client['status'] in ('crashed', 'timeout') and not steps:
                parts.append('<p class="muted">No result: the client '
                             + ('did not finish in time' if client['status'] == 'timeout'
                                else 'exited without one') + '. The end of the log:</p>')
                parts.append('<pre>' + html.escape('\n'.join(client['tail'])) + '</pre>')
            if client['screenshots']:
                parts.append('<div class="shots">')
                for shot in client['screenshots']:
                    parts.append(f'<figure><a href="{html.escape(shot["file"])}"><img src="'
                                 f'{html.escape(shot["file"])}" alt="{html.escape(shot["name"])}"'
                                 f' loading="lazy"></a><figcaption>{html.escape(shot["name"])}'
                                 '</figcaption></figure>')
                parts.append('</div>')
            if client['notable']:
                parts.append('<details><summary>Mod and test log lines</summary><pre>'
                             + html.escape('\n'.join(client['notable'])) + '</pre></details>')
        parts.append('</section>')
        sections.append('\n'.join(parts))
    page = f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>BOZ Test report</title><style>{_STYLE}</style></head>
<body><main>
<h1>{html.escape(title)}</h1>
<p class="muted">{passed} of {len(results)} passed · {time.strftime("%Y-%m-%d %H:%M")}</p>
<table><tr><th>Test</th><th>Build</th><th>Result</th><th>Time</th></tr>
{"".join(rows)}</table>
{"".join(sections)}
</main></body></html>
'''
    path = report / 'index.html'
    path.write_text(page, encoding='utf-8', newline='\n')
    (report / 'report.json').write_text(json.dumps([{
        'test': result.case.name, 'build': result.build, 'status': result.status,
        'seconds': round(result.seconds, 1),
        'clients': [{key: client[key] for key in ('role', 'status', 'result')}
                    for client in result.clients],
    } for result in results], indent=2), encoding='utf-8', newline='\n')
    return path


# --- Entry point --------------------------------------------------------------------------------

@dataclass
class Plan:
    cases: list[TestCase]
    title: str


def plan_for(root: Path, targets: list[str], only: list[str] | None, smoke: bool,
             work: Path) -> Plan:
    """What to run: each target is an installed mod id, a mod folder or an SDK project folder
    (built and installed first). No targets: every installed mod's tests, and a smoke test for
    each mod without any."""
    from . import project as sdk_project
    from . import sdkhome

    installed = {mod.id: mod for mod in sdkhome.client_mods(root)}
    chosen: list[tuple[str, Path]] = []
    for target in targets or list(installed):
        path = Path(target).expanduser()
        if (path / sdk_project.PROJECT_FILE).is_file():
            project = sdk_project.load_project(path)
            game = None
            if project.kind == 'map':
                from . import library
                game = library.open_game(root)
            sdk_project.install_project(project, root, force=True, game=game)
            chosen.append((project.mod.id, project.root))
        elif (path / 'mod.toml').is_file():
            mod_id = str(mod_manifest(path).get('id') or path.name)
            if mod_id not in installed:
                raise TestError(f'{path} is not installed in {root}: install it first')
            chosen.append((mod_id, path))
        elif target in installed:
            chosen.append((target, installed[target].folder))
        else:
            raise TestError(f'no installed mod, mod folder or project: {target}')
    cases = []
    for mod_id, folder in chosen:
        found = [] if smoke else find_tests(folder, mod_id, only)
        if not found and not only:
            manifest = mod_manifest(installed[mod_id].folder if mod_id in installed else folder)
            maps = [str(item) for item in manifest.get('maps', [])]
            found = [smoke_test(mod_id, maps, work / 'smoke')]
        cases += found
    title = 'BOZ Test: ' + (', '.join(mod for mod, _ in chosen) if chosen else 'nothing to run')
    return Plan(cases, title)


def run(root: str | Path, targets: list[str] | None = None, archs: list[str] | None = None,
        only: list[str] | None = None, report: str | Path | None = None, smoke: bool = False,
        coop_mix: bool = False, progress=print) -> tuple[Path, list[RunResult]]:
    """Run the tests; returns the report page and the results."""
    from . import sdkhome

    root = Path(root).expanduser().resolve()
    if not (root / 'assets' / 'boz.s3e.unpacked').is_file():
        raise TestError(f'{root} has no game data (assets/boz.s3e.unpacked)')
    builds = find_builds(root, archs)
    if not builds:
        raise TestError(f'no client build found in {root}' +
                        (f' for {", ".join(archs)}' if archs else ''))
    report = Path(report).expanduser().resolve() if report else root / 'test-report'
    if report.exists():
        shutil.rmtree(report)
    report.mkdir(parents=True)
    work = Path(tempfile.mkdtemp(prefix='boz-test-'))
    try:
        plan = plan_for(root, list(targets or []), only, smoke, work)
        all_mods = [mod.id for mod in sdkhome.client_mods(root)]
        results = []
        for case in plan.cases:
            for build in builds:
                if case.archs and build.arch not in case.archs:
                    continue
                guest = None
                if coop_mix and case.players > 1 and len(builds) > 1:
                    guest = next(other for other in builds if other is not build)
                progress(f'{case.name} on {build.arch}' + (f' + {guest.arch}' if guest else '')
                         + ' ...')
                result = run_case(root, build, case, all_mods, report, work, guest)
                progress(f'  {result.status} ({result.seconds:.0f} s)')
                results.append(result)
        return write_report(results, report, plan.title), results
    finally:
        shutil.rmtree(work, ignore_errors=True)
