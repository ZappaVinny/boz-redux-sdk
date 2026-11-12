import json
import tempfile
import unittest
from pathlib import Path

from bozkit import png, testing


class TestingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def write(self, relative: str, text: str) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
        return path

    def test_dark_screenshots_convert(self):
        # Pixel bytes that look like whitespace (a dark frame) right after the header.
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            (folder / 'a.ppm').write_bytes(b'P6\n2 2\n255\n' + bytes([10, 32, 9, 0, 0, 0, 13, 12, 11, 1, 2, 3]))
            self.assertTrue(testing._ppm_to_png(folder / 'a.ppm', folder / 'a.png'))
            (folder / 'b.ppm').write_bytes(b'P6\n2 2\n255\n' + bytes(5))
            self.assertFalse(testing._ppm_to_png(folder / 'b.ppm', folder / 'b.png'))

    def test_options_come_from_the_header_only(self):
        path = self.write('m/tests/a.lua', '--! timeout: 90\n-- about it\n--! touch: true\n'
                          '--! players: 2\n\nlocal x = 1\n--! arch: x64\n')
        options = testing.read_options(path)
        self.assertEqual(options, {'timeout': '90', 'touch': 'true', 'players': '2'})
        case = testing.TestCase('a', path, 'm', options)
        self.assertEqual((case.timeout, case.touch, case.players, case.archs), (90, True, 2, []))

    def test_bad_option_values_fall_back(self):
        case = testing.TestCase('a', Path('a.lua'), 'm', {'timeout': 'soon', 'players': 'x'})
        self.assertEqual((case.timeout, case.players, case.touch),
                         (testing.DEFAULT_TIMEOUT, 1, False))

    def test_find_tests_sorted_and_filtered(self):
        self.write('m/tests/b.lua', '')
        self.write('m/tests/a.lua', '--! mods: developer, other\n')
        self.write('m/tests/notes.txt', '')
        found = testing.find_tests(self.root / 'm', 'm')
        self.assertEqual([case.name for case in found], ['a', 'b'])
        self.assertEqual(found[0].extra_mods, ['developer', 'other'])
        self.assertEqual([case.name for case in testing.find_tests(self.root / 'm', 'm', ['b'])],
                         ['b'])
        self.assertEqual(testing.find_tests(self.root / 'none', 'none'), [])

    def test_smoke_test_runs_in_the_developer_mod(self):
        case = testing.smoke_test('my_map', ['my_map'], self.root)
        self.assertEqual(case.mod, testing.DEVELOPER_MOD)
        self.assertEqual(case.extra_mods, ['my_map'])
        text = case.file.read_text(encoding='utf-8')
        self.assertIn('local map = "my_map"', text)
        self.assertEqual(case.timeout, 240)
        self.assertIn('local map = nil', testing.smoke_test('x', [], self.root).file.read_text(
            encoding='utf-8'))

    def test_builds_found_in_a_checkout(self):
        import sys
        exe = 'codboz_s3e_loader.exe' if sys.platform == 'win32' else 'codboz_s3e_loader'
        platform = 'windows' if sys.platform == 'win32' else 'linux'
        self.write(f'build/{platform}-x64/bin/{exe}', '')
        self.write(f'build/{platform}-x86/bin/{exe}', '')
        self.assertEqual([b.arch for b in testing.find_builds(self.root)], ['x86', 'x64'])
        self.assertEqual([b.arch for b in testing.find_builds(self.root, ['x64'])], ['x64'])

    def test_client_ini_enables_only_the_chosen_mods(self):
        path = self.root / 'client.ini'
        testing._client_ini(path, ['developer', 'map'], ['developer', 'map', 'other', 'more'])
        text = path.read_text(encoding='utf-8')
        self.assertIn('order = developer, map\n', text)
        self.assertIn('disabled = other, more\n', text)
        self.assertIn('fullscreen = false\n', text)

    def test_ppm_becomes_png(self):
        ppm = self.root / 'a.ppm'
        ppm.write_bytes(b'P6\n2 1\n255\n' + bytes([255, 0, 0, 0, 0, 255]))
        self.assertTrue(testing._ppm_to_png(ppm, self.root / 'a.png'))
        width, height, rgba = png.read_rgba((self.root / 'a.png').read_bytes())
        self.assertEqual((width, height), (2, 1))
        self.assertEqual(rgba, bytes([255, 0, 0, 255, 0, 0, 255, 255]))

    def test_client_report_statuses(self):
        report = self.root / 'report'
        report.mkdir()
        out = self.root / 'out'
        out.mkdir()
        log = self.root / 'log.txt'
        log.write_text('[lua] started x\nother\n[test] finished: exit 1\n', encoding='utf-8')
        self.assertEqual(testing._client_report('solo', None, out, log, report, 'p')['status'],
                         'timeout')
        self.assertEqual(testing._client_report('solo', 139, out, log, report, 'p')['status'],
                         'crashed')
        (out / 'result.json').write_text(json.dumps({'status': 'failed', 'test': None}),
                                         encoding='utf-8')
        client = testing._client_report('solo', 1, out, log, report, 'p')
        self.assertEqual(client['status'], 'failed')
        self.assertEqual(client['notable'], ['[lua] started x', '[test] finished: exit 1'])
        self.assertTrue((report / 'p-solo.log').is_file())

    def test_report_page(self):
        case = testing.TestCase('boot', Path('boot.lua'), 'developer')
        client = {'role': 'solo', 'status': 'failed', 'exit': 1, 'log': 'boot.log',
                  'screenshots': [{'name': 'kino', 'file': 'boot-kino.png'}], 'notable': ['[lua] x'],
                  'tail': [], 'result': {'status': 'failed', 'lua_errors': 1,
                                         'first_lua_error': 'developer: <oops>',
                                         'test': {'steps': [
                                             {'name': 'starts', 'passed': True, 'seconds': 3},
                                             {'name': 'doors', 'passed': False, 'seconds': 1,
                                              'failures': ['Door1 <closed>']}]}}}
        results = [testing.RunResult(case, 'x86', 'failed', 12.0, [client]),
                   testing.RunResult(case, 'x64', 'passed', 10.0, [dict(client, status='passed')])]
        page = testing.write_report(results, self.root, 'BOZ Test: developer')
        text = page.read_text(encoding='utf-8')
        self.assertIn('1 of 2 passed', text)
        self.assertIn('Door1 &lt;closed&gt;', text)
        self.assertIn('boot-kino.png', text)
        data = json.loads((self.root / 'report.json').read_text(encoding='utf-8'))
        self.assertEqual([item['status'] for item in data], ['failed', 'passed'])


if __name__ == '__main__':
    unittest.main()
