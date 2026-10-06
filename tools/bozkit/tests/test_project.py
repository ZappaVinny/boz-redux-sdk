"""SDK project/compiler tests using only authored synthetic files."""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bozkit import project  # noqa: E402


class ProjectTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def make_project(self) -> project.Project:
        return project.create_project(self.root / 'example', 'example', 'Example Mod', 'Tester')

    def test_create_and_load(self) -> None:
        loaded = project.create_project(self.root / 'example', 'example', 'Example Mod', 'Tester',
                                        description='Created in the SDK')
        self.assertEqual(loaded.schema, project.PROJECT_SCHEMA)
        self.assertEqual(loaded.mod.id, 'example')
        self.assertEqual(loaded.mod.description, 'Created in the SDK')
        self.assertTrue((loaded.scripts / 'main.lua').is_file())
        self.assertTrue(project.validate_project(loaded).ok)

    def test_invalid_id_is_reported(self) -> None:
        loaded = self.make_project()
        manifest = loaded.root / project.PROJECT_FILE
        manifest.write_text(manifest.read_text().replace('id = "example"', 'id = "Bad ID"'))
        loaded = project.load_project(loaded.root)
        result = project.validate_project(loaded)
        self.assertFalse(result.ok)
        self.assertIn('mod.id', result.errors[0])

    def test_new_rejects_invalid_id(self) -> None:
        with self.assertRaises(project.ProjectError):
            project.create_project(self.root / 'bad', 'Bad ID', 'Bad', 'Tester')

    def test_other_game_versions_are_rejected(self) -> None:
        loaded = self.make_project()
        manifest = loaded.root / project.PROJECT_FILE
        manifest.write_text(manifest.read_text().replace('game = "1.0.11"', 'game = "1.0.10"'))
        result = project.validate_project(project.load_project(loaded.root))
        self.assertFalse(result.ok)
        self.assertIn('no other game version is supported', result.errors[0])

    def test_build_contains_sources_standard_library_and_report(self) -> None:
        loaded = self.make_project()
        (loaded.assets / 'made-by-test.txt').write_text('asset\n')
        output, report = project.build_project(loaded)
        self.assertTrue((output / 'scripts' / 'main.lua').is_file())
        self.assertTrue((output / 'scripts' / 'boz' / 'player.lua').is_file())
        self.assertEqual((output / 'assets' / 'made-by-test.txt').read_text(), 'asset\n')
        self.assertEqual(json.loads((output / project.BUILD_REPORT).read_text())['files'], report['files'])
        self.assertIn('id = "example"', (output / 'mod.toml').read_text())

    def test_distribution_warns_but_allows_game_derived_assets(self) -> None:
        loaded = self.make_project()
        asset = loaded.assets / 'edited.group.bin'
        asset.write_bytes(b'synthetic')
        manifest = loaded.root / project.PROJECT_FILE
        manifest.write_text(manifest.read_text() + '''

[[provenance]]
path = "assets/edited.group.bin"
kind = "game-derived"
note = "Private test asset"
''')
        loaded = project.load_project(loaded.root)
        result = project.validate_project(loaded, 'distribution')
        self.assertTrue(result.ok)
        self.assertTrue(any('distribution rights' in item for item in result.warnings))
        output, _ = project.build_project(loaded, profile='distribution')
        self.assertEqual((output / 'assets' / asset.name).read_bytes(), b'synthetic')

    def test_package_is_reproducible(self) -> None:
        loaded = self.make_project()
        first, _ = project.package_project(loaded, self.root / 'first.zip')
        second, _ = project.package_project(loaded, self.root / 'second.zip')
        self.assertEqual(hashlib.sha256(first.read_bytes()).digest(), hashlib.sha256(second.read_bytes()).digest())
        with zipfile.ZipFile(first) as archive:
            self.assertIn('example/mod.toml', archive.namelist())
            self.assertTrue(all(info.date_time == (1980, 1, 1, 0, 0, 0) for info in archive.infolist()))

    def test_install_refuses_replacement_without_force(self) -> None:
        loaded = self.make_project()
        client = self.root / 'client'
        client.mkdir()
        installed = project.install_project(loaded, client)
        self.assertTrue((installed / 'mod.toml').is_file())
        with self.assertRaises(project.ProjectError):
            project.install_project(loaded, client)
        project.install_project(loaded, client, force=True)

    def test_build_refuses_to_replace_arbitrary_directory(self) -> None:
        loaded = self.make_project()
        output = self.root / 'not-a-build'
        output.mkdir()
        (output / 'keep.txt').write_text('keep')
        with self.assertRaises(project.ProjectError):
            project.build_project(loaded, output)
        self.assertEqual((output / 'keep.txt').read_text(), 'keep')

    def test_project_paths_cannot_escape(self) -> None:
        loaded = self.make_project()
        manifest = loaded.root / project.PROJECT_FILE
        manifest.write_text(manifest.read_text().replace('scripts = "scripts"', 'scripts = "../scripts"'))
        with self.assertRaises(project.ProjectError):
            project.load_project(loaded.root)


if __name__ == '__main__':
    unittest.main()
