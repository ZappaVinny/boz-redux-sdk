"""The standard library names game struct fields instead of raw numbers: every
core.offset("Struct", "field") / core.size("Struct") it uses exists in the game definition
(gamedef structs or reflection), and no new raw offsets ("+ 0x..", "local X = 0x..") appear
outside the generated data files."""
import re
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
LIB = ROOT / 'lib' / 'boz'
GAMEDEF = ROOT / 'gamedef'
# Generated data, and the Flash and SWF readers (file formats, not game memory).
SKIP = {'symbol_data.lua', 'reflection_data.lua', 'event_names.lua', 'cvar_data.lua', 'avm1.lua',
        'swf.lua', 'client.lua'}
CALL = re.compile(r'(?:core\.offset|offset)\("([A-Za-z_]+)", "([A-Za-z_]+)"\)')
WRAPPED = re.compile(r'local function (\w+)\(field\) return core\.offset\("([A-Za-z_]+)", field\) end')
SIZE = re.compile(r'core\.size\("([A-Za-z_]+)"\)')
RAW = re.compile(r'[+-]\s*0x[0-9a-fA-F]+\b|^\s*local [\w, ]+=\s*0x[0-9a-fA-F]{1,4}\b')


def lua_files():
    return [p for p in LIB.rglob('*.lua') if p.name not in SKIP]


def code_of(text: str) -> str:
    return '\n'.join(line.split('--', 1)[0] for line in text.splitlines())


class StdlibOffsetTests(unittest.TestCase):
    def setUp(self):
        symbols = tomllib.loads((GAMEDEF / 'symbols' / 'boz-1.0.11.toml').read_text(encoding='utf-8'))
        self.structs = {s['name']: s for s in symbols.get('struct', [])}
        reflection = tomllib.loads((GAMEDEF / 'reflection' / 'boz-1.0.11.toml').read_text(encoding='utf-8'))
        self.classes = {c['name']: c for c in reflection['class']}

    def known(self, struct: str, field: str, seen=None) -> bool:
        if any(f['name'] == field for f in self.structs.get(struct, {}).get('field', [])):
            return True
        seen = seen or set()
        info = self.classes.get(struct)
        if not info or struct in seen:
            return False
        seen.add(struct)
        if any(f['name'] == field for f in info.get('fields', [])):
            return True
        return any(self.known(base['name'], field, seen) for base in info.get('bases', []))

    def test_named_fields_exist(self):
        missing = []
        for path in lua_files():
            text = code_of(path.read_text(encoding='utf-8'))
            uses = list(CALL.findall(text))
            for helper, struct in WRAPPED.findall(text):
                uses += [(struct, field) for field in re.findall(rf'\b{helper}\("([A-Za-z_]+)"\)', text)]
            for struct, field in uses:
                if not self.known(struct, field):
                    missing.append(f'{path.relative_to(LIB)}: {struct}.{field}')
            for struct in SIZE.findall(text):
                if not self.structs.get(struct, {}).get('size'):
                    missing.append(f'{path.relative_to(LIB)}: size of {struct}')
        self.assertEqual(missing, [])

    def test_no_raw_offsets(self):
        found = []
        for path in lua_files():
            for number, line in enumerate(code_of(path.read_text(encoding='utf-8')).splitlines(), 1):
                if RAW.search(line):
                    found.append(f'{path.relative_to(LIB)}:{number}: {line.strip()}')
        self.assertEqual(found, [], 'name these in gamedef (a [[struct]] field) and use core.offset')


if __name__ == '__main__':
    unittest.main()
