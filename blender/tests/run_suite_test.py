#!/usr/bin/env python3
"""Build the editor, make an Empty map project and run suite_headless.py in background Blender
with it, as the launcher would open it."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools' / 'bozkit'))
sys.path.insert(0, str(ROOT / 'tools'))

from bozkit import project  # noqa: E402
import build_suite  # noqa: E402


def main() -> int:
    blender = shutil.which('blender') or 'blender'
    build_suite.build(blender)
    from bozkit import library, sdkhome
    real_home = sdkhome.data_dir()
    runs = [('empty', None)]
    if (real_home / 'library' / library.GAME_VERSION / 'index.sqlite').is_file():
        runs.append(('debug', real_home))   # the user's own asset library, read only
        runs.append(('kino', real_home))
    for template, home in runs:
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            game = library.LibraryPack(home / 'library' / library.GAME_VERSION) if home else None
            made = project.create_project(temp / 'map', 'test_map', 'Test Map', 'Tests',
                                          kind='map', template=template, game=game)
            env = dict(os.environ, BLENDER_USER_SCRIPTS=str(build_suite.OUTPUT / 'scripts'),
                       BLENDER_USER_CONFIG=str(temp / 'config'), BOZ_PROJECT=str(made.root),
                       BOZ_SDK_ROOT=str(ROOT), BOZ_SDK_HOME=str(home or temp / 'home'),
                       BOZ_CLIENT='', BOZ_TEST_LIBRARY='1' if home else '')
            result = subprocess.run([blender, '-b', '--app-template', 'boz_suite', '--python',
                                     str(Path(__file__).with_name('suite_headless.py'))],
                                    env=env, capture_output=True, text=True, timeout=600)
        output = result.stdout + result.stderr
        if 'BOZ_SUITE_OK' not in output:
            print(f'{template}:\n{output}')
            return 1
        print(f'{template}: BOZ_SUITE_OK')
        for line in output.splitlines():
            if line.startswith('BOZ_SUITE_INFO'):
                print(f'  {line[len("BOZ_SUITE_INFO "):]}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
