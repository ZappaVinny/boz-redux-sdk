"""The editor definitions of the client's Lua API (lib/boz/types/client.lua) name every function
the client registers (its luaL_Reg tables), when the client checkout sits next to the SDK."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CLIENT = ROOT.parent / 'boz-redux' / 'src'
TYPES = ROOT / 'lib' / 'boz' / 'types' / 'client.lua'
SOURCES = ['lua_runtime.c', 'lua_settings.c', 'lua_assets.c', 'lua_network.c', 'lua_hooks.c',
           'overlay.cpp']
INTERNAL = {'finish', 'finger'}   # test primitives the harness wraps (test.touch, ...)


class ClientTypesTests(unittest.TestCase):
    @unittest.skipUnless(CLIENT.is_dir(), 'no client checkout next to the SDK')
    def test_every_client_function_is_described(self):
        described = set(re.findall(r'^function [A-Za-z]+[.:]([a-z_]+)\(', TYPES.read_text(encoding='utf-8'),
                                   re.M))
        missing = []
        for source in SOURCES:
            text = (CLIENT / source).read_text(encoding='utf-8')
            for name in re.findall(r'\{"([a-z_]+)", *[a-z_]+\}', text):
                if name not in described and name not in INTERNAL:
                    missing.append(f'{source}: {name}')
        self.assertEqual(missing, [], 'add these to lib/boz/types/client.lua')


if __name__ == '__main__':
    unittest.main()
