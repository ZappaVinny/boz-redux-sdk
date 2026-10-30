"""Script property declarations and stubs."""
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bozkit import scripts  # noqa: E402


class ScriptTests(unittest.TestCase):
    def test_properties(self):
        text = '\n'.join([
            '---@property delay number 2 "Seconds before it opens"',
            '---@property count integer 3',
            '  ---@property armed bool true "Starts armed"',
            '---@property label string "Hello \\"there\\"" "What it says"',
            '---@property opens prefab "" The prefab it opens',
            '-- @property not_this number 1',
            'local x = 1',
        ])
        props = scripts.parse_properties(text)
        self.assertEqual([(p.name, p.type, p.default) for p in props],
                         [('delay', 'number', 2.0), ('count', 'integer', 3), ('armed', 'bool', True),
                          ('label', 'string', 'Hello "there"'), ('opens', 'prefab', '')])
        self.assertEqual(props[0].description, 'Seconds before it opens')
        self.assertEqual(props[4].description, 'The prefab it opens')
        self.assertEqual(scripts.values(props, {'delay': '5', 'armed': 'false', 'gone': 1}),
                         {'delay': 5.0, 'count': 3, 'armed': False, 'label': 'Hello "there"',
                          'opens': ''})

    def test_bad_declarations(self):
        for text in ('---@property x colour 1', '---@property x number abc',
                     '---@property x number 1\n---@property x number 2'):
            with self.assertRaises(scripts.ScriptError):
                scripts.parse_properties(text)

    def test_stub(self):
        with tempfile.TemporaryDirectory() as temp:
            relative = scripts.new_script(temp, 'vault')
            self.assertEqual(relative, 'prefabs/vault.lua')
            text = (Path(temp) / relative).read_text(encoding='utf-8')
            self.assertIn('function on_hit(volume, info)', text)
            self.assertNotIn('boz.prefab()', text)
            self.assertEqual([p.name for p in scripts.parse_properties(text)], ['message'])
            self.assertEqual(scripts.list_scripts(temp), ['prefabs/vault.lua'])
            luac = shutil.which('luac')
            if luac:
                self.assertEqual(subprocess.run([luac, '-p', str(Path(temp) / relative)]).returncode, 0)
        with self.assertRaises(scripts.ScriptError):
            scripts.stub('two words')


if __name__ == '__main__':
    unittest.main()
