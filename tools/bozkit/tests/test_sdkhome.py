"""Launcher model tests: settings, projects and a synthetic client folder."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bozkit import project, sdkhome  # noqa: E402

INI = """# BOZ Redux client settings.

[display]
# Borderless fullscreen.
fullscreen = true

[mods]
order = developer, other
disabled = other

[debug]
status = false
"""


class SdkHomeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        patcher = mock.patch.dict(os.environ, {'BOZ_SDK_HOME': str(self.root / 'home')})
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def make_client(self, game_files: bool = True) -> Path:
        client = self.root / 'client'
        (client / 'mods').mkdir(parents=True)
        (client / 'boz-redux').write_text('launcher', encoding='utf-8')
        (client / 'client.ini').write_text(INI, encoding='utf-8')
        for mod_id in ('developer', 'other'):
            (client / 'mods' / mod_id).mkdir()
            (client / 'mods' / mod_id / 'mod.toml').write_text(
                f'id = "{mod_id}"\nname = "{mod_id.title()}"\nversion = "1.0"\n', encoding='utf-8')
        if game_files:
            assets = client / 'assets'
            assets.mkdir()
            (assets / 'boz.s3e.unpacked').mkdir()
            for name, size in sdkhome.PACKS.items():
                with open(assets / name, 'wb') as stream:
                    stream.truncate(size)  # sparse: right size, no data
        return client

    def test_settings_round_trip(self) -> None:
        settings = sdkhome.Settings.load()
        self.assertTrue(settings.first_run)
        settings.client = '/games/boz'
        settings.add_project(self.root / 'a')
        settings.add_project(self.root / 'a')  # no duplicates
        settings.save()
        loaded = sdkhome.Settings.load()
        self.assertFalse(loaded.first_run)
        self.assertEqual(len(loaded.projects), 1)
        self.assertGreater(loaded.projects[0].last_opened, 0)
        loaded.remove_project(self.root / 'a')
        self.assertEqual(loaded.projects, [])

    def test_client_status(self) -> None:
        status = sdkhome.client_status(self.make_client())
        self.assertEqual(status.kind, 'release')
        self.assertTrue(status.game_ready)
        self.assertEqual([(mod.id, mod.enabled) for mod in status.mods],
                         [('developer', True), ('other', False)])
        self.assertFalse(sdkhome.client_status(self.root).is_client)

    def test_missing_game_data_is_reported(self) -> None:
        status = sdkhome.client_status(self.make_client(game_files=False))
        self.assertTrue(status.is_client)
        self.assertFalse(status.game_ready)
        self.assertIn('blackops_etc.dz', status.missing)

    def test_ini_edits_keep_everything_else(self) -> None:
        client = self.make_client()
        sdkhome.set_mod_enabled(client, 'other', True)
        sdkhome.set_mod_enabled(client, 'developer', False)
        text = (client / 'client.ini').read_text(encoding='utf-8')
        self.assertIn('disabled = developer\n', text)
        self.assertIn('# Borderless fullscreen.', text)
        self.assertIn('[debug]\nstatus = false', text)
        sdkhome.ini_set(client, 'debug', 'log_files', 'true')
        sdkhome.ini_set(client, 'new', 'key', 'value')
        self.assertEqual(sdkhome.ini_get(client, 'debug', 'log_files'), 'true')
        self.assertEqual(sdkhome.ini_get(client, 'new', 'key'), 'value')
        self.assertEqual(sdkhome.ini_get(client, 'debug', 'status'), 'false')

    def test_script_and_map_projects(self) -> None:
        script = project.create_project(self.root / 's', 'my_mod', 'My Mod', 'Me', template='round')
        self.assertEqual(script.kind, 'script')
        self.assertIn('CWaveManager::StartWave',
                      (script.scripts / 'main.lua').read_text(encoding='utf-8'))
        self.assertTrue((script.scripts / 'boz' / 'player.lua').is_file())
        self.assertTrue((script.scripts / '.luarc.json').is_file())
        self.assertFalse(script.include_standard_library)  # it carries its own copy
        built, _ = project.build_project(script)
        self.assertTrue((built / 'scripts' / 'boz' / 'player.lua').is_file())
        level = project.create_project(self.root / 'm', 'my-map', 'My Map', 'Me', kind='map',
                                       template='empty')
        self.assertEqual((level.kind, level.map_name, level.map_template),
                         ('map', 'my_map', 'empty'))
        self.assertTrue((level.root / 'source' / 'world.json').is_file())
        self.assertTrue(project.validate_project(level).ok)
        with self.assertRaises(project.ProjectError):  # the debug arena needs the game's data
            project.create_project(self.root / 'd', 'debug_map', 'D', 'Me', kind='map',
                                   template='debug')
        with self.assertRaises(project.ProjectError):  # a shipped level's name
            project.create_project(self.root / 'k', 'kino', 'K', 'Me', kind='map')
        with self.assertRaises(project.ProjectError):
            project.create_project(self.root / 'x', 'x', 'X', 'Me', kind='map', template='round')

    def test_schema_1_projects_still_load(self) -> None:
        root = self.root / 'old'
        root.mkdir()
        (root / project.PROJECT_FILE).write_text(
            'schema = 1\n\n[mod]\nid = "old"\nname = "Old"\nversion = "1"\nauthor = "Me"\n'
            'game = "1.0.11"\n', encoding='utf-8')
        loaded = project.load_project(root)
        self.assertEqual((loaded.schema, loaded.kind), (1, 'script'))
        renamed = sdkhome.update_metadata(loaded, name='Older')
        self.assertEqual((renamed.schema, renamed.mod.name), (2, 'Older'))

    def test_rename_and_duplicate(self) -> None:
        original = project.create_project(self.root / 'a', 'a_map', 'A', 'Me', kind='map')
        (original.root / 'build').mkdir()
        copy = sdkhome.duplicate_project(original, self.root / 'b', 'b_map', 'B')
        self.assertEqual((copy.mod.id, copy.mod.name, copy.map_name), ('b_map', 'B', 'b_map'))
        self.assertFalse((copy.root / 'build').exists())
        moved = sdkhome.rename_project(copy, 'Bee', self.root / 'bee')
        self.assertEqual((moved.root.name, moved.mod.name, moved.mod.id), ('bee', 'Bee', 'b_map'))
        self.assertFalse((self.root / 'b').exists())
        with self.assertRaises(project.ProjectError):
            sdkhome.duplicate_project(original, original.root / 'inside', 'c', 'C')

    def test_developer_mod_is_installed_when_missing(self) -> None:
        client = self.make_client()
        sdk = self.root / 'sdk'
        (sdk / 'mods' / 'developer' / 'scripts').mkdir(parents=True)
        (sdk / 'mods' / 'developer' / 'mod.toml').write_text('id = "developer"\n', encoding='utf-8')
        (sdk / 'mods' / 'developer' / 'assets').mkdir()
        import shutil
        shutil.rmtree(client / 'mods' / 'developer')
        with mock.patch.object(sdkhome, 'sdk_root', return_value=sdk):
            installed = sdkhome.ensure_developer_mod(client)
        self.assertTrue((installed / 'mod.toml').is_file())
        self.assertFalse((installed / 'assets').exists())  # map edits never ship

    def test_suggest_id(self) -> None:
        self.assertEqual(sdkhome.suggest_id('Cool Mod 2!'), 'cool_mod_2')
        self.assertEqual(sdkhome.suggest_id('2 Fast'), 'mod_2_fast')
        self.assertEqual(sdkhome.suggest_id('!!!'), 'my_mod')



class StartGameTests(unittest.TestCase):
    def test_the_game_keeps_its_saves_in_the_client(self):
        from unittest import mock
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'codboz_s3e_loader').write_text('', encoding='utf-8')
            (root / 'codboz_s3e_loader.exe').write_text('', encoding='utf-8')
            calls = []
            with mock.patch.object(sdkhome, 'start_detached',
                                   lambda command, cwd, log=None, env=None: calls.append(env)), \
                    mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop('BOZ_SAVES', None)
                sdkhome.start_game(root)
            self.assertEqual(calls[0]['HOME'], str(root / 'saves'))
            self.assertTrue((root / 'saves').is_dir())


class OpenPathTests(unittest.TestCase):
    def test_opening_never_waits(self):
        from unittest import mock
        started = []
        with mock.patch.object(sdkhome, 'start_detached', lambda command, cwd, *a, **k: started.append(command)), \
                mock.patch.object(sdkhome.sys, 'platform', 'linux'), \
                mock.patch('shutil.which', lambda name: '/usr/bin/code' if name == 'code' else None):
            sdkhome.open_path('/tmp/x/Vault.lua', editor=True)
            sdkhome.open_path('/tmp/x')
        self.assertEqual(started, [['/usr/bin/code', '--goto', str(Path('/tmp/x/Vault.lua'))],
                                   ['xdg-open', str(Path('/tmp/x'))]])


class BrokenBlendTests(unittest.TestCase):
    def test_empty_map_blend_is_set_aside(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'map.blend').write_bytes(b'')
            fake = mock.Mock(root=root)
            with mock.patch.object(sdkhome, 'find_blender', lambda settings: Path('/usr/bin/blender')), \
                    mock.patch.object(sdkhome, 'suite_dir', lambda: root / 'suite'):
                (root / 'suite' / 'scripts' / 'startup' / 'bl_app_templates_user' / 'boz_suite').mkdir(parents=True)
                command, _env = sdkhome.editor_command(fake, mock.Mock(client=''))
            self.assertFalse((root / 'map.blend').exists())
            self.assertTrue((root / 'map.blend.broken').exists())
            self.assertNotIn(str(root / 'map.blend'), command)


if __name__ == '__main__':
    unittest.main()
